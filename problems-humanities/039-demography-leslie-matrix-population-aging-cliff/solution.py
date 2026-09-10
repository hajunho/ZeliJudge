import sys
import json

class DemographyEngine:
    def __init__(self, config=None):
        config = config or {}
        self.fecundity = config.get("fecundity", [0.0, 0.3, 0.8, 0.1, 0.0])
        self.survival = config.get("survival", [0.98, 0.97, 0.95, 0.85, 0.60])

    def step(self, pop_vector, migration_vector=None):
        n = len(pop_vector)
        next_pop = [0.0] * n

        births = sum(self.fecundity[i] * pop_vector[i] for i in range(n))
        next_pop[0] = births

        for i in range(1, n - 1):
            next_pop[i] = pop_vector[i - 1] * self.survival[i - 1]

        next_pop[n - 1] = (pop_vector[n - 2] * self.survival[n - 2]) + (pop_vector[n - 1] * self.survival[n - 1])

        if migration_vector and len(migration_vector) == n:
            for i in range(n):
                next_pop[i] = max(0.0, next_pop[i] + migration_vector[i])

        return next_pop

    def analyze(self, pop_vector):
        p_youth = pop_vector[0]
        p_work = sum(pop_vector[1:4])
        p_elderly = pop_vector[4]
        total = sum(pop_vector)

        elderly_ratio = (p_elderly / total * 100.0) if total > 0 else 0.0
        if elderly_ratio >= 20.0:
            society_stage = "SUPER_AGED"
        elif elderly_ratio >= 14.0:
            society_stage = "AGED"
        elif elderly_ratio >= 7.0:
            society_stage = "AGING"
        else:
            society_stage = "YOUNG"

        dep_youth = round((p_youth / p_work * 100.0), 2) if p_work > 0 else 0.0
        dep_old = round((p_elderly / p_work * 100.0), 2) if p_work > 0 else 0.0
        dep_total = round(dep_youth + dep_old, 2)
        aging_index = round((p_elderly / p_youth * 100.0), 2) if p_youth > 0 else 0.0

        return {
            "total_population": round(total, 2),
            "youth_pop": round(p_youth, 2),
            "working_pop": round(p_work, 2),
            "elderly_pop": round(p_elderly, 2),
            "elderly_ratio_pct": round(elderly_ratio, 2),
            "society_stage": society_stage,
            "dependency_ratios": {
                "youth": dep_youth,
                "old_age": dep_old,
                "total": dep_total
            },
            "aging_index": aging_index
        }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return

    data = json.loads(raw)
    config = data.get("config", {})
    engine = DemographyEngine(config)
    initial_pop = data.get("initial_population", [10.0, 10.0, 15.0, 8.0, 4.0])
    cycles = data.get("cycles", 5)
    migration_per_cycle = data.get("migration_per_cycle", None)

    history = []
    current_pop = list(initial_pop)

    working_peak_val = sum(current_pop[1:4])
    working_peak_cycle = 0
    demographic_cliff_detected = False
    demographic_cliff_cycle = None
    aging_crossover_cycle = None

    curr_analysis = engine.analyze(current_pop)
    history.append({
        "cycle": 0,
        "population_vector": [round(x, 2) for x in current_pop],
        "analysis": curr_analysis
    })
    if curr_analysis["aging_index"] >= 100.0 and aging_crossover_cycle is None:
        aging_crossover_cycle = 0

    for c in range(1, cycles + 1):
        current_pop = engine.step(current_pop, migration_per_cycle)
        analysis = engine.analyze(current_pop)
        history.append({
            "cycle": c,
            "population_vector": [round(x, 2) for x in current_pop],
            "analysis": analysis
        })

        if analysis["aging_index"] >= 100.0 and aging_crossover_cycle is None:
            aging_crossover_cycle = c

        curr_work = analysis["working_pop"]
        if curr_work > working_peak_val and not demographic_cliff_detected:
            working_peak_val = curr_work
            working_peak_cycle = c
        elif curr_work < working_peak_val and not demographic_cliff_detected:
            demographic_cliff_detected = True
            demographic_cliff_cycle = c

    output = {
        "cycles_simulated": cycles,
        "working_age_peak": {
            "cycle": working_peak_cycle,
            "peak_population": round(working_peak_val, 2)
        },
        "demographic_cliff": {
            "detected": demographic_cliff_detected,
            "cliff_onset_cycle": demographic_cliff_cycle
        },
        "aging_crossover": {
            "crossover_cycle": aging_crossover_cycle
        },
        "history": history
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()
