import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class BeauvoirEngine:
    def __init__(self, config: dict):
        self.subject_id = config.get("subject_id", "SUBJECT_BEAUVOIR_01")
        self.immanence_level = float(config.get("initial_immanence", 0.7))
        self.transcendence_project = float(config.get("initial_transcendence", 0.2))
        self.economic_autonomy = float(config.get("initial_economic_autonomy", 0.2))
        self.bad_faith_complicity = float(config.get("initial_bad_faith", 0.1))
        self.patriarchal_pressure = float(config.get("initial_patriarchal_pressure", 0.8))

        self.other_index = 0.0
        self.captivity_score = 0.0
        self.liberation_score = 0.0
        self.existential_state = "BECOMING_WOMAN"

        self.history_log = []
        self._recompute(0, "INIT")

    def _recompute(self, step: int, event_name: str):
        self.immanence_level = max(0.0, min(1.0, self.immanence_level))
        self.transcendence_project = max(0.0, min(1.0, self.transcendence_project))
        self.economic_autonomy = max(0.0, min(1.0, self.economic_autonomy))
        self.bad_faith_complicity = max(0.0, min(1.0, self.bad_faith_complicity))
        self.patriarchal_pressure = max(0.0, min(1.0, self.patriarchal_pressure))

        # 1. Other Index
        self.other_index = round(min(1.0, self.patriarchal_pressure * (1.0 - self.economic_autonomy) * 0.6 + self.immanence_level * 0.4), 4)

        # 2. Captivity Score
        self.captivity_score = round(min(1.0, self.immanence_level * (1.0 - self.transcendence_project) + self.bad_faith_complicity * 0.3), 4)

        # 3. Liberation Score
        score = self.transcendence_project * 0.45 + self.economic_autonomy * 0.35 + (1.0 - self.other_index) * 0.20 - self.bad_faith_complicity * 0.15
        self.liberation_score = round(max(0.0, min(1.0, score)), 4)

        # 4. Existential State
        if self.liberation_score >= 0.70 and self.transcendence_project >= 0.60:
            self.existential_state = "SOVEREIGN_SUBJECT"
        elif self.captivity_score >= 0.65:
            self.existential_state = "CONFINED_IMMANENCE"
        elif self.other_index >= 0.65:
            self.existential_state = "ABSOLUTE_OTHER"
        elif self.bad_faith_complicity >= 0.50:
            self.existential_state = "COMPLICIT_BAD_FAITH"
        else:
            self.existential_state = "BECOMING_WOMAN"

        self.history_log.append({
            "step": step,
            "event": event_name,
            "other_index": self.other_index,
            "captivity_score": self.captivity_score,
            "liberation_score": self.liberation_score,
            "existential_state": self.existential_state
        })

    def apply_event(self, step: int, event: dict):
        action = event.get("action")
        intensity = float(event.get("intensity", 0.5))

        if action == "PATRIARCHAL_ENFORCEMENT":
            self.patriarchal_pressure = min(1.0, self.patriarchal_pressure + intensity * 0.3)
            self.immanence_level = min(1.0, self.immanence_level + intensity * 0.25)
        elif action == "DOMESTIC_CONFINEMENT":
            self.immanence_level = min(1.0, self.immanence_level + intensity * 0.35)
            self.transcendence_project = max(0.0, self.transcendence_project - intensity * 0.3)
        elif action == "BAD_FAITH_SURRENDER":
            self.bad_faith_complicity = min(1.0, self.bad_faith_complicity + intensity * 0.4)
            self.economic_autonomy = max(0.0, self.economic_autonomy - intensity * 0.25)
        elif action == "ECONOMIC_INDEPENDENCE":
            self.economic_autonomy = min(1.0, self.economic_autonomy + intensity * 0.45)
            self.patriarchal_pressure = max(0.0, self.patriarchal_pressure - intensity * 0.25)
            self.bad_faith_complicity = max(0.0, self.bad_faith_complicity - intensity * 0.3)
        elif action == "EXISTENTIAL_PROJECT":
            self.transcendence_project = min(1.0, self.transcendence_project + intensity * 0.5)
            self.immanence_level = max(0.0, self.immanence_level - intensity * 0.4)
            self.bad_faith_complicity = max(0.0, self.bad_faith_complicity - intensity * 0.35)
        elif action == "RECIPROCAL_SOLIDARITY":
            self.patriarchal_pressure = max(0.0, self.patriarchal_pressure - intensity * 0.35)
            self.transcendence_project = min(1.0, self.transcendence_project + intensity * 0.25)

        self._recompute(step, action)

    def get_summary(self):
        return {
            "subject_id": self.subject_id,
            "final_metrics": {
                "other_index": self.other_index,
                "captivity_score": self.captivity_score,
                "liberation_score": self.liberation_score,
                "existential_state": self.existential_state
            },
            "parameters": {
                "immanence_level": round(self.immanence_level, 4),
                "transcendence_project": round(self.transcendence_project, 4),
                "economic_autonomy": round(self.economic_autonomy, 4),
                "bad_faith_complicity": round(self.bad_faith_complicity, 4),
                "patriarchal_pressure": round(self.patriarchal_pressure, 4)
            },
            "trajectory": self.history_log
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    events = input_data.get("events", [])

    engine = BeauvoirEngine(config)
    for i, evt in enumerate(events, start=1):
        engine.apply_event(i, evt)

    output = engine.get_summary()
    print(json.dumps(output, separators=(',', ':')))

if __name__ == "__main__":
    main()
