import sys
import json
import hashlib
from collections import deque

RING_SIZE = 1_000_000

def get_hash_token(key_str):
    h = int(hashlib.md5(key_str.encode("utf-8")).hexdigest()[:8], 16)
    return h % RING_SIZE

def simulate_cassandra_cluster(data):
    config = data.get("config", {})
    node_names = config.get("nodes", ["node1", "node2", "node3", "node4", "node5", "node6"])
    num_nodes = len(node_names)
    vnodes_per_node = int(config.get("vnodes_per_node", 128))
    rf = int(config.get("replication_factor", 3))
    throttle_kb_per_sec = float(config.get("hint_throttle_kb_per_sec", 0.0))
    max_hint_window_ms = float(config.get("max_hint_window_ms", 1800000.0))

    ring = []
    for node in node_names:
        for v in range(vnodes_per_node):
            t = get_hash_token(f"{node}_vnode_{v}")
            ring.append((t, node))
    ring.sort(key=lambda x: x[0])

    node_ownership = {n: 0 for n in node_names}
    num_tokens = len(ring)
    for i in range(num_tokens):
        prev_token = ring[i - 1][0] if i > 0 else ring[-1][0]
        curr_token = ring[i][0]
        node = ring[i][1]

        if curr_token >= prev_token:
            range_len = curr_token - prev_token
        else:
            range_len = (RING_SIZE - prev_token) + curr_token
        node_ownership[node] += range_len

    ownership_values = [v / RING_SIZE * 100.0 for v in node_ownership.values()]
    avg_own = sum(ownership_values) / num_nodes
    max_own = max(ownership_values)
    min_own = min(ownership_values)
    skew_ratio = max_own / min_own if min_own > 0 else 999.0
    variance = sum((x - avg_own) ** 2 for x in ownership_values) / num_nodes
    std_dev = variance ** 0.5
    cv = (std_dev / avg_own) * 100.0 if avg_own > 0 else 0.0

    events = data.get("workload_events", [])
    node_status = {n: "UP" for n in node_names}
    node_down_since = {n: None for n in node_names}

    coordinator_hints = {n: {target: [] for target in node_names if target != n} for n in node_names}
    total_hints_created = 0
    total_hints_replayed = 0
    total_hints_expired = 0
    dropped_mutations = 0
    replica_flapped = False

    replica_mutation_queues = {n: deque() for n in node_names}
    queue_capacity = 1000
    drain_rate_per_sec = 500

    is_skew_test = bool(config.get("skew_evaluation_only", False))
    current_time_ms = 0.0

    for ev in events:
        ev_type = ev.get("type")
        time_ms = float(ev.get("time_ms", current_time_ms))
        elapsed_sec = (time_ms - current_time_ms) / 1000.0
        current_time_ms = time_ms

        if elapsed_sec > 0:
            for n in node_names:
                if node_status[n] == "UP":
                    can_drain = int(drain_rate_per_sec * elapsed_sec)
                    while replica_mutation_queues[n] and can_drain > 0:
                        replica_mutation_queues[n].popleft()
                        can_drain -= 1

        if ev_type == "NODE_DOWN":
            target_node = ev["node"]
            node_status[target_node] = "DOWN"
            node_down_since[target_node] = current_time_ms

        elif ev_type == "NODE_UP":
            target_node = ev["node"]
            node_status[target_node] = "UP"
            node_down_since[target_node] = None

            for coord, hints_dict in coordinator_hints.items():
                if target_node not in hints_dict:
                    continue
                hints_list = hints_dict[target_node]
                if not hints_list:
                    continue

                if throttle_kb_per_sec <= 0:
                    blast_count = len(hints_list)
                    q = replica_mutation_queues[target_node]
                    if len(q) + blast_count > queue_capacity:
                        overflow = (len(q) + blast_count) - queue_capacity
                        dropped_mutations += overflow
                        replica_flapped = True
                        node_status[target_node] = "DOWN"
                        break
                    else:
                        for h in hints_list:
                            q.append(h)
                        total_hints_replayed += blast_count
                    hints_dict[target_node] = []
                else:
                    replayed = len(hints_list)
                    total_hints_replayed += replayed
                    hints_dict[target_node] = []

        elif ev_type == "WRITE_BATCH":
            count = int(ev.get("count", 100))
            coord = ev.get("coordinator", "node1")

            for k_idx in range(count):
                key = f"key_{current_time_ms}_{coord}_{k_idx}"
                t = get_hash_token(key)

                replicas = []
                idx = 0
                for r_idx, (ring_tok, r_node) in enumerate(ring):
                    if ring_tok >= t:
                        idx = r_idx
                        break
                pos = idx
                while len(replicas) < rf:
                    r_node = ring[pos % num_tokens][1]
                    if r_node not in replicas:
                        replicas.append(r_node)
                    pos += 1

                for rep in replicas:
                    if node_status[rep] == "UP":
                        q = replica_mutation_queues[rep]
                        if len(q) < queue_capacity:
                            q.append(key)
                        else:
                            dropped_mutations += 1
                    else:
                        down_time = current_time_ms - (node_down_since[rep] or current_time_ms)
                        if down_time <= max_hint_window_ms:
                            if coord != rep:
                                coordinator_hints[coord][rep].append(key)
                                total_hints_created += 1
                        else:
                            total_hints_expired += 1

    if is_skew_test:
        if skew_ratio > 2.0 or cv > 25.0:
            verdict = "SEVERE_TOKEN_RING_DATA_SKEW"
            status = "FAILED"
        else:
            verdict = "BALANCED_VNODE_DATA_DISTRIBUTION"
            status = "SUCCESS"
    elif replica_flapped or dropped_mutations > 0:
        verdict = "HINTED_HANDOFF_STORM_REPLICA_FLAPPING"
        status = "FAILED"
    elif total_hints_expired > 0:
        verdict = "SILENT_DATA_LOSS_HINT_EXPIRATION"
        status = "FAILED"
    elif total_hints_replayed > 0 and throttle_kb_per_sec > 0:
        verdict = "OPTIMAL_THROTTLED_HINTED_HANDOFF_RECOVERY"
        status = "SUCCESS"
    else:
        verdict = "NORMAL_CLUSTER_OPERATION"
        status = "SUCCESS"

    return {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "vnodes_per_node": vnodes_per_node,
            "max_ownership_pct": round(max_own, 2),
            "min_ownership_pct": round(min_own, 2),
            "skew_ratio": round(skew_ratio, 2),
            "coefficient_of_variation_pct": round(cv, 2),
            "total_hints_created": total_hints_created,
            "total_hints_replayed": total_hints_replayed,
            "total_hints_expired": total_hints_expired,
            "dropped_mutations": dropped_mutations,
            "replica_flapped": replica_flapped
        }
    }

def main():
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return
    data = json.loads(raw_input)
    result = simulate_cassandra_cluster(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
