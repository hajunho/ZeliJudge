import sys
import json
import copy

# Ensure UTF-8 I/O for Korean/multilingual text on Windows environments
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

class GenderSubject:
    def __init__(self, subject_id: str, name: str, assigned_sex: str, performed_gender: str, desire_orientation: str, conformity_ratio: float):
        self.subject_id = subject_id
        self.name = name
        self.assigned_sex = assigned_sex
        self.performed_gender = performed_gender
        self.desire_orientation = desire_orientation
        self.conformity_ratio = min(1.0, max(0.0, float(conformity_ratio)))
        self.performativity_iterations = 0
        self.trouble_index = 0.0
        self.is_intelligible = True

    def evaluate(self, matrix_coercion: float):
        is_normative_gender = (
            (self.assigned_sex == "male" and self.performed_gender == "masculine") or
            (self.assigned_sex == "female" and self.performed_gender == "feminine")
        )
        is_normative_desire = (self.desire_orientation == "hetero")
        
        dissonance = 0.0
        if not is_normative_gender:
            dissonance += 0.55
        if not is_normative_desire:
            dissonance += 0.45

        raw_trouble = dissonance * (1.0 - self.conformity_ratio * 0.7)
        self.trouble_index = round(min(1.0, max(0.0, raw_trouble)), 4)

        abject_pressure = matrix_coercion * dissonance * (1.0 - self.conformity_ratio)
        self.is_intelligible = (abject_pressure < 0.45)

    def iterate_performance(self, subversion_intensity: float):
        self.performativity_iterations += 1
        sub = float(subversion_intensity)
        if sub > 0.0:
            self.conformity_ratio = max(0.0, self.conformity_ratio - sub * 0.4)
        else:
            self.conformity_ratio = min(1.0, self.conformity_ratio + 0.1)

    def to_dict(self) -> dict:
        return {
            "subject_id": self.subject_id,
            "name": self.name,
            "assigned_sex": self.assigned_sex,
            "performed_gender": self.performed_gender,
            "desire_orientation": self.desire_orientation,
            "conformity_ratio": round(self.conformity_ratio, 4),
            "iterations": self.performativity_iterations,
            "trouble_index": self.trouble_index,
            "is_intelligible": self.is_intelligible
        }

class ButlerPerformativityEngine:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.matrix_coercion = float(config.get("matrix_coercion", 0.70))
        self.subjects = {}
        for s_cfg in config.get("subjects", []):
            s = GenderSubject(
                subject_id=s_cfg["subject_id"],
                name=s_cfg["name"],
                assigned_sex=s_cfg.get("assigned_sex", "male"),
                performed_gender=s_cfg.get("performed_gender", "masculine"),
                desire_orientation=s_cfg.get("desire_orientation", "hetero"),
                conformity_ratio=s_cfg.get("conformity_ratio", 0.90)
            )
            self.subjects[s.subject_id] = s

        self.current_step = 0
        self.avg_trouble = 0.0
        self.matrix_state = "NORMATIVE_HEGEMONY"
        self.query_logs = []
        self._evaluate()

    def _evaluate(self):
        if not self.subjects:
            self.avg_trouble = 0.0
            self.matrix_state = "NORMATIVE_HEGEMONY"
            return

        for s in self.subjects.values():
            s.evaluate(self.matrix_coercion)

        total_t = sum(s.trouble_index for s in self.subjects.values())
        self.avg_trouble = round(total_t / len(self.subjects), 4)

        if self.avg_trouble >= 0.55:
            self.matrix_state = "PARODIC_SUBVERSION_RUPTURE"
        elif self.avg_trouble >= 0.25:
            self.matrix_state = "CONTESTED_GENDER_TROUBLE"
        else:
            self.matrix_state = "NORMATIVE_HEGEMONY"

    def perform_citation(self, subject_id: str, subversion_intensity: float):
        if subject_id in self.subjects:
            s = self.subjects[subject_id]
            s.iterate_performance(subversion_intensity)
            if subversion_intensity > 0.0:
                self.matrix_coercion = max(0.0, self.matrix_coercion - float(subversion_intensity) * 0.15)
            self._evaluate()

    def enforce_matrix_norms(self, intensity: float):
        eff = float(intensity)
        self.matrix_coercion = min(1.0, max(0.0, self.matrix_coercion + eff))
        for s in self.subjects.values():
            s.conformity_ratio = min(1.0, s.conformity_ratio + eff * 0.2)
        self._evaluate()

    def reassign_performance(self, subject_id: str, new_gender: str, new_desire: str):
        if subject_id in self.subjects:
            s = self.subjects[subject_id]
            s.performed_gender = new_gender
            s.desire_orientation = new_desire
            self._evaluate()

    def step(self):
        self.current_step += 1
        self._evaluate()

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "PERFORM_CITATION":
                self.perform_citation(cmd["subject_id"], cmd.get("subversion_intensity", 0.0))
            elif ctype == "ENFORCE_MATRIX_NORMS":
                self.enforce_matrix_norms(cmd["intensity"])
            elif ctype == "REASSIGN_PERFORMANCE":
                self.reassign_performance(cmd["subject_id"], cmd["new_gender"], cmd["new_desire"])
            elif ctype == "STEP":
                self.step()
            elif ctype == "QUERY_BUTLER_STATE":
                self.query_logs.append({
                    "step": self.current_step,
                    "matrix_coercion": round(self.matrix_coercion, 4),
                    "avg_trouble": self.avg_trouble,
                    "matrix_state": self.matrix_state,
                    "unintelligible_count": sum(1 for s in self.subjects.values() if not s.is_intelligible),
                    "subjects": {sid: s.to_dict() for sid, s in sorted(self.subjects.items())}
                })

    def get_final_result(self) -> dict:
        return {
            "total_steps": self.current_step,
            "matrix_coercion": round(self.matrix_coercion, 4),
            "avg_trouble": self.avg_trouble,
            "matrix_state": self.matrix_state,
            "unintelligible_count": sum(1 for s in self.subjects.values() if not s.is_intelligible),
            "subjects": {sid: s.to_dict() for sid, s in sorted(self.subjects.items())},
            "query_logs": self.query_logs
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = ButlerPerformativityEngine(data.get("config", {}))
    engine.run_commands(data.get("commands", []))
    print(json.dumps(engine.get_final_result(), separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
