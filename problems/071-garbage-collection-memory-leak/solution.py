import sys
from collections import OrderedDict

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    heap_max_mb = 512
    lru_cap = 3
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "HEAP_MAX_MB":
                heap_max_mb = int(parts[1])
            elif parts[0] == "LRU_CACHE_CAPACITY":
                lru_cap = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    # =========================================================================
    # State for Naive Leaky Engine
    # =========================================================================
    n_heap_objs = {}          # obj_id -> size_mb
    n_stack_frames = []       # list of sets of obj_id
    n_static_cache = set()    # unbounded set of obj_id
    n_listeners = set()       # unbounded set of obj_id
    n_oom = False
    n_peak_heap = 0

    # =========================================================================
    # State for Robust Managed GC Engine
    # =========================================================================
    r_heap_objs = {}          # obj_id -> size_mb
    r_stack_frames = []       # list of sets of obj_id
    r_lru_cache = OrderedDict()  # obj_id -> size_mb (OrderedDict for LRU)
    r_listeners = set()       # set of obj_id
    r_oom = False
    r_peak_heap = 0

    out_lines = []
    total_alloc_count = 0
    total_requested_mb = 0

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "PUSH_STACK_FRAME":
            n_stack_frames.append(set())
            r_stack_frames.append(set())
            depth = len(r_stack_frames)
            out_lines.append(f"ACT {act_idx} PUSH_STACK_FRAME")
            out_lines.append(f"  NAIVE: FRAME_DEPTH:{depth}")
            out_lines.append(f"  ROBUST: FRAME_DEPTH:{depth}")

        elif cmd == "POP_STACK_FRAME":
            if n_stack_frames:
                n_stack_frames.pop()
            if r_stack_frames:
                r_stack_frames.pop()
            depth = len(r_stack_frames)
            out_lines.append(f"ACT {act_idx} POP_STACK_FRAME")
            out_lines.append(f"  NAIVE: FRAME_DEPTH:{depth}")
            out_lines.append(f"  ROBUST: FRAME_DEPTH:{depth}")

        elif cmd == "ALLOC_OBJECT":
            obj_id = act[1]
            size_mb = int(act[2])
            target_type = act[3]

            total_alloc_count += 1
            total_requested_mb += size_mb

            # 1. Naive Engine
            n_heap_objs[obj_id] = size_mb
            if target_type == "STACK":
                if not n_stack_frames:
                    n_stack_frames.append(set())
                n_stack_frames[-1].add(obj_id)
            elif target_type == "STATIC_CACHE":
                n_static_cache.add(obj_id)
            elif target_type == "LISTENER":
                n_listeners.add(obj_id)

            n_used = sum(n_heap_objs.values())
            n_peak_heap = max(n_peak_heap, n_used)
            if n_used > heap_max_mb:
                n_oom = True
            n_status = "OOM_CRASH" if n_oom else "OK"

            # 2. Robust Engine
            evicted_str = ""
            if target_type == "STATIC_CACHE":
                if len(r_lru_cache) >= lru_cap and obj_id not in r_lru_cache:
                    # Evict least recently used (first item in OrderedDict)
                    evicted_id, _ = r_lru_cache.popitem(last=False)
                    evicted_str = f" [EVICTED:{evicted_id}]"
                r_lru_cache[obj_id] = size_mb
                r_lru_cache.move_to_end(obj_id)
            elif target_type == "STACK":
                if not r_stack_frames:
                    r_stack_frames.append(set())
                r_stack_frames[-1].add(obj_id)
            elif target_type == "LISTENER":
                r_listeners.add(obj_id)

            r_heap_objs[obj_id] = size_mb
            r_used = sum(r_heap_objs.values())
            r_peak_heap = max(r_peak_heap, r_used)
            if r_used > heap_max_mb:
                r_oom = True
            r_status = "OOM_CRASH" if r_oom else "OK"

            out_lines.append(f"ACT {act_idx} ALLOC_OBJECT {obj_id} SIZE:{size_mb}MB TARGET:{target_type}")
            out_lines.append(f"  NAIVE: ALLOCATED HEAP_USED:{n_used}MB/{heap_max_mb}MB STATUS:{n_status}")
            out_lines.append(f"  ROBUST: ALLOCATED HEAP_USED:{r_used}MB/{heap_max_mb}MB STATUS:{r_status}{evicted_str}")

        elif cmd == "UNSUBSCRIBE_LISTENER":
            obj_id = act[1]

            # Naive ignores unsubscribe (simulating developer omission)
            # Robust removes from listeners set
            if obj_id in r_listeners:
                r_listeners.remove(obj_id)

            out_lines.append(f"ACT {act_idx} UNSUBSCRIBE_LISTENER {obj_id}")
            out_lines.append("  NAIVE: IGNORED_LEAKING")
            out_lines.append("  ROBUST: UNLINKED_FROM_ROOT")

        elif cmd == "TRIGGER_GC":
            # 1. Naive GC
            # Roots: stack frames + static_cache + listeners
            n_roots = set()
            for f in n_stack_frames:
                n_roots.update(f)
            n_roots.update(n_static_cache)
            n_roots.update(n_listeners)

            n_reclaimed = 0
            for o_id in list(n_heap_objs.keys()):
                if o_id not in n_roots:
                    n_reclaimed += n_heap_objs[o_id]
                    del n_heap_objs[o_id]

            n_rem = sum(n_heap_objs.values())
            n_live = len(n_heap_objs)
            if n_rem <= heap_max_mb:
                n_oom = False

            # 2. Robust GC
            r_roots = set()
            for f in r_stack_frames:
                r_roots.update(f)
            r_roots.update(r_lru_cache.keys())
            r_roots.update(r_listeners)

            r_reclaimed = 0
            for o_id in list(r_heap_objs.keys()):
                if o_id not in r_roots:
                    r_reclaimed += r_heap_objs[o_id]
                    del r_heap_objs[o_id]

            r_rem = sum(r_heap_objs.values())
            r_live = len(r_heap_objs)
            if r_rem <= heap_max_mb:
                r_oom = False

            out_lines.append(f"ACT {act_idx} TRIGGER_GC")
            out_lines.append(f"  NAIVE: RECLAIMED:{n_reclaimed}MB REMAINING_HEAP:{n_rem}MB/{heap_max_mb}MB LIVE_OBJS:{n_live}")
            out_lines.append(f"  ROBUST: RECLAIMED:{r_reclaimed}MB REMAINING_HEAP:{r_rem}MB/{heap_max_mb}MB LIVE_OBJS:{r_live}")

        elif cmd == "CHECK_MEMORY":
            # Leaked objects in Naive: objects in static_cache that exceed lru_cap or listeners that should have been freed
            # More formally: any object in naive that is not currently in robust heap
            leaked_cnt = max(0, len(n_heap_objs) - len(r_heap_objs))
            n_used = sum(n_heap_objs.values())
            r_used = sum(r_heap_objs.values())

            if n_oom:
                n_health = "OOM_CRASH"
            elif leaked_cnt > 0:
                n_health = "CRITICAL_LEAK"
            else:
                n_health = "HEALTHY"

            r_health = "OOM_CRASH" if r_oom else "HEALTHY"

            out_lines.append(f"ACT {act_idx} CHECK_MEMORY")
            out_lines.append(f"  NAIVE: HEAP:{n_used}MB LEAKED_OBJECTS:{leaked_cnt} HEALTH:{n_health}")
            out_lines.append(f"  ROBUST: HEAP:{r_used}MB LEAKED_OBJECTS:0 HEALTH:{r_health}")

    # Summary
    n_final = sum(n_heap_objs.values())
    r_final = sum(r_heap_objs.values())
    saved_mb = max(0, n_final - r_final)
    efficiency = (saved_mb / n_final * 100.0) if n_final > 0 else 0.0
    final_leaked = max(0, len(n_heap_objs) - len(r_heap_objs))

    out_lines.append(f"SUMMARY TOTAL_ALLOCATIONS:{total_alloc_count} (TOTAL_REQUESTED:{total_requested_mb}MB)")
    out_lines.append(f"SUMMARY NAIVE PEAK_HEAP:{n_peak_heap}MB FINAL_HEAP:{n_final}MB OOM_CRASH:{'YES' if n_oom else 'NO'} LEAKED_OBJS:{final_leaked}")
    out_lines.append(f"SUMMARY ROBUST PEAK_HEAP:{r_peak_heap}MB FINAL_HEAP:{r_final}MB OOM_CRASH:NO LEAKED_OBJS:0")
    out_lines.append(f"SUMMARY MEMORY_SAVED:{saved_mb}MB (EFFICIENCY:{efficiency:.2f}%)")
    out_lines.append("SUMMARY GC_MANAGEMENT_VERDICT: ROBUST_PREVENTS_OOM")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
