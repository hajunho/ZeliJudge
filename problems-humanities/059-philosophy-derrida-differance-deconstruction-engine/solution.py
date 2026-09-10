# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #059: 자크 데리다의 해체주의: 차연(Différance), 흔적(Trace) 및 위계적 2항 대립 아포리아(Aporia) 분석 엔진
Jacques Derrida's Deconstruction (1967 Of Grammatology), Différance (Spatial Difference + Temporal Deferral),
Trace, Critique of Logocentrism/Phonocentrism, Textual Aporia & Undecidables (Pharmakon, Arche-Writing, Supplement) Simulator
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_deconstruction_engine(data):
    config = data.get("config", {})
    max_depth = config.get("max_deferral_depth", 10)
    asym_thresh = config.get("asymmetry_threshold", 0.60)

    pairs = {p["pair_id"]: p for p in data.get("binary_hierarchies", [])}
    traces = {t["term_id"]: t for t in data.get("sign_traces", [])}
    texts = data.get("target_texts", [])

    results = []
    aporia_cnt = 0
    overturned_cnt = 0

    for txt in texts:
        t_id = txt["text_id"]
        title = txt.get("title", "")
        p_id = txt.get("primary_pair_id")
        pair = pairs.get(p_id, {})

        priv_name = pair.get("privileged_term", "Privileged")
        marg_name = pair.get("marginalized_term", "Marginalized")
        undecidable = pair.get("undecidable_concept", "Undecidable")

        freqs = txt.get("term_frequencies", {})
        p_cnt = freqs.get("privileged_count", 0)
        m_cnt = freqs.get("marginalized_count", 0)
        tot = p_cnt + m_cnt
        dom_ratio = round(p_cnt / tot, 4) if tot > 0 else 0.5
        bias = "LOGOCENTRIC_HIERARCHY" if dom_ratio >= asym_thresh else "BALANCED_OR_AMBIGUOUS"

        blind_spots = txt.get("blind_spot_quotes", [])
        explicit_asserts = txt.get("explicit_assertions", [])

        inversion_occurred = len(blind_spots) > 0
        aporia_detected = (len(explicit_asserts) > 0) and (len(blind_spots) > 0)

        if inversion_occurred:
            overturned_cnt += 1
            inv_status = "HIERARCHY_OVERTURNED"
        else:
            inv_status = "HIERARCHY_MAINTAINED"

        if aporia_detected:
            aporia_cnt += 1
            aporia_desc = f"텍스트는 {priv_name}의 순수성을 주장하나, 이를 확립하기 위해 필연적으로 {marg_name}에 기생·의존하는 자기모순적 아포리아 노출"
        else:
            aporia_desc = None

        curr_id = txt.get("start_trace_term_id")
        deferral_path = []
        visited = set()
        while curr_id and len(deferral_path) < max_depth:
            if curr_id in visited:
                deferral_path.append(f"{curr_id} (CIRCULAR_DEFERRAL)")
                break
            visited.add(curr_id)
            deferral_path.append(curr_id)
            if curr_id in traces:
                next_defs = traces[curr_id].get("future_deferrals", [])
                curr_id = next_defs[0] if next_defs else None
            else:
                break

        results.append({
            "text_id": t_id,
            "title": title,
            "binary_pair": {
                "pair_id": p_id,
                "privileged_term": priv_name,
                "marginalized_term": marg_name,
                "undecidable_concept": undecidable
            },
            "asymmetry_analysis": {
                "privileged_count": p_cnt,
                "marginalized_count": m_cnt,
                "dominance_ratio": dom_ratio,
                "bias_status": bias
            },
            "deconstructive_inversion": {
                "status": inv_status,
                "blind_spot_evidence_count": len(blind_spots)
            },
            "aporia": {
                "aporia_detected": aporia_detected,
                "description": aporia_desc
            },
            "re_inscription": {
                "undecidable_concept": undecidable,
                "resolution": f"이항 대립을 해체하고 양자를 동시에 조건짓는 미결정항 '{undecidable}'로 재기입"
            },
            "differance_trace": {
                "start_term": txt.get("start_trace_term_id"),
                "deferral_chain": deferral_path,
                "chain_length": len(deferral_path)
            }
        })

    return {
        "summary": {
            "total_texts_deconstructed": len(texts),
            "logocentric_hierarchies_found": sum(1 for r in results if r["asymmetry_analysis"]["bias_status"] == "LOGOCENTRIC_HIERARCHY"),
            "hierarchies_overturned": overturned_cnt,
            "aporias_exposed": aporia_cnt
        },
        "deconstruction_reports": results
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_deconstruction_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
