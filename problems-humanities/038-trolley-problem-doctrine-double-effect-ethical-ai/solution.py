import sys
import json

class MoralEngine:
    def __init__(self, config=None):
        config = config or {}
        self.child_bonus = config.get("child_bonus", 30.0)
        self.elderly_penalty = config.get("elderly_penalty", 10.0)
        self.law_bonus = config.get("law_bonus", 20.0)
        self.omission_hurdle = config.get("omission_hurdle", 15.0)

    def calculate_entity_value(self, entity):
        val = 100.0 * entity.get("weight", 1.0)
        age = entity.get("age", 30)
        if age < 18:
            val += self.child_bonus
        elif age > 65:
            val -= self.elderly_penalty
        
        if entity.get("law_abiding", True):
            val += self.law_bonus
        else:
            val -= self.law_bonus
        return val

    def evaluate_scenario(self, scenario):
        name = scenario.get("name", "unnamed")
        options = scenario.get("options", [])

        util_scores = {}
        kantian_verdicts = {}
        dde_verdicts = {}
        mm_scores = {}

        for opt in options:
            opt_id = opt["id"]
            action_type = opt.get("action_type", "MAINTAIN_COURSE")
            is_instrumental = opt.get("is_harm_instrumental_means", False)
            casualties = opt.get("casualties", [])
            saved = opt.get("saved", [])
            is_active_intervention = opt.get("is_active_intervention", False)

            # 1. Pure Utilitarian Calculation
            raw_saved_count = len(saved)
            raw_lost_count = len(casualties)
            net_util = raw_saved_count - raw_lost_count
            util_scores[opt_id] = {
                "net_lives": net_util,
                "saved_count": raw_saved_count,
                "lost_count": raw_lost_count
            }

            # 2. Kantian Deontology: Humanity as an End in Itself
            if is_instrumental:
                kantian_verdicts[opt_id] = {
                    "verdict": "FORBIDDEN",
                    "reason": "VIOLATION_OF_HUMANITY_FORMULATION_USED_AS_MERE_MEANS"
                }
            elif action_type in ["PHYSICAL_PUSH", "ORGAN_HARVEST_MURDER"]:
                kantian_verdicts[opt_id] = {
                    "verdict": "FORBIDDEN",
                    "reason": "DIRECT_BATTERY_ASSAULT_OF_RATIONAL_AGENT"
                }
            else:
                kantian_verdicts[opt_id] = {
                    "verdict": "PERMITTED",
                    "reason": "NO_CATEGORICAL_IMPERATIVE_BREACH"
                }

            # 3. Doctrine of Double Effect (DDE)
            failed_dde = []
            if action_type in ["PHYSICAL_PUSH", "DIRECT_BATTERY", "ORGAN_HARVEST_MURDER"]:
                failed_dde.append("FAILED_ACT_NATURE_INHERENTLY_EVIL")
            if is_instrumental:
                failed_dde.append("FAILED_EVIL_AS_INSTRUMENTAL_MEANS")
            if raw_saved_count <= raw_lost_count and raw_lost_count > 0:
                failed_dde.append("FAILED_PROPORTIONALITY_NET_HARM_GREATER_OR_EQUAL")

            if len(failed_dde) == 0:
                dde_verdicts[opt_id] = {"status": "PERMISSIBLE", "failed_tests": []}
            else:
                dde_verdicts[opt_id] = {"status": "IMPERMISSIBLE", "failed_tests": failed_dde}

            # 4. MIT Moral Machine Augmented Score
            total_val_saved = sum(self.calculate_entity_value(e) for e in saved)
            total_val_lost = sum(self.calculate_entity_value(e) for e in casualties)
            net_mm = total_val_saved - total_val_lost

            if is_active_intervention:
                net_mm -= self.omission_hurdle

            mm_scores[opt_id] = round(net_mm, 2)

        best_util_opt = max(options, key=lambda o: util_scores[o["id"]]["net_lives"])["id"]
        best_mm_opt = max(options, key=lambda o: mm_scores[o["id"]])["id"]

        return {
            "scenario": name,
            "utilitarian_evaluation": {
                "selected_option": best_util_opt,
                "scores": util_scores
            },
            "kantian_deontology": kantian_verdicts,
            "doctrine_of_double_effect": dde_verdicts,
            "moral_machine_evaluation": {
                "selected_option": best_mm_opt,
                "scores": mm_scores
            }
        }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    data = json.loads(raw)
    config = data.get("config", {})
    engine = MoralEngine(config)
    scenarios = data.get("scenarios", [])
    results = [engine.evaluate_scenario(sc) for sc in scenarios]

    output = {
        "scenarios_evaluated": len(results),
        "evaluations": results
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
