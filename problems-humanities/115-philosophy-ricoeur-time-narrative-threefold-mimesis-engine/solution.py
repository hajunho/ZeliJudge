import sys
import json

def solve():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    subject = data.get("subject", {})
    name = subject.get("name", "Unknown_Subject")

    events = data.get("life_events", [])
    config = data.get("interpretation_config", {})
    emplotment_mode = config.get("emplotment_mode", "DIALECTICAL")
    suspicion_filter = config.get("suspicion_filter_applied", True)
    refiguration_horizon = config.get("refiguration_horizon", "ETHICAL_RESPONSIBILITY")

    # 1. MIMESIS 1 (Prefiguration / 선-형상화)
    n_events = len(events)
    if n_events == 0:
        timestamps = [0]
    else:
        timestamps = [e.get("timestamp", 0) for e in events]
    chrono_span = max(timestamps) - min(timestamps)

    valences = [e.get("valence", 0.0) for e in events]
    avg_valence = sum(valences) / n_events if n_events > 0 else 0.0

    actions_count = sum(1 for e in events if e.get("event_type") == "ACTION")
    contingencies_count = sum(1 for e in events if e.get("event_type") == "CONTINGENCY")
    promises_count = sum(1 for e in events if e.get("event_type") == "PROMISE")

    prefig_score = round(avg_valence * 0.5 + (actions_count / max(1, n_events)) * 0.5, 4)

    mimesis_1 = {
        "chronological_span": chrono_span,
        "actions_count": actions_count,
        "contingencies_count": contingencies_count,
        "promises_count": promises_count,
        "prefig_score": prefig_score
    }

    # 2. MIMESIS 2 (Configuration / 형상화 - 이질적인 것들의 종합)
    plot_tension = 0.0
    for i in range(len(valences) - 1):
        plot_tension += abs(valences[i+1] - valences[i])
    plot_tension = round(plot_tension, 4)

    suspicious_events = []
    if suspicion_filter:
        for e in events:
            m = str(e.get("motive", "")).lower()
            if any(k in m for k in ["pride", "vanity", "hypocrisy", "illusion", "coercion"]):
                suspicious_events.append(e.get("id"))
    suspicion_index = round(len(suspicious_events) / max(1, n_events), 4)

    mode_multipliers = {
        "TRAGIC_TO_REDEMPTIVE": 1.25,
        "DIALECTICAL": 1.15,
        "CHRONIC_EPISODIC": 0.85
    }
    mode_mult = mode_multipliers.get(emplotment_mode, 1.0)

    contingency_integration = (contingencies_count * 0.2 + promises_count * 0.3) / max(1, n_events)
    synthesis_score = min(1.0, max(0.1, round((0.5 + contingency_integration - suspicion_index * 0.2) * mode_mult, 4)))

    second_naivete_attained = suspicion_filter and (synthesis_score >= 0.6) and (len(suspicious_events) <= n_events // 2)

    mimesis_2 = {
        "emplotment_mode": emplotment_mode,
        "plot_tension": plot_tension,
        "suspicion_index": suspicion_index,
        "suspicious_event_ids": suspicious_events,
        "synthesis_score": synthesis_score,
        "second_naivete_attained": second_naivete_attained
    }

    # 3. MIMESIS 3 (Refiguration / 재-형상화)
    phenomenological_time_factor = round(1.0 + (plot_tension * 0.15) + (promises_count * 0.25), 4)

    horizon_boost = {
        "ETHICAL_RESPONSIBILITY": 1.2,
        "EXISTENTIAL_LIBERATION": 1.15,
        "AESTHETIC_CONTEMPLATION": 1.05
    }.get(refiguration_horizon, 1.0)

    world_disclosure_depth = round(min(1.0, synthesis_score * horizon_boost * (1.1 if second_naivete_attained else 0.9)), 4)

    mimesis_3 = {
        "refiguration_horizon": refiguration_horizon,
        "phenomenological_time_factor": phenomenological_time_factor,
        "world_disclosure_depth": world_disclosure_depth
    }

    # 4. NARRATIVE IDENTITY (동일성 Idem vs 자기성 Ipse)
    trait_modifications = sum(1 for e in events if "trait_change" in e)
    idem_stability = round(max(0.1, 1.0 - (trait_modifications * 0.2)), 4)

    fidelity_sum = sum(e.get("fidelity_cost", 0.5) for e in events if e.get("event_type") == "PROMISE")
    ipse_fidelity = round(min(1.0, fidelity_sum / max(1, promises_count)), 4) if promises_count > 0 else 0.5

    narrative_identity_metric = round(0.35 * idem_stability + 0.35 * ipse_fidelity + 0.30 * synthesis_score, 4)

    if narrative_identity_metric >= 0.75 and ipse_fidelity >= 0.7:
        identity_status = "NARRATIVE_IDENTITY_ACHIEVED"
    elif ipse_fidelity < 0.5 and idem_stability > 0.7:
        identity_status = "STAGNANT_IDEM_DOMINANCE"
    elif narrative_identity_metric < 0.5:
        identity_status = "EPISODIC_FRAGMENTATION"
    else:
        identity_status = "DIALECTICAL_TENSION_IN_PROGRESS"

    narrative_identity = {
        "idem_stability": idem_stability,
        "ipse_fidelity": ipse_fidelity,
        "narrative_identity_metric": narrative_identity_metric,
        "identity_status": identity_status
    }

    result = {
        "subject_name": name,
        "mimesis_1_prefiguration": mimesis_1,
        "mimesis_2_configuration": mimesis_2,
        "mimesis_3_refiguration": mimesis_3,
        "narrative_identity": narrative_identity
    }

    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
