import sys
import json
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def evaluate_speech_act(context: Dict[str, Any], utterance: Dict[str, Any]) -> Dict[str, Any]:
    speaker = utterance.get("speaker", "")
    hearer = utterance.get("hearer", "")
    syntactic_form = utterance.get("syntactic_form", "Declarative")
    verb = utterance.get("performative_verb", "")
    force_type = utterance.get("force_type", "")
    prop = utterance.get("proposition", {})
    indirect_cue = utterance.get("indirect_cue", None)
    
    # 1. Direct Illocutionary Force
    direct_force = {
        "Declarative": "ASSERTIVE",
        "Imperative": "DIRECTIVE",
        "Interrogative": "DIRECTIVE_QUESTION",
        "Exclamative": "EXPRESSIVE"
    }.get(syntactic_form, force_type or "ASSERTIVE")
    
    if verb in ["promise", "swear", "vow", "guarantee"]:
        direct_force = "COMMISSIVE"
    elif verb in ["order", "request", "ask", "command", "plead"]:
        direct_force = "DIRECTIVE"
    elif verb in ["state", "claim", "assert", "report"]:
        direct_force = "ASSERTIVE"
    elif verb in ["thank", "apologize", "congratulate"]:
        direct_force = "EXPRESSIVE"
    elif verb in ["declare", "sentence", "baptize", "fire", "pronounce"]:
        direct_force = "DECLARATION"

    is_indirect = False
    effective_force = direct_force
    
    if indirect_cue:
        is_indirect = True
        if indirect_cue in ["ability_request", "desire_statement", "reason_question"]:
            effective_force = "DIRECTIVE"
        elif indirect_cue == "intention_question":
            effective_force = "COMMISSIVE"

    # 2. Felicity Conditions Check
    violations = []
    flaw_type = None
    
    # A. Propositional Content Condition
    if effective_force == "COMMISSIVE":
        if prop.get("actor") != "speaker" or prop.get("time") != "future":
            violations.append({"condition": "Propositional Content", "reason": "Commissive must predicate a future act of the speaker."})
            flaw_type = "MISFIRE"
    elif effective_force == "DIRECTIVE":
        if prop.get("actor") != "hearer" or prop.get("time") != "future":
            violations.append({"condition": "Propositional Content", "reason": "Directive must predicate a future act of the hearer."})
            flaw_type = "MISFIRE"

    # B. Preparatory Condition
    authorities = context.get("authorities", {})
    speaker_auth = authorities.get(speaker, [])
    
    if effective_force == "DECLARATION":
        required_auth = utterance.get("required_authority")
        if required_auth and required_auth not in speaker_auth:
            violations.append({"condition": "Preparatory Condition", "reason": f"Speaker lacks authority '{required_auth}'."})
            flaw_type = "MISFIRE"
    elif effective_force == "COMMISSIVE":
        if not context.get("hearer_prefers_action", True):
            violations.append({"condition": "Preparatory Condition", "reason": "Hearer does not prefer or welcome the promised action."})
            flaw_type = "MISFIRE"
    elif effective_force == "DIRECTIVE":
        capabilities = context.get("capabilities", {}).get(hearer, [])
        action = prop.get("action")
        if action and action not in capabilities:
            violations.append({"condition": "Preparatory Condition", "reason": f"Hearer lacks capability to perform '{action}'."})
            flaw_type = "MISFIRE"

    # C. Sincerity Condition
    speaker_intentions = context.get("speaker_intentions", {}).get(speaker, {})
    if effective_force == "COMMISSIVE":
        if not speaker_intentions.get("intends_to_perform", True):
            violations.append({"condition": "Sincerity Condition", "reason": "Speaker has no intention of fulfilling commitment."})
            if not flaw_type:
                flaw_type = "ABUSE"
    elif effective_force == "ASSERTIVE":
        speaker_beliefs = context.get("speaker_beliefs", {}).get(speaker, {})
        claim_key = prop.get("claim")
        if claim_key and not speaker_beliefs.get(claim_key, True):
            violations.append({"condition": "Sincerity Condition", "reason": "Speaker does not believe the asserted proposition."})
            if not flaw_type:
                flaw_type = "ABUSE"

    is_felicitous = (len(violations) == 0)
    verdict = "FELICITOUS" if is_felicitous else flaw_type
    
    new_institutional_state = dict(context.get("institutional_state", {}))
    if is_felicitous and effective_force == "DECLARATION":
        state_change = utterance.get("state_transformation", {})
        for k, v in state_change.items():
            new_institutional_state[k] = v

    return {
        "direct_force": direct_force,
        "effective_force": effective_force,
        "is_indirect": is_indirect,
        "is_felicitous": is_felicitous,
        "verdict": verdict,
        "flaw_type": flaw_type,
        "violations": violations,
        "updated_institutional_state": new_institutional_state
    }

def process_dialogue(data: Dict[str, Any]) -> Dict[str, Any]:
    context = data.get("context", {})
    utterances = data.get("utterances", [])
    
    evaluations = []
    current_context = dict(context)
    
    for utt in utterances:
        res = evaluate_speech_act(current_context, utt)
        evaluations.append({
            "utterance_id": utt.get("id", ""),
            "evaluation": res
        })
        # If institutional state changed, update context for subsequent utterances
        current_context["institutional_state"] = res["updated_institutional_state"]
        
    return {
        "evaluations": evaluations,
        "final_institutional_state": current_context.get("institutional_state", {})
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    res = process_dialogue(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
