import sys
import math

class CacheSimulator:
    def __init__(self, ttl_ticks, db_cost_delta, db_max_concurrency, beta):
        self.ttl = ttl_ticks
        self.delta = db_cost_delta
        self.max_concurrency = db_max_concurrency
        self.beta = beta

        self.current_tick = 0
        self.total_requests = 0

        # Naive Engine
        self.naive_expiry = ttl_ticks
        self.naive_hits = 0
        self.naive_queries = 0
        self.naive_crashed = False
        self.naive_tick_queries = 0
        self.naive_needs_refresh = False

        # Mutex Engine
        self.mutex_expiry = ttl_ticks
        self.mutex_hits = 0
        self.mutex_queries = 0
        self.mutex_locked = False
        self.mutex_needs_refresh = False

        # XFetch Engine
        self.xfetch_expiry = ttl_ticks
        self.xfetch_hits = 0
        self.xfetch_queries = 0
        self.xfetch_early_refreshes = 0

    def tick(self, num_ticks):
        if self.naive_needs_refresh:
            self.naive_expiry = self.current_tick + self.ttl
            self.naive_needs_refresh = False

        if self.mutex_needs_refresh:
            self.mutex_expiry = self.current_tick + self.ttl
            self.mutex_needs_refresh = False

        self.current_tick += num_ticks
        self.naive_tick_queries = 0
        self.mutex_locked = False

    def get_item(self, req_id, pseudo_u=0.5):
        self.total_requests += 1

        # 1. Naive Engine: If expired, every concurrent request in this tick hits DB!
        if self.current_tick < self.naive_expiry:
            n_status = "CACHE_HIT"
            self.naive_hits += 1
        else:
            n_status = "CACHE_MISS_DB_QUERY"
            self.naive_queries += 1
            self.naive_tick_queries += 1
            if self.naive_tick_queries > self.max_concurrency:
                self.naive_crashed = True
            # Cache is only refreshed at end of tick or next tick
            # In simulation, we mark it to be refreshed at tick end
            self.naive_needs_refresh = True

        n_overload = "CRASH_DETECTED" if self.naive_crashed else "NONE"

        # 2. Mutex Engine: Only 1 request gets mutex lock and hits DB, others blocked/stale
        if self.current_tick < self.mutex_expiry:
            m_status = "CACHE_HIT"
            self.mutex_hits += 1
        else:
            if not self.mutex_locked:
                self.mutex_locked = True
                self.mutex_queries += 1
                self.mutex_needs_refresh = True
                m_status = "MUTEX_ACQUIRED_DB_QUERY"
            else:
                m_status = "MUTEX_BLOCKED_WAIT"
                self.mutex_hits += 1

        # 3. XFetch Engine: Probabilistic early refresh before expiration
        rem_ttl = self.xfetch_expiry - self.current_tick
        if rem_ttl > 0:
            u_safe = max(0.00001, min(0.99999, pseudo_u))
            xfetch_val = -self.beta * self.delta * math.log(u_safe)

            if xfetch_val > rem_ttl:
                x_status = "XFETCH_EARLY_REFRESH"
                self.xfetch_queries += 1
                self.xfetch_early_refreshes += 1
                self.xfetch_hits += 1
                self.xfetch_expiry = self.current_tick + self.ttl
            else:
                x_status = "CACHE_HIT"
                self.xfetch_hits += 1
        else:
            x_status = "CACHE_EXPIRED_DB_QUERY"
            self.xfetch_queries += 1
            self.xfetch_expiry = self.current_tick + self.ttl

        return n_status, n_overload, m_status, x_status, max(0, rem_ttl)


def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    ttl_ticks = 20
    db_cost_delta = 5
    db_max_concurrency = 5
    beta = 1.0
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "CACHE_TTL_TICKS":
                ttl_ticks = int(parts[1])
            elif parts[0] == "DB_QUERY_COST_TICKS":
                db_cost_delta = int(parts[1])
            elif parts[0] == "DB_MAX_CONCURRENCY":
                db_max_concurrency = int(parts[1])
            elif parts[0] == "XFETCH_BETA":
                beta = float(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    sim = CacheSimulator(ttl_ticks, db_cost_delta, db_max_concurrency, beta)
    out_lines = []

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "GET_ITEM":
            req_id = act[1]
            u_val = float(act[2]) if len(act) > 2 else 0.5

            n_stat, n_ovld, m_stat, x_stat, rem = sim.get_item(req_id, u_val)
            out_lines.append(f"ACT {act_idx} GET_ITEM ID:{req_id} TICK:{sim.current_tick}")
            out_lines.append(f"  NAIVE: STATUS:{n_stat} DB_OVERLOAD:{n_ovld}")
            out_lines.append(f"  MUTEX: STATUS:{m_stat}")
            out_lines.append(f"  XFETCH: STATUS:{x_stat} REMAINING_TTL:{rem}")

        elif cmd == "TICK":
            ticks = int(act[1])
            sim.tick(ticks)
            out_lines.append(f"ACT {act_idx} TICK {ticks} (CURRENT_TICK:{sim.current_tick})")

        elif cmd == "CHECK_METRICS":
            n_state = "OVERLOAD_CRASHED" if sim.naive_crashed else "HEALTHY"
            out_lines.append(f"ACT {act_idx} CHECK_METRICS")
            out_lines.append(f"  NAIVE: TOTAL:{sim.total_requests} HITS:{sim.naive_hits} DB_QUERIES:{sim.naive_queries} DB_STATUS:{n_state}")
            out_lines.append(f"  MUTEX: TOTAL:{sim.total_requests} HITS:{sim.mutex_hits} DB_QUERIES:{sim.mutex_queries} DB_STATUS:HEALTHY")
            out_lines.append(f"  XFETCH: TOTAL:{sim.total_requests} HITS:{sim.xfetch_hits} DB_QUERIES:{sim.xfetch_queries} EARLY_REFRESHES:{sim.xfetch_early_refreshes} DB_STATUS:HEALTHY")

    q_saved = sim.naive_queries - sim.xfetch_queries
    q_red = (q_saved / sim.naive_queries * 100.0) if sim.naive_queries > 0 else 0.0
    n_final_state = "OVERLOAD_CRASHED" if sim.naive_crashed else "HEALTHY"

    out_lines.append(f"SUMMARY TOTAL_GET_REQUESTS:{sim.total_requests}")
    out_lines.append(f"SUMMARY NAIVE HITS:{sim.naive_hits} DB_QUERIES:{sim.naive_queries} DB_STATUS:{n_final_state}")
    out_lines.append(f"SUMMARY MUTEX HITS:{sim.mutex_hits} DB_QUERIES:{sim.mutex_queries} DB_STATUS:HEALTHY")
    out_lines.append(f"SUMMARY XFETCH HITS:{sim.xfetch_hits} DB_QUERIES:{sim.xfetch_queries} EARLY_REFRESHES:{sim.xfetch_early_refreshes} DB_STATUS:HEALTHY")
    out_lines.append(f"SUMMARY DB_QUERY_REDUCTION:{q_red:.2f}%")
    out_lines.append("SUMMARY CACHE_VERDICT: MUTEX_AND_XFETCH_PREVENT_STAMPEDE_CRASH")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
