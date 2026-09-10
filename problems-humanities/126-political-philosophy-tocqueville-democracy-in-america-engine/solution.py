import json
import sys

# Ensure UTF-8 encoding on Windows
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
    init_state = payload.get("initial_state", {})
    events = payload.get("events", [])
    
    equality = float(init_state.get("equality_level", 60.0))
    centralization = float(init_state.get("centralization", 30.0))
    individualism = float(init_state.get("individualism", 35.0))
    associations = float(init_state.get("civic_associations", 50.0))
    conformism = float(init_state.get("majority_conformism", 30.0))
    
    history = []
    
    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        if ev_type == "EGALITARIAN_EXPANSION":
            intensity = float(ev_params.get("intensity", 20.0))
            equality = min(100.0, equality + intensity)
            individualism = min(100.0, individualism + intensity * 0.4)
            conformism = min(100.0, conformism + intensity * 0.3)
            
        elif ev_type == "INDIVIDUALISTIC_WITHDRAWAL":
            apathy = float(ev_params.get("apathy", 25.0))
            individualism = min(100.0, individualism + apathy)
            associations = max(0.0, associations - apathy * 0.8)
            centralization = min(100.0, centralization + apathy * 0.3)
            
        elif ev_type == "MAJORITY_OPINION_PRESSURE":
            pressure = float(ev_params.get("pressure", 30.0))
            conformism = min(100.0, conformism + pressure)
            associations = max(0.0, associations - pressure * 0.4)
            
        elif ev_type == "TUTELARY_STATE_EXPANSION":
            bureaucracy = float(ev_params.get("bureaucracy", 30.0))
            centralization = min(100.0, centralization + bureaucracy)
            individualism = min(100.0, individualism + bureaucracy * 0.4)
            associations = max(0.0, associations - bureaucracy * 0.6)
            
        elif ev_type == "FORM_CIVIC_ASSOCIATION":
            vitality = float(ev_params.get("vitality", 30.0))
            associations = min(100.0, associations + vitality)
            individualism = max(0.0, individualism - vitality * 0.7)
            conformism = max(0.0, conformism - vitality * 0.3)
            centralization = max(0.0, centralization - vitality * 0.3)
            
        elif ev_type == "FREE_PRESS_DEBATE":
            pluralism = float(ev_params.get("pluralism", 25.0))
            conformism = max(0.0, conformism - pluralism)
            associations = min(100.0, associations + pluralism * 0.5)
            individualism = max(0.0, individualism - pluralism * 0.3)
            
        elif ev_type == "CIVIC_EDUCATION_RENEWAL":
            enlightenment = float(ev_params.get("enlightenment", 20.0))
            individualism = max(0.0, individualism - enlightenment * 0.6)
            associations = min(100.0, associations + enlightenment * 0.5)
            
        raw_liberty = (0.40 * associations) + (0.20 * equality) - (0.25 * centralization) - (0.20 * individualism) - (0.15 * conformism) + 50.0
        liberty = round(min(100.0, max(0.0, raw_liberty)), 2)
        
        if centralization >= 70.0 and individualism >= 60.0 and associations < 40.0:
            regime = "DEMOCRATIC_DESPOTISM"
        elif conformism >= 70.0 and liberty < 50.0:
            regime = "TYRANNY_OF_MAJORITY"
        elif associations >= 75.0 and centralization < 40.0:
            regime = "TOWNSHIP_SELF_GOVERNANCE"
        elif liberty >= 65.0 and associations >= 50.0:
            regime = "FREE_DEMOCRATIC_REPUBLIC"
        elif individualism >= 75.0 and liberty < 40.0:
            regime = "ATOMIZED_MASS_SOCIETY"
        else:
            regime = "MODERATE_DEMOCRACY"
            
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "equality": round(equality, 2),
            "centralization": round(centralization, 2),
            "individualism": round(individualism, 2),
            "associations": round(associations, 2),
            "conformism": round(conformism, 2),
            "liberty_index": liberty,
            "regime": regime
        })
        
    result = {
        "final_regime": history[-1]["regime"] if history else "UNKNOWN",
        "final_liberty_index": history[-1]["liberty_index"] if history else 0.0,
        "is_free_society": (history[-1]["liberty_index"] >= 60.0 and history[-1]["regime"] in ["FREE_DEMOCRATIC_REPUBLIC", "TOWNSHIP_SELF_GOVERNANCE"]) if history else False,
        "is_despotic_or_tyrannical": (history[-1]["regime"] in ["DEMOCRATIC_DESPOTISM", "TYRANNY_OF_MAJORITY"]) if history else False,
        "final_state": {
            "equality": round(equality, 2),
            "centralization": round(centralization, 2),
            "individualism": round(individualism, 2),
            "associations": round(associations, 2),
            "conformism": round(conformism, 2)
        },
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
