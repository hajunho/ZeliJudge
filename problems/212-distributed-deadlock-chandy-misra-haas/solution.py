import sys
import json
from collections import defaultdict
import heapq

def simulate_distributed_deadlock(data):
    config = data.get("config", {})
    mode = config.get("mode", "CHANDY_MISRA_HAAS_EDGE_CHASING")
    victim_policy = config.get("victim_policy", "YOUNGEST")
    coordinator_interval = config.get("coordinator_interval_ms", 100)
    coordinator_network_delay = config.get("coordinator_network_delay_ms", 50)
    probe_network_delay = config.get("probe_network_delay_ms", 5)

    tx_info = {}
    for tx in data.get("transactions", []):
        tx_info[tx["tx_id"]] = {
            "tx_id": tx["tx_id"],
            "home_node": tx.get("node", "node-1"),
            "priority": tx.get("priority", 10),
            "start_time": tx.get("start_time", 0),
            "status": "ACTIVE", # ACTIVE, BLOCKED, COMMITTED, ABORTED
            "waiting_for_tx": None,
            "waiting_for_res": None,
            "held_locks": set(),
        }

    resources = {}
    for r in data.get("resources", []):
        key = (r["node"], r["resource_id"])
        resources[key] = {
            "holder": None,
            "wait_queue": []
        }

    events = sorted(data.get("events", []), key=lambda x: x["timestamp"])

    metrics = {
        "total_events_processed": len(events),
        "local_cycles_detected": 0,
        "distributed_cycles_detected": 0,
        "phantom_deadlocks_detected": 0,
        "probes_initiated": 0,
        "probes_forwarded": 0,
        "coordinator_messages_sent": 0,
        "aborted_transactions": [],
        "committed_transactions": [],
        "deadlock_resolution_latencies_ms": []
    }

    if mode == "CHANDY_MISRA_HAAS_EDGE_CHASING":
        pq = []
        counter = 0
        for ev in events:
            counter += 1
            heapq.heappush(pq, (ev["timestamp"], 0, counter, "CLIENT_EVENT", ev))

        def abort_transaction_cmh(victim_id, current_time, init_time):
            v_info = tx_info[victim_id]
            if v_info["status"] in ("ABORTED", "COMMITTED"):
                return
            v_info["status"] = "ABORTED"
            if victim_id not in metrics["aborted_transactions"]:
                metrics["aborted_transactions"].append(victim_id)
            if v_info["waiting_for_res"]:
                r_key = v_info["waiting_for_res"]
                if r_key in resources and victim_id in resources[r_key]["wait_queue"]:
                    resources[r_key]["wait_queue"].remove(victim_id)
                v_info["waiting_for_res"] = None
                v_info["waiting_for_tx"] = None

            for r_key in list(v_info["held_locks"]):
                r_obj = resources[r_key]
                if r_obj["holder"] == victim_id:
                    r_obj["holder"] = None
                    if r_obj["wait_queue"]:
                        next_tx = r_obj["wait_queue"].pop(0)
                        r_obj["holder"] = next_tx
                        tx_info[next_tx]["held_locks"].add(r_key)
                        tx_info[next_tx]["waiting_for_res"] = None
                        tx_info[next_tx]["waiting_for_tx"] = None
                        tx_info[next_tx]["status"] = "ACTIVE"
            v_info["held_locks"].clear()
            latency = current_time - init_time
            metrics["deadlock_resolution_latencies_ms"].append(latency)

        while pq:
            current_time, priority_tag, _, ev_type, payload = heapq.heappop(pq)

            if ev_type == "CLIENT_EVENT":
                action = payload["action"]
                tx_id = payload["tx_id"]
                if tx_id not in tx_info:
                    continue
                t_ctx = tx_info[tx_id]
                if t_ctx["status"] == "ABORTED":
                    continue

                if action == "ACQUIRE_LOCK":
                    res_key = (payload["node"], payload["resource_id"])
                    if res_key not in resources:
                        resources[res_key] = {"holder": None, "wait_queue": []}
                    res_obj = resources[res_key]
                    if res_obj["holder"] is None:
                        res_obj["holder"] = tx_id
                        t_ctx["held_locks"].add(res_key)
                    else:
                        holder_id = res_obj["holder"]
                        if holder_id != tx_id:
                            t_ctx["status"] = "BLOCKED"
                            t_ctx["waiting_for_res"] = res_key
                            t_ctx["waiting_for_tx"] = holder_id
                            res_obj["wait_queue"].append(tx_id)

                            metrics["probes_initiated"] += 1
                            holder_node = tx_info[holder_id]["home_node"]
                            delay = 0 if payload["node"] == t_ctx["home_node"] and holder_node == t_ctx["home_node"] else probe_network_delay
                            probe_data = {
                                "initiator": tx_id,
                                "sender": tx_id,
                                "receiver": holder_id,
                                "at_node": holder_node,
                                "initiated_time": current_time,
                                "path": [tx_id]
                            }
                            counter += 1
                            heapq.heappush(pq, (current_time + delay, 1, counter, "PROBE_ARRIVE", probe_data))

                elif action == "RELEASE_LOCK":
                    res_key = (payload["node"], payload["resource_id"])
                    if res_key in resources and resources[res_key]["holder"] == tx_id:
                        resources[res_key]["holder"] = None
                        t_ctx["held_locks"].discard(res_key)
                        if resources[res_key]["wait_queue"]:
                            next_tx = resources[res_key]["wait_queue"].pop(0)
                            resources[res_key]["holder"] = next_tx
                            tx_info[next_tx]["held_locks"].add(res_key)
                            tx_info[next_tx]["waiting_for_res"] = None
                            tx_info[next_tx]["waiting_for_tx"] = None
                            tx_info[next_tx]["status"] = "ACTIVE"

                elif action == "COMMIT":
                    if t_ctx["status"] == "ACTIVE":
                        t_ctx["status"] = "COMMITTED"
                        if tx_id not in metrics["committed_transactions"]:
                            metrics["committed_transactions"].append(tx_id)
                        for res_key in list(t_ctx["held_locks"]):
                            resources[res_key]["holder"] = None
                            if resources[res_key]["wait_queue"]:
                                next_tx = resources[res_key]["wait_queue"].pop(0)
                                resources[res_key]["holder"] = next_tx
                                tx_info[next_tx]["held_locks"].add(res_key)
                                tx_info[next_tx]["waiting_for_res"] = None
                                tx_info[next_tx]["waiting_for_tx"] = None
                                tx_info[next_tx]["status"] = "ACTIVE"
                        t_ctx["held_locks"].clear()

            elif ev_type == "PROBE_ARRIVE":
                initiator = payload["initiator"]
                sender = payload["sender"]
                receiver = payload["receiver"]
                init_time = payload["initiated_time"]
                path = payload["path"]

                if tx_info[initiator]["status"] in ("ABORTED", "COMMITTED"):
                    continue

                rec_ctx = tx_info.get(receiver)
                if not rec_ctx or rec_ctx["status"] in ("ABORTED", "COMMITTED"):
                    continue

                if rec_ctx["status"] != "BLOCKED":
                    continue

                waiting_on = rec_ctx["waiting_for_tx"]
                if not waiting_on:
                    continue

                if waiting_on == initiator:
                    full_cycle = path + [receiver]
                    nodes_in_cycle = set([tx_info[tx]["home_node"] for tx in full_cycle])
                    if len(nodes_in_cycle) == 1:
                        metrics["local_cycles_detected"] += 1
                    else:
                        metrics["distributed_cycles_detected"] += 1

                    cycle_members = [tx for tx in full_cycle if tx_info[tx]["status"] == "BLOCKED"]
                    if not cycle_members:
                        continue
                    if victim_policy == "YOUNGEST":
                        victim = max(cycle_members, key=lambda x: (tx_info[x]["start_time"], tx_info[x]["priority"], tx_info[x]["tx_id"]))
                    else:
                        victim = max(cycle_members, key=lambda x: (tx_info[x]["priority"], tx_info[x]["start_time"], tx_info[x]["tx_id"]))

                    abort_transaction_cmh(victim, current_time, init_time)
                else:
                    if waiting_on not in path:
                        metrics["probes_forwarded"] += 1
                        next_node = tx_info[waiting_on]["home_node"]
                        curr_node = rec_ctx["home_node"]
                        delay = 0 if next_node == curr_node else probe_network_delay
                        next_probe = {
                            "initiator": initiator,
                            "sender": receiver,
                            "receiver": waiting_on,
                            "at_node": next_node,
                            "initiated_time": init_time,
                            "path": path + [receiver]
                        }
                        counter += 1
                        heapq.heappush(pq, (current_time + delay, 1, counter, "PROBE_ARRIVE", next_probe))

    elif mode == "CENTRALIZED_WFG_COORDINATOR":
        max_time = max([e["timestamp"] for e in events]) + 500
        coordinator_events = []

        tx_status = {k: v for k, v in tx_info.items()}
        ev_idx = 0
        n_events = len(events)
        active_edges_at_node = defaultdict(set)

        coord_internal_graph = defaultdict(set)
        processed_coord_ev_idx = 0

        for current_time in range(0, max_time + 1):
            while ev_idx < n_events and events[ev_idx]["timestamp"] == current_time:
                payload = events[ev_idx]
                ev_idx += 1
                action = payload["action"]
                tx_id = payload["tx_id"]
                t_ctx = tx_status[tx_id]
                if t_ctx["status"] == "ABORTED":
                    continue

                if action == "ACQUIRE_LOCK":
                    res_key = (payload["node"], payload["resource_id"])
                    if res_key not in resources:
                        resources[res_key] = {"holder": None, "wait_queue": []}
                    res_obj = resources[res_key]
                    if res_obj["holder"] is None:
                        res_obj["holder"] = tx_id
                        t_ctx["held_locks"].add(res_key)
                    else:
                        holder_id = res_obj["holder"]
                        if holder_id != tx_id:
                            t_ctx["status"] = "BLOCKED"
                            t_ctx["waiting_for_res"] = res_key
                            t_ctx["waiting_for_tx"] = holder_id
                            res_obj["wait_queue"].append(tx_id)
                            edge = (tx_id, holder_id)
                            active_edges_at_node[payload["node"]].add(edge)
                            coordinator_events.append((current_time + coordinator_network_delay, "ADD_EDGE", edge))
                            metrics["coordinator_messages_sent"] += 1

                elif action == "RELEASE_LOCK":
                    res_key = (payload["node"], payload["resource_id"])
                    if res_key in resources and resources[res_key]["holder"] == tx_id:
                        resources[res_key]["holder"] = None
                        t_ctx["held_locks"].discard(res_key)
                        if resources[res_key]["wait_queue"]:
                            next_tx = resources[res_key]["wait_queue"].pop(0)
                            resources[res_key]["holder"] = next_tx
                            tx_status[next_tx]["held_locks"].add(res_key)
                            old_edge = (next_tx, tx_id)
                            active_edges_at_node[payload["node"]].discard(old_edge)
                            coordinator_events.append((current_time + coordinator_network_delay, "DEL_EDGE", old_edge))
                            metrics["coordinator_messages_sent"] += 1
                            tx_status[next_tx]["waiting_for_res"] = None
                            tx_status[next_tx]["waiting_for_tx"] = None
                            tx_status[next_tx]["status"] = "ACTIVE"

                elif action == "COMMIT":
                    if t_ctx["status"] == "ACTIVE":
                        t_ctx["status"] = "COMMITTED"
                        if tx_id not in metrics["committed_transactions"]:
                            metrics["committed_transactions"].append(tx_id)
                        for res_key in list(t_ctx["held_locks"]):
                            resources[res_key]["holder"] = None
                            if resources[res_key]["wait_queue"]:
                                next_tx = resources[res_key]["wait_queue"].pop(0)
                                resources[res_key]["holder"] = next_tx
                                tx_status[next_tx]["held_locks"].add(res_key)
                                old_edge = (next_tx, tx_id)
                                active_edges_at_node[res_key[0]].discard(old_edge)
                                coordinator_events.append((current_time + coordinator_network_delay, "DEL_EDGE", old_edge))
                                metrics["coordinator_messages_sent"] += 1
                                tx_status[next_tx]["waiting_for_res"] = None
                                tx_status[next_tx]["waiting_for_tx"] = None
                                tx_status[next_tx]["status"] = "ACTIVE"
                        t_ctx["held_locks"].clear()

            if current_time > 0 and current_time % coordinator_interval == 0:
                while processed_coord_ev_idx < len(coordinator_events):
                    arr_time, m_type, edge = coordinator_events[processed_coord_ev_idx]
                    if arr_time <= current_time:
                        u, v = edge
                        if m_type == "ADD_EDGE":
                            coord_internal_graph[u].add(v)
                        elif m_type == "DEL_EDGE":
                            coord_internal_graph[u].discard(v)
                        processed_coord_ev_idx += 1
                    else:
                        break

                def find_cycles(adj):
                    visited = {}
                    cycles = []
                    def dfs(node, path):
                        visited[node] = 1
                        for neighbor in sorted(list(adj.get(node, []))):
                            if visited.get(neighbor, 0) == 1:
                                idx = path.index(neighbor)
                                cycles.append(path[idx:])
                            elif visited.get(neighbor, 0) == 0:
                                dfs(neighbor, path + [neighbor])
                        visited[node] = 2

                    for n in sorted(list(adj.keys())):
                        if visited.get(n, 0) == 0:
                            dfs(n, [n])
                    return cycles

                detected_cycles = find_cycles(coord_internal_graph)
                if detected_cycles:
                    for cycle in detected_cycles:
                        is_real = True
                        for i in range(len(cycle)):
                            u = cycle[i]
                            v = cycle[(i + 1) % len(cycle)]
                            if tx_status[u]["status"] != "BLOCKED" or tx_status[u]["waiting_for_tx"] != v:
                                is_real = False
                                break

                        if victim_policy == "YOUNGEST":
                            victim = max(cycle, key=lambda x: (tx_status[x]["start_time"], tx_status[x]["priority"], tx_status[x]["tx_id"]))
                        else:
                            victim = max(cycle, key=lambda x: (tx_status[x]["priority"], tx_status[x]["start_time"], tx_status[x]["tx_id"]))

                        if is_real:
                            nodes_in_cycle = set([tx_status[tx]["home_node"] for tx in cycle])
                            if len(nodes_in_cycle) == 1:
                                metrics["local_cycles_detected"] += 1
                            else:
                                metrics["distributed_cycles_detected"] += 1
                        else:
                            metrics["phantom_deadlocks_detected"] += 1

                        if tx_status[victim]["status"] != "ABORTED":
                            tx_status[victim]["status"] = "ABORTED"
                            if victim not in metrics["aborted_transactions"]:
                                metrics["aborted_transactions"].append(victim)
                            if victim in coord_internal_graph:
                                del coord_internal_graph[victim]
                            for u in coord_internal_graph:
                                coord_internal_graph[u].discard(victim)

                            if tx_status[victim]["waiting_for_res"]:
                                r_key = tx_status[victim]["waiting_for_res"]
                                if r_key in resources and victim in resources[r_key]["wait_queue"]:
                                    resources[r_key]["wait_queue"].remove(victim)
                                tx_status[victim]["waiting_for_res"] = None
                                tx_status[victim]["waiting_for_tx"] = None
                            for r_key in list(tx_status[victim]["held_locks"]):
                                resources[r_key]["holder"] = None
                                if resources[r_key]["wait_queue"]:
                                    next_tx = resources[r_key]["wait_queue"].pop(0)
                                    resources[r_key]["holder"] = next_tx
                                    tx_status[next_tx]["held_locks"].add(r_key)
                                    tx_status[next_tx]["waiting_for_res"] = None
                                    tx_status[next_tx]["waiting_for_tx"] = None
                                    tx_status[next_tx]["status"] = "ACTIVE"
                            tx_status[victim]["held_locks"].clear()

    if metrics["phantom_deadlocks_detected"] > 0:
        verdict = "PHANTOM_DEADLOCK_FALSE_ABORT"
        status = "FAILED"
    elif metrics["distributed_cycles_detected"] > 0 or metrics["local_cycles_detected"] > 0:
        verdict = "DEADLOCK_DETECTED_CYCLE_RESOLVED"
        status = "SUCCESS"
    elif len(metrics["committed_transactions"]) > 0 and len(metrics["aborted_transactions"]) == 0:
        verdict = "NO_DEADLOCK_EXECUTION_COMPLETED"
        status = "SUCCESS"
    else:
        verdict = "UNRESOLVED_EXECUTION_STALL"
        status = "FAILED"

    avg_res_latency = (sum(metrics["deadlock_resolution_latencies_ms"]) / len(metrics["deadlock_resolution_latencies_ms"])) if metrics["deadlock_resolution_latencies_ms"] else 0.0

    return {
        "status": status,
        "verdict": verdict,
        "mode": mode,
        "metrics": {
            "total_events_processed": metrics["total_events_processed"],
            "local_cycles_detected": metrics["local_cycles_detected"],
            "distributed_cycles_detected": metrics["distributed_cycles_detected"],
            "phantom_deadlocks_detected": metrics["phantom_deadlocks_detected"],
            "probes_initiated": metrics["probes_initiated"],
            "probes_forwarded": metrics["probes_forwarded"],
            "coordinator_messages_sent": metrics["coordinator_messages_sent"],
            "aborted_transactions": metrics["aborted_transactions"],
            "committed_transactions": metrics["committed_transactions"],
            "average_resolution_latency_ms": round(avg_res_latency, 2)
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_distributed_deadlock(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
