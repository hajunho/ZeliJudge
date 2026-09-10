import sys
import json

class SocialMobilityEngine:
    def __init__(self, config=None):
        config = config or {}

    def analyze_mobility(self, transition_matrix, initial_distribution=None):
        k = len(transition_matrix)
        w = initial_distribution if initial_distribution else [1.0 / k] * k

        trace_p = sum(transition_matrix[i][i] for i in range(k))
        prais_index = (k - trace_p) / (k - 1) if k > 1 else 0.0

        r_up = 0.0
        r_down = 0.0
        r_stay = 0.0

        for i in range(k):
            for j in range(k):
                flow = w[i] * transition_matrix[i][j]
                if j > i:
                    r_up += flow
                elif j < i:
                    r_down += flow
                else:
                    r_stay += flow

        sticky_floor = transition_matrix[0][0]
        glass_ceiling_ratio = transition_matrix[0][k - 1] / max(transition_matrix[k - 1][k - 1], 1e-6)

        w_next = [0.0] * k
        for j in range(k):
            w_next[j] = sum(w[i] * transition_matrix[i][j] for i in range(k))

        pi = list(w)
        for _ in range(100):
            pi_next = [0.0] * k
            for j in range(k):
                pi_next[j] = sum(pi[i] * transition_matrix[i][j] for i in range(k))
            pi = pi_next

        ige_proxy = 1.0 - prais_index

        return {
            "prais_mobility_index": round(prais_index, 4),
            "mobility_rates": {
                "upward": round(r_up * 100.0, 2),
                "downward": round(r_down * 100.0, 2),
                "immobility": round(r_stay * 100.0, 2)
            },
            "sticky_floor_prob": round(sticky_floor, 4),
            "glass_ceiling_ratio": round(glass_ceiling_ratio, 4),
            "next_gen_distribution": [round(x, 4) for x in w_next],
            "steady_state_distribution": [round(x, 4) for x in pi],
            "estimated_ige": round(ige_proxy, 4)
        }

    def multi_generation_projection(self, transition_matrix, initial_distribution, generations=5):
        k = len(transition_matrix)
        w = list(initial_distribution)
        history = [list(w)]

        for _ in range(generations):
            w_next = [0.0] * k
            for j in range(k):
                w_next[j] = sum(w[i] * transition_matrix[i][j] for i in range(k))
            w = w_next
            history.append([round(x, 4) for x in w])

        return history

    def gatsby_regression(self, countries_data, target_gini):
        n = len(countries_data)
        xs = [c["gini"] for c in countries_data]
        ys = [1.0 - c["prais_mobility"] for c in countries_data]

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
        den = sum((xs[i] - mean_x) ** 2 for i in range(n))

        b = num / den if den > 0 else 0.0
        a = mean_y - b * mean_x

        pred_ige = a + b * target_gini
        return {
            "slope_b": round(b, 4),
            "intercept_a": round(a, 4),
            "target_gini": round(target_gini, 4),
            "predicted_ige": round(pred_ige, 4)
        }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    data = json.loads(raw)
    engine = SocialMobilityEngine()
    op_type = data.get("operation", "ANALYZE_MOBILITY")

    if op_type == "ANALYZE_MOBILITY":
        mat = data.get("transition_matrix", [])
        init_dist = data.get("initial_distribution", None)
        res = engine.analyze_mobility(mat, init_dist)
        output = {"operation": op_type, "result": res}

    elif op_type == "MULTI_GEN_PROJECTION":
        mat = data.get("transition_matrix", [])
        init_dist = data.get("initial_distribution", [])
        gens = data.get("generations", 5)
        hist = engine.multi_generation_projection(mat, init_dist, gens)
        output = {"operation": op_type, "generations": gens, "projection_history": hist}

    elif op_type == "GATSBY_REGRESSION":
        countries = data.get("countries", [])
        target_gini = data.get("target_gini", 0.35)
        reg = engine.gatsby_regression(countries, target_gini)
        output = {"operation": op_type, "regression": reg}

    else:
        output = {"error": "unknown_operation"}

    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
