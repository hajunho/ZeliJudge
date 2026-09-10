import sys
import math
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ART_POWER = {
    "MUSIC": 1.0,
    "TRAGEDY": 0.8,
    "POETRY": 0.7,
    "PAINTING": 0.6,
    "SCULPTURE": 0.5,
    "ARCHITECTURE": 0.4
}

class SchopenhauerEngine:
    def __init__(self, config):
        self.default_art = config.get("default_art", "MUSIC")

    def evaluate_subject(self, params):
        will = params["will_intensity"]
        fulfillment = params["fulfillment_ratio"]
        maya = params.get("maya_illusion", 0.8)
        alpha = params.get("aesthetic_attunement", 0.5)
        beta = params.get("ascetic_discipline", 0.3)
        art_genre = params.get("art_genre", self.default_art).upper()

        pain = round(will * (1.0 - fulfillment), 4)
        boredom = round(will * fulfillment * 0.75, 4)
        net_suffering = round(min(1.0, pain + 0.6 * boredom), 4)

        art_power = ART_POWER.get(art_genre, 0.5)
        will_suspension = round(min(1.0, alpha * art_power), 4)
        suffering_in_art = round(net_suffering * (1.0 - will_suspension), 4)

        compassion = round(min(1.0, (1.0 - maya) * (0.5 + 0.5 * beta)), 4)
        quietive = round(min(1.0, beta * (1.0 - maya) * (1.0 - 0.3 * will)), 4)

        if quietive >= 0.55:
            stance = "ASCETIC_NIRVANA"
            verdict = "의지의 부정(Verneinung des Willens zum Leben): 마야의 장막을 찢고 도달한 성스러운 무욕과 열반"
        elif will_suspension >= 0.50:
            stance = "AESTHETIC_TRANSCENDENCE"
            verdict = "순수한 무의지적 인식의 주체: 예술과 음악을 통한 고통의 일시적 정지"
        elif compassion >= 0.50:
            stance = "ETHICAL_COMPASSION"
            verdict = "동포애적 연민(Mitleid): 타트 트밤 아시(Tat Tvam Asi), 타인의 고통을 나의 고통으로 체현"
        else:
            stance = "PENDULUM_SUFFERING"
            verdict = "의지의 진자(Pendel): 결핍의 고통과 충족의 권태 사이를 영구 방황하는 개별화의 망상"

        return {
            "pain": pain,
            "boredom": boredom,
            "net_suffering": net_suffering,
            "will_suspension": will_suspension,
            "suffering_in_art": suffering_in_art,
            "compassion": compassion,
            "quietive": quietive,
            "stance": stance,
            "verdict": verdict
        }

    def simulate_pendulum_trajectory(self, params):
        will = params["will_intensity"]
        steps = params.get("steps", 5)
        trajectory = []
        for i in range(steps):
            f = 0.5 + 0.5 * math.sin(i * (math.pi / 2))
            f = round(f, 2)
            eval_res = self.evaluate_subject({
                "will_intensity": will,
                "fulfillment_ratio": f,
                "maya_illusion": params.get("maya_illusion", 0.8),
                "aesthetic_attunement": params.get("aesthetic_attunement", 0.2),
                "ascetic_discipline": params.get("ascetic_discipline", 0.1)
            })
            trajectory.append({
                "step": i + 1,
                "fulfillment": f,
                "pain": eval_res["pain"],
                "boredom": eval_res["boredom"],
                "net_suffering": eval_res["net_suffering"],
                "phase": "PAIN" if eval_res["pain"] > eval_res["boredom"] else "BOREDOM"
            })
        return {
            "will_intensity": will,
            "steps_count": steps,
            "trajectory": trajectory
        }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = SchopenhauerEngine(data.get("config", {}))
    results = []
    for op in data.get("operations", []):
        name = op["op"]
        if name == "EVALUATE_SUBJECT":
            results.append(engine.evaluate_subject(op["params"]))
        elif name == "SIMULATE_PENDULUM":
            results.append(engine.simulate_pendulum_trajectory(op["params"]))
        else:
            raise ValueError(f"Unknown op: {name}")

    print(json.dumps(results, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
