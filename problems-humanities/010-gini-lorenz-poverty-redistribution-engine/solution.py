import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def calculate_inequality_metrics(incomes_with_weights, poverty_line_ratio=0.5):
    """
    incomes_with_weights: list of (income, weight)
    Sorted by income ascending.
    """
    if not incomes_with_weights:
        return None

    # Sort ascending
    data = sorted(incomes_with_weights, key=lambda x: x[0])
    
    total_pop = sum(w for _, w in data)
    total_income = sum(inc * w for inc, w in data)

    if total_pop == 0:
        return None

    # Median calculation (weighted median)
    half_pop = total_pop / 2.0
    cum_w = 0.0
    median_income = 0.0
    for i, (inc, w) in enumerate(data):
        cum_w += w
        if cum_w >= half_pop:
            median_income = inc
            break

    poverty_line = median_income * poverty_line_ratio

    # Gini calculation via Trapezoidal rule on Lorenz curve
    p_prev = 0.0
    L_prev = 0.0
    cum_pop = 0.0
    cum_inc = 0.0
    auc = 0.0

    # For FGT
    fgt_p0_sum = 0.0
    fgt_p1_sum = 0.0
    fgt_p2_sum = 0.0

    for inc, w in data:
        cum_pop += w
        cum_inc += inc * w
        p_curr = cum_pop / total_pop
        L_curr = cum_inc / total_income if total_income > 0 else 0.0

        auc += (L_prev + L_curr) / 2.0 * (p_curr - p_prev)
        p_prev = p_curr
        L_prev = L_curr

        # FGT
        if poverty_line > 0 and inc < poverty_line:
            gap = (poverty_line - inc) / poverty_line
            fgt_p0_sum += w
            fgt_p1_sum += w * gap
            fgt_p2_sum += w * (gap ** 2)

    gini = max(0.0, 1.0 - 2.0 * auc) if total_income > 0 else 0.0
    fgt_p0 = fgt_p0_sum / total_pop
    fgt_p1 = fgt_p1_sum / total_pop
    fgt_p2 = fgt_p2_sum / total_pop

    # Decile shares calculation
    decile_incomes = [0.0] * 10
    decile_target_step = total_pop / 10.0
    
    cur_decile = 0
    cur_pop_consumed = 0.0
    
    for inc, w in data:
        remaining_w = w
        while remaining_w > 0 and cur_decile < 10:
            decile_capacity = (cur_decile + 1) * decile_target_step - cur_pop_consumed
            if remaining_w <= decile_capacity + 1e-9:
                decile_incomes[cur_decile] += inc * remaining_w
                cur_pop_consumed += remaining_w
                remaining_w = 0.0
                if abs(cur_pop_consumed - (cur_decile + 1) * decile_target_step) < 1e-9:
                    cur_decile += 1
            else:
                decile_incomes[cur_decile] += inc * decile_capacity
                cur_pop_consumed += decile_capacity
                remaining_w -= decile_capacity
                cur_decile += 1

    decile_shares = [round(inc / total_income, 4) if total_income > 0 else 0.0 for inc in decile_incomes]

    # Palma ratio: D10 / (D1 + D2 + D3 + D4)
    d10 = decile_incomes[9]
    bottom40 = sum(decile_incomes[:4])
    palma = round(d10 / bottom40, 4) if bottom40 > 0 else 0.0

    # S80/S20 ratio (Quintile ratio): (D9 + D10) / (D1 + D2)
    top20 = sum(decile_incomes[8:10])
    bottom20 = sum(decile_incomes[:2])
    s80_s20 = round(top20 / bottom20, 4) if bottom20 > 0 else 0.0

    return {
        "median_income": round(median_income, 2),
        "poverty_line": round(poverty_line, 2),
        "gini": round(gini, 4),
        "palma_ratio": palma,
        "s80_s20_ratio": s80_s20,
        "fgt_p0_headcount": round(fgt_p0, 4),
        "fgt_p1_gap": round(fgt_p1, 4),
        "fgt_p2_severity": round(fgt_p2, 4),
        "decile_shares": decile_shares
    }

def process_redistribution_simulation(input_data: dict) -> dict:
    sim_id = input_data.get("simulation_id", "SIM_DEFAULT")
    poverty_line_ratio = input_data.get("poverty_line_ratio", 0.5)
    households = input_data.get("households", [])

    pre_data = []
    post_data = []
    total_pop = 0

    for hh in households:
        m = hh.get("members", 1)
        if m <= 0:
            m = 1
        m_sqrt = math.sqrt(m)
        market_inc = hh.get("market_income", 0.0)
        tax = hh.get("tax", 0.0)
        transfer = hh.get("transfer", 0.0)

        # Equivalised disposable income
        disp_inc = max(0.0, market_inc - tax + transfer)
        mkt_eq = max(0.0, market_inc) / m_sqrt
        disp_eq = disp_inc / m_sqrt

        pre_data.append((mkt_eq, m))
        post_data.append((disp_eq, m))
        total_pop += m

    pre_metrics = calculate_inequality_metrics(pre_data, poverty_line_ratio)
    post_metrics = calculate_inequality_metrics(post_data, poverty_line_ratio)

    rs = round(pre_metrics["gini"] - post_metrics["gini"], 4)
    gini_red_pct = round((rs / pre_metrics["gini"]) * 100.0, 2) if pre_metrics["gini"] > 0 else 0.0
    
    p0_diff = pre_metrics["fgt_p0_headcount"] - post_metrics["fgt_p0_headcount"]
    pov_red_pct = round((p0_diff / pre_metrics["fgt_p0_headcount"]) * 100.0, 2) if pre_metrics["fgt_p0_headcount"] > 0 else 0.0

    if rs >= 0.08:
        eval_str = "SIGNIFICANT_PROGRESSIVE_REDISTRIBUTION"
    elif rs >= 0.03:
        eval_str = "MODERATE_PROGRESSIVE_REDISTRIBUTION"
    elif rs > 0.0:
        eval_str = "SLIGHT_PROGRESSIVE_REDISTRIBUTION"
    elif rs == 0.0:
        eval_str = "NEUTRAL_REDISTRIBUTION"
    else:
        eval_str = "REGRESSIVE_REDISTRIBUTION"

    return {
        "simulation_id": sim_id,
        "total_households": len(households),
        "total_population": total_pop,
        "pre_redistribution": pre_metrics,
        "post_redistribution": post_metrics,
        "redistribution_effect": {
            "reynolds_smolensky": rs,
            "gini_reduction_percent": gini_red_pct,
            "poverty_reduction_percent": pov_red_pct,
            "evaluation": eval_str
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = process_redistribution_simulation(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
