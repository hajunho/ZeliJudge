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
    pointer_size = data.get("pointer_size", 8)
    scan_threshold_cycles = data.get("scan_threshold_cycles", 2)
    operations = data.get("operations", [])

    mem_words = {}
    objects = {}
    roots = set()

    scan_history = []
    op_log = []

    stats = {
        "total_allocations": 0,
        "total_frees": 0,
        "scan_runs": 0,
        "suspected_leaks_count": 0,
        "confirmed_leaks_count": 0,
        "false_positive_mitigations": 0
    }

    def find_object_containing(addr):
        for p, obj in objects.items():
            if obj["state"] == "ACTIVE":
                if p <= addr < p + obj["size"]:
                    return obj
        return None

    for op in operations:
        op_type = op.get("op")

        if op_type == "KMALLOC":
            ptr = op["ptr"]
            size = op["size"]
            min_count = op.get("min_count", 1)
            is_black = op.get("is_black", False)
            backtrace = op.get("backtrace", "unknown")

            ptr = (ptr + (pointer_size - 1)) & ~(pointer_size - 1)
            objects[ptr] = {
                "ptr": ptr,
                "size": size,
                "min_count": min_count,
                "is_black": is_black,
                "backtrace": backtrace,
                "count": 0,
                "unreferenced_cycles": 0,
                "state": "ACTIVE"
            }
            stats["total_allocations"] += 1
            op_log.append({
                "op": "KMALLOC",
                "ptr": ptr,
                "size": size,
                "status": "TRACKED"
            })

        elif op_type == "KFREE":
            ptr = op["ptr"]
            if ptr in objects and objects[ptr]["state"] == "ACTIVE":
                objects[ptr]["state"] = "FREED"
                stats["total_frees"] += 1
                obj_size = objects[ptr]["size"]
                words_to_del = [w for w in mem_words if ptr <= w < ptr + obj_size]
                for w in words_to_del:
                    del mem_words[w]
                op_log.append({"op": "KFREE", "ptr": ptr, "status": "REMOVED"})
            else:
                op_log.append({"op": "KFREE", "ptr": ptr, "status": "NOT_FOUND_OR_ALREADY_FREED"})

        elif op_type == "ADD_ROOT_POINTER":
            target_ptr = op["target_ptr"]
            roots.add(target_ptr)
            op_log.append({"op": "ADD_ROOT_POINTER", "target_ptr": target_ptr, "status": "ROOT_ADDED"})

        elif op_type == "REMOVE_ROOT_POINTER":
            target_ptr = op["target_ptr"]
            roots.discard(target_ptr)
            op_log.append({"op": "REMOVE_ROOT_POINTER", "target_ptr": target_ptr, "status": "ROOT_REMOVED"})

        elif op_type == "WRITE_POINTER":
            src_addr = op["src_addr"]
            offset = op.get("offset", 0)
            target_ptr = op["target_ptr"]
            dest_word = (src_addr + offset) & ~(pointer_size - 1)
            mem_words[dest_word] = target_ptr
            op_log.append({
                "op": "WRITE_POINTER",
                "src_addr": dest_word,
                "target_ptr": target_ptr,
                "status": "WRITTEN"
            })

        elif op_type == "KMEMLEAK_IGNORE":
            ptr = op["ptr"]
            if ptr in objects:
                objects[ptr]["is_black"] = True
                stats["false_positive_mitigations"] += 1
                op_log.append({"op": "KMEMLEAK_IGNORE", "ptr": ptr, "status": "IGNORED_BLACK"})

        elif op_type == "KMEMLEAK_NOT_LEAK":
            ptr = op["ptr"]
            if ptr in objects:
                objects[ptr]["min_count"] = 0
                stats["false_positive_mitigations"] += 1
                op_log.append({"op": "KMEMLEAK_NOT_LEAK", "ptr": ptr, "status": "MARKED_NOT_LEAK"})

        elif op_type == "SCAN":
            stats["scan_runs"] += 1
            for obj in objects.values():
                if obj["state"] == "ACTIVE":
                    obj["count"] = 0

            gray_list = []

            for r in roots:
                target_obj = find_object_containing(r)
                if target_obj and target_obj["state"] == "ACTIVE":
                    target_obj["count"] += 1

            for obj in objects.values():
                if obj["state"] == "ACTIVE" and not obj["is_black"]:
                    if obj["min_count"] == 0 or obj["count"] >= obj["min_count"]:
                        gray_list.append(obj)

            visited_gray = set(obj["ptr"] for obj in gray_list)

            while gray_list:
                curr_obj = gray_list.pop(0)
                start_w = curr_obj["ptr"]
                end_w = curr_obj["ptr"] + curr_obj["size"]
                for w_addr in range(start_w, end_w, pointer_size):
                    val = mem_words.get(w_addr)
                    if val is not None:
                        ref_obj = find_object_containing(val)
                        if ref_obj and ref_obj["state"] == "ACTIVE" and not ref_obj["is_black"]:
                            ref_obj["count"] += 1
                            if ref_obj["count"] >= ref_obj["min_count"] and ref_obj["ptr"] not in visited_gray:
                                visited_gray.add(ref_obj["ptr"])
                                gray_list.append(ref_obj)

            suspected_in_this_scan = []
            confirmed_in_this_scan = []

            for obj in objects.values():
                if obj["state"] == "ACTIVE" and not obj["is_black"]:
                    if obj["count"] < obj["min_count"]:
                        obj["unreferenced_cycles"] += 1
                        suspected_in_this_scan.append(obj["ptr"])
                        if obj["unreferenced_cycles"] >= scan_threshold_cycles:
                            confirmed_in_this_scan.append({
                                "ptr": obj["ptr"],
                                "size": obj["size"],
                                "backtrace": obj["backtrace"],
                                "unreferenced_cycles": obj["unreferenced_cycles"]
                            })
                    else:
                        obj["unreferenced_cycles"] = 0

            stats["suspected_leaks_count"] = len(suspected_in_this_scan)
            stats["confirmed_leaks_count"] = len(confirmed_in_this_scan)

            scan_history.append({
                "scan_id": stats["scan_runs"],
                "gray_count": len(visited_gray),
                "suspected_leaks": suspected_in_this_scan,
                "confirmed_leaks": confirmed_in_this_scan
            })
            op_log.append({
                "op": "SCAN",
                "scan_id": stats["scan_runs"],
                "suspected_leaks_count": len(suspected_in_this_scan),
                "confirmed_leaks_count": len(confirmed_in_this_scan)
            })

    active_objs = [
        {
            "ptr": o["ptr"],
            "size": o["size"],
            "count": o["count"],
            "min_count": o["min_count"],
            "is_black": o["is_black"],
            "unreferenced_cycles": o["unreferenced_cycles"],
            "backtrace": o["backtrace"]
        }
        for o in sorted(objects.values(), key=lambda x: x["ptr"]) if o["state"] == "ACTIVE"
    ]

    result = {
        "pointer_size": pointer_size,
        "scan_threshold_cycles": scan_threshold_cycles,
        "active_objects_count": len(active_objs),
        "stats": stats,
        "scan_history": scan_history,
        "active_objects": active_objs,
        "op_log": op_log
    }

    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
