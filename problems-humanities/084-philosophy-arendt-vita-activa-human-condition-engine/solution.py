import sys
import json

# Windows 콘솔 UTF-8 입출력 호환성 보장
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def round4(val: float) -> float:
    return round(val, 4)

def clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))

class ArendtVitaActivaEngine:
    def __init__(self, config: dict):
        self.polity_id = config.get("polity_id", "polity_01")
        self.labor = float(config.get("labor_metabolism_load", 0.5))
        self.work = float(config.get("work_fabrication_durability", 0.5))
        self.action = float(config.get("action_plurality_engagement", 0.5))
        self.forgiveness = float(config.get("forgiveness_capacity", 0.5))
        self.promising = float(config.get("promising_fidelity", 0.5))

    def compute_metrics(self):
        # 1. Animal Laborans Index (ALI)
        raw_ali = self.labor * 0.7 + (1.0 - self.action) * 0.3 - 0.2 * self.work
        ali = clamp(raw_ali)

        # 2. Public Realm Openness (PRO)
        raw_pro = self.action * 0.6 + self.work * 0.2 + self.promising * 0.2 * (1.0 - 0.5 * self.labor)
        pro = clamp(raw_pro)

        # 3. Natality Index (NI)
        raw_ni = self.action * 0.5 + self.forgiveness * 0.25 + self.promising * 0.25
        ni = clamp(raw_ni)

        # 4. Vita Activa Health (VAH)
        raw_vah = 0.4 * pro + 0.4 * ni + 0.2 * (1.0 - ali)
        vah = clamp(raw_vah)

        # State transition priority
        if ali >= 0.70 and pro < 0.35:
            state = "ANIMAL_LABORANS_DOMINANCE"
        elif pro >= 0.70 and ni >= 0.70 and vah >= 0.70:
            state = "POLITICAL_POLIS_FLOURISHING"
        elif self.work >= 0.65 and self.action < 0.40:
            state = "HOMO_FABER_INSTRUMENTALITY"
        else:
            state = "CONVENTIONAL_VITA_ACTIVA"

        return {
            "animal_laborans_index": round4(ali),
            "public_realm_openness": round4(pro),
            "natality_index": round4(ni),
            "vita_activa_health": round4(vah),
            "vita_activa_state": state
        }

    def process_step(self, action_item: dict):
        act_type = action_item.get("type")
        intensity = float(action_item.get("intensity", 0.5))

        if act_type == "BIOLOGICAL_CONSUMPTION_CYCLE":
            self.labor = clamp(self.labor + 0.18 * intensity)
            self.action = clamp(self.action - 0.15 * intensity)
            self.forgiveness = clamp(self.forgiveness - 0.10 * intensity)

        elif act_type == "WORLD_FABRICATION":
            self.work = clamp(self.work + 0.20 * intensity)
            self.promising = clamp(self.promising + 0.10 * intensity)
            self.labor = clamp(self.labor - 0.08 * intensity)

        elif act_type == "POLITICAL_SPEECH_AND_ACTION":
            self.action = clamp(self.action + 0.22 * intensity)
            self.promising = clamp(self.promising + 0.12 * intensity)
            self.labor = clamp(self.labor - 0.12 * intensity)

        elif act_type == "MUTUAL_FORGIVENESS_AND_PROMISE":
            self.forgiveness = clamp(self.forgiveness + 0.25 * intensity)
            self.promising = clamp(self.promising + 0.20 * intensity)
            self.action = clamp(self.action + 0.10 * intensity)

        return self.compute_metrics()

    def run_simulation(self, actions: list) -> dict:
        initial = self.compute_metrics()
        timeline = []
        for act in actions:
            res = self.process_step(act)
            timeline.append({
                "action": act.get("type"),
                "state": res["vita_activa_state"],
                "ali": res["animal_laborans_index"],
                "pro": res["public_realm_openness"],
                "ni": res["natality_index"],
                "vah": res["vita_activa_health"]
            })
        final = self.compute_metrics()

        return {
            "polity_id": self.polity_id,
            "initial_state": initial,
            "final_state": final,
            "timeline": timeline,
            "parameters": {
                "labor": round4(self.labor),
                "work": round4(self.work),
                "action": round4(self.action),
                "forgiveness": round4(self.forgiveness),
                "promising": round4(self.promising)
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    engine = ArendtVitaActivaEngine(data.get("config", {}))
    result = engine.run_simulation(data.get("actions", []))

    print(json.dumps(result, separators=(',', ':')))

if __name__ == "__main__":
    main()
