import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    
    input_data = json.loads(raw_input)
    
    prod = input_data.get("production_config", {})
    working_day = prod.get("working_day_hours", 8.0)
    necessary_labor = prod.get("necessary_labor_hours", 4.0)
    constant_c = float(prod.get("constant_capital_c", 1000.0))
    variable_v = float(prod.get("variable_capital_v", 500.0))
    
    # 1. Surplus Value & Exploitation
    surplus_hours = max(0.0, round(working_day - necessary_labor, 4))
    rate_of_surplus_value_pct = round((surplus_hours / max(0.01, necessary_labor)) * 100.0, 2)
    surplus_s = round(variable_v * (rate_of_surplus_value_pct / 100.0), 2)
    
    # 2. 4-Fold Alienation Index
    alienation = input_data.get("alienation_factors", {})
    a_product = alienation.get("product_appropriation_ratio", 0.9)
    a_act = alienation.get("work_automation_monotony", 0.8)
    a_species = alienation.get("species_being_suppression", 0.85)
    a_social = alienation.get("interpersonal_competition", 0.75)
    
    composite_alienation = round((a_product + a_act + a_species + a_social) / 4.0, 4)
    
    if composite_alienation >= 0.8:
        alienation_verdict = "RADICAL_FETISHISTIC_ALIENATION"
    elif composite_alienation >= 0.5:
        alienation_verdict = "STRUCTURAL_WAGE_LABOR_ALIENATION"
    else:
        alienation_verdict = "MILD_COMMODITY_ALIENATION"
        
    # 3. Organic Composition of Capital & Rate of Profit
    organic_comp = round(constant_c / max(0.01, (constant_c + variable_v)), 4)
    rate_of_profit_pct = round((surplus_s / max(0.01, (constant_c + variable_v))) * 100.0, 2)
    
    # 4. Technological Innovation Rounds (TRPF: Tendency of Rate of Profit to Fall)
    rounds = input_data.get("innovation_rounds", [])
    current_c = constant_c
    current_v = variable_v
    
    trajectory = []
    
    for r in rounds:
        r_num = r.get("round", 1)
        added_c = r.get("added_machinery_c", 0.0)
        delta_v = r.get("delta_variable_v", 0.0)
        
        current_c = round(current_c + added_c, 2)
        current_v = max(0.0, round(current_v + delta_v, 2))
        
        r_surplus_s = round(current_v * (rate_of_surplus_value_pct / 100.0), 2)
        r_total_capital = round(current_c + current_v, 2)
        r_organic = round(current_c / max(0.01, r_total_capital), 4)
        r_profit_pct = round((r_surplus_s / max(0.01, r_total_capital)) * 100.0, 2)
        
        crisis_state = "NORMAL_ACCUMULATION"
        if r_profit_pct < 10.0 and r_organic > 0.85:
            crisis_state = "CRISIS_OF_OVERACCUMULATION_TRPF"
        elif r_profit_pct < 15.0:
            crisis_state = "FALLING_PROFITABILITY_WARNING"
            
        trajectory.append({
            "round": r_num,
            "constant_capital_c": current_c,
            "variable_capital_v": current_v,
            "total_capital": r_total_capital,
            "organic_composition": r_organic,
            "surplus_value_s": r_surplus_s,
            "rate_of_profit_pct": r_profit_pct,
            "state": crisis_state
        })

    final_profit_rate = trajectory[-1]["rate_of_profit_pct"] if trajectory else rate_of_profit_pct
    final_organic = trajectory[-1]["organic_composition"] if trajectory else organic_comp
    
    if final_profit_rate < 10.0 and final_organic > 0.85:
        systemic_verdict = "SYSTEMIC_CRISIS_TRPF_REALIZED"
    elif final_profit_rate < rate_of_profit_pct:
        systemic_verdict = "TENDENTIAL_FALL_DEMONSTRATED"
    else:
        systemic_verdict = "STABLE_EXPLOITATION_EQUILIBRIUM"

    result = {
        "surplus_value_analysis": {
            "working_day_hours": working_day,
            "necessary_labor_hours": necessary_labor,
            "surplus_labor_hours": surplus_hours,
            "rate_of_exploitation_pct": rate_of_surplus_value_pct,
            "initial_surplus_value_s": surplus_s
        },
        "alienation_profile": {
            "product_alienation": a_product,
            "act_of_production_alienation": a_act,
            "species_being_alienation": a_species,
            "social_relations_alienation": a_social,
            "composite_alienation_index": composite_alienation,
            "verdict": alienation_verdict
        },
        "initial_macro_metrics": {
            "organic_composition_of_capital": organic_comp,
            "initial_rate_of_profit_pct": rate_of_profit_pct
        },
        "accumulation_trajectory": trajectory,
        "systemic_historical_verdict": systemic_verdict
    }

    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
