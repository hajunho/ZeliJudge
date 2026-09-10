import sys
import math
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class SisyphusEngine:
    def __init__(self, config):
        self.mass = config.get("boulder_mass", 100.0)
        self.gravity = config.get("gravity", 9.8)
        self.peak_height = config.get("peak_height", 50.0)
        self.total_cycles = 0
        self.total_work_done = 0.0
        self.lucid_moments_count = 0

    def evaluate_subject(self, params):
        desire = params["desire_for_meaning"]   # D in [0, 1]
        silence = params["world_silence"]       # S in [0, 1]
        lucidity = params["lucidity"]           # Lambda in [0, 1]
        hope = params["hope_escapism"]          # H in [0, 1]
        vitality = params.get("vitality", 0.5)  # V in [0, 1]
        experiences = params.get("experiences_count", 1)

        # 1. Absurdity Index
        raw_a = lucidity * math.sqrt(desire * silence) * (1.0 - 0.5 * hope)
        absurd_index = round(min(1.0, max(0.0, raw_a)), 4)

        # 2. Classification of Stance
        if hope >= 0.50:
            stance = "PHILOSOPHICAL_SUICIDE"
            verdict = "도약(Leap of Faith)에 의한 지성의 희생 및 형이상학적 현실 도피"
            revolt = 0.0
            freedom = round((1.0 - hope) * (1.0 - desire * 0.5), 4)
            passion = round(0.1 * vitality, 4)
            is_happy = False
        elif vitality < 0.20 and absurd_index > 0.55:
            stance = "PHYSICAL_SUICIDE"
            verdict = "부조리의 무게를 견디지 못하고 의식을 소멸시키는 육체적 자살 (패배 및 굴복)"
            revolt = 0.0
            freedom = 0.0
            passion = 0.0
            is_happy = False
        else:
            stance = "ABSURD_REVOLT"
            verdict = "부조리를 직시하며 희망 없이 삶의 조건을 긍정하는 항거(La Revolte)"
            revolt = round(min(1.0, lucidity * (1.0 - hope) * (1.0 + 0.5 * absurd_index)), 4)
            freedom = round(min(1.0, (1.0 - hope) * (0.5 * lucidity + 0.5 * (1.0 - desire * 0.5))), 4)
            exp_factor = min(2.0, 1.0 + math.log1p(experiences) * 0.2)
            passion = round(min(1.0, absurd_index * lucidity * exp_factor), 4)
            is_happy = (revolt >= 0.40 and lucidity >= 0.50 and stance == "ABSURD_REVOLT")

        return {
            "absurd_index": absurd_index,
            "stance": stance,
            "revolt": revolt,
            "freedom": freedom,
            "passion": passion,
            "verdict": verdict,
            "sisyphus_happy": is_happy
        }

    def simulate_boulder_cycle(self, params):
        cycles = params.get("cycles", 1)
        lucidity = params.get("lucidity", 0.8)
        desire = params.get("desire_for_meaning", 0.8)
        hope = params.get("hope_escapism", 0.1)

        cycle_results = []
        for i in range(1, cycles + 1):
            work = self.mass * self.gravity * self.peak_height
            self.total_cycles += 1
            self.total_work_done += work

            defiance = round(lucidity * (1.0 - hope), 4)
            triumph = round(min(1.0, defiance * (1.0 + 0.1 * math.log(i + 1))), 4)
            if triumph >= 0.5:
                self.lucid_moments_count += 1

            cycle_results.append({
                "cycle": self.total_cycles,
                "work_joules": round(work, 2),
                "peak_reached": True,
                "descent_consciousness": {
                    "lucidity": lucidity,
                    "defiance": defiance,
                    "triumph_index": triumph,
                    "fate_mastered": triumph >= 0.6
                }
            })

        return {
            "completed_cycles": cycles,
            "total_cycles_so_far": self.total_cycles,
            "total_work_joules": round(self.total_work_done, 2),
            "lucid_moments_count": self.lucid_moments_count,
            "recent_cycle": cycle_results[-1] if cycle_results else None
        }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = SisyphusEngine(data.get("config", {}))
    results = []
    for op in data.get("operations", []):
        name = op["op"]
        if name == "EVALUATE_SUBJECT":
            results.append(engine.evaluate_subject(op["params"]))
        elif name == "SIMULATE_BOULDER_CYCLE":
            results.append(engine.simulate_boulder_cycle(op["params"]))
        elif name == "GET_ENGINE_STATS":
            results.append({
                "total_cycles": engine.total_cycles,
                "total_work_joules": round(engine.total_work_done, 2),
                "lucid_moments_count": engine.lucid_moments_count
            })
        else:
            raise ValueError(f"Unknown op: {name}")

    print(json.dumps(results, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
