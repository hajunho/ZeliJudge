# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #047: Historiography Leopold von Ranke's Source Criticism (Quellenkritik)
https://github.com/hajunho/ZeliJudge
"""

import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def evaluate_source_criticism(data):
    config = data.get("config", {})
    half_life = config.get("temporal_decay_half_life_years", 50.0)

    claims = {c["claim_id"]: c for c in data.get("claims", [])}
    sources = data.get("sources", [])

    source_evaluations = {}

    for s in sources:
        s_id = s["source_id"]

        # 1. External criticism (Physical authenticity & anachronisms)
        phys = s.get("physical_authenticity", {})
        consistent = phys.get("material_age_consistent", True)
        anachronisms = phys.get("anachronisms_detected", 0)

        if not consistent or anachronisms > 0:
            auth_score = max(0.0, 1.0 - 0.4 * anachronisms - (0.5 if not consistent else 0.0))
        else:
            auth_score = 1.0

        is_forgery = (auth_score < 0.3)

        # 2. Temporal proximity
        created_yr = s.get("created_year", 0)
        event_yr = s.get("event_year", 0)
        dt = abs(created_yr - event_yr)
        temporal_score = math.pow(2.0, -dt / half_life)

        # 3. Internal criticism (Reliability & Bias)
        author = s.get("author_reliability", {})
        is_eyewitness = author.get("direct_eyewitness", False)
        eye_score = 1.0 if is_eyewitness else 0.6
        competence = author.get("competence_score", 0.8)
        bias = author.get("conflict_of_interest_bias", 0.0)

        credibility = auth_score * temporal_score * eye_score * competence * (1.0 - bias)
        weight = round(credibility, 3)

        source_evaluations[s_id] = {
            "source_id": s_id,
            "is_forgery": is_forgery,
            "authenticity_score": round(auth_score, 2),
            "temporal_proximity_score": round(temporal_score, 2),
            "credibility_weight": weight,
            "copied_from": s.get("corroboration_links", [])
        }

    # 4. Adjudication of Claims
    claim_results = []
    for c_id in sorted(claims.keys()):
        claim_info = claims[c_id]
        support_sources = []
        refute_sources = []

        for s in sources:
            s_id = s["source_id"]
            if source_evaluations[s_id]["is_forgery"]:
                continue
            for att in s.get("attested_claims", []):
                if att.get("claim_id") == c_id:
                    stance = att.get("stance", "SUPPORT")
                    if stance == "SUPPORT":
                        support_sources.append(s_id)
                    elif stance == "REFUTE":
                        refute_sources.append(s_id)

        # Eliminate dependent copies
        def filter_independent(src_ids):
            indep = []
            for sid in src_ids:
                parents = source_evaluations[sid]["copied_from"]
                if not any(p in src_ids for p in parents):
                    indep.append(sid)
            return sorted(indep)

        indep_support = filter_independent(support_sources)
        indep_refute = filter_independent(refute_sources)

        w_sup = sum(source_evaluations[sid]["credibility_weight"] for sid in indep_support)
        w_ref = sum(source_evaluations[sid]["credibility_weight"] for sid in indep_refute)

        # Testis unus constraint
        witness_factor = 1.0 - (0.35 if len(indep_support) <= 1 else 0.0)

        total_w = w_sup + w_ref + 0.05
        raw_prob = (w_sup / total_w) * witness_factor
        hpi = round(min(1.0, max(0.0, raw_prob)), 2)

        if hpi >= 0.70:
            verdict = "HISTORICALLY_ESTABLISHED"
        elif hpi >= 0.45:
            verdict = "PROBABLE_PLAUSIBLE"
        elif hpi >= 0.20:
            verdict = "CONTESTED_AMBIGUOUS"
        else:
            verdict = "REJECTED_UNSUBSTANTIATED"

        claim_results.append({
            "claim_id": c_id,
            "description": claim_info.get("description", ""),
            "factuality_index": hpi,
            "verdict": verdict,
            "independent_support_witnesses": indep_support,
            "independent_refute_witnesses": indep_refute,
            "support_weight_sum": round(w_sup, 3),
            "refute_weight_sum": round(w_ref, 3)
        })

    return {
        "sources_analyzed": len(sources),
        "source_evaluations": source_evaluations,
        "claims_adjudication": claim_results
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = evaluate_source_criticism(data)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
