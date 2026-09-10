import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

KANT_CATEGORIES = {
    "QUANTITY": {"UNITY", "PLURALITY", "TOTALITY"},
    "QUALITY": {"REALITY", "NEGATION", "LIMITATION"},
    "RELATION": {"SUBSTANCE", "CAUSALITY", "COMMUNITY"},
    "MODALITY": {"POSSIBILITY", "ACTUALITY", "NECESSITY"}
}

NOUMENAL_TOPICS = {"IMMORTAL_SOUL", "COSMOLOGICAL_INFINITY", "GOD_EXISTENCE"}

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    agent_id = input_data.get("agent_id", "Transcendental_Subject")
    ich_denke_active = input_data.get("ich_denke_active", True)
    
    raw_sensations = input_data.get("raw_sensations", [])
    intuited_representations = {}
    aesthetic_failures = []
    
    for sens in raw_sensations:
        sid = sens.get("id")
        content = sens.get("content")
        has_time = sens.get("temporal_timestamp") is not None
        has_space = sens.get("spatial_coord") is not None
        
        is_external = sens.get("is_external", True)
        if not has_time:
            aesthetic_failures.append({"id": sid, "reason": "LACKS_TEMPORAL_FORM"})
            continue
        if is_external and not has_space:
            aesthetic_failures.append({"id": sid, "reason": "EXTERNAL_LACKS_SPATIAL_FORM"})
            continue
            
        intuited_representations[sid] = {
            "id": sid,
            "content": content,
            "intuited_in_time": True,
            "intuited_in_space": is_external,
            "synthesized_by_category": False
        }

    categories_applied = input_data.get("categories_applied", [])
    synthesized_phenomena = {}
    blind_intuitions = 0
    empty_concepts = 0
    
    for cat_op in categories_applied:
        op_id = cat_op.get("op_id", "CAT_OP")
        cat_type = cat_op.get("category_type", "RELATION").upper()
        cat_name = cat_op.get("category_name", "CAUSALITY").upper()
        target_ids = cat_op.get("target_sensations", [])
        
        valid_targets = [tid for tid in target_ids if tid in intuited_representations]
        if not valid_targets:
            empty_concepts += 1
            continue
            
        for tid in valid_targets:
            intuited_representations[tid]["synthesized_by_category"] = True
            
        synthesized_phenomena[op_id] = {
            "op_id": op_id,
            "category": f"{cat_type}:{cat_name}",
            "synthesized_targets": valid_targets,
            "apperception_unified": ich_denke_active,
            "status": "OBJECT_OF_EXPERIENCE_CONSTITUTED" if ich_denke_active else "FRAGMENTED_SENSIBILITY"
        }
        
    blind_intuitions = sum(1 for r in intuited_representations.values() if not r["synthesized_by_category"])

    judgments = input_data.get("synthetic_judgments", [])
    evaluated_judgments = []
    synthetic_a_priori_count = 0
    
    for j in judgments:
        jid = j.get("id")
        jtype = j.get("type", "SYNTHETIC_A_PRIORI")
        stmt = j.get("statement", "")
        domain = j.get("domain", "MATHEMATICS")
        
        if jtype == "ANALYTIC":
            status = "EXPLICATIVE_LOGICAL_NECESSITY"
            extends_knowledge = False
            is_a_priori = True
        elif jtype == "SYNTHETIC_A_POSTERIORI":
            status = "AMPLIATIVE_CONTINGENT_EXPERIENCE"
            extends_knowledge = True
            is_a_priori = False
        else:
            status = "AMPLIATIVE_UNIVERSALLY_NECESSARY"
            extends_knowledge = True
            is_a_priori = True
            synthetic_a_priori_count += 1
            
        evaluated_judgments.append({
            "id": jid,
            "statement": stmt,
            "type": jtype,
            "domain": domain,
            "status": status,
            "extends_knowledge": extends_knowledge,
            "is_a_priori": is_a_priori
        })

    metaphysics = input_data.get("metaphysical_inquiries", [])
    dialectical_results = []
    antinomies_flagged = 0
    
    for q in metaphysics:
        qid = q.get("query_id")
        topic = q.get("topic", "EMPIRICAL_OBJECT").upper()
        
        if topic in NOUMENAL_TOPICS:
            antinomies_flagged += 1
            dialectical_results.append({
                "query_id": qid,
                "topic": topic,
                "realm": "DING_AN_SICH_NOUMENON",
                "knowable": False,
                "epistemic_verdict": "TRANSCENDENTAL_ILLUSION_ANTINOMY",
                "reason": "Exceeds sensible intuition; regulative ideal of reason only, cannot be constituted into scientific knowledge"
            })
        else:
            dialectical_results.append({
                "query_id": qid,
                "topic": topic,
                "realm": "PHENOMENON_ERSCHEINUNG",
                "knowable": True,
                "epistemic_verdict": "LEGITIMATE_OBJECT_OF_EXPERIENCE",
                "reason": "Structured through space-time intuition and categories under transcendental apperception"
            })

    total_sens = len(raw_sensations)
    aesthetic_score = (len(intuited_representations) / total_sens * 25.0) if total_sens > 0 else 25.0
    analytic_score = min(35.0, len(synthesized_phenomena) * 12.0)
    synthetic_score = min(20.0, synthetic_a_priori_count * 10.0)
    critique_score = min(20.0, antinomies_flagged * 10.0)
    
    apperception_penalty = 0.0 if ich_denke_active else -30.0
    total_score = max(0.0, min(100.0, round(aesthetic_score + analytic_score + synthetic_score + critique_score + apperception_penalty, 2)))
    
    if total_score >= 80.0:
        verdict = "TRANSCENDENTAL_IDEALISM_MATURE"
    elif total_score >= 50.0:
        verdict = "DEVELOPING_CRITICAL_PHILOSOPHY"
    else:
        verdict = "PRE_CRITICAL_DOGMATIC_SLUMBER"

    output = {
        "agent_id": agent_id,
        "metrics": {
            "raw_sensations_received": total_sens,
            "intuited_representations": len(intuited_representations),
            "aesthetic_form_failures": len(aesthetic_failures),
            "synthesized_phenomena_count": len(synthesized_phenomena),
            "blind_intuitions_count": blind_intuitions,
            "empty_concepts_count": empty_concepts,
            "synthetic_a_priori_judgments": synthetic_a_priori_count,
            "antinomies_contained": antinomies_flagged,
            "transcendental_unity_of_apperception": ich_denke_active,
            "critical_philosophy_score": total_score
        },
        "verdict": verdict,
        "phenomena": synthesized_phenomena,
        "judgments": evaluated_judgments,
        "dialectic_critique": dialectical_results
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
