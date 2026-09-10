import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class HobbesEngine:
    def __init__(self, config):
        self.sword_power = config.get("sovereign_sword_power", 0.0)
        self.agents = {}

    def add_agent(self, op):
        aid = op["id"]
        power = op.get("power", 0.5)
        distrust = op.get("distrust", 0.5)
        glory = op.get("glory", 0.5)
        self.agents[aid] = {
            "id": aid,
            "power": power,
            "distrust": distrust,
            "glory": glory,
            "covenant_signed": False
        }
        return {"status": "AGENT_ADDED", "id": aid, "power": power}

    def sign_covenant(self, op):
        aid = op["id"]
        if aid in self.agents:
            self.agents[aid]["covenant_signed"] = True
            return {"status": "COVENANT_SIGNED", "id": aid}
        return {"error": "AGENT_NOT_FOUND"}

    def set_sovereign_sword(self, op):
        self.sword_power = op["sword_power"]
        return {"status": "SWORD_UPDATED", "sword_power": self.sword_power}

    def evaluate_state(self):
        agent_list = list(self.agents.values())
        n = len(agent_list)
        if n < 2:
            return {"status": "INSUFFICIENT_AGENTS", "count": n}

        pair_conflicts = []
        for i in range(n):
            for j in range(i + 1, n):
                a1 = agent_list[i]
                a2 = agent_list[j]
                comp_factor = 1.0 - abs(a1["power"] - a2["power"])
                diff_factor = (a1["distrust"] + a2["distrust"]) / 2.0
                glory_factor = (a1["glory"] + a2["glory"]) / 2.0
                c = 0.40 * comp_factor + 0.35 * diff_factor + 0.25 * glory_factor
                pair_conflicts.append(min(1.0, max(0.0, c)))

        raw_war_index = sum(pair_conflicts) / len(pair_conflicts)
        war_index = round(raw_war_index, 4)
        fear_of_death = round(min(1.0, war_index * 1.2), 4)

        signed_count = sum(1 for a in agent_list if a["covenant_signed"])
        covenant_ratio = round(signed_count / n, 4)

        enforcement = round(min(1.0, self.sword_power * covenant_ratio), 4)
        residual_conflict = round(max(0.0, war_index * (1.0 - enforcement)), 4)
        civilization_index = round(min(1.0, enforcement * (1.0 - residual_conflict)), 4)

        if enforcement >= 0.65:
            state = "LEVIATHAN_ORDER"
            verdict = "리바이어던 확립: 주권자의 칼에 의한 절대 평화 및 사회계약 이행"
        elif covenant_ratio >= 0.50 and self.sword_power < 0.40:
            state = "WORDS_WITHOUT_SWORD"
            verdict = "칼 없는 규약은 한낱 말에 불과함: 강제력 결여로 인한 계약 불이행 및 내전 위험"
        else:
            state = "BELLUM_OMNIUM_CONTRA_OMNES"
            verdict = "만인에 대한 만인의 투쟁: 고독하고 가난하며 험악하고 잔인하며 짧은 삶"

        return {
            "agent_count": n,
            "war_index": war_index,
            "fear_of_death": fear_of_death,
            "covenant_ratio": covenant_ratio,
            "sword_power": self.sword_power,
            "enforcement": enforcement,
            "residual_conflict": residual_conflict,
            "civilization_index": civilization_index,
            "state": state,
            "verdict": verdict
        }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = HobbesEngine(data.get("config", {}))
    results = []
    for op in data.get("operations", []):
        name = op["op"]
        if name == "ADD_AGENT":
            results.append(engine.add_agent(op))
        elif name == "SIGN_COVENANT":
            results.append(engine.sign_covenant(op))
        elif name == "SET_SWORD":
            results.append(engine.set_sovereign_sword(op))
        elif name == "EVALUATE_STATE":
            results.append(engine.evaluate_state())
        else:
            raise ValueError(f"Unknown op: {name}")

    print(json.dumps(results, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
