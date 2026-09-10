import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    agent_id = input_data.get("agent_id", "Humean_Inquirer")
    perceptions = input_data.get("perceptions", [])
    observations = input_data.get("observations", [])
    claims = input_data.get("claims", [])
    introspection = input_data.get("introspection", {})
    
    # 1. Perception Analysis & Copy Principle
    impressions_map = {}
    ideas_map = {}
    fictions = []
    
    for p in perceptions:
        pid = p.get("id")
        ptype = p.get("type")
        vivacity = p.get("vivacity", 1.0 if ptype == "IMPRESSION" else 0.4)
        
        if ptype == "IMPRESSION":
            impressions_map[pid] = {
                "id": pid,
                "content": p.get("content"),
                "vivacity": vivacity
            }
        elif ptype == "IDEA":
            src_id = p.get("source_impression_id")
            has_source = src_id in impressions_map
            valid_copy = has_source and (impressions_map[src_id]["vivacity"] >= 0.5)
            
            ideas_map[pid] = {
                "id": pid,
                "content": p.get("content"),
                "vivacity": vivacity,
                "source_impression_id": src_id,
                "is_legitimate_copy": valid_copy
            }
            if not valid_copy:
                fictions.append(pid)

    # 2. Hume's Fork & Metaphysics Elimination
    evaluated_claims = []
    flames_count = 0
    
    for c in claims:
        cid = c.get("id")
        ctype = c.get("type")
        stmt = c.get("statement", "")
        
        if ctype == "RELATION_OF_IDEAS":
            evaluated_claims.append({
                "id": cid,
                "fork_branch": "RELATIONS_OF_IDEAS",
                "epistemic_status": "DEMONSTRATIVELY_CERTAIN",
                "negation_conceivable": False,
                "action": "PRESERVE_AS_A_PRIORI_KNOWLEDGE"
            })
        elif ctype == "MATTER_OF_FACT":
            evaluated_claims.append({
                "id": cid,
                "fork_branch": "MATTERS_OF_FACT",
                "epistemic_status": "CONTINGENT_EMPIRICAL",
                "negation_conceivable": True,
                "action": "PROBABLE_INDUCTION_SUBJECT_TO_EXPERIENCE"
            })
        elif ctype == "METAPHYSICAL_SUBSTANCE":
            flames_count += 1
            evaluated_claims.append({
                "id": cid,
                "fork_branch": "SOPHISTRY_AND_ILLUSION",
                "epistemic_status": "UNGROUNDED_METAPHYSICS",
                "negation_conceivable": True,
                "action": "COMMIT_TO_THE_FLAMES"
            })

    # 3. Causality & Problem of Induction
    pair_counts = {}
    pair_conjunctions = {}
    
    for obs in observations:
        ea = obs.get("event_a")
        eb = obs.get("event_b")
        spatial = obs.get("spatial_contiguous", True)
        temporal = obs.get("temporal_priority", True)
        occurred_together = obs.get("conjoined", True)
        
        pair_key = f"{ea}->{eb}"
        pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1
        
        if spatial and temporal and occurred_together:
            pair_conjunctions[pair_key] = pair_conjunctions.get(pair_key, 0) + 1
            
    causal_inferences = []
    for pair_key, total in pair_counts.items():
        conj = pair_conjunctions.get(pair_key, 0)
        rate = round(conj / total, 3) if total > 0 else 0.0
        
        habit_formed = rate >= 0.75 and total >= 3
        belief_level = round(min(1.0, rate * (min(10, total) / 10.0)), 2)
        
        causal_inferences.append({
            "pair": pair_key,
            "observations_count": total,
            "constant_conjunction_rate": rate,
            "habit_formed": habit_formed,
            "customary_belief_strength": belief_level,
            "necessary_connexion_perceived": False,
            "status": "HABITUAL_EXPECTATION" if habit_formed else "INSUFFICIENT_EXPERIENCE"
        })

    # 4. Bundle Theory of Self Introspection
    self_query = introspection.get("query_self", True)
    stream = introspection.get("introspection_stream", [])
    flux_count = len(stream)
    
    self_verdict = {
        "substantial_self_found": False,
        "perceptions_in_flux": flux_count,
        "nature_of_mind": "THEATER_OF_PASSING_PERCEPTIONS",
        "description": "Mind is a bundle or collection of different perceptions which succeed each other with an inconceivable rapidity"
    }

    # Metric calculations
    total_ideas = len(ideas_map)
    valid_ideas = sum(1 for i in ideas_map.values() if i["is_legitimate_copy"])
    copy_score = (valid_ideas / total_ideas * 40.0) if total_ideas > 0 else 40.0
    
    flames_score = min(30.0, flames_count * 15.0)
    induction_score = min(30.0, len(causal_inferences) * 10.0)
    skepticism_score = round(copy_score + flames_score + induction_score, 2)
    
    if skepticism_score >= 80.0:
        verdict = "RADICAL_EMPIRICAL_SKEPTICISM"
    elif skepticism_score >= 50.0:
        verdict = "MODERATE_ACADEMIC_SKEPTICISM"
    else:
        verdict = "DOGMATIC_SLUMBER"

    output = {
        "agent_id": agent_id,
        "metrics": {
            "impressions_count": len(impressions_map),
            "ideas_count": len(ideas_map),
            "fiction_ideas_count": len(fictions),
            "flames_committed_count": flames_count,
            "causal_habits_formed": sum(1 for c in causal_inferences if c["habit_formed"]),
            "epistemic_skepticism_score": skepticism_score
        },
        "verdict": verdict,
        "copy_principle": {
            "ideas": ideas_map,
            "fictions": fictions
        },
        "humes_fork_claims": evaluated_claims,
        "causal_inferences": causal_inferences,
        "bundle_self": self_verdict
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
