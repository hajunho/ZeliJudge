# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #058: 클로드 레비스트로스의 구조인류학: 신소(Mytheme) 2원 대립 분석 및 신화의 카논 변형 공식(Canonical Formula) 엔진
Claude Lévi-Strauss's Structural Anthropology (1958) & Mythologiques (1964-1971),
Mytheme Binary Oppositions (Nature/Culture, Raw/Cooked), Mediators &
Canonical Formula of Myth: F_x(a) : F_y(b) ≃ F_x(b) : F_{a^-1}(y) Simulator
"""
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_structural_mythology_engine(data):
    config = data.get("config", {})
    tolerance = config.get("isomorphism_tolerance", 0.10)

    axes = {a["axis_id"]: a for a in data.get("binary_axes", [])}
    mytheme_dict = {m["mytheme_id"]: m for m in data.get("mythemes", [])}
    myths = {m["myth_id"]: m for m in data.get("myths", [])}
    inquiries = data.get("canonical_inquiries", [])

    myth_profiles = {}
    for m_id, myth in myths.items():
        seq = myth.get("mytheme_sequence", [])
        themes = [mytheme_dict[tid] for tid in seq if tid in mytheme_dict]

        axis_scores = {}
        for ax_id in axes.keys():
            vals = [t.get("axis_values", {}).get(ax_id, 0.0) for t in themes]
            avg_val = sum(vals) / len(vals) if vals else 0.0
            tension = max(vals) - min(vals) if vals else 0.0
            axis_scores[ax_id] = {
                "mean": round(avg_val, 4),
                "tension": round(tension, 4)
            }

        mediators = []
        for t in themes:
            vals = [abs(t.get("axis_values", {}).get(ax_id, 0.0)) for ax_id in axes.keys()]
            if vals and all(v <= 0.25 for v in vals):
                mediators.append(t["mytheme_id"])

        myth_profiles[m_id] = {
            "myth_id": m_id,
            "culture": myth.get("culture", ""),
            "total_mythemes": len(themes),
            "axis_scores": axis_scores,
            "mediators": sorted(list(set(mediators)))
        }

    inquiry_results = []
    for inq in inquiries:
        iq_id = inq["inquiry_id"]
        s_id = inq["source_myth_id"]
        t_id = inq["target_myth_id"]
        mapping = inq.get("mapping", {})

        term_a = mapping.get("term_a")
        term_b = mapping.get("term_b")
        func_x = mapping.get("func_x")
        func_y = mapping.get("func_y")

        src_themes = [mytheme_dict[tid] for tid in myths.get(s_id, {}).get("mytheme_sequence", []) if tid in mytheme_dict]
        tgt_themes = [mytheme_dict[tid] for tid in myths.get(t_id, {}).get("mytheme_sequence", []) if tid in mytheme_dict]

        has_src_xa = any(t.get("term") == term_a and t.get("function") == func_x for t in src_themes)
        has_src_yb = any(t.get("term") == term_b and t.get("function") == func_y for t in src_themes)

        has_tgt_xb = any(t.get("term") == term_b and t.get("function") == func_x for t in tgt_themes)
        has_tgt_ay = any((t.get("term") == f"{term_a}_inv" or t.get("term_inverted") == term_a) and t.get("function") == func_y for t in tgt_themes)

        is_valid = has_src_xa and has_src_yb and has_tgt_xb and has_tgt_ay
        t_type = "CANONICAL_ISOMORPHISM" if is_valid else "STRUCTURAL_DIVERGENCE"

        inquiry_results.append({
            "inquiry_id": iq_id,
            "source_myth": s_id,
            "target_myth": t_id,
            "canonical_formula": f"F_{func_x}({term_a}) : F_{func_y}({term_b}) ≃ F_{func_x}({term_b}) : F_{term_a}^(-1)({func_y})",
            "isomorphism_valid": is_valid,
            "transformation_type": t_type,
            "verification_details": {
                "source_has_Fx_a": has_src_xa,
                "source_has_Fy_b": has_src_yb,
                "target_has_Fx_b": has_tgt_xb,
                "target_has_Fa_inv_y": has_tgt_ay
            }
        })

    return {
        "summary": {
            "total_myths_analyzed": len(myths),
            "total_inquiries": len(inquiries),
            "canonical_isomorphisms_confirmed": sum(1 for r in inquiry_results if r["isomorphism_valid"]),
            "structural_divergences": sum(1 for r in inquiry_results if not r["isomorphism_valid"])
        },
        "myth_profiles": myth_profiles,
        "inquiry_results": inquiry_results
    }


def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_structural_mythology_engine(data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
