import sys
import os
import copy
import json

class GramsciHegemonyEngine:
    def __init__(self, config: dict):
        self.coercion = float(config.get("initial_coercion", 0.5))
        self.consent = float(config.get("initial_consent", 0.5))
        self.trench_saturation = float(config.get("initial_trench_saturation", 0.2))
        
        if "institutions" in config:
            self.institutions = copy.deepcopy(config["institutions"])
        else:
            self.institutions = {
                "media": {"hegemonic_control": 0.8, "organic_infiltrated": 0.2},
                "education": {"hegemonic_control": 0.7, "organic_infiltrated": 0.3},
                "trade_unions": {"hegemonic_control": 0.4, "organic_infiltrated": 0.6},
                "judiciary": {"hegemonic_control": 0.9, "organic_infiltrated": 0.1}
            }
        self.organic_intellectuals_count = 0
        self.traditional_intellectuals_count = 0
        self.event_log = []
        self.history = []
        self.stats = {
            "operations_count": 0,
            "war_of_maneuver_attempts": 0,
            "war_of_position_actions": 0,
            "hegemonic_stability_count": 0,
            "organic_crisis_count": 0,
            "counter_hegemony_count": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def calc_hegemony_index(self) -> float:
        alignment = 1.0 - abs(self.consent - self.coercion)
        raw_h = (0.60 * self.consent) + (0.40 * alignment)
        return round(min(1.0, max(0.0, raw_h)), 4)

    def calc_state(self, h_index: float) -> str:
        if h_index >= 0.70:
            return "HEGEMONIC_STABILITY"
        elif h_index >= 0.40:
            return "ORGANIC_CRISIS"
        else:
            return "COUNTER_HEGEMONIC_TRANSCENDENCE"

    def deploy_intellectual(self, intellectual_type: str, domain: str, power: float) -> dict:
        self.stats["operations_count"] += 1
        inst = self.institutions.get(domain, {"hegemonic_control": 0.5, "organic_infiltrated": 0.5})

        if intellectual_type == "ORGANIC":
            self.organic_intellectuals_count += 1
            gain = round(power * 0.15, 4)
            inst["organic_infiltrated"] = round(min(1.0, inst["organic_infiltrated"] + gain), 4)
            inst["hegemonic_control"] = round(max(0.0, inst["hegemonic_control"] - gain), 4)
            self.consent = round(max(0.0, self.consent - gain * 0.5), 4)
            self.log(f"ORGANIC_INTELLECTUAL domain={domain} power={power} gain={gain}")
        else:
            self.traditional_intellectuals_count += 1
            gain = round(power * 0.10, 4)
            inst["hegemonic_control"] = round(min(1.0, inst["hegemonic_control"] + gain), 4)
            self.consent = round(min(1.0, self.consent + gain * 0.4), 4)
            self.log(f"TRADITIONAL_INTELLECTUAL domain={domain} power={power} gain={gain}")

        avg_organic = sum(d["organic_infiltrated"] for d in self.institutions.values()) / max(1, len(self.institutions))
        self.trench_saturation = round(avg_organic, 4)

        h_index = self.calc_hegemony_index()
        state = self.calc_state(h_index)

        res = {
            "op": "DEPLOY_INTELLECTUAL",
            "type": intellectual_type,
            "domain": domain,
            "consent": self.consent,
            "trench_saturation": self.trench_saturation,
            "hegemony_index": h_index,
            "state": state
        }
        self.history.append(res)
        return res

    def execute_strategy(self, strategy: str, strength: float) -> dict:
        self.stats["operations_count"] += 1

        if strategy == "WAR_OF_MANEUVER":
            self.stats["war_of_maneuver_attempts"] += 1
            if self.trench_saturation < 0.60:
                self.coercion = round(min(1.0, self.coercion + 0.25), 4)
                status = "FAILED_TRENCH_REBOUND"
                self.log(f"WAR_OF_MANEUVER FAILED trench_saturation={self.trench_saturation} < 0.60 coercion_backlash={self.coercion}")
            else:
                self.coercion = round(max(0.0, self.coercion - strength * 0.5), 4)
                self.consent = round(max(0.0, self.consent - strength * 0.4), 4)
                status = "BREAKTHROUGH_HISTORICAL_BLOC"
                self.log(f"WAR_OF_MANEUVER SUCCESS breakthrough at trench_saturation={self.trench_saturation}")

        elif strategy == "WAR_OF_POSITION":
            self.stats["war_of_position_actions"] += 1
            trench_boost = round(strength * 0.12, 4)
            for d in self.institutions.values():
                d["organic_infiltrated"] = round(min(1.0, d["organic_infiltrated"] + trench_boost), 4)
                d["hegemonic_control"] = round(max(0.0, d["hegemonic_control"] - trench_boost), 4)
            avg_organic = sum(d["organic_infiltrated"] for d in self.institutions.values()) / max(1, len(self.institutions))
            self.trench_saturation = round(avg_organic, 4)
            self.consent = round(max(0.0, self.consent - trench_boost * 0.8), 4)
            status = "TRENCH_CONSOLIDATED"
            self.log(f"WAR_OF_POSITION consolidated trench_saturation={self.trench_saturation} consent={self.consent}")

        h_index = self.calc_hegemony_index()
        state = self.calc_state(h_index)

        res = {
            "op": "EXECUTE_STRATEGY",
            "strategy": strategy,
            "status": status,
            "trench_saturation": self.trench_saturation,
            "coercion": self.coercion,
            "consent": self.consent,
            "hegemony_index": h_index,
            "state": state
        }
        self.history.append(res)
        return res

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = GramsciHegemonyEngine(config)

    for op_info in operations:
        op = op_info.get("op")
        if op == "DEPLOY_INTELLECTUAL":
            itype = op_info.get("type", "ORGANIC")
            dom = op_info.get("domain", "media")
            pwr = op_info.get("power", 1.0)
            engine.deploy_intellectual(itype, dom, pwr)
        elif op == "EXECUTE_STRATEGY":
            strat = op_info.get("strategy", "WAR_OF_POSITION")
            strength = op_info.get("strength", 1.0)
            engine.execute_strategy(strat, strength)

    h_final = engine.calc_hegemony_index()
    state_final = engine.calc_state(h_final)

    for h_item in engine.history:
        st = h_item.get("state")
        if st == "HEGEMONIC_STABILITY":
            engine.stats["hegemonic_stability_count"] += 1
        elif st == "ORGANIC_CRISIS":
            engine.stats["organic_crisis_count"] += 1
        elif st == "COUNTER_HEGEMONIC_TRANSCENDENCE":
            engine.stats["counter_hegemony_count"] += 1

    return {
        "stats": engine.stats,
        "final_metrics": {
            "coercion": engine.coercion,
            "consent": engine.consent,
            "trench_saturation": engine.trench_saturation,
            "hegemony_index": h_final,
            "state": state_final
        },
        "institutions": engine.institutions,
        "history": engine.history,
        "event_log": engine.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
