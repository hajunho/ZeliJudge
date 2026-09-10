import sys
import json
import math

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    consumer_id = input_data.get("consumer_id", "CONSUMER_A")
    capital_budget = float(input_data.get("capital_budget", 1000.0))
    social_prestige = float(input_data.get("social_prestige", 10.0))
    synthetic_lack = float(input_data.get("synthetic_lack", 0.3))
    alienation_index = float(input_data.get("alienation_index", 0.2))
    operations = input_data.get("operations", [])
    
    current_w = capital_budget
    current_s = social_prestige
    current_l = synthetic_lack
    current_a = alienation_index
    
    stats = {
        "commodities_purchased": 0,
        "failed_purchases": 0,
        "marketing_exposures": 0,
        "symbolic_potlatches": 0,
        "total_exchange_value_spent": 0.0,
        "total_sign_value_acquired": 0.0
    }
    
    op_log = []
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "CONSUME_SIGN_COMMODITY":
            item = op.get("item_name", "COMMODITY")
            uv = float(op.get("use_value", 1.0))
            ev = float(op.get("exchange_value", 50.0))
            sv = float(op.get("sign_value", 10.0))
            
            if current_w < ev:
                stats["failed_purchases"] += 1
                op_log.append({
                    "op": "CONSUME_SIGN_COMMODITY",
                    "item_name": item,
                    "status": "REJECTED_CAPITAL_INSUFFICIENT",
                    "capital_budget": round(current_w, 2),
                    "required_exchange_value": ev
                })
                continue
                
            stats["commodities_purchased"] += 1
            stats["total_exchange_value_spent"] = round(stats["total_exchange_value_spent"] + ev, 2)
            stats["total_sign_value_acquired"] = round(stats["total_sign_value_acquired"] + sv, 2)
            
            current_w = round(current_w - ev, 2)
            delta_s = round(sv * (1.0 + 0.1 * math.log(1.0 + uv)), 2)
            current_s = round(current_s + delta_s, 2)
            
            current_l = min(1.0, round(current_l * 0.5 + 0.3 * (sv / (10.0 + sv)), 4))
            delta_a = round(0.05 * (sv / (10.0 + uv)), 4)
            current_a = min(1.0, round(current_a + delta_a, 4))
            
            op_log.append({
                "op": "CONSUME_SIGN_COMMODITY",
                "item_name": item,
                "status": "SIGN_CONSUMED_CODE_REINFORCED",
                "remaining_capital": current_w,
                "prestige_gained": delta_s,
                "new_synthetic_lack": current_l,
                "new_alienation": current_a
            })
            
        elif op_type == "SIMULATE_LACK_INDUCTION":
            stats["marketing_exposures"] += 1
            campaign = op.get("campaign_name", "AD_BLITZ")
            pc = float(op.get("code_pressure", 0.5))
            
            delta_l = round(pc * (1.0 - current_l) * 0.6, 4)
            current_l = min(1.0, round(current_l + delta_l, 4))
            current_a = min(1.0, round(current_a + pc * 0.1, 4))
            
            op_log.append({
                "op": "SIMULATE_LACK_INDUCTION",
                "campaign_name": campaign,
                "status": "SYNTHETIC_NEED_INDUCED",
                "lack_increase": delta_l,
                "new_synthetic_lack": current_l,
                "new_alienation": current_a
            })
            
        elif op_type == "SYMBOLIC_EXCHANGE_POTLATCH":
            g = float(op.get("gift_sacrifice_value", 100.0))
            if current_w < g:
                op_log.append({
                    "op": "SYMBOLIC_EXCHANGE_POTLATCH",
                    "status": "REJECTED_SACRIFICE_EXCEEDS_WEALTH",
                    "capital_budget": current_w,
                    "sacrifice_attempted": g
                })
                continue
                
            stats["symbolic_potlatches"] += 1
            current_w = round(current_w - g, 2)
            factor = g / (100.0 + g)
            delta_a = round(0.25 * factor, 4)
            delta_l = round(0.30 * factor, 4)
            current_a = max(0.0, round(current_a - delta_a, 4))
            current_l = max(0.0, round(current_l - delta_l, 4))
            
            op_log.append({
                "op": "SYMBOLIC_EXCHANGE_POTLATCH",
                "sacrifice_value": g,
                "status": "SYMBOLIC_GIFT_CODE_SUBVERTED",
                "remaining_capital": current_w,
                "alienation_reduction": delta_a,
                "new_alienation": current_a,
                "new_synthetic_lack": current_l
            })

    if current_a >= 0.70 and current_l >= 0.50:
        verdict = "HYPER_CONSUMER_SISYPHUS"
    elif current_a <= 0.20 and current_l <= 0.20:
        verdict = "SYMBOLIC_POTLATCH_RESISTANT"
    elif current_s >= 80.0:
        verdict = "HIGH_PRESTIGE_CODE_SIGNIFIER"
    else:
        verdict = "ALIENATED_EVERYDAY_CONSUMER"

    res = {
        "consumer_id": consumer_id,
        "initial_state": {
            "capital_budget": capital_budget,
            "social_prestige": social_prestige,
            "synthetic_lack": synthetic_lack,
            "alienation_index": alienation_index
        },
        "final_state": {
            "capital_budget": current_w,
            "social_prestige": current_s,
            "synthetic_lack": current_l,
            "alienation_index": current_a,
            "sociological_verdict": verdict
        },
        "stats": stats,
        "op_log": op_log
    }
    
    sys.stdout.write(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    solve()
