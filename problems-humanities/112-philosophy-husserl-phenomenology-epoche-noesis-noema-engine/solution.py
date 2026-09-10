import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    agent_id = data.get("agent_id", "Husserl_Investigator")
    attitude = data.get("initial_attitude", "NATURAL_ATTITUDE")
    acts = data.get("operations", [])
    
    attitude_history = [attitude]
    action_log = []
    
    world_bracketed = (attitude != "NATURAL_ATTITUDE")
    eidetic_invariants = []
    constituted_noemata = []
    
    epoche_depth = 0.0
    eidetic_clarity = 0.0
    intentional_synthesis_score = 0.0
    
    for op in acts:
        op_name = op.get("op")
        params = op.get("params", {})
        
        if op_name == "PERFORM_EPOCHE":
            bracket = params.get("bracket_world", True)
            if bracket:
                world_bracketed = True
                epoche_depth = min(100.0, epoche_depth + 40.0)
                if attitude == "NATURAL_ATTITUDE":
                    attitude = "PHENOMENOLOGICAL_REDUCTION"
                    attitude_history.append(attitude)
                status = "NATURAL_ATTITUDE_BRACKETED"
            else:
                world_bracketed = False
                attitude = "NATURAL_ATTITUDE"
                status = "RETURN_TO_NATURAL_ATTITUDE"
                
            action_log.append({
                "op": "PERFORM_EPOCHE",
                "attitude": attitude,
                "world_bracketed": world_bracketed,
                "epoche_depth": round(epoche_depth, 2),
                "status": status
            })
            
        elif op_name == "FREE_EIDETIC_VARIATION":
            if not world_bracketed:
                action_log.append({
                    "op": "FREE_EIDETIC_VARIATION",
                    "status": "CANNOT_PERFORM_IN_NATURAL_ATTITUDE"
                })
            else:
                object_class = params.get("target_class", "OBJECT")
                variations = params.get("variation_traits", [])
                invariants = params.get("invariable_traits", [])
                
                variation_count = len(variations)
                eidetic_clarity = min(100.0, eidetic_clarity + variation_count * 15.0)
                
                for inv in invariants:
                    if inv not in eidetic_invariants:
                        eidetic_invariants.append(inv)
                        
                if eidetic_clarity >= 40.0 and attitude in ("PHENOMENOLOGICAL_REDUCTION", "NATURAL_ATTITUDE"):
                    attitude = "EIDETIC_REDUCTION"
                    attitude_history.append(attitude)
                    
                action_log.append({
                    "op": "FREE_EIDETIC_VARIATION",
                    "attitude": attitude,
                    "target_class": object_class,
                    "extracted_eidos": invariants,
                    "eidetic_clarity": round(eidetic_clarity, 2),
                    "status": "EIDOS_ISOLATED"
                })
                
        elif op_name == "CONSTITUTE_NOEMA":
            noesis_mode = params.get("noesis_mode", "PERCEPTION")
            target_object = params.get("target_object", "UNKNOWN")
            known_faces = params.get("visible_aspects", [])
            hidden_faces = params.get("co_intended_horizon", [])
            lifeworld_context = params.get("lifeworld_context", "ROOM")
            
            validity = 1.0 if world_bracketed else 0.5
            if noesis_mode == "RECOLLECTION":
                validity *= 0.85
            elif noesis_mode == "IMAGINATION":
                validity *= 0.70
                
            noema_entry = {
                "noematic_core": target_object,
                "noesis_act": noesis_mode,
                "internal_horizon": hidden_faces,
                "external_horizon": lifeworld_context,
                "constitutional_validity": round(validity, 2)
            }
            constituted_noemata.append(noema_entry)
            intentional_synthesis_score += round(validity * 25.0, 2)
            
            action_log.append({
                "op": "CONSTITUTE_NOEMA",
                "attitude": attitude,
                "noesis_act": noesis_mode,
                "noematic_core": target_object,
                "constitutional_validity": round(validity, 2),
                "status": "NOEMA_CONSTITUTED"
            })
            
        elif op_name == "TRANSCENDENTAL_REDUCTION":
            if world_bracketed and eidetic_clarity >= 30.0:
                attitude = "TRANSCENDENTAL_EGO"
                attitude_history.append(attitude)
                epoche_depth = 100.0
                status = "TRANSCENDENTAL_SUBJECTIVITY_UNVEILED"
            else:
                status = "REDUCTION_PRECONDITIONS_UNMET"
                
            action_log.append({
                "op": "TRANSCENDENTAL_REDUCTION",
                "attitude": attitude,
                "status": status
            })

    if attitude == "TRANSCENDENTAL_EGO" and len(constituted_noemata) >= 1:
        verdict = "TRANSCENDENTAL_PHENOMENOLOGIST"
    elif attitude == "EIDETIC_REDUCTION":
        verdict = "EIDETIC_RESEARCHER"
    elif attitude == "PHENOMENOLOGICAL_REDUCTION":
        verdict = "BRACKETED_INVESTIGATOR"
    else:
        verdict = "NAIVE_REALIST_OBSERVER"
        
    result = {
        "agent_id": agent_id,
        "metrics": {
            "current_attitude": attitude,
            "attitude_history": attitude_history,
            "world_bracketed": world_bracketed,
            "epoche_depth": round(epoche_depth, 2),
            "eidetic_clarity": round(eidetic_clarity, 2),
            "intentional_synthesis_score": round(intentional_synthesis_score, 2),
            "total_noemata_count": len(constituted_noemata),
            "eidetic_invariants": sorted(eidetic_invariants)
        },
        "verdict": verdict,
        "constituted_noemata": constituted_noemata,
        "action_log": action_log
    }
    
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    solve()
