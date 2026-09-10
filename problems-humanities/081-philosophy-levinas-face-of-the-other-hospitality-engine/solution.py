import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class LevinasEngine:
    def __init__(self, config: dict):
        self.subject_id = config.get("subject_id", "SELF_01")
        self.responsiveness = float(config.get("initial_responsiveness", 0.3))
        self.possession_drive = float(config.get("initial_possession_drive", 0.7))
        self.other_vulnerability = float(config.get("initial_vulnerability", 0.5))
        self.appeal_intensity = float(config.get("initial_appeal_intensity", 0.5))
        self.substitution_level = float(config.get("initial_substitution", 0.1))

        self.totality_index = 0.0
        self.responsibility_index = 0.0
        self.hospitality_score = 0.0
        self.ethical_state = "EGOCENTRIC_SELF"

        self.history_log = []
        self._recompute(0, "INIT")

    def _recompute(self, step: int, event_name: str):
        self.responsiveness = max(0.0, min(1.0, self.responsiveness))
        self.possession_drive = max(0.0, min(1.0, self.possession_drive))
        self.other_vulnerability = max(0.0, min(1.0, self.other_vulnerability))
        self.appeal_intensity = max(0.0, min(1.0, self.appeal_intensity))
        self.substitution_level = max(0.0, min(1.0, self.substitution_level))

        # 1. Totality Index
        self.totality_index = round(min(1.0, (1.0 - self.responsiveness) * 0.7 + self.possession_drive * 0.3), 4)

        # 2. Responsibility Index
        self.responsibility_index = round(min(1.0, self.other_vulnerability * self.appeal_intensity * 0.6 + self.responsiveness * 0.4), 4)

        # 3. Hospitality Score
        score = self.responsiveness * 0.45 + (1.0 - self.totality_index) * 0.35 + self.substitution_level * 0.20
        self.hospitality_score = round(max(0.0, min(1.0, score)), 4)

        # 4. Ethical State
        if self.hospitality_score >= 0.70 and self.responsibility_index >= 0.60:
            self.ethical_state = "INFINITE_HOSPITALITY"
        elif self.totality_index >= 0.65:
            self.ethical_state = "TOTALITARIAN_APPROPRIATION"
        elif self.responsibility_index >= 0.60:
            self.ethical_state = "ETHICAL_HOSTAGE"
        elif self.other_vulnerability >= 0.65:
            self.ethical_state = "VULNERABLE_FACE_REVEALED"
        else:
            self.ethical_state = "EGOCENTRIC_SELF"

        self.history_log.append({
            "step": step,
            "event": event_name,
            "totality_index": self.totality_index,
            "responsibility_index": self.responsibility_index,
            "hospitality_score": self.hospitality_score,
            "ethical_state": self.ethical_state
        })

    def apply_event(self, step: int, event: dict):
        action = event.get("action")
        intensity = float(event.get("intensity", 0.5))

        if action == "EGOISTIC_ENJOYMENT":
            self.possession_drive = min(1.0, self.possession_drive + intensity * 0.3)
            self.responsiveness = max(0.0, self.responsiveness - intensity * 0.35)
        elif action == "EPIPHANY_OF_THE_FACE":
            self.other_vulnerability = min(1.0, self.other_vulnerability + intensity * 0.35)
            self.appeal_intensity = min(1.0, self.appeal_intensity + intensity * 0.4)
            self.responsiveness = min(1.0, self.responsiveness + intensity * 0.3)
            self.possession_drive = max(0.0, self.possession_drive - intensity * 0.25)
        elif action == "COMMANDMENT_DO_NOT_KILL":
            self.possession_drive = max(0.0, self.possession_drive - intensity * 0.45)
            self.responsiveness = min(1.0, self.responsiveness + intensity * 0.35)
            self.substitution_level = min(1.0, self.substitution_level + intensity * 0.25)
        elif action == "TOTALIZING_DOMINATION":
            self.possession_drive = min(1.0, self.possession_drive + intensity * 0.4)
            self.responsiveness = max(0.0, self.responsiveness - intensity * 0.4)
            self.other_vulnerability = min(1.0, self.other_vulnerability + intensity * 0.3)
        elif action == "RADICAL_SUBSTITUTION":
            self.substitution_level = min(1.0, self.substitution_level + intensity * 0.45)
            self.responsiveness = min(1.0, self.responsiveness + intensity * 0.4)
            self.possession_drive = max(0.0, self.possession_drive - intensity * 0.4)
        elif action == "UNCONDITIONAL_HOSPITALITY":
            self.responsiveness = min(1.0, self.responsiveness + intensity * 0.45)
            self.possession_drive = max(0.0, self.possession_drive - intensity * 0.35)
            self.substitution_level = min(1.0, self.substitution_level + intensity * 0.3)

        self._recompute(step, action)

    def get_summary(self):
        return {
            "subject_id": self.subject_id,
            "final_metrics": {
                "totality_index": self.totality_index,
                "responsibility_index": self.responsibility_index,
                "hospitality_score": self.hospitality_score,
                "ethical_state": self.ethical_state
            },
            "parameters": {
                "responsiveness": round(self.responsiveness, 4),
                "possession_drive": round(self.possession_drive, 4),
                "other_vulnerability": round(self.other_vulnerability, 4),
                "appeal_intensity": round(self.appeal_intensity, 4),
                "substitution_level": round(self.substitution_level, 4)
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

    engine = LevinasEngine(config)
    for i, evt in enumerate(events, start=1):
        engine.apply_event(i, evt)

    output = engine.get_summary()
    print(json.dumps(output, separators=(',', ':')))

if __name__ == "__main__":
    main()
