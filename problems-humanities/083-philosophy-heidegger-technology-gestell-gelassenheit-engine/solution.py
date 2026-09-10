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

class HeideggerTechnologyEngine:
    def __init__(self, config: dict):
        self.system_id = config.get("system_id", "system_01")
        self.calculative_drive = float(config.get("calculative_drive", 0.5))
        self.standing_reserve_pressure = float(config.get("standing_reserve_pressure", 0.5))
        self.meditative_capacity = float(config.get("meditative_capacity", 0.5))
        self.poetic_attunement = float(config.get("poetic_attunement", 0.5))
        self.openness_to_mystery = float(config.get("openness_to_mystery", 0.5))

    def compute_metrics(self):
        # 1. Gestell Index (GI)
        raw_gi = self.calculative_drive * 0.6 + self.standing_reserve_pressure * 0.4 - 0.2 * self.meditative_capacity
        gi = clamp(raw_gi)

        # 2. Standing Reserve Score (SRS)
        raw_srs = self.standing_reserve_pressure * ((1.0 + self.calculative_drive) / 2.0) - 0.25 * self.poetic_attunement
        srs = clamp(raw_srs)

        # 3. Gelassenheit Score (GS)
        raw_gs = (self.meditative_capacity * 0.5 +
                  self.openness_to_mystery * 0.3 +
                  self.poetic_attunement * 0.2 * (1.0 - 0.5 * gi))
        gs = clamp(raw_gs)

        # 4. Saving Power Index (SPI)
        spi = clamp(0.5 * gs + 0.5 * self.openness_to_mystery)

        # Regime determination priority
        if gi >= 0.75 and srs >= 0.70:
            regime = "GESTELL_TOTALITARIANISM"
        elif self.poetic_attunement >= 0.70 and self.openness_to_mystery >= 0.70 and gi < 0.40:
            regime = "POETIC_DWELLING"
        elif gs >= 0.65 and spi >= 0.60:
            regime = "GELASSENHEIT_RELEASEMENT"
        else:
            regime = "CALCULATIVE_DOMINANCE"

        return {
            "gestell_index": round4(gi),
            "standing_reserve_score": round4(srs),
            "gelassenheit_score": round4(gs),
            "saving_power_index": round4(spi),
            "existential_regime": regime
        }

    def process_step(self, action: dict):
        act_type = action.get("type")
        intensity = float(action.get("intensity", 0.5))

        if act_type == "RESOURCE_OPTIMIZATION":
            self.calculative_drive = clamp(self.calculative_drive + 0.15 * intensity)
            self.standing_reserve_pressure = clamp(self.standing_reserve_pressure + 0.18 * intensity)
            self.poetic_attunement = clamp(self.poetic_attunement - 0.10 * intensity)

        elif act_type == "MEDITATIVE_PAUSE":
            self.meditative_capacity = clamp(self.meditative_capacity + 0.20 * intensity)
            self.calculative_drive = clamp(self.calculative_drive - 0.12 * intensity)
            self.openness_to_mystery = clamp(self.openness_to_mystery + 0.10 * intensity)

        elif act_type == "POETIC_CREATION":
            self.poetic_attunement = clamp(self.poetic_attunement + 0.22 * intensity)
            self.openness_to_mystery = clamp(self.openness_to_mystery + 0.15 * intensity)
            self.standing_reserve_pressure = clamp(self.standing_reserve_pressure - 0.12 * intensity)

        elif act_type == "RADICAL_RELEASEMENT":
            self.openness_to_mystery = clamp(self.openness_to_mystery + 0.25 * intensity)
            self.meditative_capacity = clamp(self.meditative_capacity + 0.15 * intensity)
            self.standing_reserve_pressure = clamp(self.standing_reserve_pressure - 0.20 * intensity)
            self.calculative_drive = clamp(self.calculative_drive - 0.18 * intensity)

        return self.compute_metrics()

    def run_simulation(self, actions: list) -> dict:
        initial = self.compute_metrics()
        timeline = []
        for act in actions:
            res = self.process_step(act)
            timeline.append({
                "action": act.get("type"),
                "regime": res["existential_regime"],
                "gi": res["gestell_index"],
                "srs": res["standing_reserve_score"],
                "gs": res["gelassenheit_score"]
            })
        final = self.compute_metrics()

        return {
            "system_id": self.system_id,
            "initial_state": initial,
            "final_state": final,
            "timeline": timeline,
            "parameters": {
                "calculative_drive": round4(self.calculative_drive),
                "standing_reserve_pressure": round4(self.standing_reserve_pressure),
                "meditative_capacity": round4(self.meditative_capacity),
                "poetic_attunement": round4(self.poetic_attunement),
                "openness_to_mystery": round4(self.openness_to_mystery)
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    engine = HeideggerTechnologyEngine(data.get("config", {}))
    result = engine.run_simulation(data.get("actions", []))

    print(json.dumps(result, separators=(',', ':')))

if __name__ == "__main__":
    main()
