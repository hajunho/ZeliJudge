import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    subject_id = input_data.get("subject_id", "Hegelian_Citizen")
    actions = input_data.get("actions", [])
    
    abstract_right_score = 0.0
    morality_score = 0.0
    family_score = 0.0
    civil_society_score = 0.0
    state_score = 0.0
    
    property_count = 0
    contracts_count = 0
    crimes_negated = 0
    market_trades = 0
    pauperism_mitigated = 0
    civic_duties = 0
    
    action_log = []
    
    for act in actions:
        atype = act.get("type")
        params = act.get("params", {})
        
        if atype == "ACQUIRE_PROPERTY":
            property_count += 1
            abstract_right_score += min(10.0, params.get("value", 10.0) * 0.5)
            action_log.append({
                "type": atype,
                "domain": "ABSTRACT_RIGHT",
                "status": "PROPERTY_EMBODIED_WILL",
                "desc": "External object appropriated as sphere of personality"
            })
            
        elif atype == "SIGN_CONTRACT":
            contracts_count += 1
            abstract_right_score += min(10.0, params.get("value", 10.0) * 0.5)
            action_log.append({
                "type": atype,
                "domain": "ABSTRACT_RIGHT",
                "status": "COMMON_WILL_FORMED",
                "desc": "Two persons mediating property rights via mutual recognition"
            })
            
        elif atype == "COMMIT_CRIME":
            severity = params.get("severity", 5.0)
            abstract_right_score = max(0.0, abstract_right_score - severity)
            action_log.append({
                "type": atype,
                "domain": "ABSTRACT_RIGHT",
                "status": "RIGHT_NEGATED",
                "desc": "Transgression against universal will"
            })
            
        elif atype == "ENFORCE_PUNISHMENT":
            severity = params.get("severity", 5.0)
            crimes_negated += 1
            abstract_right_score += min(10.0, severity * 1.0)
            action_log.append({
                "type": atype,
                "domain": "ABSTRACT_RIGHT",
                "status": "NEGATION_OF_NEGATION_RIGHT_RESTORED",
                "desc": "Retribution restores the reality of right as rationality"
            })
            
        elif atype == "INTERNAL_INTENTION":
            clarity = params.get("moral_clarity", 5.0)
            is_hypocrisy = params.get("is_empty_formalism", False)
            if is_hypocrisy:
                morality_score = max(0.0, morality_score - 5.0)
                status = "EMPTY_FORMALISM_CRITIQUED"
            else:
                morality_score += min(15.0, clarity * 1.5)
                status = "SUBJECTIVE_WILL_CONGRUENT_WITH_GOOD"
            action_log.append({
                "type": atype,
                "domain": "MORALITY",
                "status": status,
                "desc": "Subjective conscience weighing duty, welfare, and intent"
            })
            
        elif atype == "FAMILY_LOVE":
            solidarity = params.get("solidarity", 10.0)
            family_score += min(10.0, solidarity * 1.0)
            action_log.append({
                "type": atype,
                "domain": "SITTLICHKEIT_FAMILY",
                "status": "NATURAL_ETHICAL_UNITY",
                "desc": "Individual self surrendered into altruistic organic love"
            })
            
        elif atype == "MARKET_TRANSACTION":
            market_trades += 1
            surplus = params.get("utility", 10.0)
            civil_society_score += min(8.0, surplus * 0.5)
            action_log.append({
                "type": atype,
                "domain": "SITTLICHKEIT_CIVIL_SOCIETY",
                "status": "SYSTEM_OF_NEEDS_SATISFACTION",
                "desc": "Self-interest mediated through universal division of labor"
            })
            
        elif atype == "CORPORATION_MUTUAL_AID":
            pauperism_mitigated += 1
            welfare = params.get("welfare_support", 10.0)
            civil_society_score += min(7.0, welfare * 0.7)
            action_log.append({
                "type": atype,
                "domain": "SITTLICHKEIT_CIVIL_SOCIETY",
                "status": "CORPORATION_PAUPERISM_HEALED",
                "desc": "Ethical root of civil society restoring honor and stability"
            })
            
        elif atype == "STATE_CIVIC_DUTY":
            civic_duties += 1
            devotion = params.get("patriotic_rationality", 10.0)
            state_score += min(20.0, devotion * 2.0)
            action_log.append({
                "type": atype,
                "domain": "SITTLICHKEIT_STATE",
                "status": "CONCRETE_FREEDOM_ACTUALIZED",
                "desc": "Union of universal interest and particular individuality"
            })

    abstract_right_final = round(min(30.0, abstract_right_score), 2)
    morality_final = round(min(25.0, morality_score), 2)
    sittlichkeit_final = round(min(45.0, family_score + civil_society_score + state_score), 2)
    
    total_freedom = round(abstract_right_final + morality_final + sittlichkeit_final, 2)
    
    if total_freedom >= 80.0:
        verdict = "CONCRETE_FREEDOM_REALIZED"
    elif total_freedom >= 50.0:
        verdict = "CIVIL_SOCIETY_PARTICULARITY"
    else:
        verdict = "ABSTRACT_LEGALISM_OR_FORMAL_MORALITY"
        
    output = {
        "subject_id": subject_id,
        "metrics": {
            "abstract_right_score": abstract_right_final,
            "morality_score": morality_final,
            "sittlichkeit_score": sittlichkeit_final,
            "total_freedom_realization_score": total_freedom,
            "properties_owned": property_count,
            "contracts_ratified": contracts_count,
            "crimes_negated": crimes_negated,
            "civil_market_trades": market_trades,
            "civic_duties_rendered": civic_duties
        },
        "verdict": verdict,
        "action_log": action_log
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
