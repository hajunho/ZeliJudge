import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
        
    input_data = json.loads(raw_input)
    
    social = input_data.get("social_climate", {})
    conformity_pressure = social.get("conformity_pressure", 0.5)
    paternalism_bias = social.get("paternalism_bias", 0.3)
    
    actions = input_data.get("individual_actions", [])
    
    action_evaluations = []
    total_protected = 0
    total_intervened = 0
    total_tyranny_blocked = 0
    accumulated_truth_vitality = 0.0
    accumulated_individuality = 0.0
    
    for act in actions:
        aid = act.get("action_id", "ACT")
        agent = act.get("agent", "Anonymous")
        atype = act.get("action_type", "EXPRESSION_DISSENT")
        harm_others = round(float(act.get("harm_severity_to_others", 0.0)), 4)
        offense = round(float(act.get("offense_or_dislike_level", 0.0)), 4)
        is_debate = act.get("is_opinion_or_debate", True)
        veracity = act.get("truth_veracity", "PARTIAL_TRUTH")
        
        # 1. Harm Principle Evaluation
        if harm_others >= 0.5:
            ruling = "COERCIVE_INTERVENTION_JUSTIFIED"
            liberty_status = "RESTRICTED"
            justification = "Direct and substantial harm to others detected"
            total_intervened += 1
        elif harm_others < 0.2 and offense >= 0.4 and (conformity_pressure >= 0.5 or paternalism_bias >= 0.4):
            ruling = "TYRANNY_OF_MAJORITY_BLOCKED"
            liberty_status = "PROTECTED_AGAINST_SOCIAL_TYRANNY"
            justification = "Dislike or moral aversion without other-harm cannot justify suppression"
            total_tyranny_blocked += 1
            total_protected += 1
        else:
            ruling = "INDIVIDUAL_SOVEREIGNTY_PROTECTED"
            liberty_status = "SOVEREIGN_LIBERTY"
            justification = "Self-regarding action or harmless diversity of lifestyle"
            total_protected += 1
            
        # 2. Epistemic Vitality & Debate Dynamics
        epistemic_verdict = "NOT_APPLICABLE"
        vitality_gain = 0.0
        
        if is_debate and liberty_status != "RESTRICTED":
            if veracity == "TRUE":
                epistemic_verdict = "DISSENTIENT_TRUTH_REVEALED"
                vitality_gain = 1.0
            elif veracity == "PARTIAL_TRUTH":
                epistemic_verdict = "DIALECTICAL_SYNTHESIS_REFINED"
                vitality_gain = 0.75
            else: # FALSE
                epistemic_verdict = "LIVING_TRUTH_PRESERVED_OVER_DEAD_DOGMA"
                vitality_gain = 0.5
        elif is_debate and liberty_status == "RESTRICTED":
            epistemic_verdict = "SPEECH_RESTRICTED_DUE_TO_CLEAR_AND_PRESENT_HARM"
            vitality_gain = 0.0
            
        accumulated_truth_vitality = round(accumulated_truth_vitality + vitality_gain, 4)
        
        # 3. Individuality & Experiments in Living
        individuality_contrib = 0.0
        if liberty_status in ["PROTECTED_AGAINST_SOCIAL_TYRANNY", "SOVEREIGN_LIBERTY"]:
            individuality_contrib = round(max(0.1, 1.0 - (conformity_pressure * 0.5)), 4)
        accumulated_individuality = round(accumulated_individuality + individuality_contrib, 4)
        
        action_evaluations.append({
            "action_id": aid,
            "agent": agent,
            "action_type": atype,
            "harm_to_others": harm_others,
            "offense_level": offense,
            "ruling": ruling,
            "liberty_status": liberty_status,
            "epistemic_verdict": epistemic_verdict,
            "individuality_contribution": individuality_contrib,
            "justification": justification
        })

    total_actions = len(actions)
    liberty_preservation_rate_pct = round((total_protected / max(1, total_actions)) * 100.0, 2)
    social_progress_index = round((accumulated_truth_vitality * 0.5) + (accumulated_individuality * 0.5), 4)
    
    if liberty_preservation_rate_pct >= 80.0 and social_progress_index >= 3.0:
        civilization_regime = "FLOURISHING_FREE_SOCIETY"
    elif conformity_pressure >= 0.7 and total_tyranny_blocked == 0:
        civilization_regime = "STAGNANT_CHINESE_STATIONARY_MODEL"
    elif total_intervened > total_protected:
        civilization_regime = "COERCIVE_DISCIPLINARY_REGIME"
    else:
        civilization_regime = "CONTESTED_LIBERAL_TRANSITION"

    result = {
        "harm_principle_summary": {
            "total_actions": total_actions,
            "protected_liberties": total_protected,
            "justified_interventions": total_intervened,
            "tyranny_of_majority_blocked": total_tyranny_blocked,
            "liberty_preservation_rate_pct": liberty_preservation_rate_pct
        },
        "epistemic_and_individual_vitality": {
            "accumulated_truth_vitality": accumulated_truth_vitality,
            "accumulated_individuality": accumulated_individuality,
            "social_progress_index": social_progress_index,
            "civilization_regime": civilization_regime
        },
        "action_evaluations": action_evaluations
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
