import sys

class CFSSchedulerSimulator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.period_us = 100000   # 100ms
        self.quota_us = 200000    # 2.0 cores (200ms)
        self.burst_us = 0         # disabled by default
        self.threads = 1

        # Dynamic state
        self.curr_period_pos_us = 0
        self.curr_quota_remaining_us = 200000
        self.burst_pool_us = 0
        self.is_throttled = False
        self.curr_period_throttled = False

        # Cumulative stats
        self.nr_periods = 0
        self.nr_throttled = 0
        self.throttled_time_us = 0
        self.total_cpu_time_us = 0

    def config(self, period_us, quota_us, burst_us=0):
        self.period_us = int(period_us)
        self.quota_us = int(quota_us)
        self.burst_us = int(burst_us)
        self.curr_quota_remaining_us = self.quota_us
        return f"CONFIG_OK period_us={self.period_us} quota_us={self.quota_us} burst_us={self.burst_us}"

    def set_threads(self, count):
        self.threads = max(0, int(count))
        return f"SET_THREADS_OK count={self.threads}"

    def elapse(self, duration_ms):
        total_time_us = int(duration_ms) * 1000
        t_rem = total_time_us

        while t_rem > 0:
            time_to_boundary = self.period_us - self.curr_period_pos_us

            if self.is_throttled:
                dt = min(t_rem, time_to_boundary)
                self.throttled_time_us += dt
                self.curr_period_pos_us += dt
                t_rem -= dt
            else:
                if self.threads == 0:
                    dt = min(t_rem, time_to_boundary)
                    self.curr_period_pos_us += dt
                    t_rem -= dt
                else:
                    time_to_exhaust = self.curr_quota_remaining_us / float(self.threads)
                    dt = min(float(t_rem), float(time_to_boundary), time_to_exhaust)
                    # Round down or integer convert safely
                    dt_int = int(round(dt))
                    if dt_int <= 0 and dt > 0:
                        dt_int = 1

                    cpu_spent = dt_int * self.threads
                    self.curr_quota_remaining_us -= cpu_spent
                    self.total_cpu_time_us += cpu_spent
                    self.curr_period_pos_us += dt_int
                    t_rem -= dt_int

                    if self.curr_quota_remaining_us <= 0:
                        self.curr_quota_remaining_us = 0
                        self.is_throttled = True
                        if not self.curr_period_throttled:
                            self.curr_period_throttled = True
                            self.nr_throttled += 1

            if self.curr_period_pos_us >= self.period_us:
                self.nr_periods += 1
                if not self.curr_period_throttled:
                    unused = max(0, self.curr_quota_remaining_us)
                    if self.burst_us > 0:
                        self.burst_pool_us = min(self.burst_us, self.burst_pool_us + unused)
                else:
                    # Throttled periods exhaust quota, so no new unused quota
                    pass

                # Reset for new period
                self.curr_period_pos_us = 0
                self.curr_quota_remaining_us = self.quota_us + self.burst_pool_us
                self.burst_pool_us = 0
                self.is_throttled = False
                self.curr_period_throttled = False

        return f"ELAPSE_OK duration_ms={duration_ms}"

    def report(self):
        total_eval_periods = self.nr_periods + (1 if self.curr_period_pos_us > 0 else 0)
        if total_eval_periods > 0:
            pct = (self.nr_throttled / float(total_eval_periods)) * 100.0
        else:
            pct = 0.0

        status_str = "THROTTLED" if self.is_throttled else "RUNNABLE"

        lines = [
            "--- CFS_CPU_STAT ---",
            f"NR_PERIODS: {self.nr_periods}",
            f"NR_THROTTLED: {self.nr_throttled}",
            f"THROTTLED_PERIODS_PCT: {pct:.2f}%",
            f"THROTTLED_TIME_US: {self.throttled_time_us}",
            f"TOTAL_CPU_TIME_US: {self.total_cpu_time_us}",
            f"BURST_POOL_US: {self.burst_pool_us}",
            f"STATUS: {status_str}",
            "--- END_REPORT ---"
        ]
        return "\n".join(lines)


def parse_tokens(tokens):
    kv = {}
    pos = []
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            kv[k.strip().lower()] = v.strip()
        else:
            pos.append(t.strip())
    return kv, pos


def main():
    sim = CFSSchedulerSimulator()
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        cmd = parts[0].upper()
        kv, pos = parse_tokens(parts[1:])

        if cmd == "CONFIG":
            p = kv.get("period_us", pos[0] if len(pos) > 0 else 100000)
            q = kv.get("quota_us", pos[1] if len(pos) > 1 else 200000)
            b = kv.get("burst_us", pos[2] if len(pos) > 2 else 0)
            print(sim.config(p, q, b))
        elif cmd == "SET_THREADS":
            cnt = kv.get("count", pos[0] if len(pos) > 0 else 1)
            print(sim.set_threads(cnt))
        elif cmd == "ELAPSE":
            dur = kv.get("duration_ms", pos[0] if len(pos) > 0 else 100)
            print(sim.elapse(dur))
        elif cmd == "REPORT":
            print(sim.report())
        elif cmd == "RESET":
            sim.reset()
            print("RESET_OK")


if __name__ == "__main__":
    main()
