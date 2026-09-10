import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class FanonEngine:
    def __init__(self, config: dict):
        self.subject_id = config.get("subject_id", "SUBJ_01")
        self.corporeal_autonomy = float(config.get("initial_corporeal_autonomy", 0.8))
        self.white_mask_level = float(config.get("initial_white_mask", 0.0))
        self.self_suppression = float(config.get("initial_self_suppression", 0.0))
        self.linguistic_assimilation = float(config.get("initial_linguistic_assimilation", 0.0))
        self.praxis_action = float(config.get("initial_praxis", 0.0))
        self.master_acceptance = float(config.get("master_acceptance_level", 0.05))

        self.epidermal_index = 0.0
        self.neurosis_index = 0.0
        self.mutual_recognition = 0.0
        self.disalienation_score = 0.0
        self.existential_state = "ALIENATED_SUBJECT"

        self.history_log = []
        self._recompute(0, "INIT")

    def _recompute(self, step: int, event_name: str):
        self.corporeal_autonomy = max(0.0, min(1.0, self.corporeal_autonomy))
        self.white_mask_level = max(0.0, min(1.0, self.white_mask_level))
        self.self_suppression = max(0.0, min(1.0, self.self_suppression))
        self.linguistic_assimilation = max(0.0, min(1.0, self.linguistic_assimilation))
        self.praxis_action = max(0.0, min(1.0, self.praxis_action))
        self.master_acceptance = max(0.0, min(1.0, self.master_acceptance))

        # 1. Epidermal Index
        self.epidermal_index = round(min(1.0, (1.0 - self.corporeal_autonomy) * 0.7 + self.self_suppression * 0.3), 4)

        # 2. Neurosis Index
        unmask_gap = self.white_mask_level * (1.0 - self.master_acceptance)
        assim_friction = self.self_suppression * self.linguistic_assimilation
        self.neurosis_index = round(min(1.0, unmask_gap * 0.65 + assim_friction * 0.35), 4)

        # 3. Mutual Recognition
        rec_product = self.white_mask_level * self.master_acceptance
        self.mutual_recognition = round(max(0.0, rec_product - 0.15), 4)

        # 4. Disalienation Score
        unmasking_effort = 1.0 - self.white_mask_level
        score = (1.0 - self.epidermal_index) * 0.35 + self.praxis_action * 0.45 + unmasking_effort * 0.20
        self.disalienation_score = round(max(0.0, min(1.0, score)), 4)

        # 5. Existential State
        if self.disalienation_score >= 0.70 and self.praxis_action >= 0.60:
            self.existential_state = "LIBERATED_HUMAN"
        elif self.neurosis_index >= 0.60:
            self.existential_state = "COLONIAL_NEUROSIS"
        elif self.epidermal_index >= 0.65:
            self.existential_state = "EPIDERMALIZED_OBJECT"
        elif self.white_mask_level >= 0.50:
            self.existential_state = "MIMICRY_ALIENATION"
        else:
            self.existential_state = "ALIENATED_SUBJECT"

        self.history_log.append({
            "step": step,
            "event": event_name,
            "epidermal_index": self.epidermal_index,
            "neurosis_index": self.neurosis_index,
            "mutual_recognition": self.mutual_recognition,
            "disalienation_score": self.disalienation_score,
            "existential_state": self.existential_state
        })

    def apply_event(self, step: int, event: dict):
        action = event.get("action")
        intensity = float(event.get("intensity", 0.5))

        if action == "COLONIAL_GAZE":
            self.corporeal_autonomy = max(0.0, self.corporeal_autonomy - intensity * 0.4)
            self.self_suppression = min(1.0, self.self_suppression + intensity * 0.25)
        elif action == "ADOPT_WHITE_MASK":
            self.white_mask_level = min(1.0, self.white_mask_level + intensity * 0.35)
            self.linguistic_assimilation = min(1.0, self.linguistic_assimilation + intensity * 0.4)
            self.self_suppression = min(1.0, self.self_suppression + intensity * 0.3)
        elif action == "MASTER_REJECTION":
            self.master_acceptance = max(0.0, self.master_acceptance - intensity * 0.2)
            self.self_suppression = min(1.0, self.self_suppression + intensity * 0.2)
        elif action == "CRITICAL_CONSCIOUSNESS":
            self.white_mask_level = max(0.0, self.white_mask_level - intensity * 0.3)
            self.corporeal_autonomy = min(1.0, self.corporeal_autonomy + intensity * 0.3)
            self.praxis_action = min(1.0, self.praxis_action + intensity * 0.2)
        elif action == "DECOLONIAL_PRAXIS":
            self.praxis_action = min(1.0, self.praxis_action + intensity * 0.45)
            self.white_mask_level = max(0.0, self.white_mask_level - intensity * 0.4)
            self.self_suppression = max(0.0, self.self_suppression - intensity * 0.35)
            self.corporeal_autonomy = min(1.0, self.corporeal_autonomy + intensity * 0.35)

        self._recompute(step, action)

    def get_summary(self):
        return {
            "subject_id": self.subject_id,
            "final_metrics": {
                "epidermal_index": self.epidermal_index,
                "neurosis_index": self.neurosis_index,
                "mutual_recognition": self.mutual_recognition,
                "disalienation_score": self.disalienation_score,
                "existential_state": self.existential_state
            },
            "parameters": {
                "corporeal_autonomy": round(self.corporeal_autonomy, 4),
                "white_mask_level": round(self.white_mask_level, 4),
                "self_suppression": round(self.self_suppression, 4),
                "linguistic_assimilation": round(self.linguistic_assimilation, 4),
                "praxis_action": round(self.praxis_action, 4)
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

    engine = FanonEngine(config)
    for i, evt in enumerate(events, start=1):
        engine.apply_event(i, evt)

    output = engine.get_summary()
    print(json.dumps(output, separators=(',', ':')))

if __name__ == "__main__":
    main()
