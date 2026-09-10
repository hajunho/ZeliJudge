import sys
import json

def run_foucault_engine(data):
    cohorts = data.get("population_cohorts", [])
    interventions = data.get("governmental_interventions", [])
    params = data.get("engine_params", {})
    
    epoch = int(params.get("sovereignty_vs_biopower_epoch", 1975))
    racism_thresh = float(params.get("racism_division_threshold", 0.20))

    state_cohorts = {}
    for c in cohorts:
        cid = c["cohort_id"]
        state_cohorts[cid] = {
            "cohort_id": cid,
            "population_size": int(c.get("population_size", 1000)),
            "individual_discipline_level": float(c.get("individual_discipline_level", 0.5)),
            "health_index": float(c.get("health_index", 0.5)),
            "natality_rate": float(c.get("natality_rate", 0.02)),
            "mortality_rate": float(c.get("mortality_rate", 0.01)),
            "docility_index": float(c.get("docility_index", 0.5)),
            "deviation_frequency": float(c.get("deviation_frequency", 0.1)),
            "targeted_apparatus": c.get("targeted_apparatus", "clinic")
        }

    total_discursive_volume = 0.0

    intervention_log = []
    for iv in interventions:
        ivid = iv["intervention_id"]
        tcid = iv.get("target_cohort_id", "")
        ptype = iv.get("pole_type", "biopolitics_regulatory")
        reg_int = float(iv.get("regulatory_intensity", 0.1))
        disc_surv = float(iv.get("discursive_surveillance", 0.1))

        if tcid not in state_cohorts:
            intervention_log.append({
                "intervention_id": ivid,
                "status": "COHORT_NOT_FOUND"
            })
            continue

        tgt = state_cohorts[tcid]
        disc_inc = round(disc_surv * (tgt["population_size"] / 1000.0), 4)
        total_discursive_volume += disc_inc

        if ptype == "anatomo_disciplinary":
            tgt["individual_discipline_level"] = min(1.0, tgt["individual_discipline_level"] + (reg_int * 0.4))
            tgt["deviation_frequency"] = max(0.0, tgt["deviation_frequency"] - (reg_int * 0.3))
            action_desc = "Individual body disciplined through timetable and surveillance"
        else:
            tgt["health_index"] = min(1.0, tgt["health_index"] + (reg_int * 0.5))
            tgt["mortality_rate"] = max(0.001, tgt["mortality_rate"] - (reg_int * tgt["mortality_rate"] * 0.5))
            action_desc = "Population vital rates regulated through hygiene and social insurance"

        intervention_log.append({
            "intervention_id": ivid,
            "target_cohort": tcid,
            "pole_type": ptype,
            "discursive_explosion_volume": disc_inc,
            "action_desc": action_desc
        })

    evaluated_cohorts = []
    agg_docile = 0.0
    agg_homeostasis = 0.0
    total_population = sum(c["population_size"] for c in state_cohorts.values())

    for cid, c in state_cohorts.items():
        d_level = c["individual_discipline_level"]
        d_idx = c["docility_index"]
        dev_freq = c["deviation_frequency"]
        
        docile_score = round(d_level * d_idx * (1.0 - dev_freq), 4)

        mort = c["mortality_rate"]
        nat = c["natality_rate"]
        vitality_ratio = round(nat / mort, 4) if mort > 0 else 10.0
        homeostasis_index = round(c["health_index"] * min(2.0, vitality_ratio / 2.0), 4)

        is_risk_group = dev_freq >= racism_thresh
        abandonment_index = round(dev_freq * (1.0 - docile_score), 4) if is_risk_group else 0.0

        if is_risk_group and abandonment_index >= 0.15:
            modality = "MAKE_LIVE_LET_DIE"
        elif is_risk_group:
            modality = "EXCLUSIONARY_SURVEILLANCE"
        else:
            modality = "NORMALIZE_AND_OPTIMIZE"

        weight = c["population_size"] / total_population if total_population > 0 else 1.0
        agg_docile += docile_score * weight
        agg_homeostasis += homeostasis_index * weight

        evaluated_cohorts.append({
            "cohort_id": cid,
            "population_size": c["population_size"],
            "docile_body_score": docile_score,
            "homeostasis_index": homeostasis_index,
            "vitality_ratio": vitality_ratio,
            "state_racism_risk": is_risk_group,
            "abandonment_index": abandonment_index,
            "power_modality": modality
        })

    agg_docile = round(agg_docile, 4)
    agg_homeostasis = round(agg_homeostasis, 4)
    total_discursive_volume = round(total_discursive_volume, 4)

    if epoch < 1789:
        macro_regime = "CLASSICAL_SOVEREIGN_RIGHT_OF_SWORD"
    elif agg_homeostasis >= agg_docile:
        macro_regime = "SECURITY_AND_BIOPOLITICAL_POPULATION_GOVERNANCE"
    else:
        macro_regime = "DISCIPLINARY_SOCIETY_OF_SURVEILLANCE"

    return {
        "cohort_analyses": evaluated_cohorts,
        "governmental_interventions_log": intervention_log,
        "biopower_system_summary": {
            "aggregate_docile_body_score": agg_docile,
            "aggregate_homeostasis_index": agg_homeostasis,
            "total_discursive_explosion_volume": total_discursive_volume,
            "macro_governmental_regime": macro_regime
        }
    }

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_foucault_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
