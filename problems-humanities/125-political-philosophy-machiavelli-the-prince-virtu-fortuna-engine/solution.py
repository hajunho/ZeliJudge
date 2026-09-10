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
    initial_state = payload.get("initial_state", {})
    events = payload.get("events", [])
    
    stability = float(initial_state.get("stability", 50.0))
    affection = float(initial_state.get("affection", 50.0))
    fear = float(initial_state.get("fear", 50.0))
    hatred = float(initial_state.get("hatred", 10.0))
    treasury = int(initial_state.get("treasury", 1000))
    military_type = initial_state.get("military_type", "MERCENARY")
    
    virtu = float(config.get("virtu", 70.0))
    lion = float(config.get("lion_prowess", 70.0))
    fox = float(config.get("fox_cunning", 70.0))
    
    rebellion_occurred = False
    deposed = False
    history = []
    
    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        if ev_type == "FORTUNA_TEMPEST":
            magnitude = float(ev_params.get("magnitude", 40.0))
            dam = (stability * 0.40) + (virtu * 0.40) + (fox * 0.20)
            net_damage = max(0.0, magnitude - dam * 0.5)
            
            if military_type == "MERCENARY" and net_damage > 15.0:
                net_damage *= 1.5
                treasury = max(0, treasury - 300)
                fear = max(0.0, fear - 20.0)
            elif military_type == "AUXILIARY" and net_damage > 20.0:
                stability = max(0.0, stability - 30.0)
                
            stability = max(0.0, stability - net_damage)
            affection = max(0.0, affection - net_damage * 0.3)
            
        elif ev_type == "EXERCISE_LION":
            force_intensity = float(ev_params.get("intensity", 30.0))
            target_threat = float(ev_params.get("threat", 25.0))
            mil_mult = 1.2 if military_type == "CITIZEN_MILITIA" else (0.8 if military_type == "MERCENARY" else 0.9)
            effective_force = (lion * 0.6 + force_intensity * 0.4) * mil_mult
            
            if effective_force >= target_threat:
                stability = min(100.0, stability + 15.0)
                fear = min(100.0, fear + force_intensity * 0.6)
            else:
                stability = max(0.0, stability - 15.0)
                fear = max(0.0, fear - 10.0)
                
        elif ev_type == "EXERCISE_FOX":
            cunning_level = float(ev_params.get("cunning", 30.0))
            trap_difficulty = float(ev_params.get("trap_difficulty", 25.0))
            effective_fox = (fox * 0.6 + cunning_level * 0.4)
            
            if effective_fox >= trap_difficulty:
                stability = min(100.0, stability + 10.0)
                fear = min(100.0, fear + 5.0)
                affection = min(100.0, affection + 5.0)
            else:
                hatred = min(100.0, hatred + 20.0)
                affection = max(0.0, affection - 15.0)
                
        elif ev_type == "CRUELTY_EXECUTION":
            severity = float(ev_params.get("severity", 40.0))
            is_single_stroke = bool(ev_params.get("single_stroke", True))
            confiscate_property = bool(ev_params.get("confiscate_patrimony", False))
            
            if is_single_stroke:
                fear = min(100.0, fear + severity * 0.8)
                stability = min(100.0, stability + severity * 0.4)
                if confiscate_property:
                    hatred = min(100.0, hatred + severity * 0.8)
                else:
                    hatred = min(100.0, hatred + severity * 0.2)
            else:
                fear = min(100.0, fear + severity * 0.4)
                hatred = min(100.0, hatred + severity * 1.2)
                stability = max(0.0, stability - 20.0)
                
        elif ev_type == "DISBURSE_FAVORS":
            amount = int(ev_params.get("amount", 200))
            distribution = ev_params.get("distribution", "GRADUAL")
            actual_spent = min(amount, treasury)
            treasury -= actual_spent
            
            if distribution == "GRADUAL":
                affection = min(100.0, affection + (actual_spent / 10.0))
                hatred = max(0.0, hatred - 10.0)
                stability = min(100.0, stability + 10.0)
            else:
                affection = min(100.0, affection + 10.0)
                hatred = min(100.0, hatred + 15.0)
                
        elif ev_type == "REFORM_MILITARY":
            new_type = ev_params.get("target_type", "CITIZEN_MILITIA")
            cost = int(ev_params.get("cost", 300))
            if treasury >= cost:
                treasury -= cost
                military_type = new_type
                stability = min(100.0, stability + 20.0)
                virtu = min(100.0, virtu + 10.0)
                
        if hatred >= 70.0:
            rebellion_occurred = True
            stability = max(0.0, stability - 40.0)
            if stability <= 10.0 or hatred >= 90.0:
                deposed = True
                
        if deposed:
            posture = "DEPOSED_RUINED"
        elif hatred >= 70.0:
            posture = "TYRANNICAL_REBELLION"
        elif fear >= 50.0 and hatred < 50.0:
            posture = "PRUDENT_FEARED_RULER"
        elif affection >= 60.0 and fear < 30.0:
            posture = "NAIVE_VULNERABLE_LOVED"
        else:
            posture = "BALANCED_PRAGMATIC"
            
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "stability": round(stability, 2),
            "fear": round(fear, 2),
            "hatred": round(hatred, 2),
            "affection": round(affection, 2),
            "treasury": treasury,
            "military_type": military_type,
            "posture": posture
        })
        
    result = {
        "final_posture": history[-1]["posture"] if history else "UNKNOWN",
        "final_stability": round(stability, 2),
        "is_machiavellian_optimum": (fear >= 50.0 and hatred < 50.0 and not deposed),
        "rebellion_occurred": rebellion_occurred,
        "deposed": deposed,
        "state": {
            "stability": round(stability, 2),
            "affection": round(affection, 2),
            "fear": round(fear, 2),
            "hatred": round(hatred, 2),
            "treasury": treasury,
            "military_type": military_type
        },
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
