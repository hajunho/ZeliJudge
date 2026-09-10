import sys
import os
import json

def analyze_zizek_ideology(input_data: dict) -> dict:
    config = input_data.get("config", {})
    subjects = input_data.get("subjects", [])
    n = len(subjects)

    if n == 0:
        return {
            "subject_evaluations": [],
            "collective_ideology": {
                "total_subjects": 0,
                "mode_distribution": {
                    "classical_false_consciousness": 0,
                    "cynical_reason": 0,
                    "emancipatory_resistance": 0,
                    "blind_drift": 0
                },
                "mean_cynicism": 0.0,
                "mean_fantasy_integrity": 0.0,
                "mean_theft_of_enjoyment": 0.0,
                "traversed_fantasy_count": 0,
                "hegemonic_diagnosis": "FRAGMENTED_IDEOLOGICAL_FIELD"
            }
        }

    evaluations = []
    mode_dist = {
        "classical_false_consciousness": 0,
        "cynical_reason": 0,
        "emancipatory_resistance": 0,
        "blind_drift": 0
    }
    cynicism_sum = 0.0
    fantasy_sum = 0.0
    theft_sum = 0.0
    traversed_count = 0

    for sub in subjects:
        sid = sub.get("id")
        name = sub.get("name")
        knows = bool(sub.get("knows_truth", False))
        acts = bool(sub.get("acts_compliantly", True))

        imaginary = float(sub.get("imaginary_ego", 0.5))
        symbolic = float(sub.get("symbolic_order", 0.5))
        real_trauma = float(sub.get("real_trauma", 0.2))
        scapegoat_bias = float(sub.get("scapegoat_bias", 0.0))

        # 1. Ideological Consciousness Mode
        if not knows and acts:
            ideology_mode = "CLASSICAL_FALSE_CONSCIOUSNESS"
            mode_desc = "맑스적 허위의식: '그들은 알지 못하기에 행한다'"
            cynicism_idx = 0.0
            mode_dist["classical_false_consciousness"] += 1
        elif knows and acts:
            ideology_mode = "CYNICAL_REASON"
            mode_desc = "지젝/슬로터다이크 냉소적 이성: '그들은 잘 알고 있으면서도 행한다'"
            cynicism_idx = round(0.5 + 0.5 * (1.0 - symbolic), 4)
            mode_dist["cynical_reason"] += 1
        elif knows and not acts:
            ideology_mode = "EMANCIPATORY_RESISTANCE"
            mode_desc = "해방적 저항: 환상을 횡단하고 체제 순응 거부"
            cynicism_idx = 0.0
            mode_dist["emancipatory_resistance"] += 1
        else:
            ideology_mode = "BLIND_DRIFT"
            mode_desc = "맹목적 일탈: 비판적 자각 없는 무질서한 표류"
            cynicism_idx = 0.0
            mode_dist["blind_drift"] += 1

        cynicism_sum += cynicism_idx

        # 2. Constitutive Lack (상징계 대타자의 결여)
        constitutive_lack = max(0.0, round(1.0 - symbolic, 4))

        # 3. Fantasy Screen Integrity (환상 스크린이 실재계의 트라우마를 가리는 정도)
        raw_integrity = (symbolic * 0.6 + imaginary * 0.4) * (1.0 - real_trauma * 0.8)
        fantasy_integrity = max(0.0, min(1.0, round(raw_integrity, 4)))
        fantasy_sum += fantasy_integrity

        if fantasy_integrity >= 0.70:
            fantasy_status = "HEGEMONIC_FANTASY_STABLE"
        elif fantasy_integrity >= 0.35:
            fantasy_status = "FANTASY_FISSURED"
        else:
            fantasy_status = "ERUPTION_OF_THE_REAL"

        # 4. Theft of Enjoyment (향유의 도둑질 투사도)
        theft_raw = (constitutive_lack * 0.6 + real_trauma * 0.4) * scapegoat_bias
        theft_of_enjoyment = max(0.0, min(1.0, round(theft_raw, 4)))
        theft_sum += theft_of_enjoyment

        # 5. Traversing the Fantasy (환상의 횡단 판정)
        traversed = (knows and not acts and fantasy_integrity < 0.35)
        if traversed:
            traversed_count += 1

        evaluations.append({
            "id": sid,
            "name": name,
            "ideology_mode": ideology_mode,
            "mode_desc": mode_desc,
            "cynicism_index": cynicism_idx,
            "constitutive_lack": constitutive_lack,
            "fantasy_integrity": fantasy_integrity,
            "fantasy_status": fantasy_status,
            "theft_of_enjoyment": theft_of_enjoyment,
            "traversed_fantasy": traversed
        })

    mean_cynicism = round(cynicism_sum / n, 4)
    mean_fantasy = round(fantasy_sum / n, 4)
    mean_theft = round(theft_sum / n, 4)

    cynical_ratio = mode_dist["cynical_reason"] / n
    classical_ratio = mode_dist["classical_false_consciousness"] / n
    emancipatory_ratio = mode_dist["emancipatory_resistance"] / n

    if cynical_ratio >= 0.50:
        diagnosis = "CYNICAL_POST_IDEOLOGICAL_HEGEMONY"
    elif mean_theft >= 0.50:
        diagnosis = "POPULIST_OTHERING_SCAPEGOAT_POLARIZATION"
    elif classical_ratio >= 0.50:
        diagnosis = "ORTHODOX_DOCTRINAL_HEGEMONY"
    elif emancipatory_ratio >= 0.40:
        diagnosis = "COUNTER_HEGEMONIC_FERMENT"
    else:
        diagnosis = "FRAGMENTED_IDEOLOGICAL_FIELD"

    return {
        "subject_evaluations": evaluations,
        "collective_ideology": {
            "total_subjects": n,
            "mode_distribution": mode_dist,
            "mean_cynicism": mean_cynicism,
            "mean_fantasy_integrity": mean_fantasy,
            "mean_theft_of_enjoyment": mean_theft,
            "traversed_fantasy_count": traversed_count,
            "hegemonic_diagnosis": diagnosis
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
    result = analyze_zizek_ideology(data)
    print(json.dumps(result, ensure_ascii=False))
