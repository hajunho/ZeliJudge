import sys
import json
import math

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def simulate_rousseau(input_data):
    common_good = input_data.get("common_good", {})
    citizens = input_data.get("citizens", [])
    factions = input_data.get("factions", {})
    laws = input_data.get("proposed_laws", [])
    executive = input_data.get("executive", {})
    
    dimensions = list(common_good.keys())
    
    # 1. Citizen Stated Votes
    citizen_votes = {}
    for c in citizens:
        c_id = c["citizen_id"]
        v_i = c.get("civic_virtue", 0.5)
        raw_pref = c.get("private_preferences", {})
        f_id = c.get("faction_id")
        f_loyalty = c.get("faction_loyalty", 0.0)
        
        eff_pref = {}
        for d in dimensions:
            ind_val = raw_pref.get(d, 0.0)
            if f_id and f_id in factions:
                f_val = factions[f_id].get(d, 0.0)
                eff_val = (1.0 - f_loyalty) * ind_val + f_loyalty * f_val
            else:
                eff_val = ind_val
            eff_pref[d] = eff_val
            
        w_i = {}
        for d in dimensions:
            c_val = common_good.get(d, 0.0)
            p_val = eff_pref.get(d, 0.0)
            w_i[d] = round(v_i * c_val + (1.0 - v_i) * p_val, 4)
            
        citizen_votes[c_id] = {
            "stated_vote": w_i,
            "civic_virtue": v_i,
            "faction_id": f_id
        }
        
    # 2. Will of All (Volonté de tous)
    n = len(citizens)
    will_of_all = {}
    for d in dimensions:
        sum_d = sum(citizen_votes[c["citizen_id"]]["stated_vote"][d] for c in citizens)
        will_of_all[d] = round(sum_d / max(1, n), 4)
        
    # 3. General Will (Volonté générale)
    total_virtue = sum(c.get("civic_virtue", 0.5) for c in citizens)
    general_will = {}
    for d in dimensions:
        if total_virtue > 0:
            weighted_sum = sum(citizen_votes[c["citizen_id"]]["civic_virtue"] * citizen_votes[c["citizen_id"]]["stated_vote"][d] for c in citizens)
            general_will[d] = round(weighted_sum / total_virtue, 4)
        else:
            general_will[d] = will_of_all[d]

    # 4. Divergence & Faction Polarization
    dist_all_common = math.sqrt(sum((will_of_all[d] - common_good[d]) ** 2 for d in dimensions))
    dist_general_common = math.sqrt(sum((general_will[d] - common_good[d]) ** 2 for d in dimensions))
    
    faction_votes = {}
    for c in citizens:
        f_id = c.get("faction_id", "independent")
        if f_id not in faction_votes:
            faction_votes[f_id] = []
        faction_votes[f_id].append(c["citizen_id"])
        
    faction_polarization = 0.0
    if len(factions) > 1:
        f_means = {}
        for f_id in factions:
            members = faction_votes.get(f_id, [])
            if members:
                m_vec = [sum(citizen_votes[mid]["stated_vote"][d] for mid in members) / len(members) for d in dimensions]
                f_means[f_id] = m_vec
        f_keys = list(f_means.keys())
        diff_sq = 0.0
        pairs = 0
        for i in range(len(f_keys)):
            for j in range(i + 1, len(f_keys)):
                pairs += 1
                diff_sq += sum((f_means[f_keys[i]][k] - f_means[f_keys[j]][k]) ** 2 for k in range(len(dimensions)))
        if pairs > 0:
            faction_polarization = round(math.sqrt(diff_sq / pairs), 4)

    # 5. Law Enactment & Compliance
    enacted_laws = []
    enforcement_reports = []
    
    for law in laws:
        law_id = law["law_id"]
        policy_vector = law["policy_vector"]
        alignment = sum(general_will.get(d, 0.0) * policy_vector.get(d, 0.0) for d in dimensions)
        passed = alignment >= law.get("threshold", 0.0)
        
        if passed:
            enacted_laws.append(law_id)
            for c in citizens:
                c_id = c["citizen_id"]
                raw_pref = c.get("private_preferences", {})
                ind_align = sum(raw_pref.get(d, 0.0) * policy_vector.get(d, 0.0) for d in dimensions)
                if ind_align >= 0:
                    status = "OBEYS_AUTONOMOUSLY"
                else:
                    status = "FORCED_TO_BE_FREE"
                enforcement_reports.append({
                    "law_id": law_id,
                    "citizen_id": c_id,
                    "compliance": status,
                    "moral_liberty_restored": True if status == "FORCED_TO_BE_FREE" else False
                })

    # 6. Executive Usurpation & Degeneration
    exec_power = executive.get("power", 0.5)
    exec_corporate_bias = executive.get("corporate_will_bias", 0.5)
    civic_oversight = executive.get("civic_oversight", 0.5)
    
    degeneration_index = round((exec_power * exec_corporate_bias) / max(0.01, civic_oversight), 4)
    
    if degeneration_index >= executive.get("dissolution_threshold", 2.0):
        republic_status = "STATE_DISSOLVED_USURPATION"
        sovereignty_verdict = "ANARCHY_OR_TYRANNY"
    elif degeneration_index >= 1.0:
        republic_status = "DEGENERATING_ARISTOCRACY"
        sovereignty_verdict = "SOVEREIGNTY_THREATENED"
    else:
        republic_status = "HEALTHY_LEGITIMATE_REPUBLIC"
        sovereignty_verdict = "POPULAR_SOVEREIGNTY_INTACT"

    forced_count = sum(1 for e in enforcement_reports if e["compliance"] == "FORCED_TO_BE_FREE")
    autonomous_count = sum(1 for e in enforcement_reports if e["compliance"] == "OBEYS_AUTONOMOUSLY")

    return {
        "will_of_all": will_of_all,
        "general_will": general_will,
        "divergence_metrics": {
            "will_of_all_error": round(dist_all_common, 4),
            "general_will_error": round(dist_general_common, 4),
            "faction_polarization": faction_polarization
        },
        "enacted_laws": enacted_laws,
        "enforcement_summary": {
            "total_evaluations": len(enforcement_reports),
            "autonomous_obediences": autonomous_count,
            "forced_to_be_free_count": forced_count
        },
        "executive_state": {
            "degeneration_index": degeneration_index,
            "republic_status": republic_status,
            "sovereignty_verdict": sovereignty_verdict
        },
        "detailed_enforcement": enforcement_reports
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_rousseau(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
