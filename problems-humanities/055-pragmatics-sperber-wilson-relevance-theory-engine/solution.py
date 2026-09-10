import sys
import json
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def compute_relevance_for_candidate(prior_context: Dict[str, float], 
                                   inference_rules: List[Dict[str, Any]],
                                   candidate: Dict[str, Any]) -> Dict[str, Any]:
    explicature = candidate.get("explicature", {})
    processing_effort = float(candidate.get("processing_effort", 1.0))
    if processing_effort <= 0:
        processing_effort = 0.001
        
    contextual_implications = []
    strengthenings = []
    eliminations = []
    
    current_beliefs = dict(prior_context)
    effects_score = 0.0
    
    # 1. Direct Assertions on Prior Beliefs
    for fact, conf in explicature.items():
        if fact in current_beliefs:
            prior_conf = current_beliefs[fact]
            if (conf >= 0.5 and prior_conf >= 0.5) or (conf < 0.5 and prior_conf < 0.5):
                delta = abs(conf - prior_conf)
                strengthenings.append({"fact": fact, "prior": prior_conf, "new": conf, "gain": round(delta, 3)})
                effects_score += 1.0 + delta
            else:
                delta = abs(conf - prior_conf)
                eliminations.append({"fact": fact, "eliminated_prior": prior_conf, "new": conf, "gain": round(delta, 3)})
                effects_score += 2.0 + delta
            current_beliefs[fact] = conf
        else:
            current_beliefs[fact] = conf
            effects_score += 1.0

    # 2. Contextual Implications
    for rule in inference_rules:
        premises = rule.get("premises", [])
        conclusion = rule.get("conclusion")
        rule_strength = float(rule.get("strength", 1.0))
        
        satisfied = True
        uses_new_input = False
        min_premise_conf = 1.0
        
        for p in premises:
            val = current_beliefs.get(p, 0.0)
            if val < 0.5:
                satisfied = False
                break
            min_premise_conf = min(min_premise_conf, val)
            if p in explicature:
                uses_new_input = True
                
        if satisfied and uses_new_input and conclusion:
            implication_conf = round(min_premise_conf * rule_strength, 3)
            if conclusion not in prior_context or prior_context[conclusion] < 0.5:
                contextual_implications.append({
                    "conclusion": conclusion,
                    "confidence": implication_conf,
                    "premises": premises
                })
                effects_score += 2.5 * implication_conf
                current_beliefs[conclusion] = implication_conf

    effects_score = round(effects_score, 4)
    relevance_ratio = round(effects_score / processing_effort, 4)

    return {
        "candidate_id": candidate.get("id"),
        "cognitive_effects_score": effects_score,
        "processing_effort": processing_effort,
        "relevance_ratio": relevance_ratio,
        "contextual_implications": contextual_implications,
        "strengthenings": strengthenings,
        "eliminations": eliminations
    }

def find_optimal_relevance(context: Dict[str, Any]) -> Dict[str, Any]:
    prior_beliefs = context.get("prior_beliefs", {})
    rules = context.get("inference_rules", [])
    candidates = context.get("candidates", [])
    
    evaluated = []
    best_candidate = None
    best_ratio = -1.0
    
    for cand in candidates:
        res = compute_relevance_for_candidate(prior_beliefs, rules, cand)
        evaluated.append(res)
        if res["relevance_ratio"] > best_ratio:
            best_ratio = res["relevance_ratio"]
            best_candidate = cand.get("id")
            
    return {
        "optimal_candidate_id": best_candidate,
        "highest_relevance_ratio": best_ratio,
        "candidate_evaluations": evaluated
    }

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    result = find_optimal_relevance(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
