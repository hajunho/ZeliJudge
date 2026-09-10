import sys
import os
import json

class DebordSpectacleEngine:
    def __init__(self, config: dict):
        self.mode = config.get("initial_mode", "DIFFUSE")
        self.being = float(config.get("initial_being", 0.4))
        self.having = float(config.get("initial_having", 0.4))
        self.appearing = float(config.get("initial_appearing", 0.2))
        self.media_amplification = float(config.get("media_amplification", 0.5))

        self.event_log = []
        self.history = []
        self.stats = {
            "operations_count": 0,
            "detournement_count": 0,
            "derive_count": 0,
            "alienation_count": 0,
            "max_spectacle_index": 0.0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def calc_spectacle_index(self) -> float:
        total = max(0.0001, self.being + self.having + self.appearing)
        ratio = self.appearing / total

        mode_factor = 1.0
        if self.mode == "CONCENTRATED":
            mode_factor = 1.10
        elif self.mode == "DIFFUSE":
            mode_factor = 1.00
        elif self.mode == "INTEGRATED":
            mode_factor = 1.25

        raw_s = ratio * (1.0 + 0.4 * self.media_amplification) * mode_factor
        s_idx = round(min(1.0, max(0.0, raw_s)), 4)
        if s_idx > self.stats["max_spectacle_index"]:
            self.stats["max_spectacle_index"] = s_idx
        return s_idx

    def calc_state(self, s_idx: float) -> str:
        if s_idx >= 0.75:
            return "TOTAL_SPECTACULAR_ALIENATION"
        elif s_idx >= 0.45:
            return "DIFFUSE_COMMODITY_FETISHISM"
        else:
            return "SITUATIONIST_EMANCIPATION"

    def broadcast_spectacle(self, spectacle_type: str, intensity: float, commodity_fetish: float) -> dict:
        self.stats["operations_count"] += 1

        shift_to_having = round(min(self.being, intensity * 0.10), 4)
        self.being = round(self.being - shift_to_having, 4)
        self.having = round(self.having + shift_to_having, 4)

        shift_to_appearing = round(min(self.having, intensity * 0.15 + commodity_fetish * 0.10), 4)
        self.having = round(self.having - shift_to_appearing, 4)
        self.appearing = round(self.appearing + shift_to_appearing, 4)

        self.mode = spectacle_type
        s_idx = self.calc_spectacle_index()
        state = self.calc_state(s_idx)

        if state == "TOTAL_SPECTACULAR_ALIENATION":
            self.stats["alienation_count"] += 1

        self.log(f"BROADCAST_SPECTACLE type={spectacle_type} intensity={intensity} S={s_idx} state={state}")
        res = {
            "op": "BROADCAST_SPECTACLE",
            "type": spectacle_type,
            "being": round(self.being, 4),
            "having": round(self.having, 4),
            "appearing": round(self.appearing, 4),
            "spectacle_index": s_idx,
            "state": state
        }
        self.history.append(res)
        return res

    def apply_detournement(self, target_image: str, subversive_power: float) -> dict:
        self.stats["operations_count"] += 1
        self.stats["detournement_count"] += 1

        reclaimed = round(min(self.appearing, subversive_power * 0.20), 4)
        self.appearing = round(self.appearing - reclaimed, 4)
        self.being = round(self.being + reclaimed, 4)

        s_idx = self.calc_spectacle_index()
        state = self.calc_state(s_idx)

        self.log(f"DETOURNEMENT target={target_image} power={subversive_power} reclaimed={reclaimed} S={s_idx}")
        res = {
            "op": "APPLY_DETOURNEMENT",
            "target": target_image,
            "reclaimed": reclaimed,
            "being": round(self.being, 4),
            "appearing": round(self.appearing, 4),
            "spectacle_index": s_idx,
            "state": state
        }
        self.history.append(res)
        return res

    def perform_derive(self, duration_hours: float, spontaneous_events: int) -> dict:
        self.stats["operations_count"] += 1
        self.stats["derive_count"] += 1

        gain_being = round(min(0.3, duration_hours * 0.03 + spontaneous_events * 0.04), 4)
        having_reduction = round(min(self.having, gain_being * 0.5), 4)
        self.having = round(self.having - having_reduction, 4)
        self.being = round(self.being + gain_being, 4)

        s_idx = self.calc_spectacle_index()
        state = self.calc_state(s_idx)

        self.log(f"DERIVE duration={duration_hours} spontaneous={spontaneous_events} gain_being={gain_being} S={s_idx}")
        res = {
            "op": "PERFORM_DERIVE",
            "duration_hours": duration_hours,
            "gain_being": gain_being,
            "being": round(self.being, 4),
            "spectacle_index": s_idx,
            "state": state
        }
        self.history.append(res)
        return res

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = DebordSpectacleEngine(config)

    for op_info in operations:
        op = op_info.get("op")
        if op == "BROADCAST_SPECTACLE":
            stype = op_info.get("type", "DIFFUSE")
            intensity = op_info.get("intensity", 1.0)
            cf = op_info.get("commodity_fetish", 0.5)
            engine.broadcast_spectacle(stype, intensity, cf)
        elif op == "APPLY_DETOURNEMENT":
            target = op_info.get("target_image", "ad_billboard")
            power = op_info.get("subversive_power", 1.0)
            engine.apply_detournement(target, power)
        elif op == "PERFORM_DERIVE":
            dur = op_info.get("duration_hours", 2.0)
            spont = op_info.get("spontaneous_events", 1)
            engine.perform_derive(dur, spont)

    final_s = engine.calc_spectacle_index()
    final_state = engine.calc_state(final_s)

    return {
        "stats": engine.stats,
        "final_ontology": {
            "being": round(engine.being, 4),
            "having": round(engine.having, 4),
            "appearing": round(engine.appearing, 4),
            "spectacle_index": final_s,
            "state": final_state,
            "mode": engine.mode
        },
        "history": engine.history,
        "event_log": engine.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
