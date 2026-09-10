import json
import sys

# Ensure UTF-8 input/output on Windows
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
        
    payload = json.loads(raw_data)
    config = payload.get("config", {})
    initial_state = payload.get("initial_state", {})
    events = payload.get("events", [])
    
    basic_liberty_threshold = float(config.get("basic_liberty_threshold", 80.0))
    liberty_inequality_tolerance = float(config.get("liberty_inequality_tolerance", 5.0))
    min_opportunity_threshold = float(config.get("min_opportunity_threshold", 70.0))
    
    raw_strata = initial_state.get("strata", [
        {"name": "T1_least_advantaged", "wealth": 20.0, "liberty": 85.0, "opportunity": 75.0},
        {"name": "T2_working_class", "wealth": 40.0, "liberty": 85.0, "opportunity": 78.0},
        {"name": "T3_middle_class", "wealth": 70.0, "liberty": 85.0, "opportunity": 82.0},
        {"name": "T4_upper_middle", "wealth": 120.0, "liberty": 85.0, "opportunity": 88.0},
        {"name": "T5_top_bracket", "wealth": 250.0, "liberty": 85.0, "opportunity": 95.0}
    ])
    strata = [dict(s) for s in raw_strata]
    
    history = []
    
    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        status = "OK"
        detail = ""
        
        if ev_type == "TAX_AND_REDISTRIBUTE":
            tax_rate_top = float(ev_params.get("tax_rate_top", 0.20))
            efficiency_loss = float(ev_params.get("deadweight_loss", 0.05))
            
            tax_collected = 0.0
            for s in strata:
                if s["name"] in ["T4_upper_middle", "T5_top_bracket"]:
                    levy = s["wealth"] * tax_rate_top
                    s["wealth"] -= levy
                    tax_collected += levy
                    
            net_transfer = tax_collected * (1.0 - efficiency_loss)
            strata[0]["wealth"] += net_transfer * 0.70
            strata[1]["wealth"] += net_transfer * 0.30
            status = "REDISTRIBUTED"
            detail = f"Tax collected: {round(tax_collected, 2)}, net transfer: {round(net_transfer, 2)}"
            
        elif ev_type == "PUBLIC_EDUCATION_INVESTMENT":
            amount = float(ev_params.get("amount", 20.0))
            for s in strata:
                if s["name"] == "T1_least_advantaged":
                    s["opportunity"] = min(100.0, s["opportunity"] + amount * 0.5)
                    s["wealth"] += amount * 0.3
                elif s["name"] == "T2_working_class":
                    s["opportunity"] = min(100.0, s["opportunity"] + amount * 0.3)
                    s["wealth"] += amount * 0.2
            status = "OPPORTUNITY_ENHANCED"
            detail = f"Education investment increased T1 opportunity to {round(strata[0]['opportunity'], 2)}"
            
        elif ev_type == "DEREGULATION_GROWTH":
            growth_top = float(ev_params.get("growth_top", 50.0))
            growth_bottom = float(ev_params.get("growth_bottom", 2.0))
            liberty_cost_bottom = float(ev_params.get("liberty_cost_bottom", 0.0))
            
            strata[4]["wealth"] += growth_top
            strata[3]["wealth"] += growth_top * 0.5
            strata[0]["wealth"] += growth_bottom
            strata[0]["liberty"] = max(0.0, strata[0]["liberty"] - liberty_cost_bottom)
            status = "GROWTH_APPLIED"
            detail = f"Top gained {growth_top}, bottom gained {growth_bottom}, liberty cost {liberty_cost_bottom}"
            
        elif ev_type == "BASIC_INCOME_DIVIDEND":
            amount = float(ev_params.get("amount_per_capita", 15.0))
            for s in strata:
                s["wealth"] += amount
            status = "DIVIDEND_DISTRIBUTED"
            detail = f"Universal basic income dividend of {amount} added to all strata"
            
        elif ev_type == "SELECT_DISTRIBUTION_SCHEME":
            candidates = ev_params.get("candidates", [])
            best_rawls = None
            best_rawls_t1 = -1e9
            best_utilitarian = None
            best_util_sum = -1e9
            
            for c in candidates:
                w_list = c["strata_wealth"]
                lib = float(c.get("min_liberty", 85.0))
                opp = float(c.get("min_opportunity", 75.0))
                t1 = w_list[0]
                u_sum = sum(w_list)
                
                if lib >= basic_liberty_threshold and opp >= min_opportunity_threshold:
                    if t1 > best_rawls_t1:
                        best_rawls_t1 = t1
                        best_rawls = c["scheme_name"]
                        
                if u_sum > best_util_sum:
                    best_util_sum = u_sum
                    best_utilitarian = c["scheme_name"]
                    
            status = "SCHEME_SELECTED"
            detail = f"Rawls Maximin: {best_rawls} (T1={best_rawls_t1}), Utilitarian: {best_utilitarian} (Sum={round(best_util_sum, 2)})"
            
        min_liberty = min(s["liberty"] for s in strata)
        max_liberty = max(s["liberty"] for s in strata)
        liberty_gap = max_liberty - min_liberty
        passes_liberty_principle = (min_liberty >= basic_liberty_threshold and liberty_gap <= liberty_inequality_tolerance)
        
        min_opp = min(s["opportunity"] for s in strata)
        passes_opportunity_principle = (min_opp >= min_opportunity_threshold)
        
        t1_wealth = strata[0]["wealth"]
        total_wealth = sum(s["wealth"] for s in strata)
        
        if not passes_liberty_principle:
            justice_status = "UNJUST_LIBERTY_VIOLATION"
        elif not passes_opportunity_principle:
            justice_status = "UNJUST_OPPORTUNITY_DEFICIT"
        elif t1_wealth >= 35.0:
            justice_status = "JUST_WELL_ORDERED_SOCIETY"
        elif t1_wealth >= 25.0:
            justice_status = "MODERATELY_JUST"
        else:
            justice_status = "INSUFFICIENT_MAXIMIN_TRANSFER"
            
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "status": status,
            "t1_wealth": round(t1_wealth, 2),
            "total_wealth": round(total_wealth, 2),
            "min_liberty": round(min_liberty, 2),
            "min_opportunity": round(min_opp, 2),
            "justice_status": justice_status,
            "detail": detail
        })
        
    result = {
        "final_justice_status": history[-1]["justice_status"] if history else "UNKNOWN",
        "is_just_society": (history[-1]["justice_status"] in ["JUST_WELL_ORDERED_SOCIETY", "MODERATELY_JUST"]) if history else False,
        "final_t1_wealth": round(strata[0]["wealth"], 2),
        "final_total_wealth": round(sum(s["wealth"] for s in strata), 2),
        "strata_final": [
            {
                "name": s["name"],
                "wealth": round(s["wealth"], 2),
                "liberty": round(s["liberty"], 2),
                "opportunity": round(s["opportunity"], 2)
            } for s in strata
        ],
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
