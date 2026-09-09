#!/usr/bin/env python3
import sys
from bisect import bisect_left

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)

    # 1. ?? ?? ??
    N = int(next(it))
    nodes = {}  # name -> ring_pos
    for _ in range(N):
        cmd = next(it)  # INIT_NODE
        name = next(it)
        pos = int(next(it))
        nodes[name] = pos

    # 2. ? ??
    K = int(next(it))
    keys = []  # [(name, hash_val), ...]
    key_hashes = []
    for _ in range(K):
        cmd = next(it)  # KEY
        kname = next(it)
        hval = int(next(it))
        keys.append((kname, hval))
        key_hashes.append(hval)

    # ? ? ?? ?? ?? ??
    def build_caches():
        sorted_names = sorted(nodes.keys())
        ring_items = sorted(nodes.items(), key=lambda x: x[1])
        ring_positions = [pos for _, pos in ring_items]
        ring_node_names = [name for name, _ in ring_items]
        return sorted_names, ring_positions, ring_node_names

    sorted_names, ring_positions, ring_node_names = build_caches()

    # 3. ?? ? ?? ??
    prev_mod = []
    prev_con = []
    mod_len = len(sorted_names)
    ring_len = len(ring_positions)

    for h in key_hashes:
        # Modulo
        m_node = sorted_names[h % mod_len]
        prev_mod.append(m_node)

        # Consistent Hash (bisect_left)
        idx = bisect_left(ring_positions, h)
        if idx == ring_len:
            idx = 0
        c_node = ring_node_names[idx]
        prev_con.append(c_node)

    # 4. ??? ?? ? ??
    E = int(next(it))
    total_mod_moved = 0
    total_con_moved = 0

    for _ in range(E):
        event_type = next(it)  # ADD_NODE or REMOVE_NODE
        if event_type == "ADD_NODE":
            nname = next(it)
            npos = int(next(it))
            nodes[nname] = npos
            event_tag = "ADD"
            target_name = nname
        elif event_type == "REMOVE_NODE":
            nname = next(it)
            del nodes[nname]
            event_tag = "REMOVE"
            target_name = nname
        else:
            raise ValueError(f"Unknown event type: {event_type}")

        # ?? ??
        sorted_names, ring_positions, ring_node_names = build_caches()
        mod_len = len(sorted_names)
        ring_len = len(ring_positions)

        new_mod = []
        new_con = []
        m_moved = 0
        c_moved = 0

        for i, h in enumerate(key_hashes):
            nm_node = sorted_names[h % mod_len]
            if nm_node != prev_mod[i]:
                m_moved += 1
            new_mod.append(nm_node)

            idx = bisect_left(ring_positions, h)
            if idx == ring_len:
                idx = 0
            nc_node = ring_node_names[idx]
            if nc_node != prev_con[i]:
                c_moved += 1
            new_con.append(nc_node)

        print(f"EVENT {event_tag} {target_name} MODULO_MOVED:{m_moved}/{K} CONSISTENT_MOVED:{c_moved}/{K}")
        total_mod_moved += m_moved
        total_con_moved += c_moved
        prev_mod = new_mod
        prev_con = new_con

    print(f"SUMMARY TOTAL_EVENTS:{E} TOTAL_MODULO_MOVED:{total_mod_moved} TOTAL_CONSISTENT_MOVED:{total_con_moved}")

if __name__ == '__main__':
    solve()
