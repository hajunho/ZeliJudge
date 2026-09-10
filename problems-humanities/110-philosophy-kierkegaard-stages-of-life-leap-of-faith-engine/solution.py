import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    agent_id = input_data.get("agent_id", "Kierkegaard_Pilgrim")
    stage = input_data.get("initial_stage", "AESTHETIC").upper()
    actions = input_data.get("actions", [])
    
    hedonic_level = 0.0
    boredom_level = 0.0
    despair_level = 0.0
    ethical_duty = 0.0
    guilt_level = 0.0
    faith_depth = 0.0
    
    stage_transitions = [stage]
    action_log = []
    
    knight_of_faith = False
    tragic_hero = False
    
    for act in actions:
        atype = act.get("type")
        params = act.get("params", {})
        
        if atype == "SEEK_PLEASURE":
            h_val = params.get("hedonic_value", 10.0)
            hedonic_level += h_val
            boredom_level += h_val * 0.6
            if boredom_level >= 20.0:
                despair_level += (boredom_level - 20.0) * 0.8
            action_log.append({
                "type": atype,
                "stage": stage,
                "status": "PLEASURE_SOUGHT_BOREDOM_ACCUMULATED",
                "hedonic": round(hedonic_level, 2),
                "boredom": round(boredom_level, 2),
                "despair": round(despair_level, 2)
            })
            
        elif atype == "MAKE_ETHICAL_CHOICE":
            duty = params.get("duty_fulfillment", 10.0)
            fidelity = params.get("social_fidelity", 10.0)
            if stage == "AESTHETIC":
                stage = "ETHICAL"
                stage_transitions.append(stage)
            ethical_duty += duty + fidelity
            guilt_level += duty * 0.4
            action_log.append({
                "type": atype,
                "stage": stage,
                "status": "UNIVERSAL_ETHICAL_DUTY_ADOPTED",
                "ethical_duty": round(ethical_duty, 2),
                "guilt": round(guilt_level, 2)
            })
            
        elif atype == "CONFESS_GUILT":
            sincerity = params.get("sincerity", 1.0)
            guilt_recognized = guilt_level * sincerity
            action_log.append({
                "type": atype,
                "stage": stage,
                "status": "REPENTANCE_AND_FINITUDE_ACKNOWLEDGED",
                "guilt_recognized": round(guilt_recognized, 2)
            })
            
        elif atype == "SUSPEND_ETHICAL":
            f_commit = params.get("faith_commitment", 0.9)
            is_divine = params.get("divine_command", True)
            if is_divine and f_commit >= 0.75:
                status = "TELEOLOGICAL_SUSPENSION_VALIDATED"
                knight_of_faith = True
            elif not is_divine and f_commit >= 0.75:
                status = "TRAGIC_HERO_MORAL_SACRIFICE"
                tragic_hero = True
            else:
                status = "UNJUSTIFIED_CRIMINAL_TEMPTATION"
            action_log.append({
                "type": atype,
                "stage": stage,
                "status": status,
                "divine_command": is_divine
            })
            
        elif atype == "LEAP_OF_FAITH":
            depth = params.get("depth_fathoms", 70000.0)
            accept_paradox = params.get("accept_paradox", True)
            if accept_paradox:
                stage = "RELIGIOUS"
                stage_transitions.append(stage)
                faith_depth = depth
                action_log.append({
                    "type": atype,
                    "stage": stage,
                    "status": "LEAP_ACROSS_ABSURD_COMPLETED",
                    "faith_depth_fathoms": depth
                })
            else:
                action_log.append({
                    "type": atype,
                    "stage": stage,
                    "status": "LEAP_ABORTED_RATIONAL_DOUBT",
                    "faith_depth_fathoms": 0
                })

    base_score = 0.0
    if stage == "AESTHETIC":
        base_score = min(40.0, hedonic_level * 0.5) - min(20.0, despair_level * 0.5)
        base_score = max(10.0, base_score)
    elif stage == "ETHICAL":
        base_score = min(75.0, 40.0 + ethical_duty * 0.5)
    elif stage == "RELIGIOUS":
        base_score = min(100.0, 80.0 + (20.0 if knight_of_faith else 10.0))
        
    authenticity_score = round(base_score, 2)
    
    if stage == "RELIGIOUS" and knight_of_faith:
        verdict = "KNIGHT_OF_FAITH"
    elif stage == "ETHICAL" or tragic_hero:
        verdict = "TRAGIC_HERO_OR_ETHICAL_CITIZEN"
    else:
        verdict = "DESPAIRING_AESTHETE"
        
    output = {
        "agent_id": agent_id,
        "metrics": {
            "current_stage": stage,
            "stage_history": stage_transitions,
            "hedonic_level": round(hedonic_level, 2),
            "boredom_level": round(boredom_level, 2),
            "despair_level": round(despair_level, 2),
            "ethical_duty_score": round(ethical_duty, 2),
            "guilt_accumulated": round(guilt_level, 2),
            "faith_depth_fathoms": round(faith_depth, 2),
            "is_single_individual": (stage == "RELIGIOUS"),
            "existential_authenticity_score": authenticity_score
        },
        "verdict": verdict,
        "action_log": action_log
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
