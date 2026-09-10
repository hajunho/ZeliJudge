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
    initial_state = payload.get("initial_state", {})
    events = payload.get("events", [])
    
    citizens = {}
    init_citizens = initial_state.get("citizens", {})
    for c_id, data in init_citizens.items():
        citizens[c_id] = {
            "wealth": float(data.get("wealth", 50.0)),
            "political_power": float(data.get("political_power", 50.0)),
            "education": float(data.get("education", 50.0)),
            "healthcare": float(data.get("healthcare", 50.0)),
            "honor": float(data.get("honor", 50.0))
        }
        
    firewall_enabled = bool(initial_state.get("firewall_enabled", True))
    history = []
    total_dominance_violations = 0
    total_blocked_violations = 0
    
    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        status = "OK"
        detail = ""
        
        if ev_type == "MARKET_EXCHANGE":
            buyer_id = ev_params["buyer"]
            seller_id = ev_params["seller"]
            amount = float(ev_params.get("amount", 20.0))
            
            if buyer_id in citizens and seller_id in citizens:
                actual = min(amount, citizens[buyer_id]["wealth"])
                citizens[buyer_id]["wealth"] -= actual
                citizens[seller_id]["wealth"] += actual
                status = "MARKET_EXCHANGE_SUCCESS"
                detail = f"Legitimate market exchange of {actual} between {buyer_id} and {seller_id}."
                
        elif ev_type == "CROSS_SPHERE_CONVERSION":
            agent_id = ev_params["agent"]
            src_sphere = ev_params["src_sphere"]
            dst_sphere = ev_params["dst_sphere"]
            cost = float(ev_params.get("cost", 30.0))
            gain = float(ev_params.get("gain", 25.0))
            
            if agent_id in citizens:
                if firewall_enabled:
                    total_blocked_violations += 1
                    status = "DOMINANCE_BLOCKED_BY_FIREWALL"
                    detail = f"Firewall blocked illicit conversion of {src_sphere} to {dst_sphere} by {agent_id}."
                else:
                    actual_cost = min(cost, citizens[agent_id][src_sphere])
                    citizens[agent_id][src_sphere] -= actual_cost
                    citizens[agent_id][dst_sphere] = min(100.0, citizens[agent_id][dst_sphere] + gain)
                    total_dominance_violations += 1
                    status = "ILLICIT_DOMINANCE_CONVERTED"
                    detail = f"Sphere autonomy breached: {agent_id} converted {actual_cost} {src_sphere} to {gain} {dst_sphere}."
                    
        elif ev_type == "NEED_BASED_HEALTHCARE_DISTRIBUTION":
            recipient_id = ev_params["recipient"]
            medical_care = float(ev_params.get("care_units", 30.0))
            if recipient_id in citizens:
                citizens[recipient_id]["healthcare"] = min(100.0, citizens[recipient_id]["healthcare"] + medical_care)
                status = "HEALTHCARE_ALLOCATED_BY_NEED"
                detail = f"Healthcare allocated by need to {recipient_id} (+{medical_care})."
                
        elif ev_type == "DEMOCRATIC_OFFICE_ALLOCATION":
            candidate_id = ev_params["candidate"]
            votes_share = float(ev_params.get("votes_share", 50.0))
            if candidate_id in citizens:
                citizens[candidate_id]["political_power"] = min(100.0, citizens[candidate_id]["political_power"] + votes_share)
                status = "OFFICE_ALLOCATED_DEMOCRATICALLY"
                detail = f"Public office allocated to {candidate_id} via democratic vote."
                
        elif ev_type == "TOGGLE_SPHERE_FIREWALL":
            firewall_enabled = bool(ev_params.get("enabled", True))
            status = "FIREWALL_STATE_CHANGED"
            detail = f"Sphere boundary firewall set to {firewall_enabled}."
            
        dominant_tyrants = []
        for c_id, c in citizens.items():
            high_count = sum(1 for v in c.values() if v >= 80.0)
            if high_count >= 3:
                dominant_tyrants.append(c_id)
        dominant_tyrants.sort()
        
        is_complex_equal = (total_dominance_violations == 0 and len(dominant_tyrants) == 0)
        
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "status": status,
            "is_complex_equal": is_complex_equal,
            "total_dominance_violations": total_dominance_violations,
            "dominant_tyrants": dominant_tyrants,
            "detail": detail
        })
        
    result = {
        "final_is_complex_equal": history[-1]["is_complex_equal"] if history else False,
        "total_dominance_violations": total_dominance_violations,
        "total_blocked_violations": total_blocked_violations,
        "dominant_tyrants": history[-1]["dominant_tyrants"] if history else [],
        "citizens": {
            c_id: {
                "wealth": round(c["wealth"], 2),
                "political_power": round(c["political_power"], 2),
                "education": round(c["education"], 2),
                "healthcare": round(c["healthcare"], 2),
                "honor": round(c["honor"], 2)
            } for c_id, c in sorted(citizens.items())
        },
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
