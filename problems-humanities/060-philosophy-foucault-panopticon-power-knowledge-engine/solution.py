# -*- coding: utf-8 -*-
"""
ZeliJudge Humanities Track Problem #060
Michel Foucault: Panopticon & Disciplinary Society Engine (권력-지식과 판옵티콘 규율 사회 엔진)

Operationalizes Michel Foucault's 'Surveiller et punir' (Discipline and Punish, 1975):
1. Panoptic Visibility: Asymmetric visibility (inspecting vs unverifiable tower state).
2. Normalizing Judgment: Deviation from established institutional norm ranges.
3. Hierarchical Observation & Examination: Transforming individuals into cataloged dossiers.
4. Production of Docile Bodies & Internalized Self-Policing.
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)

    config = data.get("config", {})
    thresh = float(config.get("surveillance_intensity_threshold", 0.60))
    norm_penalty = float(config.get("normalization_penalty", 0.15))

    inst_rules = data.get("institution_rules", {})
    inst_type = inst_rules.get("institution_type", "panoptic_institution")
    norm_ranges = inst_rules.get("norm_ranges", {})

    subjects_list = data.get("subjects", [])
    # Preserve order of subjects
    subjects = []
    for s in subjects_list:
        subjects.append({
            "subject_id": s["subject_id"],
            "name": s.get("name", ""),
            "compliance": float(s.get("initial_compliance", 0.5)),
            "metrics": {k: float(v) for k, v in s.get("metrics", {}).items()}
        })

    rounds = data.get("surveillance_rounds", [])
    round_logs = []

    for rnd in rounds:
        r_num = rnd.get("round", 1)
        tower = rnd.get("tower_state", "UNVERIFIABLE")
        exam = bool(rnd.get("examination_conducted", False))
        obs = rnd.get("observed_behaviors", {})

        # Panoptic pressure:
        # Foucault's principle: Power is visible and unverifiable.
        # Even when unverifiable (tower is dark/opaque), subject assumes constant surveillance.
        pressure = 1.0 if tower == "INSPECTING" else 0.8

        subject_states = []

        for s in subjects:
            s_id = s["subject_id"]
            deltas = obs.get(s_id, {}).get("metric_deltas", {})
            for m_k, delta in deltas.items():
                s["metrics"][m_k] = round(s["metrics"].get(m_k, 0.0) + float(delta), 4)

            # Check normalization against norm ranges
            deviations = []
            for m_k, r_range in norm_ranges.items():
                min_v, max_v = float(r_range[0]), float(r_range[1])
                val = s["metrics"].get(m_k, 0.0)
                if val < min_v - 1e-7 or val > max_v + 1e-7:
                    deviations.append(m_k)

            deviations.sort()
            is_deviant = len(deviations) > 0

            old_comp = s["compliance"]
            if is_deviant:
                # Disciplinary corrective sanction
                new_comp = max(0.0, min(1.0, old_comp - norm_penalty + (pressure * 0.05)))
                body_state = "DEVIANT_ABNORMAL"
            else:
                # Normalization reinforcement
                new_comp = max(0.0, min(1.0, old_comp + (pressure * 0.10)))
                if new_comp >= thresh - 1e-7:
                    body_state = "INTERNALIZED_SELF_POLICING"
                else:
                    body_state = "DOCILE_BODY"

            s["compliance"] = round(new_comp, 4)

            # Examination creates individual dossier in the archive of power-knowledge
            dossier_status = "CATALOGED_IN_ARCHIVE" if exam else "UNRECORDED"

            subject_states.append({
                "subject_id": s_id,
                "name": s["name"],
                "compliance": round(new_comp, 4),
                "deviations": deviations,
                "body_state": body_state,
                "dossier_status": dossier_status
            })

        round_logs.append({
            "round": r_num,
            "tower_state": tower,
            "examination_conducted": exam,
            "subject_states": subject_states
        })

    # Summary
    self_policing_cnt = sum(1 for s in subjects if s["compliance"] >= thresh - 1e-7)
    deviants_cnt = len(subjects) - self_policing_cnt
    rate = round(self_policing_cnt / len(subjects), 4) if subjects else 0.0

    output = {
        "summary": {
            "institution_type": inst_type,
            "total_subjects": len(subjects),
            "internalized_self_policing_count": self_policing_cnt,
            "disciplinary_deviants_count": deviants_cnt,
            "panoptic_internalization_rate": rate
        },
        "surveillance_history": round_logs
    }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    solve()
