import sys
import json
import math

def v_func(x, alpha=0.88, beta=0.88, lam=2.25):
    if x >= 0:
        return x ** alpha
    else:
        return -lam * ((-x) ** beta)

def w_prob(p, param):
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    num = p ** param
    den = (p ** param + (1.0 - p) ** param) ** (1.0 / param)
    return num / den

def eval_single(outcomes, ref_point, params):
    alpha = params.get("alpha", 0.88)
    beta = params.get("beta", 0.88)
    lam = params.get("lambda", 2.25)
    gamma = params.get("gamma", 0.61)
    delta = params.get("delta", 0.69)
    
    ev = 0.0
    pt_val = 0.0
    
    has_pos = False
    has_neg = False
    
    for item in outcomes:
        x = item["x"]
        p = item["p"]
        ev += p * x
        
        dx = x - ref_point
        if dx > 1e-9:
            has_pos = True
            w = w_prob(p, gamma)
            val = v_func(dx, alpha, beta, lam)
        elif dx < -1e-9:
            has_neg = True
            w = w_prob(p, delta)
            val = v_func(dx, alpha, beta, lam)
        else:
            w = p
            val = 0.0
        pt_val += w * val
        
    v_ev = v_func(ev - ref_point, alpha, beta, lam)
    
    if has_pos and not has_neg:
        if pt_val < v_ev - 1e-4:
            attitude = "RISK_AVERSE"
        elif pt_val > v_ev + 1e-4:
            attitude = "RISK_SEEKING"
        else:
            attitude = "RISK_NEUTRAL"
    elif has_neg and not has_pos:
        if pt_val > v_ev + 1e-4:
            attitude = "RISK_SEEKING"
        elif pt_val < v_ev - 1e-4:
            attitude = "RISK_AVERSE"
        else:
            attitude = "RISK_NEUTRAL"
    else:
        attitude = "MIXED"
        
    return {
        "expected_value": round(ev, 4),
        "prospect_value": round(pt_val, 4),
        "value_of_ev": round(v_ev, 4),
        "risk_attitude": attitude
    }

