import sys
import math

class CacheEntry:
    def __init__(self, key, val, expiry, ttl, compute_ms):
        self.key = key
        self.val = val
        self.expiry = expiry
        self.ttl = ttl
        self.compute_ms = compute_ms

class CacheStampedeSimulator:
    def __init__(self):
        self.strategy = "NAIVE"
        self.beta = 1.0
        self.default_compute_ms = 100
        self.cache = {}
        self.locks = {} # key -> locked_until
        self.cache_hits = 0
        self.db_queries = 0
        self.early_refreshes = 0
        self.lock_waits = 0

    def reset(self):
        self.strategy = "NAIVE"
        self.beta = 1.0
        self.default_compute_ms = 100
        self.cache.clear()
        self.locks.clear()
        self.cache_hits = 0
        self.db_queries = 0
        self.early_refreshes = 0
        self.lock_waits = 0

    def config(self, strategy=None, beta=None, compute_ms=None):
        if strategy:
            self.strategy = strategy
        if beta is not None:
            self.beta = float(beta)
        if compute_ms is not None:
            self.default_compute_ms = int(compute_ms)
        return f"OK strategy={self.strategy} beta={self.beta:.2f} compute_ms={self.default_compute_ms}"

    def set_cache(self, key, val, ttl, compute_ms=None, now=0):
        c_ms = int(compute_ms) if compute_ms is not None else self.default_compute_ms
        t = int(ttl)
        n = float(now)
        expiry = n + t
        self.cache[key] = CacheEntry(key, val, expiry, t, c_ms)
        return f"CACHE_STORED key={key} val={val} expiry={expiry:.1f} compute_ms={c_ms}"

    def get(self, key, now, rand_val=0.5):
        n = float(now)
        r = float(rand_val)
        if r <= 0.0:
            r = 0.000001
        elif r > 1.0:
            r = 1.0

        if key not in self.cache:
            # Initial load from DB
            self.db_queries += 1
            val = f"db_{key}"
            ttl = 60
            expiry = n + ttl
            self.cache[key] = CacheEntry(key, val, expiry, ttl, self.default_compute_ms)
            return f"RESULT key={key} val={val} action=INITIAL_LOAD_DB latency_ms={self.default_compute_ms}"

        entry = self.cache[key]
        delta_s = entry.expiry - n
        delta_ms = delta_s * 1000.0

        if self.strategy == "NAIVE":
            if delta_s <= 0:
                # Cache expired -> Cache Stampede happens if many clients arrive here!
                self.db_queries += 1
                entry.expiry = n + entry.ttl
                return f"RESULT key={key} val={entry.val} action=CACHE_MISS_DB_QUERY latency_ms={entry.compute_ms}"
            else:
                self.cache_hits += 1
                return f"RESULT key={key} val={entry.val} action=CACHE_HIT latency_ms=0"

        elif self.strategy == "MUTEX_LOCK":
            if delta_s <= 0:
                # Cache expired -> Try acquiring lock
                locked_until = self.locks.get(key, 0.0)
                if locked_until <= n:
                    # Lock acquired! (Lock held for 1 second)
                    self.locks[key] = n + 1.0
                    self.db_queries += 1
                    entry.expiry = n + entry.ttl
                    return f"RESULT key={key} val={entry.val} action=MUTEX_ACQUIRED_DB_QUERY latency_ms={entry.compute_ms}"
                else:
                    # Lock busy! Wait and read updated cache
                    self.lock_waits += 1
                    self.cache_hits += 1
                    return f"RESULT key={key} val={entry.val} action=MUTEX_WAIT_HIT latency_ms=50"
            else:
                self.cache_hits += 1
                return f"RESULT key={key} val={entry.val} action=CACHE_HIT latency_ms=0"

        elif self.strategy == "XFETCH":
            if delta_s <= 0:
                # Already expired fallback
                self.db_queries += 1
                entry.expiry = n + entry.ttl
                return f"RESULT key={key} val={entry.val} action=CACHE_MISS_DB_QUERY latency_ms={entry.compute_ms}"
            else:
                # XFetch probabilistic test: -compute_ms * beta * ln(rand) > delta_ms
                xfetch_val = -entry.compute_ms * self.beta * math.log(r)
                if xfetch_val > delta_ms:
                    # Probabilistic early refresh triggered!
                    self.early_refreshes += 1
                    self.db_queries += 1
                    self.cache_hits += 1
                    entry.expiry = n + entry.ttl # Extended early!
                    return f"RESULT key={key} val={entry.val} action=XFETCH_EARLY_REFRESH latency_ms=0"
                else:
                    self.cache_hits += 1
                    return f"RESULT key={key} val={entry.val} action=CACHE_HIT latency_ms=0"

        return "ERROR unknown_strategy"

    def stats(self):
        return f"STATS cache_hits={self.cache_hits} db_queries={self.db_queries} early_refreshes={self.early_refreshes} lock_waits={self.lock_waits}"

def main():
    sim = CacheStampedeSimulator()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]

        if cmd == "CONFIG":
            params = {}
            for p in parts[1:]:
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            print(sim.config(
                strategy=params.get('strategy'),
                beta=params.get('beta'),
                compute_ms=params.get('compute_ms')
            ))

        elif cmd == "SET_CACHE":
            params = {}
            for p in parts[1:]:
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            print(sim.set_cache(
                key=params.get('key', 'default'),
                val=params.get('val', 'val'),
                ttl=params.get('ttl', 60),
                compute_ms=params.get('compute_ms'),
                now=params.get('now', 0)
            ))

        elif cmd == "GET":
            params = {}
            for p in parts[1:]:
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k] = v
            print(sim.get(
                key=params.get('key', 'default'),
                now=params.get('now', 0),
                rand_val=params.get('rand', 0.5)
            ))

        elif cmd == "STATS":
            print(sim.stats())

        elif cmd == "RESET":
            sim.reset()
            print("OK strategy=NAIVE beta=1.00 compute_ms=100")

if __name__ == '__main__':
    main()
