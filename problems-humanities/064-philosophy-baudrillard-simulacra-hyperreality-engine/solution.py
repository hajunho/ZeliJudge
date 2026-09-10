import sys
import os
import json

def analyze_baudrillard_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    deterrence_coupling = float(config.get("deterrence_coupling", 0.25))
    th_hyper = float(config.get("implosion_threshold_hyper", 0.70))
    th_sim = float(config.get("implosion_threshold_sim", 0.40))

    entities = input_data.get("entities", [])
    n = len(entities)
    if n == 0:
        return {
            "entity_evaluations": [],
            "phase_counts": {"phase_1": 0, "phase_2": 0, "phase_3": 0, "phase_4": 0},
            "deterrence_effect": {"alibi_present": False, "deterrence_factor": 0.0},
            "system_metrics": {
                "mean_hyperreality": 0.0,
                "implosion_index": 0.0,
                "system_diagnosis": "CLASSICAL_REPRESENTATION"
            }
        }

    evaluations = []
    phase_counts = {"phase_1": 0, "phase_2": 0, "phase_3": 0, "phase_4": 0}
    alibi_entities = []

    for e in entities:
        eid = e.get("id")
        name = e.get("name")
        has_ref = bool(e.get("referent_presence", True))
        f = float(e.get("referent_fidelity", 1.0))
        m = float(e.get("masking_index", 0.0))
        a = float(e.get("code_autonomy", 0.0))
        p = float(e.get("hyperreality_precession", 0.0))
        is_alibi = bool(e.get("is_alibi_deterrent", False))

        # Phase determination
        if has_ref:
            if f >= 0.70 and m <= 0.25 and a <= 0.30:
                phase = 1
                phase_name = "PHASE_1_SACRAMENTAL_REFLECTION"
                stage_desc = "깊은 실재의 충실한 반영 (Good Appearance)"
            else:
                phase = 2
                phase_name = "PHASE_2_MALEFICENT_MASKING"
                stage_desc = "깊은 실재의 왜곡 및 변조 (Evil Appearance)"
            hyper_idx = max(0.0, round(0.2 * m - 0.3 * f, 4))
        else:
            if (a >= 0.70 or p >= 0.70) and not (m >= 0.70 and p < 0.50):
                phase = 4
                phase_name = "PHASE_4_PURE_SIMULACRUM"
                stage_desc = "실재와 무관한 순수 시뮬라크르 및 초과실재"
            else:
                phase = 3
                phase_name = "PHASE_3_ABSENCE_CONCEALMENT"
                stage_desc = "깊은 실재의 부재를 은폐하는 환영적 알리바이"
            hyper_idx = min(1.0, max(0.0, round(0.4 * a + 0.6 * p, 4)))

        phase_counts[f"phase_{phase}"] += 1

        # Precession status
        if p >= 0.75:
            precession_status = "MODEL_PRECEDES_REALITY"
        elif p >= 0.40:
            precession_status = "PARTIAL_PRECESSION"
        else:
            precession_status = "TERRITORY_PRECEDES_MAP"

        if is_alibi and phase == 3:
            alibi_entities.append((m, eid))

        evaluations.append({
            "id": eid,
            "name": name,
            "phase": phase,
            "phase_name": phase_name,
            "stage_desc": stage_desc,
            "referent_presence": has_ref,
            "hyperreality_index": hyper_idx,
            "precession_status": precession_status,
            "is_alibi": is_alibi and phase == 3,
            "reality_alibi_score": 0.0,
            "status_badge": "NORMAL"
        })

    # Disneyland / Deterrence Effect
    alibi_present = len(alibi_entities) > 0
    if alibi_present:
        alibi_count = len(alibi_entities)
        sum_masking = sum(item[0] for item in alibi_entities)
        deterrence_factor = min(1.0, round(alibi_count * 0.25 + sum_masking * deterrence_coupling, 4))
    else:
        deterrence_factor = 0.0

    for ev in evaluations:
        if alibi_present and ev["phase"] in [1, 2]:
            ev["reality_alibi_score"] = round(deterrence_factor * (1.0 - ev["hyperreality_index"]), 4)
            ev["status_badge"] = "REINFORCED_BY_ALIBI"
        elif ev["phase"] == 4:
            ev["status_badge"] = "HYPERREAL"
        elif ev["phase"] == 3:
            ev["status_badge"] = "DETERRENCE_ALIBI" if ev["is_alibi"] else "ABSENCE_CONCEALED"
        else:
            ev["status_badge"] = "AUTHENTIC"

    # System metrics
    mean_hyper = round(sum(ev["hyperreality_index"] for ev in evaluations) / n, 4)
    phase_4_ratio = phase_counts["phase_4"] / n
    implosion_idx = min(1.0, round(mean_hyper * (1.0 + phase_4_ratio), 4))

    if implosion_idx >= th_hyper:
        diagnosis = "SYSTEMIC_HYPERREALITY"
    elif implosion_idx >= th_sim:
        diagnosis = "SIMULATION_COLONIZATION"
    else:
        diagnosis = "CLASSICAL_REPRESENTATION"

    return {
        "entity_evaluations": evaluations,
        "phase_counts": phase_counts,
        "deterrence_effect": {
            "alibi_present": alibi_present,
            "alibi_count": len(alibi_entities),
            "deterrence_factor": deterrence_factor
        },
        "system_metrics": {
            "mean_hyperreality": mean_hyper,
            "phase_4_ratio": round(phase_4_ratio, 4),
            "implosion_index": implosion_idx,
            "system_diagnosis": diagnosis
        }
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = analyze_baudrillard_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
