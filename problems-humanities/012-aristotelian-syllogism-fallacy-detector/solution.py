import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def is_subject_distributed(prop_type: str) -> bool:
    return prop_type in ("A", "E")

def is_predicate_distributed(prop_type: str) -> bool:
    return prop_type in ("E", "O")

def is_negative(prop_type: str) -> bool:
    return prop_type in ("E", "O")

def is_universal(prop_type: str) -> bool:
    return prop_type in ("A", "E")

def is_particular(prop_type: str) -> bool:
    return prop_type in ("I", "O")

VALID_NAMES = {
    ("A", "A", "A", 1): "Barbara",
    ("E", "A", "E", 1): "Celarent",
    ("A", "I", "I", 1): "Darii",
    ("E", "I", "O", 1): "Ferio",
    ("E", "A", "E", 2): "Cesare",
    ("A", "E", "E", 2): "Camestres",
    ("E", "I", "O", 2): "Festino",
    ("A", "O", "O", 2): "Baroco",
    ("I", "A", "I", 3): "Disamis",
    ("A", "I", "I", 3): "Datisi",
    ("O", "A", "O", 3): "Bocardo",
    ("E", "I", "O", 3): "Ferison",
    ("A", "E", "E", 4): "Camenes",
    ("I", "A", "I", 4): "Dimaris",
    ("E", "I", "O", 4): "Fresison"
}

def analyze_syllogism(major_premise: dict, minor_premise: dict, conclusion: dict) -> dict:
    maj_type = major_premise["type"]
    min_type = minor_premise["type"]
    con_type = conclusion["type"]

    S = conclusion["subject"]
    P = conclusion["predicate"]

    maj_terms = {major_premise["subject"], major_premise["predicate"]}
    min_terms = {minor_premise["subject"], minor_premise["predicate"]}
    all_terms = maj_terms.union(min_terms).union({S, P})

    fallacies = []

    if len(all_terms) != 3:
        fallacies.append("FALLACY_OF_FOUR_TERMS")
        return {
            "is_valid": False,
            "classical_name": None,
            "figure": None,
            "mood": f"{maj_type}{min_type}{con_type}",
            "fallacies": fallacies
        }

    m_candidates = maj_terms.intersection(min_terms)
    if len(m_candidates) != 1:
        fallacies.append("FALLACY_OF_FOUR_TERMS")
        return {
            "is_valid": False,
            "classical_name": None,
            "figure": None,
            "mood": f"{maj_type}{min_type}{con_type}",
            "fallacies": fallacies
        }
    M = list(m_candidates)[0]

    if P not in maj_terms or S not in min_terms or M in (S, P):
        fallacies.append("INVALID_PREMISE_TERM_ALIGNMENT")
        return {
            "is_valid": False,
            "classical_name": None,
            "figure": None,
            "mood": f"{maj_type}{min_type}{con_type}",
            "fallacies": fallacies
        }

    if major_premise["subject"] == M and minor_premise["predicate"] == M:
        figure = 1
    elif major_premise["predicate"] == M and minor_premise["predicate"] == M:
        figure = 2
    elif major_premise["subject"] == M and minor_premise["subject"] == M:
        figure = 3
    elif major_premise["predicate"] == M and minor_premise["subject"] == M:
        figure = 4
    else:
        figure = 0

    mood = f"{maj_type}{min_type}{con_type}"

    maj_s_dist = is_subject_distributed(maj_type)
    maj_p_dist = is_predicate_distributed(maj_type)
    m_dist_in_maj = maj_s_dist if major_premise["subject"] == M else maj_p_dist
    p_dist_in_maj = maj_p_dist if major_premise["predicate"] == P else maj_s_dist

    min_s_dist = is_subject_distributed(min_type)
    min_p_dist = is_predicate_distributed(min_type)
    m_dist_in_min = min_s_dist if minor_premise["subject"] == M else min_p_dist
    s_dist_in_min = min_s_dist if minor_premise["subject"] == S else min_p_dist

    s_dist_in_con = is_subject_distributed(con_type)
    p_dist_in_con = is_predicate_distributed(con_type)

    if not (m_dist_in_maj or m_dist_in_min):
        fallacies.append("UNDISTRIBUTED_MIDDLE")

    if p_dist_in_con and not p_dist_in_maj:
        fallacies.append("ILLICIT_MAJOR")

    if s_dist_in_con and not s_dist_in_min:
        fallacies.append("ILLICIT_MINOR")

    if is_negative(maj_type) and is_negative(min_type):
        fallacies.append("EXCLUSIVE_PREMISES")

    has_negative_premise = is_negative(maj_type) or is_negative(min_type)
    is_con_negative = is_negative(con_type)
    if has_negative_premise and not is_con_negative:
        fallacies.append("NEGATIVE_PREMISE_AFFIRMATIVE_CONCLUSION")
    if not has_negative_premise and is_con_negative:
        fallacies.append("AFFIRMATIVE_PREMISES_NEGATIVE_CONCLUSION")

    if is_universal(maj_type) and is_universal(min_type) and is_particular(con_type):
        fallacies.append("EXISTENTIAL_FALLACY")

    is_valid = (len(fallacies) == 0)
    classical_name = VALID_NAMES.get((maj_type, min_type, con_type, figure), None)

    return {
        "is_valid": is_valid,
        "classical_name": classical_name,
        "figure": figure,
        "mood": mood,
        "fallacies": sorted(fallacies)
    }

