import sys
import json

KASAN_KMALLOC_REDZONE = 0xFC
KASAN_KMALLOC_FREE = 0xFB
KASAN_SHADOW_UNMAPPED = 0xFF

def solve():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    memory_size = data.get("memory_size", 512)
    quarantine_capacity = data.get("quarantine_capacity", 3)
    operations = data.get("operations", [])

    shadow_size = memory_size // 8
    shadow = [KASAN_SHADOW_UNMAPPED] * shadow_size

    objects = {}
    quarantine_queue = []

    stats = {
        "allocations_count": 0,
        "frees_count": 0,
        "access_granted_count": 0,
        "oob_detected_count": 0,
        "uaf_detected_count": 0,
        "double_free_detected_count": 0
    }

    op_log = []

    def check_access(addr, access_size):
        for byte_off in range(access_size):
            curr_addr = addr + byte_off
            if curr_addr < 0 or curr_addr >= memory_size:
                return "OUT_OF_PHYSICAL_BOUNDS", -1
            shadow_idx = curr_addr // 8
            byte_in_chunk = curr_addr % 8
            s_val = shadow[shadow_idx]

            if s_val == 0:
                continue
            elif 1 <= s_val <= 7:
                if byte_in_chunk >= s_val:
                    return "SLAB_OUT_OF_BOUNDS", curr_addr
            elif s_val == KASAN_KMALLOC_REDZONE:
                return "SLAB_OUT_OF_BOUNDS", curr_addr
            elif s_val == KASAN_KMALLOC_FREE:
                return "USE_AFTER_FREE", curr_addr
            elif s_val == KASAN_SHADOW_UNMAPPED:
                return "UNMAPPED_ACCESS", curr_addr
        return "ACCESS_GRANTED", -1

    for op in operations:
        op_type = op.get("op")

        if op_type == "KMALLOC":
            ptr = op["ptr"]
            size = op["size"]
            redzone = op.get("redzone", 8)

            ptr = (ptr + 7) & ~7
            full_chunks = size // 8
            rem = size % 8
            redzone_chunks = (redzone + 7) // 8
            total_chunks = full_chunks + (1 if rem > 0 else 0) + redzone_chunks
            total_alloc_size = total_chunks * 8

            start_idx = ptr // 8
            for i in range(full_chunks):
                shadow[start_idx + i] = 0
            cur_idx = start_idx + full_chunks
            if rem > 0:
                shadow[cur_idx] = rem
                cur_idx += 1
            for i in range(redzone_chunks):
                shadow[cur_idx + i] = KASAN_KMALLOC_REDZONE

            objects[ptr] = {
                "ptr": ptr,
                "size": size,
                "redzone": redzone,
                "total_alloc_size": total_alloc_size,
                "state": "ALLOCATED"
            }
            stats["allocations_count"] += 1
            op_log.append({
                "op": "KMALLOC",
                "ptr": ptr,
                "size": size,
                "total_alloc_size": total_alloc_size,
                "status": "ALLOCATED_OK"
            })

        elif op_type == "KFREE":
            ptr = op["ptr"]
            if ptr not in objects:
                stats["double_free_detected_count"] += 1
                op_log.append({
                    "op": "KFREE",
                    "ptr": ptr,
                    "status": "BUG_DOUBLE_FREE_UNKNOWN_OBJECT"
                })
            else:
                obj = objects[ptr]
                if obj["state"] != "ALLOCATED":
                    stats["double_free_detected_count"] += 1
                    op_log.append({
                        "op": "KFREE",
                        "ptr": ptr,
                        "status": "BUG_DOUBLE_FREE"
                    })
                else:
                    obj["state"] = "QUARANTINED"
                    stats["frees_count"] += 1

                    start_idx = ptr // 8
                    nr_chunks = obj["total_alloc_size"] // 8
                    for i in range(nr_chunks):
                        shadow[start_idx + i] = KASAN_KMALLOC_FREE

                    quarantine_queue.append(ptr)
                    purged_ptr = None
                    if len(quarantine_queue) > quarantine_capacity:
                        purged_ptr = quarantine_queue.pop(0)
                        purged_obj = objects[purged_ptr]
                        purged_obj["state"] = "FREED"
                        p_start = purged_ptr // 8
                        p_chunks = purged_obj["total_alloc_size"] // 8
                        for i in range(p_chunks):
                            shadow[p_start + i] = KASAN_SHADOW_UNMAPPED

                    op_log.append({
                        "op": "KFREE",
                        "ptr": ptr,
                        "status": "QUARANTINED_OK",
                        "purged_from_quarantine": purged_ptr
                    })

        elif op_type == "MEMORY_ACCESS":
            addr = op["addr"]
            size = op.get("size", 1)
            is_write = op.get("is_write", False)

            result, fault_addr = check_access(addr, size)
            if result == "ACCESS_GRANTED":
                stats["access_granted_count"] += 1
            elif result == "SLAB_OUT_OF_BOUNDS":
                stats["oob_detected_count"] += 1
            elif result in ("USE_AFTER_FREE", "UNMAPPED_ACCESS"):
                stats["uaf_detected_count"] += 1

            op_log.append({
                "op": "MEMORY_ACCESS",
                "addr": addr,
                "size": size,
                "is_write": is_write,
                "status": result,
                "fault_addr": fault_addr if fault_addr != -1 else None
            })

    active_objects = sum(1 for o in objects.values() if o["state"] == "ALLOCATED")
    quarantined_objects = sum(1 for o in objects.values() if o["state"] == "QUARANTINED")

    result_data = {
        "memory_size": memory_size,
        "shadow_size": shadow_size,
        "active_objects": active_objects,
        "quarantined_objects": quarantined_objects,
        "stats": stats,
        "quarantine_queue": quarantine_queue,
        "op_log": op_log
    }

    print(json.dumps(result_data, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
