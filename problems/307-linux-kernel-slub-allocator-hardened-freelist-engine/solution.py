# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #307: 리눅스 커널 SLUB 메모리 할당자 Fast/Slow Path 및 Hardened Freelist 엔진
Linux Kernel mm/slub.c kmem_cache_cpu Fast Path, kmem_cache_node Slow Path,
CONFIG_SLAB_FREELIST_HARDENED XOR 무결성 검증 및 부분 슬랩 회수 시뮬레이션
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_slub_engine(data):
    config = data.get("config", {})
    obj_size = config.get("object_size", 64)
    objs_per_slab = config.get("objects_per_slab", 8)
    cookie = config.get("hardened_cookie", 0x12345678)
    min_partial = config.get("min_partial", 2)

    ops = data.get("operations", [])

    slab_counter = 0
    alloc_map = {}
    cpu_slabs = {}
    node_partial = []

    op_results = []
    panic_occurred = False

    def make_new_slab():
        nonlocal slab_counter
        slab_counter += 1
        s_id = slab_counter
        return {
            "slab_id": s_id,
            "base_addr": s_id * 0x1000,
            "objects": objs_per_slab,
            "inuse": 0,
            "freelist": list(range(objs_per_slab)),
            "page_freelist": []
        }

    total_allocs = 0
    total_frees = 0
    fast_path_cnt = 0
    slow_path_cnt = 0

    for op in ops:
        op_id = op["op_id"]
        op_type = op["type"]

        if panic_occurred:
            op_results.append({
                "op_id": op_id,
                "status": "PANIC_IGNORED",
                "alloc_path": None,
                "alloc_id": op.get("alloc_id")
            })
            continue

        if op_type == "ALLOC":
            cpu = op["cpu"]
            a_id = op["alloc_id"]
            total_allocs += 1

            if cpu not in cpu_slabs:
                cpu_slabs[cpu] = {"slab": None, "freelist": []}

            c = cpu_slabs[cpu]
            alloc_path = None
            allocated_obj = None

            # 1. Fast Path: c->freelist has free slots
            if c["freelist"]:
                obj_idx = c["freelist"].pop(0)
                alloc_path = "FAST_PATH"
                fast_path_cnt += 1
                c["slab"]["inuse"] += 1
                allocated_obj = (c["slab"], obj_idx)

            # 2. Slow Path Step 1: c->page->page_freelist
            elif c["slab"] and c["slab"]["page_freelist"]:
                c["freelist"] = list(c["slab"]["page_freelist"])
                c["slab"]["page_freelist"] = []
                obj_idx = c["freelist"].pop(0)
                alloc_path = "PAGE_FREELIST"
                slow_path_cnt += 1
                c["slab"]["inuse"] += 1
                allocated_obj = (c["slab"], obj_idx)

            # 3. Slow Path Step 2: kmem_cache_node partial list
            elif node_partial:
                new_slab = node_partial.pop(0)
                c["slab"] = new_slab
                c["freelist"] = list(new_slab["freelist"])
                new_slab["freelist"] = []
                obj_idx = c["freelist"].pop(0)
                alloc_path = "NODE_PARTIAL"
                slow_path_cnt += 1
                c["slab"]["inuse"] += 1
                allocated_obj = (c["slab"], obj_idx)

            # 4. Slow Path Step 3: Buddy allocator new slab
            else:
                new_slab = make_new_slab()
                c["slab"] = new_slab
                c["freelist"] = list(new_slab["freelist"])
                new_slab["freelist"] = []
                obj_idx = c["freelist"].pop(0)
                alloc_path = "NEW_SLAB"
                slow_path_cnt += 1
                c["slab"]["inuse"] += 1
                allocated_obj = (c["slab"], obj_idx)

            slab_ref, o_idx = allocated_obj
            obj_addr = slab_ref["base_addr"] + o_idx * obj_size
            alloc_map[a_id] = {
                "slab_id": slab_ref["slab_id"],
                "obj_idx": o_idx,
                "obj_addr": hex(obj_addr),
                "cpu": cpu
            }

            op_results.append({
                "op_id": op_id,
                "type": "ALLOC",
                "alloc_id": a_id,
                "status": "SUCCESS",
                "alloc_path": alloc_path,
                "slab_id": slab_ref["slab_id"],
                "obj_idx": o_idx,
                "obj_addr": hex(obj_addr)
            })

        elif op_type == "FREE":
            cpu = op["cpu"]
            a_id = op["alloc_id"]
            total_frees += 1

            if a_id not in alloc_map:
                op_results.append({
                    "op_id": op_id,
                    "type": "FREE",
                    "alloc_id": a_id,
                    "status": "DOUBLE_FREE_OR_INVALID"
                })
                continue

            info = alloc_map.pop(a_id)
            s_id = info["slab_id"]
            o_idx = info["obj_idx"]

            target_slab = None
            for c_id, c in cpu_slabs.items():
                if c["slab"] and c["slab"]["slab_id"] == s_id:
                    target_slab = c["slab"]
                    if c_id == cpu:
                        c["freelist"].insert(0, o_idx)
                    else:
                        target_slab["page_freelist"].append(o_idx)
                    break

            if not target_slab:
                for s in node_partial:
                    if s["slab_id"] == s_id:
                        target_slab = s
                        s["freelist"].append(o_idx)
                        break

            status = "FREE_SUCCESS"
            if target_slab:
                target_slab["inuse"] -= 1
                if target_slab["inuse"] == 0:
                    if target_slab in node_partial and len(node_partial) > min_partial:
                        node_partial.remove(target_slab)
                        status = "SLAB_DISCARDED_TO_BUDDY"

            op_results.append({
                "op_id": op_id,
                "type": "FREE",
                "alloc_id": a_id,
                "status": status,
                "slab_id": s_id,
                "obj_idx": o_idx
            })

        elif op_type == "CORRUPT_FREELIST":
            raw_val = op.get("corrupted_raw_ptr", 0x4141414141414141)
            panic_occurred = True
            op_results.append({
                "op_id": op_id,
                "type": "CORRUPT_FREELIST",
                "status": "KERNEL_PANIC_FREELIST_CORRUPTION",
                "detected_corrupted_ptr": hex(raw_val)
            })

    return {
        "summary": {
            "total_allocations": total_allocs,
            "total_frees": total_frees,
            "fast_path_allocations": fast_path_cnt,
            "slow_path_allocations": slow_path_cnt,
            "active_slabs_in_node_partial": len(node_partial),
            "panic_triggered": panic_occurred
        },
        "operations": op_results
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_slub_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