def reconstruct_enthymeme(given_premise: dict, conclusion: dict) -> dict:
    S = conclusion["subject"]
    P = conclusion["predicate"]

    given_terms = {given_premise["subject"], given_premise["predicate"]}
    if S in given_terms and P not in given_terms:
        M = list(given_terms - {S})[0]
        missing_role = "MAJOR"
        candidate_terms = [(P, M), (M, P)]
    elif P in given_terms and S not in given_terms:
        M = list(given_terms - {P})[0]
        missing_role = "MINOR"
        candidate_terms = [(S, M), (M, S)]
    else:
        return {"reconstructed": False, "missing_role": "UNKNOWN", "valid_candidates_count": 0, "candidates": []}

    candidates = []
    for prop_type in ["A", "E", "I", "O"]:
        for subj, pred in candidate_terms:
            cand_premise = {"type": prop_type, "subject": subj, "predicate": pred}
            if missing_role == "MAJOR":
                res = analyze_syllogism(cand_premise, given_premise, conclusion)
            else:
                res = analyze_syllogism(given_premise, cand_premise, conclusion)

            if res["is_valid"]:
                candidates.append({
                    "missing_role": missing_role,
                    "premise": cand_premise,
                    "classical_name": res["classical_name"],
                    "mood": res["mood"],
                    "figure": res["figure"]
                })

    return {
        "reconstructed": len(candidates) > 0,
        "missing_role": missing_role,
        "valid_candidates_count": len(candidates),
        "candidates": candidates
    }

def process_logic_cases(input_data: dict) -> dict:
    syllogisms = input_data.get("syllogisms", [])
    enthymemes = input_data.get("enthymemes", [])

    syl_results = []
    valid_count = 0
    fallacy_freq = {}

    for s in syllogisms:
        s_id = s.get("id")
        res = analyze_syllogism(s["major_premise"], s["minor_premise"], s["conclusion"])
        res["id"] = s_id
        if res["is_valid"]:
            valid_count += 1
        for f in res["fallacies"]:
            fallacy_freq[f] = fallacy_freq.get(f, 0) + 1
        syl_results.append(res)

    enth_results = []
    for e in enthymemes:
        e_id = e.get("id")
        recon = reconstruct_enthymeme(e["given_premise"], e["conclusion"])
        recon["id"] = e_id
        enth_results.append(recon)

    return {
        "syllogism_evaluation": {
            "total_syllogisms": len(syllogisms),
            "valid_syllogisms_count": valid_count,
            "invalid_syllogisms_count": len(syllogisms) - valid_count,
            "fallacy_frequency": dict(sorted(fallacy_freq.items())),
            "results": syl_results
        },
        "enthymeme_reconstruction": {
            "total_enthymemes": len(enthymemes),
            "results": enth_results
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = process_logic_cases(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
