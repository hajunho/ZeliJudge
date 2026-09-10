import sys
import json

def simulate_spinoza_ethics(input_data):
    agent_id = input_data.get("agent_id", "Spinoza_Seeker")
    initial_power = input_data.get("initial_power", 50.0)
    conatus_factor = input_data.get("conatus_factor", 1.0)
    
    current_power = initial_power
    encounters = input_data.get("encounters", [])
    
    evaluation_log = []
    
    total_joy = 0.0
    total_sadness = 0.0
    active_affects_count = 0
    passive_affects_count = 0
    amor_dei_events = 0
    
    for enc in encounters:
        enc_id = enc.get("id")
        external_cause = enc.get("external_cause", "World")
        raw_valence = enc.get("valence", 0.0)
        knowledge_kind = enc.get("knowledge_kind", 1)
        is_doubtful = enc.get("is_doubtful", False)
        
        if knowledge_kind == 1:
            passive_affects_count += 1
            power_delta = raw_valence * 0.8
            is_active = False
            
            if raw_valence > 0:
                primary_affect = "LAETITIA"
                total_joy += abs(power_delta)
                if is_doubtful:
                    secondary_affect = "SPES"
                else:
                    secondary_affect = "AMOR"
            elif raw_valence < 0:
                primary_affect = "TRISTITIA"
                total_sadness += abs(power_delta)
                if is_doubtful:
                    secondary_affect = "METUS"
                else:
                    secondary_affect = "ODIUM"
            else:
                primary_affect = "AFFECTUS_NEUTER"
                secondary_affect = "INDIFFERENTIA"
                
            cognition_state = "PASSIVE_BONDAGE"
            
        elif knowledge_kind == 2:
            active_affects_count += 1
            is_active = True
            cognition_state = "ACTIVE_REASON"
            
            if raw_valence < 0:
                power_delta = abs(raw_valence) * 0.2
                primary_affect = "ANIMI_ACQUIESCENTIA"
                secondary_affect = "FORTITUDO_ANIMOSITAS"
                total_joy += power_delta
            else:
                power_delta = raw_valence * 1.0 * conatus_factor
                primary_affect = "LAETITIA_ACTIVA"
                secondary_affect = "GENEROSITAS"
                total_joy += power_delta

        elif knowledge_kind == 3:
            active_affects_count += 1
            amor_dei_events += 1
            is_active = True
            cognition_state = "BEATITUDO_INTUITIVE"
            
            power_delta = max(15.0, abs(raw_valence) * 1.2) * conatus_factor
            primary_affect = "AMOR_DEI_INTELLECTUALIS"
            secondary_affect = "BEATITUDO"
            total_joy += power_delta

        new_power = round(max(0.0, min(100.0, current_power + power_delta)), 2)
        actual_delta = round(new_power - current_power, 2)
        current_power = new_power
        
        evaluation_log.append({
            "encounter_id": enc_id,
            "external_cause": external_cause,
            "knowledge_kind": knowledge_kind,
            "primary_affect": primary_affect,
            "secondary_affect": secondary_affect,
            "is_active": is_active,
            "cognition_state": cognition_state,
            "power_delta": actual_delta,
            "updated_power": current_power
        })

    total_encounters = len(encounters)
    active_ratio = round(active_affects_count / total_encounters, 2) if total_encounters > 0 else 1.0
    
    freedom_score = round(max(0.0, min(100.0, current_power * 0.5 + active_ratio * 30.0 + min(20.0, amor_dei_events * 10.0))), 2)
    
    if freedom_score >= 80.0:
        freedom_verdict = "LIBERTAS_BEATITUDO"
    elif freedom_score >= 50.0:
        freedom_verdict = "RATIONAL_LIBERATION"
    elif freedom_score >= 30.0:
        freedom_verdict = "FLUCTUATIO_ANIMI"
    else:
        freedom_verdict = "SERVITUS_PASSIONES"

    return {
        "agent_id": agent_id,
        "final_power_of_acting": current_power,
        "total_joy": round(total_joy, 2),
        "total_sadness": round(total_sadness, 2),
        "active_ratio": active_ratio,
        "amor_dei_count": amor_dei_events,
        "freedom_score": freedom_score,
        "freedom_verdict": freedom_verdict,
        "evaluation_log": evaluation_log
    }

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_spinoza_ethics(data)
    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
