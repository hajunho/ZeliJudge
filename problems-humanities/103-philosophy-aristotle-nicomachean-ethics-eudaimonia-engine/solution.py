import sys
import json

VIRTUE_TABLE = {
    "COURAGE": {"virtue": "Andreia", "deficiency": "Cowardice (Deilia)", "excess": "Rashness (Thrasytes)", "mean": 50, "tol": 15},
    "TEMPERANCE": {"virtue": "Sophrosyne", "deficiency": "Insensibility (Anaisthesia)", "excess": "Self-Indulgence (Akolasia)", "mean": 50, "tol": 15},
    "GENEROSITY": {"virtue": "Eleutheriotes", "deficiency": "Stinginess (Aneleutheria)", "excess": "Prodigality (Asotia)", "mean": 50, "tol": 15},
    "MAGNANIMITY": {"virtue": "Megalopsychia", "deficiency": "Pusillanimity (Mikropsychia)", "excess": "Vanity (Chaunotes)", "mean": 50, "tol": 15},
    "MILDNESS": {"virtue": "Praotes", "deficiency": "Spiritlessness (Aorgesia)", "excess": "Irascibility (Orgylotes)", "mean": 50, "tol": 15},
    "TRUTHFULNESS": {"virtue": "Aletheia", "deficiency": "Self-Deprecation (Eironeia)", "excess": "Boastfulness (Alazoneia)", "mean": 50, "tol": 15},
    "WITTINESS": {"virtue": "Eutrapelia", "deficiency": "Boorishness (Agroikia)", "excess": "Buffoonery (Bomolochia)", "mean": 50, "tol": 15},
    "FRIENDLINESS": {"virtue": "Philia", "deficiency": "Quarrelsomeness (Dyseris)", "excess": "Flattery (Areskeia)", "mean": 50, "tol": 15}
}

def evaluate_aristotle_ethics(input_data):
    agent_id = input_data.get("agent_id", "Citizen")
    initial_habits = input_data.get("initial_habits", {})
    alpha = input_data.get("habituation_rate", 0.1)
    
    current_habits = {v: initial_habits.get(v, 50.0) for v in VIRTUE_TABLE}
    
    actions = input_data.get("actions", [])
    action_evaluations = []
    
    total_actions = len(actions)
    virtuous_count = 0
    akrasia_count = 0
    vicious_count = 0
    continent_count = 0
    involuntary_count = 0
    
    for act in actions:
        virtue_name = act.get("virtue", "COURAGE")
        val = act.get("action_value", 50.0)
        is_compelled = act.get("compelled_by_force", False)
        is_ignorant_of_particulars = act.get("ignorant_of_circumstance", False)
        reason_knows_good = act.get("reason_knows_good", True)
        appetite_pull = act.get("appetite_intensity", 0.0)
        willpower = act.get("willpower_resolve", 0.0)
        has_remorse = act.get("has_remorse", True)

        spec = VIRTUE_TABLE.get(virtue_name, VIRTUE_TABLE["COURAGE"])
        mean = spec["mean"]
        tol = spec["tol"]
        
        diff = val - mean
        if diff < -tol:
            mean_state = "DEFICIENCY"
            classification = spec["deficiency"]
        elif diff > tol:
            mean_state = "EXCESS"
            classification = spec["excess"]
        else:
            mean_state = "MEAN"
            classification = spec["virtue"]
            
        is_voluntary = not (is_compelled or is_ignorant_of_particulars)
        
        if not is_voluntary:
            moral_state = "INVOLUNTARY"
            involuntary_count += 1
        else:
            if mean_state == "MEAN":
                if appetite_pull <= 30:
                    moral_state = "VIRTUOUS"
                    virtuous_count += 1
                else:
                    if willpower >= appetite_pull:
                        moral_state = "CONTINENT"
                        continent_count += 1
                    else:
                        moral_state = "INCONTINENT"
                        akrasia_count += 1
            else:
                if reason_knows_good:
                    if has_remorse:
                        moral_state = "INCONTINENT"
                        akrasia_count += 1
                    else:
                        moral_state = "VICIOUS"
                        vicious_count += 1
                else:
                    moral_state = "VICIOUS"
                    vicious_count += 1
                    
        if is_voluntary:
            old_h = current_habits[virtue_name]
            new_h = round(old_h + alpha * (val - old_h), 2)
            current_habits[virtue_name] = new_h
        else:
            new_h = current_habits[virtue_name]
            
        action_evaluations.append({
            "action_id": act.get("id"),
            "virtue": virtue_name,
            "mean_state": mean_state,
            "classification": classification,
            "moral_state": moral_state,
            "is_voluntary": is_voluntary,
            "updated_habit": new_h
        })

    habit_penalty = sum(abs(current_habits[v] - 50.0) for v in current_habits) / len(current_habits)
    
    if total_actions > 0:
        virtue_ratio = (virtuous_count * 1.0 + continent_count * 0.75 - akrasia_count * 0.5 - vicious_count * 1.0) / total_actions
    else:
        virtue_ratio = 1.0
        
    base_eudaimonia = max(0.0, min(100.0, 50.0 + virtue_ratio * 40.0 - habit_penalty * 0.5))
    eudaimonia_score = round(base_eudaimonia, 2)
    
    if eudaimonia_score >= 80.0:
        life_verdict = "EUDAIMON_LIFE"
    elif eudaimonia_score >= 50.0:
        life_verdict = "CONTINENT_STRUGGLE_LIFE"
    elif eudaimonia_score >= 30.0:
        life_verdict = "AKRATIC_ERRATIC_LIFE"
    else:
        life_verdict = "VICIOUS_DEBASED_LIFE"

    return {
        "agent_id": agent_id,
        "final_habits": current_habits,
        "action_evaluations": action_evaluations,
        "summary_counts": {
            "total_actions": total_actions,
            "virtuous_count": virtuous_count,
            "continent_count": continent_count,
            "akrasia_count": akrasia_count,
            "vicious_count": vicious_count,
            "involuntary_count": involuntary_count
        },
        "habit_mean_deviation": round(habit_penalty, 2),
        "eudaimonia_score": eudaimonia_score,
        "life_verdict": life_verdict
    }

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = evaluate_aristotle_ethics(data)
    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
