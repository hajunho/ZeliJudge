import sys
import json

def run_deleuze_engine(data):
    scenes = data.get("film_scenes", [])
    queries = data.get("cinematic_queries", [])
    params = data.get("engine_params", {})
    neorealism_factor = float(params.get("neorealism_sensitivity", 1.0))

    processed_scenes = {}
    mov_count = 0
    time_count = 0
    crystal_count = 0

    for sc in scenes:
        sid = sc["scene_id"]
        epoch = sc.get("historical_epoch", 1950)
        s_stim = float(sc.get("sensory_stimulus_intensity", 0.0))
        m_act = float(sc.get("motor_action_response", 0.0))
        space_def = sc.get("space_definition", "organic")
        char_role = sc.get("character_role", "actor")
        v_ratio = float(sc.get("virtual_reflection_ratio", 0.0))

        sms_coupling = round(s_stim * m_act, 4)

        base_rupture = s_stim * (1.0 - m_act)
        role_mod = 0.20 if char_role == "seer" else 0.0
        space_mod = 0.15 if space_def == "any_space_whatever" else 0.0
        postwar_mod = 0.10 if epoch >= 1945 else 0.0

        raw_rupture = (base_rupture + role_mod + space_mod + (postwar_mod * neorealism_factor))
        rupture_score = round(min(1.0, max(0.0, raw_rupture)), 4)

        if space_def == "any_space_whatever":
            asw_index = round(min(1.0, 0.60 + 0.40 * rupture_score), 4)
        else:
            asw_index = round(max(0.0, 0.40 * (1.0 - sms_coupling)), 4)

        crystal_potency = round(v_ratio * rupture_score, 4)
        crystal_formed = crystal_potency >= 0.30

        if rupture_score >= 0.50:
            image_type = "TIME_IMAGE"
            time_count += 1
            if crystal_formed or v_ratio >= 0.60:
                subtype = "CRYSTAL_IMAGE"
                crystal_count += 1
            elif v_ratio >= 0.30:
                subtype = "CHRONOSIGN_SHEET_OF_PAST"
            else:
                subtype = "OPSIGN_SONSIGN_PURE_PERCEPTION"
        else:
            image_type = "MOVEMENT_IMAGE"
            mov_count += 1
            if m_act >= 0.70:
                subtype = "ACTION_IMAGE"
            elif s_stim >= 0.70 and m_act <= 0.30:
                subtype = "AFFECTION_IMAGE"
            else:
                subtype = "PERCEPTION_IMAGE"

        processed_scenes[sid] = {
            "scene_id": sid,
            "epoch": epoch,
            "sms_coupling": sms_coupling,
            "rupture_score": rupture_score,
            "asw_index": asw_index,
            "crystal_circuit_potency": crystal_potency,
            "is_crystal_formed": crystal_formed,
            "image_type": image_type,
            "subtype": subtype
        }

    query_results = []
    for q in queries:
        qid = q["query_id"]
        tsid = q["target_scene_id"]
        r_thresh = float(q.get("sms_rupture_threshold", 0.40))
        c_thresh = float(q.get("crystal_threshold", 0.50))

        if tsid not in processed_scenes:
            query_results.append({
                "query_id": qid,
                "target_scene_id": tsid,
                "status": "SCENE_NOT_FOUND"
            })
            continue

        sc_info = processed_scenes[tsid]
        is_ruptured = sc_info["rupture_score"] >= r_thresh
        is_crystal_qual = sc_info["crystal_circuit_potency"] >= c_thresh

        query_results.append({
            "query_id": qid,
            "target_scene_id": tsid,
            "status": "SUCCESS",
            "image_type": sc_info["image_type"],
            "subtype": sc_info["subtype"],
            "rupture_score": sc_info["rupture_score"],
            "is_sms_ruptured": is_ruptured,
            "crystal_potency": sc_info["crystal_circuit_potency"],
            "is_crystal_circuit_active": is_crystal_qual,
            "philosophical_analysis": f"Scene '{tsid}' operates in {sc_info['image_type']} regime ({sc_info['subtype']})"
        })

    if time_count > mov_count:
        verdict = "MODERN_POSTWAR_TIME_CINEMA"
    elif time_count == mov_count:
        verdict = "TRANSITIONAL_HYBRID_CINEMA"
    else:
        verdict = "CLASSICAL_PREWAR_MOVEMENT_CINEMA"

    return {
        "scene_analysis": list(processed_scenes.values()),
        "cinematic_queries_evaluated": query_results,
        "deleuzian_regime_summary": {
            "total_scenes": len(scenes),
            "movement_image_count": mov_count,
            "time_image_count": time_count,
            "crystal_image_count": crystal_count,
            "dominant_regime": verdict
        }
    }

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_deleuze_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
