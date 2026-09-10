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
    
    agents = {}
    init_agents = initial_state.get("agents", {})
    for a_id, data in init_agents.items():
        agents[a_id] = {
            "holdings": float(data.get("holdings", 100.0)),
            "legitimate_title": bool(data.get("legitimate_title", True)),
            "proviso_violated": bool(data.get("proviso_violated", False))
        }
        
    history = []
    total_coercive_interventions = 0
    total_rectifications = 0
    
    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        status = "OK"
        detail = ""
        
        if ev_type == "ORIGINAL_ACQUISITION":
            agent_id = ev_params["agent_id"]
            amount = float(ev_params.get("amount", 50.0))
            violates_proviso = bool(ev_params.get("violates_lockean_proviso", False))
            
            if agent_id not in agents:
                agents[agent_id] = {"holdings": 0.0, "legitimate_title": True, "proviso_violated": False}
                
            agents[agent_id]["holdings"] += amount
            if violates_proviso:
                agents[agent_id]["proviso_violated"] = True
                agents[agent_id]["legitimate_title"] = False
                status = "ACQUISITION_PROVISO_VIOLATED"
                detail = f"Agent {agent_id} acquired {amount} but violated Lockean proviso."
            else:
                status = "LEGITIMATE_ACQUISITION"
                detail = f"Agent {agent_id} legitimately acquired {amount} from nature."
                
        elif ev_type == "VOLUNTARY_TRANSFER":
            from_id = ev_params["from_agent"]
            to_id = ev_params["to_agent"]
            amount = float(ev_params.get("amount", 20.0))
            is_coerced = bool(ev_params.get("coercion_or_fraud", False))
            
            if from_id in agents and to_id in agents:
                actual_transfer = min(amount, agents[from_id]["holdings"])
                agents[from_id]["holdings"] -= actual_transfer
                agents[to_id]["holdings"] += actual_transfer
                
                if is_coerced:
                    agents[to_id]["legitimate_title"] = False
                    status = "COERCED_OR_FRAUD_TRANSFER"
                    detail = f"Transfer of {actual_transfer} from {from_id} to {to_id} involved coercion/fraud."
                else:
                    status = "VOLUNTARY_TRANSFER_SUCCESS"
                    detail = f"Voluntary transfer of {actual_transfer} from {from_id} to {to_id} completed."
                    
        elif ev_type == "WILT_CHAMBERLAIN_TRANSACTION":
            star_id = ev_params["star_agent"]
            ticket_price = float(ev_params.get("ticket_price", 0.25))
            spectators = ev_params.get("spectator_agents", [])
            
            if star_id not in agents:
                agents[star_id] = {"holdings": 0.0, "legitimate_title": True, "proviso_violated": False}
                
            total_transferred = 0.0
            for spec_id in spectators:
                if spec_id in agents and agents[spec_id]["holdings"] >= ticket_price:
                    agents[spec_id]["holdings"] -= ticket_price
                    total_transferred += ticket_price
                    
            agents[star_id]["holdings"] += total_transferred
            status = "CHAMBERLAIN_TRANSACTION_SUCCESS"
            detail = f"{len(spectators)} spectators voluntarily paid {ticket_price} each. Star {star_id} received {total_transferred}."
            
        elif ev_type == "RECTIFY_INJUSTICE":
            victim_id = ev_params["victim_agent"]
            prep_id = ev_params["perpetrator_agent"]
            restitution = float(ev_params.get("restitution_amount", 50.0))
            
            if prep_id in agents and victim_id in agents:
                actual_restitution = min(restitution, agents[prep_id]["holdings"])
                agents[prep_id]["holdings"] -= actual_restitution
                agents[victim_id]["holdings"] += actual_restitution
                agents[prep_id]["legitimate_title"] = True
                total_rectifications += 1
                status = "INJUSTICE_RECTIFIED"
                detail = f"Perpetrator {prep_id} restored {actual_restitution} to victim {victim_id}."
                
        elif ev_type == "STATE_PATTERNED_REDISTRIBUTION":
            tax_rate = float(ev_params.get("tax_rate", 0.30))
            target_ids = ev_params.get("target_agents", [])
            beneficiary_ids = ev_params.get("beneficiary_agents", [])
            
            total_levied = 0.0
            for t_id in target_ids:
                if t_id in agents:
                    levy = agents[t_id]["holdings"] * tax_rate
                    agents[t_id]["holdings"] -= levy
                    total_levied += levy
                    
            if beneficiary_ids:
                per_ben = total_levied / len(beneficiary_ids)
                for b_id in beneficiary_ids:
                    if b_id in agents:
                        agents[b_id]["holdings"] += per_ben
                        
            total_coercive_interventions += 1
            status = "PATTERNED_TAX_IMPOSED"
            detail = f"State forcibly levied {round(total_levied, 2)} from {target_ids} to maintain pattern."
            
        elif ev_type == "MINIMAL_STATE_PROTECTION":
            status = "MINIMAL_STATE_ENFORCED"
            detail = "Night-watchman state upheld property boundaries and contract execution without redistribution."
            
        is_just = all(a["legitimate_title"] and not a["proviso_violated"] for a in agents.values())
        holdings_list = [a["holdings"] for a in agents.values()]
        min_h = min(holdings_list) if holdings_list else 0.0
        max_h = max(holdings_list) if holdings_list else 0.0
        is_patterned_equal = (min_h > 0 and (max_h / min_h) <= 1.2)
        
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "status": status,
            "is_just_entitlement": is_just,
            "is_patterned_equal": is_patterned_equal,
            "min_holding": round(min_h, 2),
            "max_holding": round(max_h, 2),
            "detail": detail
        })
        
    result = {
        "final_is_just_entitlement": all(a["legitimate_title"] and not a["proviso_violated"] for a in agents.values()),
        "final_is_patterned_equal": history[-1]["is_patterned_equal"] if history else False,
        "total_coercive_interventions": total_coercive_interventions,
        "total_rectifications": total_rectifications,
        "agents": {
            a_id: {
                "holdings": round(a["holdings"], 2),
                "legitimate_title": a["legitimate_title"],
                "proviso_violated": a["proviso_violated"]
            } for a_id, a in sorted(agents.items())
        },
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
