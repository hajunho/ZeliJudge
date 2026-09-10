import sys
import json

def run_benjamin_engine(data):
    events = data.get("historical_events", [])
    queries = data.get("constellation_queries", [])
    params = data.get("engine_params", {})

    storm_force = float(params.get("storm_of_progress_force", 1.0))
    messianic_power = float(params.get("weak_messianic_power", 1.0))

    # 1. Process events
    processed_events = []
    total_ruins_raw = 0.0
    total_ruins_eff = 0.0
    triumphal_count = 0
    total_suppressed_resonance = 0.0

    for e in events:
        eid = e["id"]
        epoch = e["epoch"]
        desc = e["description"]
        ntype = e["narrative_type"]
        r_weight = float(e.get("ruins_weight", 0.0))
        c_doc = e.get("cultural_document", "")
        b_idx = float(e.get("barbarism_index", 0.0))
        tags = [t.lower() for t in e.get("tags", [])]

        if ntype == "triumphal":
            triumphal_count += 1

        b_pen = round(b_idx * 10.0, 4)
        sub_bonus = 5.0 if ntype == "subjugated" else 0.0
        eff_ruins = round(r_weight + b_pen + sub_bonus, 4)

        if ntype == "subjugated":
            supp_res = round(r_weight * (1.0 + b_idx), 4)
        else:
            supp_res = 0.0

        danger_idx = round(eff_ruins * (1.0 + b_idx), 4)

        total_ruins_raw += r_weight
        total_ruins_eff += eff_ruins
        total_suppressed_resonance += supp_res

        processed_events.append({
            "id": eid,
            "epoch": epoch,
            "description": desc,
            "narrative_type": ntype,
            "ruins_weight": r_weight,
            "cultural_document": c_doc,
            "barbarism_index": b_idx,
            "tags": tags,
            "effective_ruins": eff_ruins,
            "suppressed_resonance": supp_res,
            "danger_index": danger_idx
        })

    total_ruins_raw = round(total_ruins_raw, 4)
    total_ruins_eff = round(total_ruins_eff, 4)
    total_suppressed_resonance = round(total_suppressed_resonance, 4)

    total_count = len(events)
    progress_ratio = round(triumphal_count / total_count, 4) if total_count > 0 else 0.0

    storm_disp = round(total_ruins_eff * storm_force, 4)
    angel_posture = "WINGS_IRRESISTIBLY_BLOWN_FORWARD" if storm_disp >= 100.0 else "GAZING_FIXEDLY_AT_RUINS"

    # 2. Brushing against the grain
    # Sort events by epoch desc, id asc
    sorted_reverse = sorted(processed_events, key=lambda x: (-x["epoch"], x["id"]))

    unmasked_monuments = []
    vanquished_voices = []

    for ev in sorted_reverse:
        if ev["cultural_document"] and ev["barbarism_index"] >= 0.50:
            unmasked_monuments.append({
                "event_id": ev["id"],
                "monument": ev["cultural_document"],
                "barbarism_index": ev["barbarism_index"],
                "unmasked_verdict": "BARBARISM_DOCUMENTED"
            })
        if ev["narrative_type"] == "subjugated":
            vanquished_voices.append(ev["id"])

    # 3. Jetztzeit constellations
    constellation_results = []
    any_blasted = False
    total_blast_energy = 0.0

    for q in queries:
        qid = q["query_id"]
        q_keys = [k.lower() for k in q.get("keywords", [])]
        threshold = float(q.get("threshold_danger", 0.0))

        candidates = []
        for ev in processed_events:
            tag_match = any(k in ev["tags"] for k in q_keys)
            desc_match = any(k in ev["description"].lower() for k in q_keys)
            if (tag_match or desc_match) and ev["danger_index"] >= threshold:
                candidates.append(ev)

        if candidates:
            # Sort by danger_index desc, epoch desc, id asc
            candidates.sort(key=lambda x: (-x["danger_index"], -x["epoch"], x["id"]))
            best = candidates[0]
            blast = round(best["danger_index"] * messianic_power, 4)
            blasted = blast >= 15.0
            if blasted:
                any_blasted = True
            total_blast_energy += blast

            constellation_results.append({
                "query_id": qid,
                "spark_found": True,
                "anchor_event_id": best["id"],
                "danger_index": best["danger_index"],
                "blast_energy": blast,
                "continuum_blasted": blasted,
                "dialectical_image": f"Past crisis '{best['id']}' flashes up into present moment '{qid}'"
            })
        else:
            constellation_results.append({
                "query_id": qid,
                "spark_found": False,
                "anchor_event_id": None,
                "danger_index": 0.0,
                "blast_energy": 0.0,
                "continuum_blasted": False,
                "dialectical_image": "No dialectical constellation formed; crisis absorbed into empty homogeneous time"
            })

    total_blast_energy = round(total_blast_energy, 4)
    total_redemption_index = round(total_blast_energy + (total_suppressed_resonance * messianic_power), 4)

    if any_blasted:
        verdict = "MESSIANIC_RUPTURE_OF_CONTINUUM"
    elif total_suppressed_resonance > 0.0:
        verdict = "LATENT_REVOLUTIONARY_TENSION"
    else:
        verdict = "HOMOGENEOUS_EMPTY_PROGRESSION"

    return {
        "angelus_novus_gaze": {
            "total_raw_ruins": total_ruins_raw,
            "total_effective_wreckage": total_ruins_eff,
            "storm_displacement": storm_disp,
            "angel_posture": angel_posture,
            "progress_illusion_ratio": progress_ratio
        },
        "brushing_against_the_grain": {
            "unmasked_monuments_count": len(unmasked_monuments),
            "unmasked_monuments": unmasked_monuments,
            "vanquished_voices_count": len(vanquished_voices),
            "vanquished_voices_ids": vanquished_voices,
            "total_suppressed_resonance": total_suppressed_resonance
        },
        "jetztzeit_constellations": constellation_results,
        "historical_materialism_verdict": {
            "total_blast_energy": total_blast_energy,
            "total_redemption_index": total_redemption_index,
            "verdict": verdict
        }
    }

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_benjamin_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
