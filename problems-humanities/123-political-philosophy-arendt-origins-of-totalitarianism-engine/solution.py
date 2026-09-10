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
    initial_groups = payload.get("groups", [])
    events = payload.get("events", [])
    
    tdi_threshold = float(config.get("totalitarian_threshold", 75.0))
    ideological_fiction = float(config.get("initial_fiction", 10.0))
    mob_elite_alliance = float(config.get("initial_alliance", 10.0))
    
    groups = {}
    for g in initial_groups:
        gid = g["id"]
        groups[gid] = {
            "name": g["name"],
            "population": int(g["population"]),
            "cohesion": float(g.get("cohesion", 80.0)),
            "isolation": float(g.get("isolation", 20.0)),
            "juridical_rights": float(g.get("juridical_rights", 100.0)),
            "moral_integrity": float(g.get("moral_integrity", 100.0)),
            "spontaneity": float(g.get("spontaneity", 100.0)),
            "status": g.get("status", "ACTIVE_CITIZEN"),
            "camp_count": 0
        }
        
    total_deported = 0
    total_fabricated = 0
    regime_state = "PRE_TOTALITARIAN"
    epoch_logs = []
    
    tot_pop = sum(g["population"] for g in groups.values())
    
    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        if ev_type == "ECONOMIC_CRISIS":
            severity = float(ev_params.get("severity", 20.0))
            for gid, g in groups.items():
                if g["status"] == "ACTIVE_CITIZEN":
                    g["cohesion"] = max(0.0, g["cohesion"] - severity * 1.5)
                    g["isolation"] = min(100.0, g["isolation"] + severity * 1.2)
            mob_elite_alliance = min(100.0, mob_elite_alliance + severity * 0.8)
            
        elif ev_type == "IMPERIALIST_EXPANSION":
            surplus_export = float(ev_params.get("surplus_export", 15.0))
            target_minority = ev_params.get("target_group", None)
            ideological_fiction = min(100.0, ideological_fiction + surplus_export * 0.7)
            if target_minority and target_minority in groups:
                tg = groups[target_minority]
                tg["juridical_rights"] = max(0.0, tg["juridical_rights"] - surplus_export * 1.8)
                if tg["juridical_rights"] < 30.0 and tg["status"] == "ACTIVE_CITIZEN":
                    tg["status"] = "SUPERFLUOUS_ALIEN"
                    
        elif ev_type == "MOB_ELITE_PACT":
            radicalism = float(ev_params.get("radicalism", 25.0))
            mob_elite_alliance = min(100.0, mob_elite_alliance + radicalism)
            ideological_fiction = min(100.0, ideological_fiction + radicalism * 1.2)
            for gid, g in groups.items():
                g["moral_integrity"] = max(0.0, g["moral_integrity"] - radicalism * 0.5)
                
        elif ev_type == "STATELESS_DENATIONALIZATION":
            target_group = ev_params.get("target_group")
            if target_group in groups:
                tg = groups[target_group]
                tg["juridical_rights"] = 0.0
                tg["status"] = "SUPERFLUOUS_ALIEN"
                tg["isolation"] = min(100.0, tg["isolation"] + 30.0)
                
        elif ev_type == "IDEOLOGICAL_PROPAGANDA":
            intensity = float(ev_params.get("intensity", 20.0))
            consistency = float(ev_params.get("logical_consistency", 1.5))
            ideological_fiction = min(100.0, ideological_fiction + intensity * consistency)
            for gid, g in groups.items():
                if g["status"] != "CORPSE_FABRICATED":
                    g["spontaneity"] = max(0.0, g["spontaneity"] - intensity * 0.8)
                    g["cohesion"] = max(0.0, g["cohesion"] - intensity * 0.6)
                    g["isolation"] = min(100.0, g["isolation"] + intensity * 0.7)
                    
        elif ev_type == "CAMP_DEPORTATION":
            target_group = ev_params.get("target_group")
            count = int(ev_params.get("count", 0))
            if target_group in groups:
                tg = groups[target_group]
                actual_deport = min(count, tg["population"] - tg["camp_count"])
                tg["camp_count"] += actual_deport
                total_deported += actual_deport
                if tg["camp_count"] > 0:
                    tg["status"] = "CAMP_INTERNEE"
                tg["juridical_rights"] = 0.0
                
        elif ev_type == "TOTAL_TERROR_CYCLE":
            terror_severity = float(ev_params.get("severity", 30.0))
            for gid, g in groups.items():
                if g["camp_count"] > 0:
                    g["moral_integrity"] = max(0.0, g["moral_integrity"] - terror_severity * 1.5)
                    g["spontaneity"] = max(0.0, g["spontaneity"] - terror_severity * 1.8)
                    if g["juridical_rights"] == 0.0 and g["moral_integrity"] <= 10.0 and g["spontaneity"] <= 5.0:
                        if g["status"] != "CORPSE_FABRICATED":
                            g["status"] = "CORPSE_FABRICATED"
                            total_fabricated += g["camp_count"]
                else:
                    g["spontaneity"] = max(0.0, g["spontaneity"] - terror_severity * 0.4)
                    g["cohesion"] = max(0.0, g["cohesion"] - terror_severity * 0.5)
                    g["isolation"] = min(100.0, g["isolation"] + terror_severity * 0.6)
                    
        # Metrics
        weighted_isolation = sum(g["isolation"] * g["population"] for g in groups.values()) / tot_pop if tot_pop > 0 else 0.0
        weighted_spontaneity = sum(g["spontaneity"] * g["population"] for g in groups.values()) / tot_pop if tot_pop > 0 else 0.0
        
        raw_tdi = (0.30 * ideological_fiction) + (0.25 * mob_elite_alliance) + (0.25 * weighted_isolation) + (0.20 * (100.0 - weighted_spontaneity))
        tdi = round(min(100.0, max(0.0, raw_tdi)), 2)
        
        if tdi >= tdi_threshold:
            regime_state = "TOTALITARIAN_RULE"
        elif tdi >= 50.0:
            regime_state = "DUAL_STATE"
        elif tdi >= 30.0:
            regime_state = "MASS_MOBILIZATION"
        else:
            regime_state = "PRE_TOTALITARIAN"
            
        epoch_logs.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "tdi": tdi,
            "regime_state": regime_state,
            "ideological_fiction": round(ideological_fiction, 2),
            "mob_elite_alliance": round(mob_elite_alliance, 2)
        })
        
    group_summaries = {}
    superfluous_pop = 0
    for gid, g in groups.items():
        if g["status"] in ["SUPERFLUOUS_ALIEN", "CAMP_INTERNEE", "CORPSE_FABRICATED"]:
            superfluous_pop += g["population"]
        group_summaries[gid] = {
            "name": g["name"],
            "status": g["status"],
            "cohesion": round(g["cohesion"], 2),
            "isolation": round(g["isolation"], 2),
            "juridical_rights": round(g["juridical_rights"], 2),
            "moral_integrity": round(g["moral_integrity"], 2),
            "spontaneity": round(g["spontaneity"], 2),
            "camp_internees": g["camp_count"]
        }
        
    superfluous_ratio = round((superfluous_pop / tot_pop) * 100.0, 2) if tot_pop > 0 else 0.0
    
    result = {
        "final_regime_state": regime_state,
        "final_tdi": epoch_logs[-1]["tdi"] if epoch_logs else 0.0,
        "is_totalitarian": (regime_state == "TOTALITARIAN_RULE"),
        "superfluous_population_ratio": superfluous_ratio,
        "total_deported": total_deported,
        "total_fabricated": total_fabricated,
        "group_status": group_summaries,
        "history": epoch_logs
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
