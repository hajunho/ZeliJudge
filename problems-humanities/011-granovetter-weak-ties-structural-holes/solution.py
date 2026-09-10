import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def analyze_social_network(input_data: dict) -> dict:
    network_id = input_data.get("network_id", "SOC_NET_01")
    nodes = input_data.get("nodes", [])
    edges = input_data.get("edges", [])
    strong_threshold = input_data.get("strong_tie_threshold", 5.0)

    n = len(nodes)
    adj = {u: set() for u in nodes}
    weights = {}

    for e in edges:
        u = e["source"]
        v = e["target"]
        w = float(e.get("weight", 1.0))
        if u in adj and v in adj and u != v:
            adj[u].add(v)
            adj[v].add(u)
            weights[(min(u, v), max(u, v))] = w

    def get_weight(u, v):
        return weights.get((min(u, v), max(u, v)), 0.0)

    edge_results = []
    local_bridge_count = 0
    weak_tie_count = 0
    strong_tie_count = 0

    for e in edges:
        u = e["source"]
        v = e["target"]
        w = get_weight(u, v)

        neighbors_u = adj[u]
        neighbors_v = adj[v]

        common = neighbors_u.intersection(neighbors_v)
        union = neighbors_u.union(neighbors_v)

        denom = len(union) - 2
        overlap = round(len(common) / denom, 4) if denom > 0 else 0.0
        is_local_bridge = (len(common) == 0)

        if is_local_bridge:
            local_bridge_count += 1

        tie_type = "STRONG_TIE" if w >= strong_threshold else "WEAK_TIE"
        if tie_type == "STRONG_TIE":
            strong_tie_count += 1
        else:
            weak_tie_count += 1

        edge_results.append({
            "source": u,
            "target": v,
            "weight": w,
            "tie_type": tie_type,
            "common_neighbors_count": len(common),
            "neighborhood_overlap": overlap,
            "is_local_bridge": is_local_bridge
        })

    bc = {u: 0.0 for u in nodes}
    for s in nodes:
        S = []
        P = {w: [] for w in nodes}
        sigma = {w: 0 for w in nodes}
        sigma[s] = 1
        d = {w: -1 for w in nodes}
        d[s] = 0
        Q = [s]
        while Q:
            v = Q.pop(0)
            S.append(v)
            for w in adj[v]:
                if d[w] < 0:
                    Q.append(w)
                    d[w] = d[v] + 1
                if d[w] == d[v] + 1:
                    sigma[w] += sigma[v]
                    P[w].append(v)

        delta = {w: 0.0 for w in nodes}
        while S:
            w = S.pop()
            for v in P[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                bc[w] += delta[w]

    for u in nodes:
        bc[u] /= 2.0

    norm_factor = ((n - 1) * (n - 2)) / 2.0 if n > 2 else 1.0
    bc_norm = {u: round(bc[u] / norm_factor, 4) if n > 2 else 0.0 for u in nodes}

    node_results = {}
    broker_count = 0
    cohesive_count = 0

    for u in nodes:
        k_u = len(adj[u])

        if k_u >= 2:
            links = 0
            neigh_list = list(adj[u])
            for i in range(len(neigh_list)):
                for j in range(i + 1, len(neigh_list)):
                    if neigh_list[j] in adj[neigh_list[i]]:
                        links += 1
            clustering = round((2.0 * links) / (k_u * (k_u - 1)), 4)
            redundant = (2.0 * links) / k_u
            effective_size = round(k_u - redundant, 4)
        else:
            clustering = 0.0
            links = 0
            effective_size = float(k_u)

        total_w_u = sum(get_weight(u, v) for v in adj[u])
        if total_w_u > 0:
            p_uv = {v: get_weight(u, v) / total_w_u for v in adj[u]}
            constraint = 0.0
            for v in adj[u]:
                direct = p_uv[v]
                indirect = 0.0
                for q in adj[u]:
                    if q != v and v in adj[q]:
                        total_w_q = sum(get_weight(q, z) for z in adj[q])
                        p_qv = get_weight(q, v) / total_w_q if total_w_q > 0 else 0.0
                        indirect += p_uv[q] * p_qv
                c_uv = (direct + indirect) ** 2
                constraint += c_uv
            constraint = round(constraint, 4)
        else:
            constraint = 1.0 if k_u > 0 else 0.0

        if k_u <= 1:
            role = "PERIPHERAL_ISOLATE"
        elif constraint <= 0.35 and bc_norm[u] >= 0.15:
            role = "KEY_BROKER"
            broker_count += 1
        elif clustering >= 0.60 and constraint >= 0.55:
            role = "COHESIVE_INSIDER"
            cohesive_count += 1
        else:
            role = "GENERAL_ACTOR"

        node_results[u] = {
            "degree": k_u,
            "clustering_coefficient": clustering,
            "effective_size": effective_size,
            "burt_constraint": constraint,
            "betweenness_centrality": bc_norm[u],
            "sociological_role": role
        }

    return {
        "network_id": network_id,
        "total_actors": n,
        "total_ties": len(edges),
        "summary": {
            "strong_ties_count": strong_tie_count,
            "weak_ties_count": weak_tie_count,
            "local_bridges_count": local_bridge_count,
            "key_brokers_count": broker_count,
            "cohesive_insiders_count": cohesive_count
        },
        "actors": node_results,
        "ties": edge_results
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = analyze_social_network(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
