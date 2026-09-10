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

# Theoretical Benford's probabilities for digits 1 to 9: P(d) = log10(1 + 1/d)
BENFORD_PROBS = {
    d: math.log10(1 + 1.0 / d) for d in range(1, 10)
}

# Chi-Square critical values for df = 8 (9 - 1 = 8)
CHI_SQUARE_CRITICAL_005 = 15.507
CHI_SQUARE_CRITICAL_001 = 20.090

def get_first_digit(val):
    s = str(abs(val)).lstrip("0").replace(".", "")
    for ch in s:
        if ch in "123456789":
            return int(ch)
    return None

def analyze_accounting_ledger(input_data):
    company_name = input_data.get("company_name", "Unknown Corp")
    ledger_records = input_data.get("transactions", [])
    significance_level = input_data.get("significance_level", 0.05)

    # 1. Filter valid positive non-zero transactions
    valid_amounts = []
    for r in ledger_records:
        amt = r.get("amount", 0)
        if isinstance(amt, (int, float)) and amt > 0:
            valid_amounts.append(amt)

    total_valid = len(valid_amounts)
    if total_valid < 50:
        return {
            "status": "INSUFFICIENT_DATA_SAMPLE",
            "company_name": company_name,
            "sample_size": total_valid,
            "chi_square_stat": 0.0,
            "critical_value": CHI_SQUARE_CRITICAL_005,
            "mad_score": 0.0,
            "digit_distributions": {},
            "diagnostics": [
                f"Sample size ({total_valid}) is too small for reliable Benford's Law analysis (minimum 50 required)."
            ],
            "recommendation": "Collect at least 50 to 100+ natural transactions across multiple orders of magnitude."
        }

    # 2. Count first digits
    counts = {d: 0 for d in range(1, 10)}
    for amt in valid_amounts:
        d = get_first_digit(amt)
        if d:
            counts[d] += 1

    # 3. Calculate observed vs expected stats
    chi_square_stat = 0.0
    total_abs_dev = 0.0
    dist_info = {}

    for d in range(1, 10):
        obs_count = counts[d]
        obs_ratio = obs_count / total_valid
        exp_prob = BENFORD_PROBS[d]
        exp_count = total_valid * exp_prob

        chi_sq_term = ((obs_count - exp_count) ** 2) / exp_count
        chi_square_stat += chi_sq_term

        abs_dev = abs(obs_ratio - exp_prob)
        total_abs_dev += abs_dev

        dist_info[str(d)] = {
            "observed_count": obs_count,
            "expected_count": round(exp_count, 1),
            "observed_ratio": round(obs_ratio, 4),
            "expected_ratio": round(exp_prob, 4),
            "deviation": round(obs_ratio - exp_prob, 4)
        }

    mad_score = round(total_abs_dev / 9.0, 4)
    chi_square_stat = round(chi_square_stat, 3)

    crit_val = CHI_SQUARE_CRITICAL_001 if significance_level == 0.01 else CHI_SQUARE_CRITICAL_005

    diagnostics = []
    # 4. Status determination
    if chi_square_stat > crit_val:
        # Check if uniform distribution fraud or specific digit anomaly
        is_uniform = all(abs(counts[d] / total_valid - 1/9) < 0.03 for d in range(1, 10))
        if is_uniform:
            status = "FABRICATED_UNIFORM_RANDOM_NUMBERS"
            diagnostics.append("Transactions follow an unnatural uniform distribution (~11.1% per digit). Clear indicator of synthetic pseudo-random generation.")
        else:
            status = "SUSPICIOUS_ACCOUNTING_ANOMALY"
            max_dev_digit = max(counts.keys(), key=lambda d: abs(counts[d] / total_valid - BENFORD_PROBS[d]))
            diagnostics.append(f"Chi-square statistic ({chi_square_stat}) exceeds critical threshold ({crit_val}). Extreme distortion detected around digit {max_dev_digit}.")
        recommendation = "Initiate forensic audit: inspect invoice paper trails, vendor tax IDs, and manual journal entries."
    else:
        status = "GENUINE_BENFORD_COMPLIANT"
        diagnostics.append(f"Transaction amounts conform strictly to Benford's Law (Chi-square: {chi_square_stat} <= {crit_val}, MAD: {mad_score}). Natural business scale confirmed.")
        recommendation = "Standard audit clearance granted."

    return {
        "status": status,
        "company_name": company_name,
        "sample_size": total_valid,
        "chi_square_stat": chi_square_stat,
        "critical_value": crit_val,
        "mad_score": mad_score,
        "digit_distributions": dist_info,
        "diagnostics": diagnostics,
        "recommendation": recommendation
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = analyze_accounting_ledger(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
