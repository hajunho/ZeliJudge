import sys
import json

def simulate_descartes_meditations(input_data):
    agent_id = input_data.get("agent_id", "Meditator_Descartes")
    config = input_data.get("config", {})
    clarity_threshold = config.get("clarity_threshold", 0.7)
    distinct_threshold = config.get("distinct_threshold", 0.7)
    evil_demon_active = config.get("evil_demon_active", False)
    
    cogito_established = False
    god_existence_proven = False
    material_world_restored = False
    
    propositions = input_data.get("propositions", [])
    evaluations = []
    
    metrics = {
        "propositions_evaluated": len(propositions),
        "beliefs_doubted_and_suspended": 0,
        "clear_and_distinct_truths": 0,
        "epistemic_errors_committed": 0,
        "judgments_suspended": 0,
        "res_cogitans_count": 0,
        "res_extensa_count": 0
    }
    
    for prop in propositions:
        p_id = prop.get("id")
        statement = prop.get("statement", "")
        category = prop.get("category", "SENSORY")
        clarity = prop.get("clarity", 0.5)
        distinctness = prop.get("distinctness", 0.5)
        will_action = prop.get("will_action", "AFFIRM")
        substance_type = prop.get("substance_type", "RES_EXTENSA")
        
        if substance_type == "RES_COGITANS":
            metrics["res_cogitans_count"] += 1
        else:
            metrics["res_extensa_count"] += 1

        if category == "COGITO":
            cogito_established = True
            is_truth = True
            verdict = "COGITO_IMMUTABLE_TRUTH"
            metrics["clear_and_distinct_truths"] += 1
            evaluations.append({
                "prop_id": p_id,
                "statement": statement,
                "verdict": verdict,
                "is_truth": is_truth,
                "will_status": "PROPERLY_ALIGNED"
            })
            continue

        if category == "ONTOLOGICAL_GOD":
            if cogito_established:
                god_existence_proven = True
                is_truth = True
                verdict = "DIVINE_TRADEMARK_VERIFIED"
                metrics["clear_and_distinct_truths"] += 1
            else:
                is_truth = False
                verdict = "PREMATURE_THEOLOGY_WITHOUT_COGITO"
            evaluations.append({
                "prop_id": p_id,
                "statement": statement,
                "verdict": verdict,
                "is_truth": is_truth,
                "will_status": "PROPERLY_ALIGNED" if is_truth else "ERROR_OF_WILL"
            })
            continue

        is_doubted = False
        doubt_reason = "NONE"
        if not god_existence_proven:
            if category == "SENSORY":
                is_doubted = True
                doubt_reason = "SENSORY_ILLUSION_OR_DREAM"
            elif category == "MATHEMATICAL" and evil_demon_active:
                is_doubted = True
                doubt_reason = "MALICIOUS_DEMON_DECEPTION"

        is_clear_and_distinct = (clarity >= clarity_threshold) and (distinctness >= distinct_threshold)
        
        if is_doubted:
            if will_action == "SUSPEND":
                verdict = "METHODOLOGICAL_DOUBT_SUSPENSION"
                metrics["judgments_suspended"] += 1
                metrics["beliefs_doubted_and_suspended"] += 1
                will_status = "VIRTUOUS_RESTRAINT"
            else:
                verdict = f"PREMATURE_ASSENT_DOUBTED_{doubt_reason}"
                metrics["epistemic_errors_committed"] += 1
                will_status = "ERROR_OF_INFINITE_WILL"
        else:
            if is_clear_and_distinct:
                if will_action == "AFFIRM":
                    verdict = "CLEAR_AND_DISTINCT_TRUTH"
                    metrics["clear_and_distinct_truths"] += 1
                    will_status = "PROPERLY_ALIGNED"
                elif will_action == "SUSPEND":
                    verdict = "EXCESSIVE_SKEPTICISM_OF_CLEAR_TRUTH"
                    metrics["judgments_suspended"] += 1
                    will_status = "UNNECESSARY_SUSPENSION"
                else:
                    verdict = "DENIAL_OF_EVIDENT_TRUTH"
                    metrics["epistemic_errors_committed"] += 1
                    will_status = "ERROR_OF_INFINITE_WILL"
            else:
                if will_action == "SUSPEND":
                    verdict = "CONFUSED_IDEA_PRUDENTLY_SUSPENDED"
                    metrics["judgments_suspended"] += 1
                    will_status = "VIRTUOUS_RESTRAINT"
                else:
                    verdict = "ERROR_WILL_EXCEEDED_INTELLECT"
                    metrics["epistemic_errors_committed"] += 1
                    will_status = "ERROR_OF_INFINITE_WILL"

        evaluations.append({
            "prop_id": p_id,
            "statement": statement,
            "verdict": verdict,
            "is_clear_and_distinct": is_clear_and_distinct,
            "will_status": will_status
        })

    if cogito_established and god_existence_proven:
        material_world_restored = True
        epistemic_state = "CARTESIAN_FOUNDATIONAL_CERTAINTY"
    elif cogito_established:
        epistemic_state = "SOLIPSISTIC_COGITO_ISOLATION"
    else:
        epistemic_state = "RADICAL_PYRRHONIAN_CHAOS"

    epistemic_health_score = round(max(0.0, min(100.0, 
        (metrics["clear_and_distinct_truths"] * 25.0 + metrics["beliefs_doubted_and_suspended"] * 15.0 - metrics["epistemic_errors_committed"] * 20.0)
    )), 2)

    return {
        "agent_id": agent_id,
        "epistemic_state": epistemic_state,
        "cogito_established": cogito_established,
        "god_existence_proven": god_existence_proven,
        "material_world_restored": material_world_restored,
        "epistemic_health_score": epistemic_health_score,
        "metrics": metrics,
        "evaluations": evaluations
    }

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_descartes_meditations(data)
    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
