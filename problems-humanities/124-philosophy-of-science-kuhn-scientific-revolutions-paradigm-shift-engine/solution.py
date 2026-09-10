import json
import sys

# Ensure UTF-8 input/output on Windows
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
        
    payload = json.loads(raw_data)
    config = payload.get("config", {})
    initial_paradigms = payload.get("paradigms", {})
    scientists_config = payload.get("community", {})
    events = payload.get("events", [])
    
    crisis_threshold = float(config.get("crisis_threshold", 60.0))
    revolution_threshold = float(config.get("revolution_threshold", 50.0))
    
    seniors = int(scientists_config.get("senior_count", 30))
    mids = int(scientists_config.get("mid_count", 40))
    juniors = int(scientists_config.get("junior_count", 30))
    tot_scientists = seniors + mids + juniors
    
    senior_affil = {pid: 0 for pid in initial_paradigms}
    mid_affil = {pid: 0 for pid in initial_paradigms}
    junior_affil = {pid: 0 for pid in initial_paradigms}
    
    dominant_pid = config.get("dominant_paradigm", list(initial_paradigms.keys())[0] if initial_paradigms else "P_OLD")
    senior_affil[dominant_pid] = seniors
    mid_affil[dominant_pid] = mids
    junior_affil[dominant_pid] = juniors
    
    paradigms = {}
    for pid, p in initial_paradigms.items():
        paradigms[pid] = {
            "name": p.get("name", pid),
            "explanatory_power": float(p.get("explanatory_power", 80.0)),
            "exemplar_reputation": float(p.get("exemplar_reputation", 90.0)),
            "solved_puzzles": int(p.get("solved_puzzles", 100)),
            "anomalies": [],
            "anomaly_severity_sum": 0.0,
            "incommensurability": float(p.get("incommensurability", 0.0))
        }
        
    current_regime = "NORMAL_SCIENCE"
    active_dominant = dominant_pid
    rival_pid = None
    
    history = []
    
    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        if ev_type == "OBSERVE_ANOMALY":
            target_p = ev_params.get("paradigm", active_dominant)
            sev = float(ev_params.get("severity", 10.0))
            desc = ev_params.get("description", "Unexplained empirical observation")
            if target_p in paradigms:
                paradigms[target_p]["anomalies"].append({"desc": desc, "severity": sev})
                paradigms[target_p]["anomaly_severity_sum"] += sev
                paradigms[target_p]["exemplar_reputation"] = max(10.0, paradigms[target_p]["exemplar_reputation"] - sev * 0.2)
                
        elif ev_type == "PUZZLE_SOLVING":
            target_p = ev_params.get("paradigm", active_dominant)
            puzzles = int(ev_params.get("puzzles", 5))
            if target_p in paradigms:
                paradigms[target_p]["solved_puzzles"] += puzzles
                paradigms[target_p]["explanatory_power"] = min(100.0, paradigms[target_p]["explanatory_power"] + puzzles * 0.5)
                if paradigms[target_p]["anomalies"]:
                    min_anom = min(paradigms[target_p]["anomalies"], key=lambda a: a["severity"])
                    if min_anom["severity"] <= puzzles * 2.0:
                        paradigms[target_p]["anomalies"].remove(min_anom)
                        paradigms[target_p]["anomaly_severity_sum"] = max(0.0, paradigms[target_p]["anomaly_severity_sum"] - min_anom["severity"])
                        
        elif ev_type == "PROPOSE_RIVAL_PARADIGM":
            new_pid = ev_params["id"]
            rival_pid = new_pid
            paradigms[new_pid] = {
                "name": ev_params.get("name", new_pid),
                "explanatory_power": float(ev_params.get("explanatory_power", 60.0)),
                "exemplar_reputation": float(ev_params.get("exemplar_reputation", 50.0)),
                "solved_puzzles": int(ev_params.get("solved_puzzles", 10)),
                "anomalies": [],
                "anomaly_severity_sum": 0.0,
                "incommensurability": float(ev_params.get("incommensurability", 0.75))
            }
            senior_affil[new_pid] = 0
            mid_affil[new_pid] = 0
            junior_affil[new_pid] = 0
            
            vanguard = int(ev_params.get("initial_vanguard", 5))
            actual_vang = min(vanguard, junior_affil[active_dominant])
            junior_affil[active_dominant] -= actual_vang
            junior_affil[new_pid] += actual_vang
            
        elif ev_type == "CRITICAL_ANOMALY_CRISIS":
            target_p = ev_params.get("paradigm", active_dominant)
            crisis_boost = float(ev_params.get("crisis_surge", 30.0))
            if target_p in paradigms:
                paradigms[target_p]["anomaly_severity_sum"] += crisis_boost
                paradigms[target_p]["exemplar_reputation"] = max(5.0, paradigms[target_p]["exemplar_reputation"] - crisis_boost * 0.5)
                
        elif ev_type == "GESTALT_CONVERSION_WAVE":
            if rival_pid and rival_pid in paradigms and active_dominant in paradigms:
                dom_p = paradigms[active_dominant]
                riv_p = paradigms[rival_pid]
                
                denom = (dom_p["explanatory_power"] * dom_p["exemplar_reputation"]) / 100.0
                c_score = (dom_p["anomaly_severity_sum"] * 100.0) / denom if denom > 0 else 100.0
                c_score = min(100.0, max(0.0, c_score))
                
                incomm = riv_p["incommensurability"]
                conversion_power = (c_score / 100.0) * (riv_p["explanatory_power"] / 100.0) * (1.0 - (0.4 * incomm))
                
                j_conv = int(round(junior_affil[active_dominant] * conversion_power * 0.70))
                m_conv = int(round(mid_affil[active_dominant] * conversion_power * 0.40))
                s_conv = int(round(senior_affil[active_dominant] * conversion_power * 0.15))
                
                junior_affil[active_dominant] -= j_conv
                junior_affil[rival_pid] += j_conv
                
                mid_affil[active_dominant] -= m_conv
                mid_affil[rival_pid] += m_conv
                
                senior_affil[active_dominant] -= s_conv
                senior_affil[rival_pid] += s_conv
                
        elif ev_type == "TEXTBOOK_REWRITE":
            target_p = ev_params.get("paradigm", rival_pid if rival_pid else active_dominant)
            if target_p in paradigms:
                paradigms[target_p]["exemplar_reputation"] = min(100.0, paradigms[target_p]["exemplar_reputation"] + 30.0)
                for p_other in list(paradigms.keys()):
                    if p_other != target_p:
                        s_f = int(senior_affil[p_other] * 0.8)
                        m_f = int(mid_affil[p_other] * 0.8)
                        j_f = int(junior_affil[p_other] * 0.8)
                        senior_affil[p_other] -= s_f
                        senior_affil[target_p] += s_f
                        mid_affil[p_other] -= m_f
                        mid_affil[target_p] += m_f
                        junior_affil[p_other] -= j_f
                        junior_affil[target_p] += j_f
                active_dominant = target_p

        dom_p = paradigms[active_dominant]
        denom = (dom_p["explanatory_power"] * dom_p["exemplar_reputation"]) / 100.0
        c_score = (dom_p["anomaly_severity_sum"] * 100.0) / denom if denom > 0 else 100.0
        c_score = round(min(100.0, max(0.0, c_score)), 2)
        
        dom_share = (senior_affil[active_dominant] + mid_affil[active_dominant] + junior_affil[active_dominant]) / tot_scientists * 100.0
        rival_share = ((senior_affil[rival_pid] + mid_affil[rival_pid] + junior_affil[rival_pid]) / tot_scientists * 100.0) if rival_pid else 0.0
        
        if rival_pid and rival_share >= 80.0:
            current_regime = "NEW_NORMAL_SCIENCE"
            active_dominant = rival_pid
        elif rival_pid and rival_share >= revolution_threshold:
            current_regime = "SCIENTIFIC_REVOLUTION"
        elif c_score >= crisis_threshold:
            current_regime = "PARADIGM_CRISIS"
        else:
            current_regime = "NORMAL_SCIENCE"
            
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "regime": current_regime,
            "dominant_paradigm": active_dominant,
            "crisis_score": c_score,
            "dominant_share": round(dom_share, 2),
            "rival_share": round(rival_share, 2) if rival_pid else 0.0
        })
        
    community_distribution = {}
    for pid in paradigms:
        tot_p = senior_affil[pid] + mid_affil[pid] + junior_affil[pid]
        community_distribution[pid] = {
            "name": paradigms[pid]["name"],
            "total_adherents": tot_p,
            "share_percent": round((tot_p / tot_scientists) * 100.0, 2),
            "seniors": senior_affil[pid],
            "mids": mid_affil[pid],
            "juniors": junior_affil[pid],
            "unresolved_anomalies": len(paradigms[pid]["anomalies"]),
            "solved_puzzles": paradigms[pid]["solved_puzzles"]
        }
        
    result = {
        "final_regime": current_regime,
        "final_dominant_paradigm": active_dominant,
        "paradigm_shifted": (active_dominant != dominant_pid),
        "final_crisis_score": history[-1]["crisis_score"] if history else 0.0,
        "community_distribution": community_distribution,
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
