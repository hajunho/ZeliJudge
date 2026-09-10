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
    monads = data.get("monads", [])
    cosmic_events = data.get("cosmic_events", [])
    ticks = data.get("simulation_ticks", 3)

    monad_states = {}
    for m in monads:
        m_id = m.get("id")
        m_type = m.get("monad_type", "BARE_MONAD")
        angle = m.get("perspective_angle", 0.0)
        clock_rate = m.get("internal_clock_rate", 1.0)
        petites = m.get("petites_perceptions", [])

        petites_sum = round(sum(petites), 4)
        has_conscious_perception = petites_sum >= 0.25
        can_apperceive = (m_type == "SPIRIT") and (petites_sum >= 0.35)

        monad_states[m_id] = {
            "id": m_id,
            "type": m_type,
            "perspective_angle": angle,
            "clock_rate": clock_rate,
            "petites_sum": petites_sum,
            "conscious_perception": has_conscious_perception,
            "apperception_achieved": can_apperceive,
            "internal_time": 0.0,
            "mirrored_events_log": []
        }

    indiscernibles_violation = False
    violating_pairs = []
    n = len(monads)
    for i in range(n):
        for j in range(i + 1, n):
            m1 = monads[i]
            m2 = monads[j]
            same_angle = abs(m1.get("perspective_angle", 0.0) - m2.get("perspective_angle", 0.0)) < 1e-4
            same_type = m1.get("monad_type") == m2.get("monad_type")
            same_petites = abs(sum(m1.get("petites_perceptions", [])) - sum(m2.get("petites_perceptions", []))) < 1e-4
            if same_angle and same_type and same_petites:
                indiscernibles_violation = True
                violating_pairs.append([m1.get("id"), m2.get("id")])

    event_by_time = {e.get("timestamp", 0): e for e in cosmic_events}

    for t in range(1, ticks + 1):
        ev = event_by_time.get(t)
        for m_id, state in monad_states.items():
            state["internal_time"] = round(state["internal_time"] + state["clock_rate"], 2)
            if ev:
                ev_intensity = ev.get("intensity", 1.0)
                ev_angle = ev.get("spatial_source_angle", 0.0)
                diff_rad = math.radians(state["perspective_angle"] - ev_angle)
                perspective_factor = math.cos(diff_rad)
                type_mult = 1.2 if state["type"] == "SPIRIT" else (1.0 if state["type"] == "SOUL" else 0.8)
                expressed_clarity = round(ev_intensity * abs(perspective_factor) * type_mult, 4)

                state["mirrored_events_log"].append({
                    "tick": t,
                    "event_id": ev.get("event_id"),
                    "perspective_factor": round(perspective_factor, 4),
                    "expressed_clarity": expressed_clarity
                })

    unique_types = len(set(m.get("monad_type") for m in monads))
    angles = [m.get("perspective_angle", 0.0) for m in monads]
    angle_spread = max(angles) - min(angles) if angles else 0.0
    variety_score = round(min(10.0, (unique_types * 2.0) + (angle_spread / 36.0)), 4)

    clock_rates = [m.get("internal_clock_rate", 1.0) for m in monads]
    mean_clock = sum(clock_rates) / max(1, len(clock_rates))
    clock_variance = sum((c - mean_clock)**2 for c in clock_rates) / max(1, len(clock_rates))
    order_score = round(max(1.0, 10.0 - clock_variance * 10.0), 4)

    best_world_optimality = round((variety_score * order_score) / 10.0, 4)

    if indiscernibles_violation:
        world_status = "VIOLATION_INDISCERNIBLE_DUPLICATE"
    elif best_world_optimality >= 7.0:
        world_status = "OPTIMUM_HARMONIA_PRAESTABILITA"
    elif order_score < 5.0:
        world_status = "DESYNCHRONIZED_MONADIC_CHAOS"
    else:
        world_status = "SUBOPTIMAL_POSSIBLE_WORLD"

    result = {
        "monad_count": len(monads),
        "indiscernibles_principle": {
            "violation": indiscernibles_violation,
            "violating_pairs": violating_pairs
        },
        "theodicy_metrics": {
            "variety_score": variety_score,
            "order_score": order_score,
            "best_world_optimality": best_world_optimality,
            "world_status": world_status
        },
        "monads_state": list(monad_states.values())
    }

    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
