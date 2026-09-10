import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def simulate_hegel_engine(input_data):
    agent_a = input_data.get("agent_a", {})
    agent_b = input_data.get("agent_b", {})
    rounds = input_data.get("interaction_rounds", 5)
    
    a_risk = agent_a.get("risk_tolerance", 0.8)
    a_fear = agent_a.get("fear_of_death", 0.3)
    b_risk = agent_b.get("risk_tolerance", 0.4)
    b_fear = agent_b.get("fear_of_death", 0.7)
    
    a_score = a_risk - a_fear
    b_score = b_risk - b_fear
    
    history_logs = []
    
    if a_score > b_score and b_fear > b_risk:
        master_id = agent_a.get("id", "Agent_A")
        slave_id = agent_b.get("id", "Agent_B")
        outcome = "ASYMMETRIC_SUBJUGATION"
    elif b_score > a_score and a_fear > a_risk:
        master_id = agent_b.get("id", "Agent_B")
        slave_id = agent_a.get("id", "Agent_A")
        outcome = "ASYMMETRIC_SUBJUGATION"
    elif a_score > 0 and b_score > 0:
        return {
            "initial_struggle": {
                "outcome": "MUTUAL_DESTRUCTION",
                "reason": "Neither consciousness fears death; mutual annihilation aborts dialectic."
            },
            "dialectic_progression": None,
            "final_synthesis": "TRAGIC_ABORTION"
        }
    else:
        return {
            "initial_struggle": {
                "outcome": "MUTUAL_ISOLATION",
                "reason": "Both withdraw into isolated self-certainty without risking life."
            },
            "dialectic_progression": None,
            "final_synthesis": "ATOMIC_ISOLATION"
        }

    master_agency = 1.0
    slave_agency = 0.2
    master_dependency = 0.1
    slave_work_accum = 0.0
    
    inversion_round = None
    aufhebung_achieved = False
    
    round_details = []
    labor_skill = input_data.get("slave_labor_skill", 0.25)
    
    for r in range(1, rounds + 1):
        master_agency = max(0.0, round(master_agency - 0.12, 4))
        master_dependency = min(1.0, round(master_dependency + 0.18, 4))
        
        slave_work_accum = round(slave_work_accum + labor_skill, 4)
        slave_agency = min(1.0, round(slave_agency + labor_skill * 0.8, 4))
        
        master_recognition = round((1.0 - master_dependency) * 0.5, 4)
        
        status = "MASTER_DOMINANT"
        if slave_agency > master_agency:
            status = "DIALECTICAL_INVERSION"
            if inversion_round is None:
                inversion_round = r
                
        if slave_agency >= 0.8 and master_dependency >= 0.7:
            status = "AUFHEBUNG_READY"
            aufhebung_achieved = True
            
        round_details.append({
            "round": r,
            "master_agency": master_agency,
            "master_dependency": master_dependency,
            "master_recognition_fulfillment": master_recognition,
            "slave_agency": slave_agency,
            "slave_work_accumulated": slave_work_accum,
            "dialectical_status": status
        })
        
    if aufhebung_achieved:
        final_verdict = "AUFHEBUNG_UNIVERSAL_MUTUAL_RECOGNITION"
        consciousness_state = "FREE_RECOGNITION_IN_ETHICAL_COMMUNITY"
    elif inversion_round is not None:
        final_verdict = "DIALECTICALLY_INVERTED_SLAVE_SUPREMACY"
        consciousness_state = "SLAVE_EMANCIPATION_IN_PROGRESS"
    else:
        final_verdict = "STAGNANT_FEUDAL_SUBJUGATION"
        consciousness_state = "UNREFLECTIVE_DEPENDENCY"
        
    return {
        "initial_struggle": {
            "master": master_id,
            "slave": slave_id,
            "outcome": outcome
        },
        "dialectic_progression": {
            "total_rounds": rounds,
            "inversion_round": inversion_round,
            "aufhebung_achieved": aufhebung_achieved,
            "final_verdict": final_verdict,
            "consciousness_state": consciousness_state
        },
        "rounds": round_details
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_hegel_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
