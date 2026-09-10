import sys
import json
import copy

# Ensure UTF-8 I/O for Korean/multilingual text on Windows environments
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

class Subject:
    def __init__(self, subject_id: str, name: str, category: str, zoe: float, bios: float):
        self.subject_id = subject_id
        self.name = name
        self.category = category  # citizen, refugee, detainee, digital_user, outlaw
        self.zoe = float(zoe)     # 0.0 ~ 1.0 (biological bare survival)
        self.bios = float(bios)   # 0.0 ~ 1.0 (political/legal citizenship standing)
        self.ban_exposure = 0.0   # 0.0 ~ 1.0 (individual exposure to sovereign ban)
        self.is_homo_sacer = False
        self.is_killable = False
        self.is_sacrificable = True

    def calculate_hs(self, sovereign_ban: float) -> float:
        effective_ban = min(1.0, max(self.ban_exposure, sovereign_ban))
        hs = self.zoe * (1.0 - self.bios) * effective_ban
        self.is_homo_sacer = (hs >= 0.60)
        if self.is_homo_sacer:
            self.is_killable = True       # May be killed with impunity (살해 가능성)
            self.is_sacrificable = False  # Excluded from sacred sacrificial rituals (희생 불가능성)
        else:
            self.is_killable = False
            self.is_sacrificable = (self.bios >= 0.50)
        return round(hs, 4)

    def to_dict(self, sovereign_ban: float) -> dict:
        hs = self.calculate_hs(sovereign_ban)
        return {
            "subject_id": self.subject_id,
            "name": self.name,
            "category": self.category,
            "zoe": round(self.zoe, 4),
            "bios": round(self.bios, 4),
            "homo_sacer_index": hs,
            "is_homo_sacer": self.is_homo_sacer,
            "is_killable": self.is_killable,
            "is_sacrificable": self.is_sacrificable
        }

class HomoSacerEngine:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.state_of_exception = float(config.get("state_of_exception", 0.30))
        self.sovereign_ban = float(config.get("sovereign_ban", 0.40))
        self.nomos_state = "CONSTITUTIONAL_STATE"
        
        self.subjects = {}
        for s_cfg in config.get("subjects", []):
            s = Subject(
                subject_id=s_cfg["subject_id"],
                name=s_cfg["name"],
                category=s_cfg.get("category", "citizen"),
                zoe=s_cfg.get("zoe", 1.0),
                bios=s_cfg.get("bios", 0.8)
            )
            self.subjects[s.subject_id] = s

        self.current_step = 0
        self.camp_index = 0.0
        self.form_of_life_index = 0.0
        self.query_logs = []
        self._evaluate()

    def _evaluate(self):
        if not self.subjects:
            self.camp_index = 0.0
            return

        hs_sum = sum(s.calculate_hs(self.sovereign_ban) for s in self.subjects.values())
        avg_hs = hs_sum / len(self.subjects)
        self.camp_index = round(min(1.0, max(0.0, self.state_of_exception * 0.5 + avg_hs * 0.5)), 4)

        if self.camp_index >= 0.65:
            self.nomos_state = "THE_CAMP_PERMANENT_EXCEPTION"
        elif self.camp_index >= 0.35:
            self.nomos_state = "HYBRID_BIO_SECURITY_ZONE"
        else:
            self.nomos_state = "CONSTITUTIONAL_RULE_OF_LAW"

    def declare_exception(self, intensity: float):
        self.state_of_exception = min(1.0, max(0.0, self.state_of_exception + float(intensity)))
        self.sovereign_ban = min(1.0, max(0.0, self.sovereign_ban + float(intensity) * 0.8))
        for s in self.subjects.values():
            s.bios = max(0.0, s.bios - float(intensity) * 0.3)
        self._evaluate()

    def impose_ban(self, subject_id: str, ban_level: float):
        if subject_id in self.subjects:
            s = self.subjects[subject_id]
            s.ban_exposure = min(1.0, s.ban_exposure + float(ban_level))
            s.bios = max(0.0, s.bios - float(ban_level) * 0.7)
            self._evaluate()

    def strip_rights(self, subject_id: str, bios_reduction: float):
        if subject_id in self.subjects:
            s = self.subjects[subject_id]
            s.bios = max(0.0, s.bios - float(bios_reduction))
            self._evaluate()

    def inoperative_commons(self, emancipation_effort: float):
        eff = float(emancipation_effort)
        self.form_of_life_index = min(1.0, self.form_of_life_index + eff)
        self.sovereign_ban = max(0.0, self.sovereign_ban - eff * 0.7)
        self.state_of_exception = max(0.0, self.state_of_exception - eff * 0.6)
        for s in self.subjects.values():
            s.ban_exposure = max(0.0, s.ban_exposure - eff)
            s.bios = min(1.0, s.bios + eff * 0.5)
        self._evaluate()

    def step(self):
        self.current_step += 1
        self._evaluate()

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "DECLARE_EXCEPTION":
                self.declare_exception(cmd["intensity"])
            elif ctype == "IMPOSE_BAN":
                self.impose_ban(cmd["subject_id"], cmd["ban_level"])
            elif ctype == "STRIP_RIGHTS":
                self.strip_rights(cmd["subject_id"], cmd["bios_reduction"])
            elif ctype == "INOPERATIVE_COMMONS":
                self.inoperative_commons(cmd["emancipation_effort"])
            elif ctype == "STEP":
                self.step()
            elif ctype == "QUERY_HOMO_SACER":
                self.query_logs.append({
                    "step": self.current_step,
                    "camp_index": self.camp_index,
                    "nomos_state": self.nomos_state,
                    "homo_sacer_count": sum(1 for s in self.subjects.values() if s.is_homo_sacer),
                    "subjects": {sid: s.to_dict(self.sovereign_ban) for sid, s in sorted(self.subjects.items())}
                })

    def get_final_result(self) -> dict:
        return {
            "total_steps": self.current_step,
            "state_of_exception": round(self.state_of_exception, 4),
            "sovereign_ban": round(self.sovereign_ban, 4),
            "camp_index": self.camp_index,
            "nomos_state": self.nomos_state,
            "form_of_life_index": round(self.form_of_life_index, 4),
            "homo_sacer_count": sum(1 for s in self.subjects.values() if s.is_homo_sacer),
            "subjects": {sid: s.to_dict(self.sovereign_ban) for sid, s in sorted(self.subjects.items())},
            "query_logs": self.query_logs
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = HomoSacerEngine(data.get("config", {}))
    engine.run_commands(data.get("commands", []))
    print(json.dumps(engine.get_final_result(), separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
