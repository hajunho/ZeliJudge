# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #057: 롤랑 바르트의 신화론(Mythologies): 1차 외연(Denotation)에서 2차 내포(Connotation) 및 이데올로기 탈신화화 엔진
Roland Barthes' Mythologies (1957), First-Order Denotation vs Second-Order Connotation/Myth,
Naturalization of Bourgeois Ideology & Reader Stances (Naive, Cynical, Mythologist) Simulator
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_barthes_engine(data):
    config = data.get("config", {})
    thresh = config.get("ideology_weight_threshold", 0.70)

    deno_dict = {d["sign_id"]: d for d in data.get("lexicon_denotations", [])}
    myth_dict = {}
    for m in data.get("myth_connotations", []):
        myth_dict.setdefault(m["base_sign_id"], []).append(m)

    artifacts = data.get("media_artifacts", [])
    analyses = []

    demyth_cnt = 0
    naive_cnt = 0
    total_myths = 0

    for art in artifacts:
        a_id = art["artifact_id"]
        title = art.get("title", "")
        stance = art.get("reader_stance", "MYTHOLOGIST")
        det_denos = art.get("detected_denotations", [])

        first_order = []
        second_order = []

        for s_id in det_denos:
            if s_id in deno_dict:
                d = deno_dict[s_id]
                first_order.append({
                    "sign_id": s_id,
                    "signifier_1": d["signifier"],
                    "signified_1": d["signified"],
                    "literal_domain": d.get("literal_domain", "")
                })

                if s_id in myth_dict:
                    for m in myth_dict[s_id]:
                        total_myths += 1
                        is_nat = m.get("naturalization_strength", 0.0) >= thresh
                        m_type = "NATURALIZED_MYTH" if is_nat else "WEAK_CONNOTATION"

                        if stance == "NAIVE_CONSUMER":
                            r_res = "NATURALIZED_ACCEPTANCE"
                            exposed = None
                        elif stance == "CYNICAL_PRODUCER":
                            r_res = "INSTRUMENTAL_PROPAGANDA"
                            exposed = m.get("ideological_motive", "")
                        else:  # MYTHOLOGIST
                            r_res = "CRITICAL_DEMYTHOLOGIZATION"
                            exposed = m.get("ideological_motive", "")

                        second_order.append({
                            "myth_id": m["myth_id"],
                            "form_2": f"{d['signifier']} + {d['signified']}",
                            "concept_2": m["connoted_concept"],
                            "myth_type": m_type,
                            "naturalization_strength": m["naturalization_strength"],
                            "reading_result": r_res,
                            "exposed_ideology": exposed
                        })

        if stance == "MYTHOLOGIST":
            demyth_cnt += len([s for s in second_order if s["reading_result"] == "CRITICAL_DEMYTHOLOGIZATION"])
        elif stance == "NAIVE_CONSUMER":
            naive_cnt += len([s for s in second_order if s["reading_result"] == "NATURALIZED_ACCEPTANCE"])

        analyses.append({
            "artifact_id": a_id,
            "title": title,
            "reader_stance": stance,
            "denotative_layers": first_order,
            "connotative_myths": second_order
        })

    return {
        "summary": {
            "total_artifacts": len(artifacts),
            "total_myths_detected": total_myths,
            "demythologized_count": demyth_cnt,
            "naturalized_acceptance_count": naive_cnt
        },
        "artifact_analyses": analyses
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_barthes_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
