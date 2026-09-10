import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class LockeEngine:
    def __init__(self, config):
        self.common_resources = config.get("common_resources", 1000.0)
        self.min_subsistence_per_capita = config.get("min_subsistence_per_capita", 10.0)
        self.spoilage_threshold = config.get("spoilage_threshold", 50.0)
        self.tyranny_threshold = config.get("tyranny_threshold", 0.65)
        self.tyranny_score = 0.0
        self.government_established = False
        self.agents = {}

    def add_agent(self, op):
        aid = op["id"]
        self.agents[aid] = {
            "id": aid,
            "perishable": 0.0,
            "durable_money": 0.0,
            "estate_land": 0.0,
            "total_labor_invested": 0.0,
            "trust": 1.0
        }
        return {"status": "AGENT_ADDED", "id": aid}

    def appropriate_by_labor(self, op):
        aid = op["id"]
        labor = op["labor_units"]
        yield_per_labor = op.get("yield_per_labor", 2.0)
        requested_resource = labor * yield_per_labor

        n = max(1, len(self.agents))
        remaining_if_taken = self.common_resources - requested_resource
        per_capita_remaining = remaining_if_taken / n

        if per_capita_remaining < self.min_subsistence_per_capita:
            return {
                "status": "PROVISO_VIOLATION_NOT_ENOUGH_LEFT",
                "id": aid,
                "requested": requested_resource,
                "per_capita_left": round(per_capita_remaining, 2),
                "required_min": self.min_subsistence_per_capita
            }

        self.common_resources -= requested_resource
        agent = self.agents[aid]
        agent["total_labor_invested"] += labor
        agent["estate_land"] += labor * 0.5

        potential_total = agent["perishable"] + requested_resource
        if potential_total > self.spoilage_threshold:
            spoiled = potential_total - self.spoilage_threshold
            agent["perishable"] = self.spoilage_threshold
            return {
                "status": "SPOILAGE_LOSS",
                "id": aid,
                "appropriated": requested_resource,
                "spoiled_units": round(spoiled, 2),
                "stored_perishable": agent["perishable"],
                "estate_land": round(agent["estate_land"], 2),
                "common_resources_left": round(self.common_resources, 2)
            }
        else:
            agent["perishable"] = potential_total
            return {
                "status": "APPROPRIATION_SUCCESS",
                "id": aid,
                "appropriated": requested_resource,
                "stored_perishable": agent["perishable"],
                "estate_land": round(agent["estate_land"], 2),
                "common_resources_left": round(self.common_resources, 2)
            }

    def trade_money(self, op):
        aid = op["id"]
        perishable_to_sell = op["perishable_amount"]
        exchange_rate = op.get("gold_per_unit", 1.0)

        agent = self.agents[aid]
        if agent["perishable"] < perishable_to_sell:
            return {"error": "INSUFFICIENT_PERISHABLE", "available": agent["perishable"]}

        agent["perishable"] -= perishable_to_sell
        gold_earned = perishable_to_sell * exchange_rate
        agent["durable_money"] += gold_earned

        return {
            "status": "TRADE_SUCCESS",
            "id": aid,
            "sold_perishable": perishable_to_sell,
            "durable_money_total": round(agent["durable_money"], 2),
            "perishable_remaining": round(agent["perishable"], 2)
        }

    def establish_commonwealth(self, op):
        signers = op.get("signers", list(self.agents.keys()))
        self.government_established = True
        self.tyranny_score = 0.0
        for aid in signers:
            if aid in self.agents:
                self.agents[aid]["trust"] = 1.0
        return {
            "status": "COMMONWEALTH_ESTABLISHED",
            "signers_count": len(signers),
            "fiduciary_trust": "ACTIVE"
        }

    def government_action(self, op):
        action = op["action"]
        severity = op.get("severity", 0.3)

        if not self.government_established:
            return {"error": "NO_GOVERNMENT"}

        if action == "PROTECT_PROPERTY":
            self.tyranny_score = max(0.0, self.tyranny_score - 0.1)
            for a in self.agents.values():
                a["trust"] = min(1.0, a["trust"] + 0.05)
            verdict = "재산권(생명·자유·자산) 수호 및 공정한 법 집행"
        else:
            self.tyranny_score = min(1.0, self.tyranny_score + severity)
            for a in self.agents.values():
                a["trust"] = max(0.0, a["trust"] - severity * 0.8)
            verdict = "대표 없는 과세 및 자의적 재산 침해로 인한 신탁 위반"

        return {
            "action": action,
            "tyranny_score": round(self.tyranny_score, 2),
            "verdict": verdict
        }

    def evaluate_revolution(self):
        if not self.government_established:
            return {
                "state": "STATE_OF_NATURE",
                "verdict": "공통 통치자 없는 자연상태: 각자가 자연법의 집행자"
            }

        avg_trust = sum(a["trust"] for a in self.agents.values()) / max(1, len(self.agents))
        is_tyrannical = (self.tyranny_score >= self.tyranny_threshold)

        if is_tyrannical:
            state = "APPEAL_TO_HEAVEN"
            verdict = "신탁 위반에 따른 정부 해체 및 하늘에의 호소(저항권/혁명권 발동)"
            justified_revolution = True
        else:
            state = "LEGITIMATE_COMMONWEALTH"
            verdict = "시민의 신탁에 기초한 정당한 입법부 및 법치주의 통치"
            justified_revolution = False

        return {
            "state": state,
            "tyranny_score": round(self.tyranny_score, 2),
            "average_trust": round(avg_trust, 2),
            "justified_revolution": justified_revolution,
            "verdict": verdict
        }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = LockeEngine(data.get("config", {}))
    results = []
    for op in data.get("operations", []):
        name = op["op"]
        if name == "ADD_AGENT":
            results.append(engine.add_agent(op))
        elif name == "APPROPRIATE_BY_LABOR":
            results.append(engine.appropriate_by_labor(op))
        elif name == "TRADE_MONEY":
            results.append(engine.trade_money(op))
        elif name == "ESTABLISH_COMMONWEALTH":
            results.append(engine.establish_commonwealth(op))
        elif name == "GOVERNMENT_ACTION":
            results.append(engine.government_action(op))
        elif name == "EVALUATE_REVOLUTION":
            results.append(engine.evaluate_revolution())
        else:
            raise ValueError(f"Unknown op: {name}")

    print(json.dumps(results, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
