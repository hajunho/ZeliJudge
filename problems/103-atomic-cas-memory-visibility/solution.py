import sys

class MemoryVariable:
    def __init__(self, name, value):
        self.name = name
        self.value = int(value)

class MemorySimulator:
    def __init__(self):
        self.variables = {}

    def init_var(self, name, value):
        self.variables[name] = MemoryVariable(name, value)
        return f"INIT_VAR_OK var={name} value={int(value)}"

    def cas(self, name, expected, new_val):
        if name not in self.variables:
            return f"ERROR:UNKNOWN_VAR var={name}"
        var = self.variables[name]
        exp = int(expected)
        nv = int(new_val)

        if var.value == exp:
            var.value = nv
            return f"CAS_SUCCESS var={name} old={exp} new={nv}"
        else:
            return f"CAS_FAILED var={name} expected={exp} actual={var.value}"

    def exec_unsafe_increment(self, name, num_threads, ops_per_thread):
        if name not in self.variables:
            return f"ERROR:UNKNOWN_VAR var={name}"
        var = self.variables[name]
        n_threads = int(num_threads)
        ops = int(ops_per_thread)
        total_ops = n_threads * ops

        initial_val = var.value
        # Deterministic simulation of interleaving race condition:
        # In a batch of n_threads concurrent read-modify-write ops,
        # threads read simultaneously. If n_threads > 1, only 1 write succeeds per batch
        # or partial writes succeed depending on collision factor.
        # We simulate step-by-step batches of size n_threads:
        current = initial_val
        lost_count = 0

        for _ in range(ops):
            # n_threads read current value concurrently
            # All n_threads compute (current + 1)
            # When writing back, they overwrite each other, resulting in only +1 net increase!
            current += 1
            lost_count += (n_threads - 1)

        var.value = current
        actual = var.value - initial_val
        rate = (actual / total_ops * 100.0) if total_ops > 0 else 0.0
        return f"UNSAFE_RESULT var={name} expected={total_ops} actual={actual} lost_updates={lost_count} success_rate={rate:.2f}%"

    def exec_atomic_increment(self, name, num_threads, ops_per_thread):
        if name not in self.variables:
            return f"ERROR:UNKNOWN_VAR var={name}"
        var = self.variables[name]
        n_threads = int(num_threads)
        ops = int(ops_per_thread)
        total_ops = n_threads * ops

        initial_val = var.value
        # Atomic CAS simulation:
        # Each thread attempts CAS. In a round of n_threads competing,
        # 1 thread succeeds on first try, others fail and retry.
        # Total successes = total_ops.
        # Retries = for each batch of n_threads, 1st succeeds, 2nd retries once, 3rd retries twice...
        # sum_{i=0}^{n-1} i = n*(n-1)/2 retries per batch!
        retries_per_batch = (n_threads * (n_threads - 1)) // 2
        total_retries = retries_per_batch * ops

        var.value += total_ops
        actual = var.value - initial_val

        return f"ATOMIC_RESULT var={name} expected={total_ops} actual={actual} cas_successes={total_ops} cas_retries={total_retries} lost_updates=0"

    def stats(self, name):
        if name not in self.variables:
            return f"ERROR:UNKNOWN_VAR var={name}"
        return f"STATS var={name} current_value={self.variables[name].value}"

def main():
    sim = MemorySimulator()
    lines = sys.stdin.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        cmd = parts[0].upper()

        if cmd == "INIT_VAR":
            print(sim.init_var(parts[1], parts[2]))
        elif cmd == "CAS":
            print(sim.cas(parts[1], parts[2], parts[3]))
        elif cmd == "EXEC_UNSAFE_INCREMENT":
            print(sim.exec_unsafe_increment(parts[1], parts[2], parts[3]))
        elif cmd == "EXEC_ATOMIC_INCREMENT":
            print(sim.exec_atomic_increment(parts[1], parts[2], parts[3]))
        elif cmd == "STATS":
            print(sim.stats(parts[1]))

if __name__ == '__main__':
    main()
