import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def simulate_kantian_engine(input_data):
    maxims = input_data.get("maxims", [])
    
    evaluation_logs = []
    
    stats = {
        "morally_worthy_autonomous": 0,
        "legal_but_heteronomous": 0,
        "strictly_impermissible": 0,
        "deficient_imperfect_duty": 0,
        "kingdom_of_ends_approved": 0
    }

    for item in maxims:
        maxim_id = item["maxim_id"]
        agent_id = item.get("agent_id", "agent")
        action_type = item.get("action_type")
        motive = item.get("motive", "DUTY")
        treats_as_mere_means = item.get("treats_others_as_mere_means", False)
        consent_given = item.get("informed_consent", True)
        
        # Step 1: Universal Law Formulation
        contradiction_in_conception = False
        conception_reason = None
        
        if action_type in ["LYING_PROMISE", "DECEPTIVE_BORROWING"]:
            contradiction_in_conception = True
            conception_reason = "Universal lying destroys the institution of promising itself (Self-defeating)."
        elif action_type in ["SUICIDE_DESPAIR", "SELF_DESTRUCTION"]:
            contradiction_in_conception = True
            conception_reason = "Using self-love to destroy life whose natural purposiveness is life preservation is self-contradictory."
            
        contradiction_in_will = False
        will_reason = None
        
        if action_type in ["REFUSE_AID", "INDIFFERENCE_TO_SUFFERING"]:
            contradiction_in_will = True
            will_reason = "A rational agent cannot consistently will a world of non-assistance, as one inevitably needs aid."
        elif action_type in ["WASTE_TALENTS", "SLOTH_IDLENESS"]:
            contradiction_in_will = True
            will_reason = "A rational being necessarily wills that faculties be developed, for they serve diverse possible ends."

        # Step 2: Humanity Formulation
        humanity_violated = False
        humanity_reason = None
        
        if treats_as_mere_means or not consent_given:
            humanity_violated = True
            humanity_reason = "Rational humanity treated merely as a means (instrumental exploitation without informed consent)."
        elif action_type in ["LYING_PROMISE", "DECEPTIVE_BORROWING"]:
            humanity_violated = True
            humanity_reason = "Deception deprives the other of possibility of consenting, reducing them to an instrument."

        # Step 3: Autonomy vs Heteronomy
        is_autonomous_duty = (motive == "DUTY")
        
        # Step 4: Synthesize Verdict
        if contradiction_in_conception or humanity_violated:
            verdict = "STRICTLY_IMPERMISSIBLE"
            duty_type = "PERFECT_DUTY_VIOLATION"
            kingdom_of_ends_valid = False
            stats["strictly_impermissible"] += 1
        elif contradiction_in_will:
            verdict = "DEFICIENT_IMPERFECT_DUTY"
            duty_type = "IMPERFECT_DUTY_VIOLATION"
            kingdom_of_ends_valid = False
            stats["deficient_imperfect_duty"] += 1
        else:
            kingdom_of_ends_valid = True
            stats["kingdom_of_ends_approved"] += 1
            if is_autonomous_duty:
                verdict = "MORALLY_WORTHY_AUTONOMOUS"
                duty_type = "DUTIFUL_AND_AUTONOMOUS"
                stats["morally_worthy_autonomous"] += 1
            else:
                verdict = "LEGAL_BUT_HETERONOMOUS"
                duty_type = "CONFORMS_TO_DUTY_EXTERNALLY"
                stats["legal_but_heteronomous"] += 1
                
        evaluation_logs.append({
            "maxim_id": maxim_id,
            "agent_id": agent_id,
            "action_type": action_type,
            "motive": motive,
            "tests": {
                "universalizability": {
                    "contradiction_in_conception": contradiction_in_conception,
                    "conception_reason": conception_reason,
                    "contradiction_in_will": contradiction_in_will,
                    "will_reason": will_reason
                },
                "humanity_as_end": {
                    "violated": humanity_violated,
                    "reason": humanity_reason
                },
                "autonomy": {
                    "pure_duty_motive": is_autonomous_duty
                }
            },
            "duty_classification": duty_type,
            "final_verdict": verdict,
            "kingdom_of_ends_member": kingdom_of_ends_valid
        })

    total = max(1, len(maxims))
    alignment_score = round(((stats["morally_worthy_autonomous"] * 1.0 + stats["legal_but_heteronomous"] * 0.5) / total) * 100, 2)
    
    return {
        "stats": stats,
        "alignment_score_pct": alignment_score,
        "evaluation_logs": evaluation_logs
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_kantian_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
