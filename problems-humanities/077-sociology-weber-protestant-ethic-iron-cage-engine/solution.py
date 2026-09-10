import sys
import json
import copy

# Ensure UTF-8 I/O for Korean/multilingual text on Windows environments
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

class EconomicAgent:
    def __init__(self, subject_id: str, name: str, calling: str, capital: float, asceticism: float, calling_devotion: float, salvation_anxiety: float):
        self.subject_id = subject_id
        self.name = name
        self.calling = calling
        self.capital = float(capital)
        self.asceticism = min(1.0, max(0.0, float(asceticism)))
        self.calling_devotion = min(1.0, max(0.0, float(calling_devotion)))
        self.salvation_anxiety = min(1.0, max(0.0, float(salvation_anxiety)))
        self.total_reinvested = 0.0
        self.total_consumed = 0.0

    def work_cycle(self, market_factor: float):
        profit = self.calling_devotion * 50.0 * (1.0 + self.asceticism * 0.8) * market_factor
        consumption = profit * (1.0 - self.asceticism) * 0.7
        reinvestment = profit - consumption
        
        self.capital += reinvestment
        self.total_reinvested += reinvestment
        self.total_consumed += consumption
        
        self.salvation_anxiety = max(0.0, self.salvation_anxiety - reinvestment * 0.001)

    def to_dict(self) -> dict:
        return {
            "subject_id": self.subject_id,
            "name": self.name,
            "calling": self.calling,
            "capital": round(self.capital, 2),
            "asceticism": round(self.asceticism, 4),
            "calling_devotion": round(self.calling_devotion, 4),
            "salvation_anxiety": round(self.salvation_anxiety, 4),
            "total_reinvested": round(self.total_reinvested, 2),
            "total_consumed": round(self.total_consumed, 2)
        }

class WeberIronCageEngine:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.rationalization_pressure = float(config.get("rationalization_pressure", 0.30))
        self.agents = {}
        for a_cfg in config.get("agents", []):
            agent = EconomicAgent(
                subject_id=a_cfg["subject_id"],
                name=a_cfg["name"],
                calling=a_cfg.get("calling", "artisan"),
                capital=a_cfg.get("capital", 100.0),
                asceticism=a_cfg.get("asceticism", 0.8),
                calling_devotion=a_cfg.get("calling_devotion", 0.85),
                salvation_anxiety=a_cfg.get("salvation_anxiety", 0.70)
            )
            self.agents[agent.subject_id] = agent

        self.current_step = 0
        self.iron_cage_index = 0.0
        self.epoch = "EARLY_PROTESTANT_ETHIC_ASCETICISM"
        self.query_logs = []
        self._evaluate()

    def _evaluate(self):
        if not self.agents:
            self.iron_cage_index = 0.0
            self.epoch = "EARLY_PROTESTANT_ETHIC_ASCETICISM"
            return

        avg_k = sum(a.capital for a in self.agents.values()) / len(self.agents)
        avg_spirit = sum(a.asceticism * a.salvation_anxiety for a in self.agents.values()) / len(self.agents)
        
        k_factor = avg_k / (avg_k + 400.0) if avg_k > 0 else 0.0
        raw_ic = self.rationalization_pressure * 0.5 + k_factor * 0.5 - avg_spirit * 0.25
        self.iron_cage_index = round(min(1.0, max(0.0, raw_ic)), 4)

        if self.iron_cage_index >= 0.75:
            self.epoch = "IRON_CAGE_MECHANICAL_PETRIFICATION"
        elif self.iron_cage_index >= 0.40:
            self.epoch = "RATIONALIZED_MODERN_CAPITALISM"
        else:
            self.epoch = "EARLY_PROTESTANT_ETHIC_ASCETICISM"

    def work_and_accumulate(self, cycles: int, market_factor: float):
        for _ in range(int(cycles)):
            for a in self.agents.values():
                a.work_cycle(float(market_factor))
        self._evaluate()

    def secular_rationalization(self, intensity: float):
        eff = float(intensity)
        self.rationalization_pressure = min(1.0, max(0.0, self.rationalization_pressure + eff))
        for a in self.agents.values():
            a.salvation_anxiety = max(0.0, a.salvation_anxiety - eff * 0.8)
            a.asceticism = max(0.2, a.asceticism - eff * 0.3)
        self._evaluate()

    def ascetic_reform(self, subject_id: str, asceticism_boost: float):
        if subject_id in self.agents:
            a = self.agents[subject_id]
            a.asceticism = min(1.0, a.asceticism + float(asceticism_boost))
            self._evaluate()

    def luxury_consumption(self, subject_id: str, waste_amount: float):
        if subject_id in self.agents:
            a = self.agents[subject_id]
            w = min(a.capital, float(waste_amount))
            a.capital -= w
            a.total_consumed += w
            a.asceticism = max(0.0, a.asceticism - 0.2)
            self._evaluate()

    def step(self):
        self.current_step += 1
        self._evaluate()

    def run_commands(self, commands: list):
        for cmd in commands:
            ctype = cmd["type"]
            if ctype == "WORK_AND_ACCUMULATE":
                self.work_and_accumulate(cmd.get("cycles", 1), cmd.get("market_factor", 1.0))
            elif ctype == "SECULAR_RATIONALIZATION":
                self.secular_rationalization(cmd["intensity"])
            elif ctype == "ASCETIC_REFORM":
                self.ascetic_reform(cmd["subject_id"], cmd["asceticism_boost"])
            elif ctype == "LUXURY_CONSUMPTION":
                self.luxury_consumption(cmd["subject_id"], cmd["waste_amount"])
            elif ctype == "STEP":
                self.step()
            elif ctype == "QUERY_WEBER_STATE":
                self.query_logs.append({
                    "step": self.current_step,
                    "rationalization_pressure": round(self.rationalization_pressure, 4),
                    "iron_cage_index": self.iron_cage_index,
                    "epoch": self.epoch,
                    "agents": {aid: a.to_dict() for aid, a in sorted(self.agents.items())}
                })

    def get_final_result(self) -> dict:
        return {
            "total_steps": self.current_step,
            "rationalization_pressure": round(self.rationalization_pressure, 4),
            "iron_cage_index": self.iron_cage_index,
            "epoch": self.epoch,
            "agents": {aid: a.to_dict() for aid, a in sorted(self.agents.items())},
            "query_logs": self.query_logs
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = WeberIronCageEngine(data.get("config", {}))
    engine.run_commands(data.get("commands", []))
    print(json.dumps(engine.get_final_result(), separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
