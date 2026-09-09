import sys

STATE_NAMES = {
    0: "STRONGLY_NOT_TAKEN",
    1: "WEAKLY_NOT_TAKEN",
    2: "WEAKLY_TAKEN",
    3: "STRONGLY_TAKEN"
}

class BranchPredictorSimulator:
    def __init__(self):
        self.pipeline_depth = 14
        self.penalty_cycles = 15
        self.counter = 2  # Default: Weakly Taken (10)
        self.data = []

    def config_cpu(self, pipeline_depth, penalty_cycles):
        self.pipeline_depth = int(pipeline_depth)
        self.penalty_cycles = int(penalty_cycles)
        self.counter = 2
        return f"CONFIG_CPU_OK pipeline_depth={self.pipeline_depth} penalty={self.penalty_cycles}cycles initial_state={STATE_NAMES[self.counter]}"

    def load_array(self, items_str):
        if not items_str.strip():
            self.data = []
        else:
            self.data = [int(x.strip()) for x in items_str.split(',') if x.strip()]
        sample = self.data[:5]
        sample_repr = ", ".join(str(x) for x in sample)
        if len(self.data) > 5:
            sample_repr += ", ..."
        return f"LOAD_ARRAY_OK size={len(self.data)} sample=[{sample_repr}]"

    def sort_array(self):
        self.data.sort()
        min_v = self.data[0] if self.data else 0
        max_v = self.data[-1] if self.data else 0
        return f"SORT_ARRAY_OK size={len(self.data)} min={min_v} max={max_v}"

    def reset_predictor(self):
        self.counter = 2
        return f"RESET_OK state={STATE_NAMES[self.counter]}"

    def run_branched(self, threshold):
        th = int(threshold)
        sum_val = 0
        hits = 0
        misses = 0
        total_cycles = 0

        for x in self.data:
            actual_taken = (x >= th)
            predicted_taken = (self.counter >= 2)

            if predicted_taken == actual_taken:
                hits += 1
                total_cycles += 1
            else:
                misses += 1
                total_cycles += (1 + self.penalty_cycles)

            # Update 2-bit counter FSM
            if actual_taken:
                self.counter = min(3, self.counter + 1)
            else:
                self.counter = max(0, self.counter - 1)

            if actual_taken:
                sum_val += x

        total = hits + misses
        hit_rate = (hits / total * 100.0) if total > 0 else 0.0
        return f"BRANCHED_RESULT sum={sum_val} total_branches={total} hits={hits} misses={misses} hit_rate={hit_rate:.2f}% total_cycles={total_cycles}"

    def run_branchless(self, threshold):
        th = int(threshold)
        sum_val = 0
        total_cycles = 0

        for x in self.data:
            # Branchless: no conditional branch instruction, fixed 2 cycles per element
            if x >= th:
                sum_val += x
            total_cycles += 2

        return f"BRANCHLESS_RESULT sum={sum_val} total_elements={len(self.data)} misses=0 total_cycles={total_cycles}"

    def stats(self):
        is_sorted = (self.data == sorted(self.data)) if self.data else True
        state_str = STATE_NAMES[self.counter]
        return f"STATS array_size={len(self.data)} is_sorted={str(is_sorted).upper()} predictor_state={state_str}"

def main():
    sim = BranchPredictorSimulator()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(maxsplit=1)
        cmd = parts[0].upper()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "CONFIG_CPU":
            p = arg.split()
            print(sim.config_cpu(p[0], p[1]))
        elif cmd == "LOAD_ARRAY":
            print(sim.load_array(arg))
        elif cmd == "SORT_ARRAY":
            print(sim.sort_array())
        elif cmd == "RESET_PREDICTOR":
            print(sim.reset_predictor())
        elif cmd == "RUN_BRANCHED":
            print(sim.run_branched(arg.strip()))
        elif cmd == "RUN_BRANCHLESS":
            print(sim.run_branchless(arg.strip()))
        elif cmd == "STATS":
            print(sim.stats())

if __name__ == '__main__':
    main()
