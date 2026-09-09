import sys

def solve():
    input_text = sys.stdin.read()
    if not input_text.strip():
        return

    lines = input_text.splitlines()
    idx = 0
    nodes = {}

    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        if line == "NODES":
            while idx < len(lines):
                nline = lines[idx].strip()
                if not nline or nline == "ACTIONS":
                    break
                idx += 1
                parts = nline.split()
                nodes[parts[0]] = int(parts[1])
        elif line == "ACTIONS":
            break

    raw_actions = []
    act_idx = 0
    while idx < len(lines):
        aline = lines[idx].strip()
        idx += 1
        if not aline:
            continue
        parts = aline.split()
        raw_actions.append((parts[0], act_idx, parts[1:]))
        act_idx += 1

    sim_queue = []
    for act_type, act_i, args in raw_actions:
        if act_type == "LOCAL":
            ev_id, node, r_t = args[0], args[1], int(args[2])
            sim_queue.append((r_t, act_i, 1, "LOCAL", ev_id, node))
        elif act_type == "MESSAGE":
            msg_id, src, dst, send_t, delay = args[0], args[1], args[2], int(args[3]), int(args[4])
            sim_queue.append((send_t, act_i, 0, "SEND", f"{msg_id}_SEND", src, msg_id))
            sim_queue.append((send_t + delay, act_i, 2, "RECV", f"{msg_id}_RECV", dst, src, msg_id))

    sim_queue.sort(key=lambda x: (x[0], x[1], x[2]))

    lamport_clocks = {n: 0 for n in nodes}
    node_prev_event = {n: None for n in nodes}
    msg_send_lamp = {}
    all_events = []
    edges = []

    for item in sim_queue:
        r_t, act_i, _, ev_type = item[0], item[1], item[2], item[3]

        if ev_type == "LOCAL":
            ev_id, node = item[4], item[5]
            lamport_clocks[node] += 1
            l_ts = lamport_clocks[node]
            p_ts = r_t + nodes.get(node, 0)
            all_events.append({'id': ev_id, 'node': node, 'phys_ts': p_ts, 'lamp_ts': l_ts})

            if node_prev_event[node]:
                edges.append((node_prev_event[node], ev_id))
            node_prev_event[node] = ev_id

        elif ev_type == "SEND":
            ev_id, src, msg_id = item[4], item[5], item[6]
            lamport_clocks[src] += 1
            l_ts = lamport_clocks[src]
            p_ts = r_t + nodes.get(src, 0)
            msg_send_lamp[msg_id] = l_ts
            all_events.append({'id': ev_id, 'node': src, 'phys_ts': p_ts, 'lamp_ts': l_ts})

            if node_prev_event[src]:
                edges.append((node_prev_event[src], ev_id))
            node_prev_event[src] = ev_id

        elif ev_type == "RECV":
            ev_id, dst, src, msg_id = item[4], item[5], item[6], item[7]
            send_l_ts = msg_send_lamp[msg_id]
            lamport_clocks[dst] = max(lamport_clocks.get(dst, 0), send_l_ts) + 1
            l_ts = lamport_clocks[dst]
            p_ts = r_t + nodes.get(dst, 0)
            all_events.append({'id': ev_id, 'node': dst, 'phys_ts': p_ts, 'lamp_ts': l_ts})

            edges.append((f"{msg_id}_SEND", ev_id))
            if node_prev_event[dst]:
                edges.append((node_prev_event[dst], ev_id))
            node_prev_event[dst] = ev_id

    # Physical Sort
    phys_sorted = sorted(all_events, key=lambda x: (x['phys_ts'], x['node'], x['id']))
    phys_idx = {ev['id']: i for i, ev in enumerate(phys_sorted)}
    phys_inversions = sum(1 for a, b in edges if phys_idx[a] > phys_idx[b])

    # Lamport Sort
    lamp_sorted = sorted(all_events, key=lambda x: (x['lamp_ts'], x['node'], x['id']))
    lamp_idx = {ev['id']: i for i, ev in enumerate(lamp_sorted)}
    lamp_inversions = sum(1 for a, b in edges if lamp_idx[a] > lamp_idx[b])

    for ev in all_events:
        sys.stdout.write(f"EVENT {ev['id']} NODE:{ev['node']} PHYS_TS:{ev['phys_ts']} LAMP_TS:{ev['lamp_ts']}\n")

    sys.stdout.write(f"SUMMARY TOTAL_EVENTS:{len(all_events)} CAUSAL_EDGES:{len(edges)}\n")
    sys.stdout.write(f"SUMMARY PHYSICAL_INVERSIONS:{phys_inversions}\n")
    sys.stdout.write(f"SUMMARY LAMPORT_INVERSIONS:{lamp_inversions}\n")
    sys.stdout.write(f"SUMMARY ANOMALIES_PREVENTED:{phys_inversions}\n")

if __name__ == '__main__':
    solve()
