import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    agent_id = data.get("agent_id", "Zarathustra_Seeker")
    spirit = data.get("initial_spirit", "CAMEL").upper()
    actions = data.get("actions", [])
    
    endurance_score = 0.0
    lion_freedom_score = 0.0
    creation_score = 0.0
    will_to_power_score = 0.0
    amor_fati_score = 0.0
    comfort_seeking_accum = 0.0
    
    spirit_history = [spirit]
    action_log = []
    
    eternal_recurrence_passed = False
    
    for act in actions:
        atype = act.get("type")
        params = act.get("params", {})
        
        if atype == "BEAR_BURDEN":
            weight = params.get("duty_weight", 10.0)
            endurance_score += weight
            status = "BURDEN_BORNE"
            
            if spirit == "CAMEL" and endurance_score >= 50.0 and params.get("encounter_dragon", False):
                spirit = "LION"
                spirit_history.append(spirit)
                status = "TRANSITION_CAMEL_TO_LION"
                
            action_log.append({
                "type": "BEAR_BURDEN",
                "spirit": spirit,
                "status": status,
                "endurance_score": round(endurance_score, 2)
            })
            
        elif atype == "ROAR_SACRED_NO":
            if spirit != "LION":
                action_log.append({
                    "type": "ROAR_SACRED_NO",
                    "spirit": spirit,
                    "status": "CANNOT_ROAR_NON_LION"
                })
            else:
                intensity = params.get("defiance_intensity", 10.0)
                lion_freedom_score += intensity
                status = "DRAGON_CONFRONTED_SACRED_NO"
                
                if lion_freedom_score >= 40.0 and params.get("creates_open_space", False):
                    spirit = "CHILD"
                    spirit_history.append(spirit)
                    status = "TRANSITION_LION_TO_CHILD"
                    
                action_log.append({
                    "type": "ROAR_SACRED_NO",
                    "spirit": spirit,
                    "status": status,
                    "lion_freedom_score": round(lion_freedom_score, 2)
                })
                
        elif atype == "SACRED_YES_PLAY":
            if spirit != "CHILD":
                action_log.append({
                    "type": "SACRED_YES_PLAY",
                    "spirit": spirit,
                    "status": "CANNOT_CREATE_NON_CHILD"
                })
            else:
                creative_act = params.get("creativity_value", 20.0)
                sacred_yes = params.get("sacred_yes", True)
                if sacred_yes:
                    creation_score += creative_act
                    status = "NEW_VALUES_CREATED"
                else:
                    status = "PLAY_ABORTED"
                    
                action_log.append({
                    "type": "SACRED_YES_PLAY",
                    "spirit": spirit,
                    "status": status,
                    "creation_score": round(creation_score, 2)
                })
                
        elif atype == "EXERCISE_WILL_TO_POWER":
            effort = params.get("self_overcoming_effort", 15.0)
            will_to_power_score += effort
            action_log.append({
                "type": "EXERCISE_WILL_TO_POWER",
                "spirit": spirit,
                "status": "SELF_OVERCOMING_ACHIEVED",
                "will_to_power_score": round(will_to_power_score, 2)
            })
            
        elif atype == "SEEK_PETTY_COMFORT":
            comfort = params.get("comfort_level", 0.5)
            comfort_seeking_accum += comfort
            action_log.append({
                "type": "SEEK_PETTY_COMFORT",
                "spirit": spirit,
                "status": "PETTY_HAPPINESS_INDULGED",
                "comfort_seeking_accum": round(comfort_seeking_accum, 2)
            })
            
        elif atype == "TEST_ETERNAL_RECURRENCE":
            embrace = params.get("embrace_infinite_loop", False)
            regret = max(0.0, min(1.0, params.get("regret_level", 0.0)))
            
            if embrace and regret <= 0.15:
                eternal_recurrence_passed = True
                amor_fati_score = round(100.0 * (1.0 - regret), 2)
                status = "ETERNAL_RECURRENCE_AFFIRMED_AMOR_FATI"
            else:
                eternal_recurrence_passed = False
                amor_fati_score = round(max(0.0, 50.0 * (1.0 - regret)), 2)
                status = "CRUSHED_BY_GREATEST_WEIGHT"
                
            action_log.append({
                "type": "TEST_ETERNAL_RECURRENCE",
                "spirit": spirit,
                "status": status,
                "amor_fati_score": amor_fati_score
            })

    stage_weights = {"CAMEL": 20.0, "LION": 50.0, "CHILD": 80.0}
    base_auth = stage_weights.get(spirit, 20.0)
    auth = base_auth + (will_to_power_score * 0.2) + (creation_score * 0.2) + (amor_fati_score * 0.2)
    auth -= (comfort_seeking_accum * 15.0)
    auth = round(max(0.0, min(100.0, auth)), 2)
    
    if comfort_seeking_accum >= 1.5 and will_to_power_score < 20.0:
        verdict = "LAST_MAN"
    elif spirit == "CHILD" and eternal_recurrence_passed and will_to_power_score >= 30.0:
        verdict = "UBERMENSCH"
    elif spirit == "CHILD":
        verdict = "CREATIVE_CHILD"
    elif spirit == "LION":
        verdict = "REBELLIOUS_LION"
    elif spirit == "CAMEL":
        verdict = "BURDENED_CAMEL"
    else:
        verdict = "PASSIVE_NIHILIST"
        
    result = {
        "agent_id": agent_id,
        "metrics": {
            "current_spirit": spirit,
            "spirit_history": spirit_history,
            "endurance_score": round(endurance_score, 2),
            "lion_freedom_score": round(lion_freedom_score, 2),
            "creation_score": round(creation_score, 2),
            "will_to_power_score": round(will_to_power_score, 2),
            "amor_fati_score": round(amor_fati_score, 2),
            "comfort_seeking_accum": round(comfort_seeking_accum, 2),
            "eternal_recurrence_passed": eternal_recurrence_passed,
            "existential_authenticity_score": auth
        },
        "verdict": verdict,
        "action_log": action_log
    }
    
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    solve()
