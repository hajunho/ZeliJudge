import sys
import json

def run_lacan_engine(data):
    subjects = data.get("psychic_subjects", [])
    params = data.get("engine_params", {})
    slippage_thresh = float(params.get("borromean_slippage_threshold", 0.35))

    results = []
    neurosis_count = 0
    psychosis_count = 0
    perversion_count = 0

    for subj in subjects:
        sid = subj["subject_id"]
        age = int(subj.get("developmental_age_months", 24))
        anxiety = float(subj.get("fragmented_body_anxiety", 0.3))
        mirror_clarity = float(subj.get("mirror_recognition_clarity", 0.7))
        castration = float(subj.get("symbolic_castration_acceptance", 0.6))
        trauma = float(subj.get("real_trauma_exposure", 0.2))
        queries = subj.get("desire_queries", [])

        # 1. Mirror Stage
        ego_idx = round(mirror_clarity * (1.0 - anxiety * 0.5), 4)
        mirror_jubilation = (6 <= age <= 18) and (mirror_clarity >= 0.50)

        if mirror_jubilation:
            ego_state = "IMAGINARY_EGO_SYNTHESIS"
        elif anxiety >= 0.60 and mirror_clarity < 0.40:
            ego_state = "CORPS_MORCELE_FRAGMENTATION"
        else:
            ego_state = "SPECULAR_IDENTIFICATION_CONSOLIDATED"

        # 2. RSI Borromean Knot & Clinical Structure
        t_i = ego_idx
        t_s = castration
        t_r = trauma

        if t_s < 0.25:
            knot_status = "BORROMEAN_SLIPPAGE_PSYCHOSIS"
            diagnosis = "PSYCHOSIS"
            psychosis_count += 1
        elif 0.25 <= t_s < 0.50 and t_i >= 0.60:
            knot_status = "DISAVOWAL_PERVERSION_KNOT"
            diagnosis = "PERVERSION"
            perversion_count += 1
        else:
            if t_r >= 0.75:
                knot_status = "TRAUMATIC_REAL_INTRUSION"
            else:
                knot_status = "STABLE_BORROMEAN_KNOT"
            diagnosis = "NEUROSIS"
            neurosis_count += 1

        topological_spread = round(max(abs(t_i - t_s), abs(t_s - t_r), abs(t_r - t_i)), 4)

        # 3. Graph of Desire
        evaluated_queries = []
        for q in queries:
            qid = q["query_id"]
            demand = q.get("big_other_demand", "")
            fantasy = q.get("fantasy_formula", "$\diamond a")

            quilting_anchored = (t_s >= 0.35)
            if not quilting_anchored:
                vector = "METONYMIC_DRIFT"
                che_vuoi_interpretation = "Unconscious unable to anchor meaning; signifier slides indefinitely without quilting point"
            elif t_r >= 0.65:
                vector = "ENCOUNTER_WITH_OBJET_A"
                che_vuoi_interpretation = f"Traversing the fantasy ({fantasy}): radical confrontation with void of the Real"
            else:
                vector = "SUBLIMATION_THROUGH_SIGNIFIER"
                che_vuoi_interpretation = "Subject articulates desire through symbolic substitution and speech addressed to Big Other"

            evaluated_queries.append({
                "query_id": qid,
                "demand": demand,
                "quilting_point_anchored": quilting_anchored,
                "desire_vector": vector,
                "che_vuoi_interpretation": che_vuoi_interpretation
            })

        results.append({
            "subject_id": sid,
            "mirror_stage": {
                "alienated_ego_index": ego_idx,
                "mirror_jubilation": mirror_jubilation,
                "ego_state": ego_state
            },
            "rsi_borromean_knot": {
                "imaginary_tension": t_i,
                "symbolic_tension": t_s,
                "real_tension": t_r,
                "topological_spread": topological_spread,
                "knot_status": knot_status
            },
            "graph_of_desire_queries": evaluated_queries,
            "clinical_structure_diagnosis": diagnosis
        })

    return {
        "subject_evaluations": results,
        "psychoanalytic_cohort_summary": {
            "total_subjects": len(subjects),
            "neurosis_count": neurosis_count,
            "psychosis_count": psychosis_count,
            "perversion_count": perversion_count
        }
    }

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_lacan_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
