import sys
import json
import math

def solve():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    plane = data.get("plane_of_immanence", {})
    dimensions = plane.get("dimensions", 3)
    gradients = plane.get("intensity_gradients", [])

    multiplicities = data.get("multiplicities", [])
    cycles = data.get("repetition_cycles", [])
    critique_enabled = data.get("representation_critique_enabled", True)

    total_intensity_spatium = 0.0
    for g in gradients:
        total_intensity_spatium += g.get("potential_delta", 0.0) ** 2
    total_intensity_spatium = round(math.sqrt(total_intensity_spatium), 4)

    actualization_events = []
    total_singularities = 0
    for m in multiplicities:
        m_id = m.get("id")
        singularities = m.get("singularities", [])
        total_singularities += len(singularities)
        thresh = m.get("intensity_threshold", 1.0)

        can_actualize = total_intensity_spatium >= thresh
        intensity_surplus = round(max(0.0, total_intensity_spatium - thresh), 4)

        actualization_events.append({
            "multiplicity_id": m_id,
            "singularities_count": len(singularities),
            "intensity_threshold": thresh,
            "status": "ACTUALIZED_INTO_EXTENSITY" if can_actualize else "VIRTUAL_LATENCY",
            "intensity_surplus": intensity_surplus
        })

    habit_count = sum(1 for c in cycles if "HABIT" in c.get("repetition_type", ""))
    memory_count = sum(1 for c in cycles if "MEMORY" in c.get("repetition_type", ""))
    eternal_return_count = sum(1 for c in cycles if "ETERNAL_RETURN" in c.get("repetition_type", ""))

    accumulated_difference = 0.0
    bare_repetition_penalty = 0.0
    for c in cycles:
        c_type = c.get("repetition_type", "")
        delta = c.get("delta_variation", 0.0)
        if "ETERNAL_RETURN" in c_type:
            if delta > 0.0:
                accumulated_difference += delta * 1.5
            else:
                bare_repetition_penalty += 1.0
        elif "MEMORY" in c_type:
            accumulated_difference += delta * 1.0
        elif "HABIT" in c_type:
            if delta == 0.0:
                bare_repetition_penalty += 0.5
            else:
                accumulated_difference += delta * 0.5

    accumulated_difference = round(accumulated_difference, 4)
    bare_repetition_penalty = round(bare_repetition_penalty, 4)

    representation_shackles = {
        "identity_subordinated": False,
        "analogy_in_judgment": False,
        "opposition_in_predicate": False,
        "resemblance_in_perception": False
    }
    if critique_enabled:
        if bare_repetition_penalty > 0.5:
            representation_shackles["identity_subordinated"] = True
            representation_shackles["resemblance_in_perception"] = True
        if total_singularities < 2:
            representation_shackles["analogy_in_judgment"] = True
        if habit_count > memory_count and habit_count > eternal_return_count:
            representation_shackles["opposition_in_predicate"] = True

    shackles_count = sum(1 for v in representation_shackles.values() if v)

    base_metric = (total_intensity_spatium * 0.3) + (accumulated_difference * 0.4) - (bare_repetition_penalty * 0.2) - (shackles_count * 0.1)
    difference_affirmation_metric = round(max(0.05, min(1.0, base_metric / 5.0)), 4)

    if difference_affirmation_metric >= 0.70 and eternal_return_count > 0:
        ontological_status = "DIFFERENCE_IN_ITSELF_UNLEASHED"
    elif shackles_count >= 3:
        ontological_status = "REPRESENTATIONAL_DOGMATISM"
    elif actualization_events and all(a["status"] == "VIRTUAL_LATENCY" for a in actualization_events):
        ontological_status = "UNACTUALIZED_VIRTUAL_CHAOS"
    else:
        ontological_status = "DRAMATIZATION_IN_PROGRESS"

    result = {
        "plane_of_immanence": {
            "dimensions": dimensions,
            "total_intensity_spatium": total_intensity_spatium
        },
        "actualization_events": actualization_events,
        "time_syntheses_breakdown": {
            "habit_syntheses": habit_count,
            "memory_syntheses": memory_count,
            "eternal_return_syntheses": eternal_return_count,
            "accumulated_difference": accumulated_difference,
            "bare_repetition_penalty": bare_repetition_penalty
        },
        "representation_critique": {
            "shackles_count": shackles_count,
            "shackles": representation_shackles
        },
        "ontological_verdict": {
            "difference_affirmation_metric": difference_affirmation_metric,
            "ontological_status": ontological_status
        }
    }

    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
