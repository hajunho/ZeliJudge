import sys
import os
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class ByungChulHanBurnoutEngine:
    def __init__(self, config: dict):
        self.config = copy.deepcopy(config)
        self.achievement_pressure = float(self.config.get("initial_achievement_pressure", 0.5))
        self.auto_exploitation = float(self.config.get("initial_auto_exploitation", 0.4))
        self.hyperactivity = float(self.config.get("initial_hyperactivity", 0.4))
        self.vita_contemplativa = float(self.config.get("initial_vita_contemplativa", 0.3))

        self.event_log = []
        self.history = []
        self.stats = {
            "projects_engaged": 0,
            "multitasking_events": 0,
            "boredom_practices": 0,
            "contemplation_sessions": 0,
            "max_burnout_index": 0.0,
            "burnout_epochs": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def calc_burnout_index(self) -> float:
        num = (self.achievement_pressure * 0.35 +
               self.auto_exploitation * 0.40 +
               self.hyperactivity * 0.25)
        denom = 1.0 + 0.8 * self.vita_contemplativa
        b_raw = num / denom
        b_idx = round(min(1.0, max(0.0, b_raw)), 4)
        if b_idx > self.stats["max_burnout_index"]:
            self.stats["max_burnout_index"] = b_idx
        return b_idx

    def calc_regime(self, b_idx: float) -> str:
        if b_idx >= 0.75:
            return "DEPRESSIVE_BURNOUT"
        elif b_idx >= 0.45:
            return "HYPERACTIVE_ACHIEVEMENT"
        else:
            return "SERENE_CONTEMPLATION"

    def engage_project(self, project_name: str, intensity: float, self_optimization_drive: float) -> dict:
        self.stats["projects_engaged"] += 1

        self.achievement_pressure = round(min(1.0, self.achievement_pressure + intensity * 0.12), 4)
        self.auto_exploitation = round(min(1.0, self.auto_exploitation + intensity * 0.15 + self_optimization_drive * 0.10), 4)
        self.hyperactivity = round(min(1.0, self.hyperactivity + intensity * 0.08), 4)
        self.vita_contemplativa = round(max(0.0, self.vita_contemplativa - intensity * 0.10), 4)

        b_idx = self.calc_burnout_index()
        regime = self.calc_regime(b_idx)
        if regime == "DEPRESSIVE_BURNOUT":
            self.stats["burnout_epochs"] += 1

        self.log(f"PROJECT_ENGAGED: '{project_name}' i={intensity} d={self_optimization_drive} -> B={b_idx} ({regime})")
        res = {
            "op": "ENGAGE_ACHIEVEMENT_PROJECT",
            "project_name": project_name,
            "achievement_pressure": self.achievement_pressure,
            "auto_exploitation": self.auto_exploitation,
            "hyperactivity": self.hyperactivity,
            "vita_contemplativa": self.vita_contemplativa,
            "burnout_index": b_idx,
            "regime": regime
        }
        self.history.append(res)
        return res

    def trigger_multitasking(self, task_count: int, notification_density: float) -> dict:
        self.stats["multitasking_events"] += 1

        h_spike = min(0.35, task_count * 0.04 + notification_density * 0.15)
        self.hyperactivity = round(min(1.0, self.hyperactivity + h_spike), 4)
        self.auto_exploitation = round(min(1.0, self.auto_exploitation + notification_density * 0.08), 4)
        self.vita_contemplativa = round(max(0.0, self.vita_contemplativa - 0.08), 4)

        b_idx = self.calc_burnout_index()
        regime = self.calc_regime(b_idx)
        if regime == "DEPRESSIVE_BURNOUT":
            self.stats["burnout_epochs"] += 1

        self.log(f"MULTITASKING_TRIGGERED: tasks={task_count} notif={notification_density} -> B={b_idx} ({regime})")
        res = {
            "op": "TRIGGER_HYPER_MULTITASKING",
            "task_count": task_count,
            "notification_density": notification_density,
            "hyperactivity": self.hyperactivity,
            "auto_exploitation": self.auto_exploitation,
            "vita_contemplativa": self.vita_contemplativa,
            "burnout_index": b_idx,
            "regime": regime
        }
        self.history.append(res)
        return res

    def practice_deep_boredom(self, duration_hours: float, digital_detox: bool) -> dict:
        self.stats["boredom_practices"] += 1

        detox_factor = 1.4 if digital_detox else 1.0
        v_boost = min(0.5, duration_hours * 0.08 * detox_factor)
        self.vita_contemplativa = round(min(1.0, self.vita_contemplativa + v_boost), 4)
        self.hyperactivity = round(max(0.0, self.hyperactivity - duration_hours * 0.10 * detox_factor), 4)
        self.achievement_pressure = round(max(0.0, self.achievement_pressure - duration_hours * 0.05), 4)

        b_idx = self.calc_burnout_index()
        regime = self.calc_regime(b_idx)

        self.log(f"PRACTICE_DEEP_BOREDOM: hours={duration_hours} detox={digital_detox} -> B={b_idx} ({regime})")
        res = {
            "op": "PRACTICE_DEEP_BOREDOM",
            "duration_hours": duration_hours,
            "digital_detox": digital_detox,
            "vita_contemplativa": self.vita_contemplativa,
            "hyperactivity": self.hyperactivity,
            "achievement_pressure": self.achievement_pressure,
            "burnout_index": b_idx,
            "regime": regime
        }
        self.history.append(res)
        return res

    def embrace_vita_contemplativa(self, meditation_depth: float) -> dict:
        self.stats["contemplation_sessions"] += 1

        self.vita_contemplativa = round(min(1.0, self.vita_contemplativa + meditation_depth * 0.25), 4)
        self.auto_exploitation = round(max(0.0, self.auto_exploitation - meditation_depth * 0.20), 4)
        self.achievement_pressure = round(max(0.0, self.achievement_pressure - meditation_depth * 0.15), 4)

        b_idx = self.calc_burnout_index()
        regime = self.calc_regime(b_idx)

        self.log(f"EMBRACE_VITA_CONTEMPLATIVA: depth={meditation_depth} -> B={b_idx} ({regime})")
        res = {
            "op": "EMBRACE_VITA_CONTEMPLATIVA",
            "meditation_depth": meditation_depth,
            "vita_contemplativa": self.vita_contemplativa,
            "auto_exploitation": self.auto_exploitation,
            "achievement_pressure": self.achievement_pressure,
            "burnout_index": b_idx,
            "regime": regime
        }
        self.history.append(res)
        return res

    def get_state(self) -> dict:
        b_idx = self.calc_burnout_index()
        regime = self.calc_regime(b_idx)
        return {
            "op": "GET_STATE",
            "achievement_pressure": self.achievement_pressure,
            "auto_exploitation": self.auto_exploitation,
            "hyperactivity": self.hyperactivity,
            "vita_contemplativa": self.vita_contemplativa,
            "burnout_index": b_idx,
            "regime": regime
        }

    def get_final_summary(self) -> dict:
        b_idx = self.calc_burnout_index()
        regime = self.calc_regime(b_idx)
        return {
            "achievement_pressure": self.achievement_pressure,
            "auto_exploitation": self.auto_exploitation,
            "hyperactivity": self.hyperactivity,
            "vita_contemplativa": self.vita_contemplativa,
            "burnout_index": b_idx,
            "regime": regime,
            "stats": self.stats,
            "event_count": len(self.event_log)
        }

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    eng = ByungChulHanBurnoutEngine(data["config"])
    results = []
    for op in data.get("operations", []):
        cmd = op["op"]
        if cmd == "ENGAGE_ACHIEVEMENT_PROJECT":
            res = eng.engage_project(
                project_name=op["project_name"],
                intensity=float(op.get("intensity", 0.5)),
                self_optimization_drive=float(op.get("self_optimization_drive", 0.5))
            )
            results.append(res)
        elif cmd == "TRIGGER_HYPER_MULTITASKING":
            res = eng.trigger_multitasking(
                task_count=int(op.get("task_count", 4)),
                notification_density=float(op.get("notification_density", 0.5))
            )
            results.append(res)
        elif cmd == "PRACTICE_DEEP_BOREDOM":
            res = eng.practice_deep_boredom(
                duration_hours=float(op.get("duration_hours", 2.0)),
                digital_detox=bool(op.get("digital_detox", False))
            )
            results.append(res)
        elif cmd == "EMBRACE_VITA_CONTEMPLATIVA":
            res = eng.embrace_vita_contemplativa(
                meditation_depth=float(op.get("meditation_depth", 0.5))
            )
            results.append(res)
        elif cmd == "GET_STATE":
            res = eng.get_state()
            results.append(res)

    output = {
        "results": results,
        "final_summary": eng.get_final_summary()
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    solve()
