import sys
import json

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    subject = input_data.get("subject", "GENIUS_SEEKER")
    intellect_ratio = float(input_data.get("intellect_ratio", 1.2))
    will_to_live = float(input_data.get("will_to_live", 0.8))
    principium_individuationis = float(input_data.get("principium_individuationis", 0.7))
    ascetic_virtue = float(input_data.get("ascetic_virtue", 0.1))
    events = input_data.get("events", [])
    
    current_w = will_to_live
    current_p = principium_individuationis
    current_av = ascetic_virtue
    
    event_log = []
    stats = {
        "art_encounters": 0,
        "sublime_transcendences": 0,
        "will_terrors": 0,
        "compassion_breakthroughs": 0,
        "ascetic_purifications": 0,
        "sabbath_episodes": 0
    }
    
    grade_map = {
        "ARCHITECTURE": (1, 0.20),
        "LANDSCAPE": (2, 0.35),
        "SCULPTURE": (3, 0.55),
        "POETRY": (4, 0.75),
        "TRAGEDY": (5, 0.90),
        "MUSIC": (999, 1.00)
    }
    
    for ev in events:
        ev_type = ev.get("type")
        
        if ev_type == "ENCOUNTER_ART":
            stats["art_encounters"] += 1
            art_form = ev.get("art_form", "MUSIC").upper()
            threat = float(ev.get("sublime_threat", 0.0))
            
            grade, mu = grade_map.get(art_form, (999, 1.00))
            
            if threat > 0.0:
                capacity = intellect_ratio * (1.0 - current_w * 0.5)
                sublime_threshold = threat * 0.7
                if capacity >= sublime_threshold:
                    stats["sublime_transcendences"] += 1
                    status = "SUBLIME_TRANSCENDENCE"
                    peace = round(min(1.0, mu * intellect_ratio * 0.9), 4)
                else:
                    stats["will_terrors"] += 1
                    status = "TERROR_OF_THE_WILL"
                    peace = 0.0
            else:
                if intellect_ratio >= current_w * 0.5:
                    stats["sabbath_episodes"] += 1
                    status = "BEAUTIFUL_CONTEMPLATION"
                    peace = round(min(1.0, mu * intellect_ratio), 4)
                else:
                    status = "WILL_BOUND_DISTRACTION"
                    peace = round(min(1.0, mu * 0.3), 4)
                    
            event_log.append({
                "type": "ENCOUNTER_ART",
                "art_form": art_form,
                "grade": grade,
                "threat": threat,
                "status": status,
                "peace_index": peace,
                "is_music_metaphysical_copy": (art_form == "MUSIC")
            })
            
        elif ev_type == "ETHICAL_INSIGHT":
            s_ext = float(ev.get("witness_suffering", 0.5))
            if s_ext > current_p * 0.6:
                stats["compassion_breakthroughs"] += 1
                delta_p = round(0.3 * s_ext, 4)
                current_p = round(max(0.0, current_p - delta_p), 4)
                compassion = round(min(1.0, s_ext * (1.0 - current_p)), 4)
                status = "TAT_TVAM_ASI_BREAKTHROUGH"
            else:
                status = "MAYA_EGO_PRESERVED"
                compassion = round(s_ext * (1.0 - current_p) * 0.2, 4)
                
            event_log.append({
                "type": "ETHICAL_INSIGHT",
                "witness_suffering": s_ext,
                "status": status,
                "compassion_index": compassion,
                "new_principium_individuationis": current_p
            })
            
        elif ev_type == "APPLY_QUIETIVE":
            stats["ascetic_purifications"] += 1
            practice = ev.get("practice", "RESIGNATION").upper()
            impulses = {
                "FASTING": 0.15,
                "CHASTITY": 0.25,
                "VOLUNTARY_POVERTY": 0.20,
                "RESIGNATION": 0.30
            }
            imp = impulses.get(practice, 0.20)
            delta_av = round(imp * (1.0 - current_p * 0.5), 4)
            current_av = round(min(1.0, current_av + delta_av), 4)
            
            delta_w = round(current_av * 0.35, 4)
            current_w = round(max(0.0, current_w - delta_w), 4)
            
            event_log.append({
                "type": "APPLY_QUIETIVE",
                "practice": practice,
                "added_ascetic_virtue": delta_av,
                "current_ascetic_virtue": current_av,
                "new_will_to_live": current_w
            })
            
    if current_w <= 0.10 and current_av >= 0.70:
        final_state = "SAINTLY_NIRVANA_NOTHINGNESS"
    elif current_p <= 0.25:
        final_state = "UNIVERSAL_COMPASSIONATE_BEING"
    elif current_w >= 0.65:
        final_state = "TANTALUS_PRISONER_OF_WILL"
    else:
        final_state = "EPHEMERAL_SABBATH_SEEKER"
        
    res = {
        "subject": subject,
        "initial_state": {
            "intellect_ratio": intellect_ratio,
            "will_to_live": will_to_live,
            "principium_individuationis": principium_individuationis,
            "ascetic_virtue": ascetic_virtue
        },
        "final_state": {
            "will_to_live": current_w,
            "principium_individuationis": current_p,
            "ascetic_virtue": current_av,
            "existential_verdict": final_state
        },
        "stats": stats,
        "event_log": event_log
    }
    
    sys.stdout.write(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    solve()