def solve():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    line = sys.stdin.read().strip()
    if not line:
        return
    data = json.loads(line)
    
    params = data.get("parameters", {})
    alpha = params.get("alpha", 0.88)
    beta = params.get("beta", 0.88)
    lam = params.get("lambda", 2.25)
    gamma = params.get("gamma", 0.61)
    delta = params.get("delta", 0.69)
    
    results = []
    
    for op_item in data.get("operations", []):
        op = op_item["op"]
        op_id = op_item.get("id", "")
        
        if op == "EVALUATE_PROSPECT":
            ref = op_item.get("reference_point", 0.0)
            outcomes = op_item.get("outcomes", [])
            res = eval_single(outcomes, ref, params)
            results.append({
                "id": op_id,
                "op": op,
                "expected_value": res["expected_value"],
                "prospect_value": res["prospect_value"],
                "value_of_ev": res["value_of_ev"],
                "risk_attitude": res["risk_attitude"]
            })
            
        elif op == "COMPARE_GAMBLES":
            ref = op_item.get("reference_point", 0.0)
            res_a = eval_single(op_item["option_a"], ref, params)
            res_b = eval_single(op_item["option_b"], ref, params)
            
            ev_a = res_a["expected_value"]
            ev_b = res_b["expected_value"]
            pv_a = res_a["prospect_value"]
            pv_b = res_b["prospect_value"]
            
            if ev_a > ev_b + 1e-4:
                ev_choice = "OPTION_A"
            elif ev_b > ev_a + 1e-4:
                ev_choice = "OPTION_B"
            else:
                ev_choice = "INDIFFERENT"
                
            if pv_a > pv_b + 1e-4:
                pv_choice = "OPTION_A"
            elif pv_b > pv_a + 1e-4:
                pv_choice = "OPTION_B"
            else:
                pv_choice = "INDIFFERENT"
                
            anomaly = (ev_choice != pv_choice)
            anomaly_type = "NONE"
            if anomaly:
                opt_a = op_item["option_a"]
                opt_b = op_item["option_b"]
                if ev_choice == "OPTION_B" and pv_choice == "OPTION_A" and len(opt_a) == 1 and opt_a[0]["p"] == 1.0 and opt_a[0]["x"] > ref:
                    anomaly_type = "CERTAINTY_EFFECT"
                elif ev_choice == "OPTION_B" and pv_choice == "OPTION_A" and any(it["x"] < ref for it in opt_b):
                    anomaly_type = "LOSS_AVERSION_REJECTION"
                elif ev_choice == "OPTION_A" and pv_choice == "OPTION_B" and any(it["p"] <= 0.05 and it["x"] > ref for it in opt_b):
                    anomaly_type = "LOTTERY_EFFECT"
                elif ev_choice == "OPTION_B" and pv_choice == "OPTION_A" and any(it["p"] <= 0.05 and it["x"] < ref for it in opt_b):
                    anomaly_type = "INSURANCE_EFFECT"
                else:
                    anomaly_type = "BEHAVIORAL_ANOMALY"
                    
            results.append({
                "id": op_id,
                "op": op,
                "option_a_ev": ev_a,
                "option_a_prospect_value": pv_a,
                "option_b_ev": ev_b,
                "option_b_prospect_value": pv_b,
                "ev_choice": ev_choice,
                "prospect_choice": pv_choice,
                "anomaly": anomaly,
                "anomaly_type": anomaly_type
            })
            
        elif op == "FRAMING_ANALYSIS":
            ref_pos = op_item.get("positive_reference_point", 0.0)
            ref_neg = op_item.get("negative_reference_point", 0.0)
            
            p_a = eval_single(op_item["positive_frame"]["option_a"], ref_pos, params)
            p_b = eval_single(op_item["positive_frame"]["option_b"], ref_pos, params)
            n_a = eval_single(op_item["negative_frame"]["option_a"], ref_neg, params)
            n_b = eval_single(op_item["negative_frame"]["option_b"], ref_neg, params)
            
            pos_choice = "OPTION_A" if p_a["prospect_value"] > p_b["prospect_value"] + 1e-4 else ("OPTION_B" if p_b["prospect_value"] > p_a["prospect_value"] + 1e-4 else "INDIFFERENT")
            neg_choice = "OPTION_A" if n_a["prospect_value"] > n_b["prospect_value"] + 1e-4 else ("OPTION_B" if n_b["prospect_value"] > n_a["prospect_value"] + 1e-4 else "INDIFFERENT")
            
            results.append({
                "id": op_id,
                "op": op,
                "positive_choice": pos_choice,
                "negative_choice": neg_choice,
                "positive_prospect_a": p_a["prospect_value"],
                "positive_prospect_b": p_b["prospect_value"],
                "negative_prospect_a": n_a["prospect_value"],
                "negative_prospect_b": n_b["prospect_value"],
                "preference_reversal": (pos_choice != neg_choice)
            })
            
        elif op == "HEDONIC_EDITING":
            events = op_item.get("events", [])
            seg_val = sum(v_func(x, alpha, beta, lam) for x in events)
            tot_x = sum(events)
            int_val = v_func(tot_x, alpha, beta, lam)
            
            if seg_val > int_val + 1e-4:
                strategy = "SEGREGATE"
            elif int_val > seg_val + 1e-4:
                strategy = "INTEGRATE"
            else:
                strategy = "INDIFFERENT"
                
            all_pos = all(x > 0 for x in events)
            all_neg = all(x < 0 for x in events)
            
            if all_pos:
                rule = "SEGREGATE_MULTIPLE_GAINS"
            elif all_neg:
                rule = "INTEGRATE_MULTIPLE_LOSSES"
            elif tot_x > 0:
                rule = "INTEGRATE_MIXED_GAIN"
            else:
                if strategy == "SEGREGATE":
                    rule = "SILVER_LINING"
                else:
                    rule = "INTEGRATE_MIXED_LOSS"
                    
            results.append({
                "id": op_id,
                "op": op,
                "events": events,
                "net_outcome": round(tot_x, 4),
                "segregated_value": round(seg_val, 4),
                "integrated_value": round(int_val, 4),
                "optimal_strategy": strategy,
                "hedonic_rule": rule
            })
            
    res = {
        "results": results
    }
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
