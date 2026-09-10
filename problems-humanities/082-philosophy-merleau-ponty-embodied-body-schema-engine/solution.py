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

class MerleauPontyEngine:
    def __init__(self, config: dict):
        self.subject_id = config.get("subject_id", "subject_01")
        self.alpha = float(config.get("sensory_motor_coupling", 0.5))
        self.beta = float(config.get("habitual_sedimentation", 0.5))
        self.motor_intentionality = float(config.get("motor_intentionality", 0.5))
        self.affordance = float(config.get("environmental_affordance", 0.5))
        self.spatial_situatedness = float(config.get("spatial_situatedness", 0.5))

    def compute_metrics(self):
        # 1. Intentional Arc Index (IAI)
        raw_iai = self.alpha * self.motor_intentionality * ((1.0 + self.beta) / 2.0) + 0.1 * self.spatial_situatedness
        iai = clamp(raw_iai, 0.0, 1.0)

        # 2. Optimum Grip Score (OGS)
        diff = abs(self.motor_intentionality * self.alpha - self.affordance)
        raw_ogs = 1.0 - diff * (1.0 - 0.4 * self.beta)
        ogs = clamp(raw_ogs, 0.0, 1.0)

        # 3. Lived Body Index (LBI)
        lbi = clamp(0.5 * iai + 0.5 * ogs, 0.0, 1.0)

        # 4. Cartesian Alienation Index (CAI)
        cai = clamp(1.0 - lbi, 0.0, 1.0)

        # State transition priority
        if iai < 0.35 or self.motor_intentionality < 0.30:
            state = "INTENTIONAL_ARC_RUPTURE"
        elif lbi >= 0.75 and ogs >= 0.70:
            state = "OPTIMUM_EMBODIED_GRIP"
        elif lbi >= 0.50:
            state = "PRE_REFLECTIVE_ACTION"
        else:
            state = "CARTESIAN_DISCORD"

        return {
            "intentional_arc_index": round4(iai),
            "optimum_grip_score": round4(ogs),
            "lived_body_index": round4(lbi),
            "cartesian_alienation_index": round4(cai),
            "embodied_state": state
        }

    def process_step(self, action: dict):
        act_type = action.get("type")
        intensity = float(action.get("intensity", 0.5))

        if act_type == "PERCEPTUAL_EXPLORATION":
            target_affordance = float(action.get("target_affordance", self.affordance))
            target_spatial = float(action.get("target_spatial", self.spatial_situatedness))
            self.affordance = clamp(self.affordance + (target_affordance - self.affordance) * intensity * 0.5)
            self.spatial_situatedness = clamp(self.spatial_situatedness + (target_spatial - self.spatial_situatedness) * intensity * 0.5)
            self.alpha = clamp(self.alpha + 0.05 * intensity)

        elif act_type == "MOTOR_HABIT_PRACTICE":
            self.beta = clamp(self.beta + 0.15 * intensity)
            self.motor_intentionality = clamp(self.motor_intentionality + 0.12 * intensity)
            self.alpha = clamp(self.alpha + 0.08 * intensity)

        elif act_type == "ENVIRONMENTAL_DISTURBANCE":
            severity = float(action.get("severity", 0.5))
            self.motor_intentionality = clamp(self.motor_intentionality - 0.25 * severity)
            self.alpha = clamp(self.alpha - 0.20 * severity)
            self.spatial_situatedness = clamp(self.spatial_situatedness - 0.15 * severity)

        elif act_type == "PHENOMENOLOGICAL_REDUCTION":
            calm_factor = float(action.get("calm_factor", 0.5))
            self.alpha = clamp(self.alpha + 0.15 * calm_factor)
            self.motor_intentionality = clamp(self.motor_intentionality + 0.10 * calm_factor)
            self.beta = clamp(self.beta + 0.05 * calm_factor)

        return self.compute_metrics()

    def run_simulation(self, actions: list) -> dict:
        initial = self.compute_metrics()
        timeline = []
        for act in actions:
            res = self.process_step(act)
            timeline.append({
                "action": act.get("type"),
                "state": res["embodied_state"],
                "lbi": res["lived_body_index"],
                "iai": res["intentional_arc_index"],
                "ogs": res["optimum_grip_score"]
            })
        final = self.compute_metrics()

        return {
            "subject_id": self.subject_id,
            "initial_state": initial,
            "final_state": final,
            "timeline": timeline,
            "parameters": {
                "alpha": round4(self.alpha),
                "beta": round4(self.beta),
                "motor_intentionality": round4(self.motor_intentionality),
                "environmental_affordance": round4(self.affordance),
                "spatial_situatedness": round4(self.spatial_situatedness)
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    engine = MerleauPontyEngine(data.get("config", {}))
    result = engine.run_simulation(data.get("actions", []))

    print(json.dumps(result, separators=(',', ':')))

if __name__ == "__main__":
    main()
