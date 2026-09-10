import sys
import json

def solve():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    page_size = data.get("page_size", 64)
    num_slots = data.get("num_slots", 4)
    sample_interval = data.get("sample_interval", 2)
    operations = data.get("operations", [])

    pool_base = 4096

    slots = []
    for i in range(num_slots):
        slots.append({
            "slot_id": i,
            "page_addr": pool_base + (2 * i + 1) * page_size,
            "left_guard": pool_base + (2 * i) * page_size,
            "right_guard": pool_base + (2 * i + 2) * page_size,
            "state": "UNUSED",
            "ptr": None,
            "size": 0,
            "align_right": False,
            "alloc_backtrace": None
        })

    alloc_counter = 0
    regular_slub_heap = 65536

    stats = {
        "allocations_requested": 0,
        "kfence_sampled_allocations": 0,
        "regular_slub_allocations": 0,
        "pool_full_fallbacks": 0,
        "frees_count": 0,
        "access_granted_count": 0,
        "oob_guard_detected_count": 0,
        "uaf_detected_count": 0,
        "double_free_detected_count": 0
    }

    op_log = []

    def get_slot_by_page(addr):
        for s in slots:
            if s["page_addr"] <= addr < s["page_addr"] + page_size:
                return s
        return None

    def is_guard_page(addr):
        if addr < pool_base or addr >= pool_base + (2 * num_slots + 1) * page_size:
            return False, -1
        page_idx = (addr - pool_base) // page_size
        if page_idx % 2 == 0:
            return True, page_idx // 2
        return False, -1

    for op in operations:
        op_type = op.get("op")

        if op_type == "KMALLOC":
            stats["allocations_requested"] += 1
            alloc_counter += 1
            size = op["size"]
            align_right = op.get("align_right", True)
            backtrace = op.get("backtrace", "kmalloc")

            is_sampled = (alloc_counter % sample_interval == 0)
            target_slot = None
            if is_sampled:
                for s in slots:
                    if s["state"] in ("UNUSED", "FREED"):
                        target_slot = s
                        break
                if not target_slot:
                    stats["pool_full_fallbacks"] += 1

            if target_slot:
                stats["kfence_sampled_allocations"] += 1
                offset = (page_size - size) if align_right else 0
                obj_ptr = target_slot["page_addr"] + offset
                target_slot["state"] = "ALLOCATED"
                target_slot["ptr"] = obj_ptr
                target_slot["size"] = size
                target_slot["align_right"] = align_right
                target_slot["alloc_backtrace"] = backtrace

                op_log.append({
                    "op": "KMALLOC",
                    "alloc_id": alloc_counter,
                    "type": "KFENCE",
                    "slot_id": target_slot["slot_id"],
                    "ptr": obj_ptr,
                    "size": size,
                    "align_right": align_right,
                    "status": "ALLOCATED_OK"
                })
            else:
                stats["regular_slub_allocations"] += 1
                obj_ptr = regular_slub_heap
                regular_slub_heap += (size + 7) & ~7
                op_log.append({
                    "op": "KMALLOC",
                    "alloc_id": alloc_counter,
                    "type": "REGULAR_SLUB",
                    "ptr": obj_ptr,
                    "size": size,
                    "status": "ALLOCATED_SLUB"
                })

        elif op_type == "KFREE":
            ptr = op["ptr"]
            found_slot = None
            for s in slots:
                if s["ptr"] == ptr or (s["page_addr"] <= ptr < s["page_addr"] + page_size):
                    found_slot = s
                    break

            if found_slot:
                if found_slot["state"] == "FREED":
                    stats["double_free_detected_count"] += 1
                    op_log.append({
                        "op": "KFREE",
                        "ptr": ptr,
                        "slot_id": found_slot["slot_id"],
                        "status": "BUG_KFENCE_DOUBLE_FREE"
                    })
                elif found_slot["state"] == "ALLOCATED":
                    found_slot["state"] = "FREED"
                    stats["frees_count"] += 1
                    op_log.append({
                        "op": "KFREE",
                        "ptr": ptr,
                        "slot_id": found_slot["slot_id"],
                        "status": "FREED_PAGE_PROTECTED"
                    })
                else:
                    op_log.append({
                        "op": "KFREE",
                        "ptr": ptr,
                        "status": "UNUSED_SLOT_FREE"
                    })
            else:
                stats["frees_count"] += 1
                op_log.append({
                    "op": "KFREE",
                    "ptr": ptr,
                    "status": "FREED_REGULAR_SLUB"
                })

        elif op_type == "MEMORY_ACCESS":
            addr = op["addr"]
            size = op.get("size", 1)
            is_write = op.get("is_write", False)

            fault_type = None
            fault_addr = None

            for b in range(addr, addr + size):
                is_guard, guard_id = is_guard_page(b)
                if is_guard:
                    fault_type = "PAGE_FAULT_OOB_GUARD"
                    fault_addr = b
                    break
                s = get_slot_by_page(b)
                if s:
                    if s["state"] == "FREED":
                        fault_type = "PAGE_FAULT_USE_AFTER_FREE"
                        fault_addr = b
                        break
                    elif s["state"] == "UNUSED":
                        fault_type = "PAGE_FAULT_UNUSED_SLOT"
                        fault_addr = b
                        break

            if fault_type == "PAGE_FAULT_OOB_GUARD":
                stats["oob_guard_detected_count"] += 1
                op_log.append({
                    "op": "MEMORY_ACCESS",
                    "addr": addr,
                    "size": size,
                    "is_write": is_write,
                    "status": "CRASH_OOB_GUARD_PAGE",
                    "fault_addr": fault_addr
                })
            elif fault_type == "PAGE_FAULT_USE_AFTER_FREE":
                stats["uaf_detected_count"] += 1
                op_log.append({
                    "op": "MEMORY_ACCESS",
                    "addr": addr,
                    "size": size,
                    "is_write": is_write,
                    "status": "CRASH_USE_AFTER_FREE",
                    "fault_addr": fault_addr
                })
            elif fault_type == "PAGE_FAULT_UNUSED_SLOT":
                op_log.append({
                    "op": "MEMORY_ACCESS",
                    "addr": addr,
                    "size": size,
                    "is_write": is_write,
                    "status": "CRASH_UNUSED_SLOT",
                    "fault_addr": fault_addr
                })
            else:
                stats["access_granted_count"] += 1
                op_log.append({
                    "op": "MEMORY_ACCESS",
                    "addr": addr,
                    "size": size,
                    "is_write": is_write,
                    "status": "ACCESS_GRANTED",
                    "fault_addr": None
                })

    active_kfence_objects = sum(1 for s in slots if s["state"] == "ALLOCATED")
    freed_kfence_objects = sum(1 for s in slots if s["state"] == "FREED")

    slots_summary = [
        {
            "slot_id": s["slot_id"],
            "page_addr": s["page_addr"],
            "state": s["state"],
            "ptr": s["ptr"],
            "size": s["size"],
            "align_right": s["align_right"],
            "alloc_backtrace": s["alloc_backtrace"]
        }
        for s in slots
    ]

    result = {
        "page_size": page_size,
        "num_slots": num_slots,
        "sample_interval": sample_interval,
        "active_kfence_objects": active_kfence_objects,
        "freed_kfence_objects": freed_kfence_objects,
        "stats": stats,
        "slots": slots_summary,
        "op_log": op_log
    }

    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
