# -*- coding: utf-8 -*-
import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def calculate_gini(incomes):
    sorted_incomes = sorted(incomes)
    n = len(sorted_incomes)
    if n == 0 or sum(sorted_incomes) == 0:
        return 0.0
    total = sum(sorted_incomes)
    numerator = sum((2 * i - n - 1) * x for i, x in enumerate(sorted_incomes, 1))
    return round(numerator / (n * total), 4)

def atkinson_welfare(distribution, rho):
    n = len(distribution)
    if n == 0:
        return 0.0
    if rho == 0.0:
        return round(sum(distribution) / n, 2)
    elif abs(rho - 1.0) < 1e-4:
        log_sum = sum(math.log(max(1e-6, u)) for u in distribution)
        return round(math.exp(log_sum / n), 2)
    else:
        p = 1.0 - rho
        mean_p = sum(max(1e-6, u) ** p for u in distribution) / n
        return round(mean_p ** (1.0 / p), 2)

class RawlsianEngine:
    def process(self, payload):
        mode = payload.get("mode", "evaluate_policies")

        if mode == "evaluate_policies":
            proposals = payload.get("proposals", [])
            config = payload.get("config", {})
            min_opp = config.get("min_opportunity_index", 0.5)

            evaluated = []
            for prop in proposals:
                pid = prop.get("id", "unknown")
                name = prop.get("name", "Unnamed")
                dist = prop.get("utility_distribution", [])
                violates = prop.get("violates_basic_liberties", False)
                opp_idx = prop.get("opportunity_index", 1.0)

                # First Principle (Equal Basic Liberties)
                if violates:
                    evaluated.append({
                        "id": pid,
                        "name": name,
                        "eligible": False,
                        "disqualification_reason": "VIOLATES_EQUAL_BASIC_LIBERTIES",
                        "least_advantaged_utility": min(dist) if dist else 0,
                        "total_utility": sum(dist) if dist else 0
                    })
                    continue

                # Principle 2(b) (Fair Equality of Opportunity)
                if opp_idx < min_opp:
                    evaluated.append({
                        "id": pid,
                        "name": name,
                        "eligible": False,
                        "disqualification_reason": "INSUFFICIENT_FAIR_OPPORTUNITY",
                        "opportunity_index": opp_idx,
                        "least_advantaged_utility": min(dist) if dist else 0,
                        "total_utility": sum(dist) if dist else 0
                    })
                    continue

                sorted_dist = sorted(dist)
                min_u = sorted_dist[0] if sorted_dist else 0
                tot_u = sum(dist)
                avg_u = round(tot_u / len(dist), 2) if dist else 0
                gini = calculate_gini(dist)
                nash_w = round(sum(math.log(max(1e-6, u)) for u in dist), 3)

                evaluated.append({
                    "id": pid,
                    "name": name,
                    "eligible": True,
                    "utility_distribution": dist,
                    "sorted_distribution": sorted_dist,
                    "least_advantaged_utility": min_u,
                    "total_utility": tot_u,
                    "average_utility": avg_u,
                    "nash_welfare": nash_w,
                    "gini_coefficient": gini,
                    "opportunity_index": opp_idx
                })

            eligible = [p for p in evaluated if p.get("eligible")]
            if not eligible:
                clean_eval = []
                for p in evaluated:
                    item = dict(p)
                    item.pop("sorted_distribution", None)
                    clean_eval.append(item)
                return {
                    "mode": "evaluate_policies",
                    "evaluated_proposals": clean_eval,
                    "rawlsian_winner": None,
                    "utilitarian_winner": None,
                    "status": "NO_ELIGIBLE_PROPOSALS"
                }

            # Leximin selection (Difference Principle)
            rawlsian_sorted = sorted(eligible, key=lambda x: x["sorted_distribution"], reverse=True)
            rawlsian_winner = rawlsian_sorted[0]

            # Utilitarian selection (Sum of utilities)
            utilitarian_sorted = sorted(eligible, key=lambda x: x["total_utility"], reverse=True)
            utilitarian_winner = utilitarian_sorted[0]

            is_divergent = (rawlsian_winner["id"] != utilitarian_winner["id"])
            least_adv_gain = round(rawlsian_winner["least_advantaged_utility"] - utilitarian_winner["least_advantaged_utility"], 2)
            efficiency_tradeoff = round(utilitarian_winner["total_utility"] - rawlsian_winner["total_utility"], 2)

            clean_eval = []
            for p in evaluated:
                item = dict(p)
                item.pop("sorted_distribution", None)
                clean_eval.append(item)

            return {
                "mode": "evaluate_policies",
                "evaluated_proposals": clean_eval,
                "rawlsian_winner": {
                    "id": rawlsian_winner["id"],
                    "name": rawlsian_winner["name"],
                    "least_advantaged_utility": rawlsian_winner["least_advantaged_utility"],
                    "total_utility": rawlsian_winner["total_utility"],
                    "gini_coefficient": rawlsian_winner["gini_coefficient"]
                },
                "utilitarian_winner": {
                    "id": utilitarian_winner["id"],
                    "name": utilitarian_winner["name"],
                    "least_advantaged_utility": utilitarian_winner["least_advantaged_utility"],
                    "total_utility": utilitarian_winner["total_utility"],
                    "gini_coefficient": utilitarian_winner["gini_coefficient"]
                },
                "comparison": {
                    "is_divergent": is_divergent,
                    "least_advantaged_gain_under_rawls": least_adv_gain,
                    "utilitarian_efficiency_tradeoff": efficiency_tradeoff
                }
            }

        elif mode == "veil_of_ignorance_simulation":
            distribution = payload.get("utility_distribution", [])
            rho_values = payload.get("inequality_aversions", [0.0, 1.0, 2.0, 10.0])

            spectrum = []
            min_u = min(distribution) if distribution else 0
            for rho in rho_values:
                w = atkinson_welfare(distribution, rho)
                if rho == 0.0:
                    interpretation = "BENTHAMITE_UTILITARIAN (Risk Neutral)"
                elif abs(rho - 1.0) < 1e-4:
                    interpretation = "NASH_BARGAINING (Proportional Sacrifices)"
                elif rho >= 10.0:
                    interpretation = "RAWLSIAN_MAXIMIN_APPROXIMATION (Extreme Risk Aversion)"
                else:
                    interpretation = f"ATKINSON_INTERMEDIATE (rho={rho})"

                spectrum.append({
                    "inequality_aversion_rho": rho,
                    "equally_distributed_equivalent_welfare": w,
                    "interpretation": interpretation
                })

            return {
                "mode": "veil_of_ignorance_simulation",
                "utility_distribution": distribution,
                "least_advantaged_utility": min_u,
                "welfare_spectrum": spectrum
            }

        else:
            return {"error": f"Unknown mode: {mode}"}

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    engine = RawlsianEngine()
    result = engine.process(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
