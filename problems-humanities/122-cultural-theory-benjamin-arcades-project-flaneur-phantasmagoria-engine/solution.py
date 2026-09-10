import sys
import json

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    subject_id = input_data.get("subject_id", "PARISIAN_FLANEUR")
    intellect = float(input_data.get("intellect", 1.2))
    initial_phantasmagoria = float(input_data.get("initial_phantasmagoria", 0.4))
    initial_aura_memory = float(input_data.get("initial_aura_memory", 0.1))
    operations = input_data.get("operations", [])
    
    current_p = initial_phantasmagoria
    current_m = initial_aura_memory
    decommodified_fragments = 0
    
    stats = {
        "arcade_strolls": 0,
        "fragments_collected": 0,
        "dialectical_flashes": 0,
        "failed_awakenings": 0
    }
    
    op_log = []
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "STROLL_ARCADE":
            stats["arcade_strolls"] += 1
            crowd = float(op.get("crowd_density", 0.5))
            glow = float(op.get("commodity_glow", 0.7))
            
            detachment = max(0.0, round(intellect * (1.0 - crowd * 0.4), 4))
            delta_p = round(glow * (1.0 - min(1.0, detachment * 0.5)), 4)
            current_p = min(1.0, round(current_p + delta_p * 0.5, 4))
            
            op_log.append({
                "op": "STROLL_ARCADE",
                "crowd_density": crowd,
                "commodity_glow": glow,
                "flaneur_detachment": detachment,
                "new_phantasmagoria": current_p
            })
            
        elif op_type == "COLLECT_FRAGMENT":
            stats["fragments_collected"] += 1
            fragment = op.get("fragment_name", "ANTIQUE_CLOCK")
            hist_depth = float(op.get("historical_depth", 0.5))
            
            delta_m = round(hist_depth * 0.4, 4)
            current_m = min(1.0, round(current_m + delta_m, 4))
            decommodified_fragments += 1
            
            op_log.append({
                "op": "COLLECT_FRAGMENT",
                "fragment_name": fragment,
                "historical_depth": hist_depth,
                "new_aura_memory": current_m,
                "decommodified_fragments": decommodified_fragments
            })
            
        elif op_type == "FLASH_DIALECTICAL_IMAGE":
            now_intensity = float(op.get("now_intensity", 0.8))
            shock = round(current_m * now_intensity, 4)
            
            if shock >= 0.35:
                stats["dialectical_flashes"] += 1
                current_p = max(0.0, round(current_p - 0.45, 4))
                status = "DIALECTICAL_AWAKENING_FLASH"
            else:
                stats["failed_awakenings"] += 1
                status = "DREAMWORLD_UNAFFECTED"
                
            op_log.append({
                "op": "FLASH_DIALECTICAL_IMAGE",
                "now_intensity": now_intensity,
                "shock_value": shock,
                "status": status,
                "new_phantasmagoria": current_p
            })

    if current_p <= 0.25 and stats["dialectical_flashes"] >= 1:
        verdict = "AWAKENED_HISTORICAL_MATERIALIST"
    elif current_p >= 0.70:
        verdict = "PHANTASMAGORIC_DREAMER"
    elif decommodified_fragments >= 2 and intellect >= 1.0:
        verdict = "MELANCHOLIC_ALLEGORIST_COLLECTOR"
    else:
        verdict = "CASUAL_URBAN_PASSERBY"

    res = {
        "subject_id": subject_id,
        "initial_state": {
            "intellect": intellect,
            "initial_phantasmagoria": initial_phantasmagoria,
            "initial_aura_memory": initial_aura_memory
        },
        "final_state": {
            "phantasmagoria_index": current_p,
            "aura_memory": current_m,
            "decommodified_fragments": decommodified_fragments,
            "consciousness_verdict": verdict
        },
        "stats": stats,
        "op_log": op_log
    }
    
    sys.stdout.write(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    solve()
