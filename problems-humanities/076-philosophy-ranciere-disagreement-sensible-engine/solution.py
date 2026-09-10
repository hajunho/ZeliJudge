import sys
import json
import copy

# Ensure UTF-8 I/O for Korean/multilingual text on Windows environments
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

class Subject:
    def __init__(self, subject_id: str, name: str, category: str, capacity: float, assigned_part: float):
        self.subject_id = subject_id
        self.name = name
        self.category = category  # elite, recognized_citizen, sans_part (몫 없는 자)
        self.capacity = float(capacity)  # inherent equality/capacity (0.0 ~ 1.0)
        self.assigned_part = float(assigned_part)  # recognized share in police order (0.0 ~ 1.0)
        self.visibility = 0.8 if self.assigned_part >= 0.5 else 0.15
        self.audibility = 0.8 if self.assigned_part >= 0.5 else 0.15
        self.speech_ratio = 0.9 if self.assigned_part >= 0.5 else 0.10  # logos vs noise
        self.is_sans_part = (self.assigned_part < 0.25)
        self.is_speech = (self.speech_ratio >= 0.50)
        self.is_noise = not self.is_speech
        self.disagreement_index = 0.0

    def evaluate(self, police_saturation: float):
        self.is_sans_part = (self.assigned_part < 0.25)
        if self.is_sans_part and police_saturation > 0.3:
            suppression = (police_saturation - 0.3) * 0.4
            self.speech_ratio = max(0.0, min(1.0, self.speech_ratio - suppression * 0.5))
            self.visibility = max(0.0, min(1.0, self.visibility - suppression * 0.4))
            self.audibility = max(0.0, min(1.0, self.audibility - suppression * 0.4))

        self.is_speech = (self.speech_ratio >= 0.50)
        self.is_noise = not self.is_speech

        gap = max(0.0, self.capacity - self.assigned_part)
        d_val = gap * (1.0 - self.speech_ratio * 0.6) * (1.0 - self.visibility * self.audibility * 0.5)
        self.disagreement_index = round(min(1.0, max(0.0, d_val)), 4)

    def to_dict(self) -> dict:
        return {
            "subject_id": self.subject_id,
            "name": self.name,
            "category": self.category,
            "capacity": round(self.capacity, 4),
            "assigned_part": round(self.assigned_part, 4),
            "visibility": round(self.visibility, 4),
            "audibility": round(self.audibility, 4),
            "speech_ratio": round(self.speech_ratio, 4),
            "is_sans_part": self.is_sans_part,
            "is_speech": self.is_speech,
            "is_noise": self.is_noise,
            "disagreement_index": self.disagreement_index
        }

class RanciereDisagreementEngine:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.police_saturation = float(config.get("police_saturation", 0.50))
        self.subjects = {}
        for s_cfg in config.get("subjects", []):
            s = Subject(
                subject_id=s_cfg["subject_id"],
                name=s_cfg["name"],
                category=s_cfg.get("category", "sans_part"),
                capacity=s_cfg.get("capacity", 1.0),
                assigned_part=s_cfg.get("assigned_part", 0.1)
            )
            self.subjects[s.subject_id] = s

        self.current_step = 0
        self.avg_disagreement = 0.0
        self.dissensus_level = 0.0
        self.regime = "OLIGARCHIC_POLICE_ORDER"
        self.query_logs = []
        self._evaluate()

    def _evaluate(self):
        if not self.subjects:
            self.avg_disagreement = 0.0
            self.dissensus_level = 0.0
            self.regime = "OLIGARCHIC_POLICE_ORDER"
            return

        for s in self.subjects.values():
            s.evaluate(self.police_saturation)

        total_d = sum(s.disagreement_index for s in self.subjects.values())
        self.avg_disagreement = round(total_d / len(self.subjects), 4)

        sans_part_speech = [s for s in self.subjects.values() if s.is_sans_part and s.is_speech]
        if sans_part_speech:
            speech_power = sum(s.speech_ratio * s.visibility for s in sans_part_speech) / len(sans_part_speech)
            self.dissensus_level = round(min(1.0, speech_power * (1.0 - self.police_saturation * 0.4)), 4)
        else:
            self.dissensus_level = 0.0

        if self.dissensus_level >= 0.40:
            self.regime = "DEMOCRATIC_DISSENSUS"
        elif self.police_saturation >= 0.70 and self.dissensus_level < 0.15:
            self.regime = "CONSENSUS_POST_POLITICS"
        else:
            self.regime = "OLIGARCHIC_POLICE_ORDER"

    def police_enforcement(self, intensity: float):
        self.police_saturation = min(1.0, max(0.0, self.police_saturation + float(intensity)))
        self._evaluate()

    def verify_equality(self, subject_id: str, effort: float):
        eff = float(effort)
        if subject_id in self.subjects:
            s = self.subjects[subject_id]
            s.speech_ratio = min(1.0, s.speech_ratio + eff * 0.8)
            s.visibility = min(1.0, s.visibility + eff * 0.6)
            s.audibility = min(1.0, s.audibility + eff * 0.7)
            self.police_saturation = max(0.0, self.police_saturation - eff * 0.25)
            self._evaluate()

    def repartition_shares(self, subject_id: str, share_delta: float):
        if subject_id in self.subjects:
            s = self.subjects[subject_id]
            s.assigned_part = min(1.0, max(0.0, s.assigned_part + float(share_delta)))
            self._evaluate()

    def step(self):
        self.current_step += 1
        self._evaluate()

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "POLICE_ENFORCEMENT":
                self.police_enforcement(cmd["intensity"])
            elif ctype == "VERIFY_EQUALITY":
                self.verify_equality(cmd["subject_id"], cmd["effort"])
            elif ctype == "REPARTITION_SHARES":
                self.repartition_shares(cmd["subject_id"], cmd["share_delta"])
            elif ctype == "STEP":
                self.step()
            elif ctype == "QUERY_DISAGREEMENT":
                self.query_logs.append({
                    "step": self.current_step,
                    "police_saturation": round(self.police_saturation, 4),
                    "avg_disagreement": self.avg_disagreement,
                    "dissensus_level": self.dissensus_level,
                    "regime": self.regime,
                    "subjects": {sid: s.to_dict() for sid, s in sorted(self.subjects.items())}
                })

    def get_final_result(self) -> dict:
        return {
            "total_steps": self.current_step,
            "police_saturation": round(self.police_saturation, 4),
            "avg_disagreement": self.avg_disagreement,
            "dissensus_level": self.dissensus_level,
            "regime": self.regime,
            "subjects": {sid: s.to_dict() for sid, s in sorted(self.subjects.items())},
            "query_logs": self.query_logs
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = RanciereDisagreementEngine(data.get("config", {}))
    engine.run_commands(data.get("commands", []))
    print(json.dumps(engine.get_final_result(), separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
