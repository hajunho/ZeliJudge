import sys
import json
import math

def compute_gini(utilities, weights):
    n = len(utilities)
    pairs = sorted(zip(utilities, weights), key=lambda x: x[0])
    vals = [p[0] for p in pairs]
    w = [p[1] for p in pairs]
    
    tot_w = sum(w)
    if tot_w == 0:
        return 0.0
        
    mean_val = sum(v * wt for v, wt in zip(vals, w)) / tot_w
    if mean_val <= 1e-9:
        return 0.0
        
    numerator = 0.0
    for i in range(n):
        for j in range(n):
            numerator += w[i] * w[j] * abs(vals[i] - vals[j])
            
    gini = numerator / (2.0 * tot_w * tot_w * mean_val)
    return round(gini, 4)

def run_simulation(req):
    strata = req.get("strata", [])
    names = [s["name"] for s in strata]
    weights = [s.get("weight", 1.0) for s in strata]
    tot_w = sum(weights)
    norm_w = [w / tot_w for w in weights]
    baselines = {s["name"]: s["baseline_utility"] for s in strata}
    base_min = min(baselines.values())
    
    evaluated_policies = {}
    logs = []
    
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "EVALUATE_POLICY":
            p_id = op_item["policy_id"]
            title = op_item.get("title", p_id)
            deltas = op_item.get("deltas", {})
            
            final_u = []
            for s in strata:
                d = deltas.get(s["name"], 0.0)
                final_u.append(round(s["baseline_utility"] + d, 4))
                
            bentham = sum(nw * u for nw, u in zip(norm_w, final_u))
            
            nash = 0.0
            if all(u > 0 for u in final_u):
                nash = math.exp(sum(nw * math.log(u) for nw, u in zip(norm_w, final_u)))
                
            rawls_min = min(final_u)
            min_idx = final_u.index(rawls_min)
            min_stratum = names[min_idx]
            sorted_u = sorted(final_u)
            
            gini = compute_gini(final_u, norm_w)
            sen_welfare = bentham * (1.0 - gini)
            
            pareto_imp = all(deltas.get(nm, 0.0) >= -1e-6 for nm in names) and any(deltas.get(nm, 0.0) > 1e-4 for nm in names)
            rawls_imp = (rawls_min > base_min + 1e-4)
            worst_off_sacrificed = (rawls_min < base_min - 1e-4)
            
            res_p = {
                "policy_id": p_id,
                "title": title,
                "final_utilities": dict(zip(names, final_u)),
                "bentham_utilitarian": round(bentham, 4),
                "nash_welfare": round(nash, 4),
                "rawls_maximin": round(rawls_min, 4),
                "least_advantaged_group": min_stratum,
                "leximin_vector": sorted_u,
                "gini_coefficient": round(gini, 4),
                "sen_equity_welfare": round(sen_welfare, 4),
                "is_pareto_improvement": pareto_imp,
                "is_rawlsian_improvement": rawls_imp,
                "worst_off_sacrificed": worst_off_sacrificed
            }
            evaluated_policies[p_id] = res_p
            logs.append({
                "step": step,
                "op": op,
                "policy_id": p_id,
                "bentham": res_p["bentham_utilitarian"],
                "rawls_min": res_p["rawls_maximin"],
                "gini": res_p["gini_coefficient"],
                "status": "EVALUATED"
            })
            
        elif op == "COMPARE_AND_RANK":
            target_ids = op_item["policy_ids"]
            subset = [evaluated_policies[pid] for pid in target_ids if pid in evaluated_policies]
            
            b_sorted = sorted(subset, key=lambda x: x["bentham_utilitarian"], reverse=True)
            n_sorted = sorted(subset, key=lambda x: x["nash_welfare"], reverse=True)
            r_sorted = sorted(subset, key=lambda x: (x["rawls_maximin"], x["leximin_vector"]), reverse=True)
            s_sorted = sorted(subset, key=lambda x: x["sen_equity_welfare"], reverse=True)
            
            bentham_best = b_sorted[0]["policy_id"]
            rawls_best = r_sorted[0]["policy_id"]
            conflict = (bentham_best != rawls_best)
            
            logs.append({
                "step": step,
                "op": op,
                "bentham_winner": bentham_best,
                "rawls_winner": rawls_best,
                "veil_of_ignorance_choice": rawls_best,
                "utilitarian_rawlsian_conflict": conflict,
                "rankings": {
                    "bentham": [x["policy_id"] for x in b_sorted],
                    "nash": [x["policy_id"] for x in n_sorted],
                    "rawls": [x["policy_id"] for x in r_sorted],
                    "sen": [x["policy_id"] for x in s_sorted]
                }
            })
            
    return {
        "operations_log": logs,
        "evaluated_policies": evaluated_policies
    }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    raw_in = sys.stdin.read().strip()
    if not raw_in:
        return
        
    req = json.loads(raw_in)
    res = run_simulation(req)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
