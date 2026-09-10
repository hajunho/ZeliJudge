# -*- coding: utf-8 -*-
import sys
import json
from collections import OrderedDict

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class AdaptiveReplacementCache:
    def __init__(self, c, initial_p=0.0):
        self.c = max(1, int(c))
        self.p = float(initial_p)
        
        self.t1 = OrderedDict()
        self.t2 = OrderedDict()
        self.b1 = OrderedDict()
        self.b2 = OrderedDict()
        
        self.hits = 0
        self.misses = 0
        self.t1_hits = 0
        self.t2_hits = 0
        self.b1_hits = 0
        self.b2_hits = 0

    def _replace(self, in_b2):
        t1_len = len(self.t1)
        if t1_len > 0 and (t1_len > self.p or (in_b2 and t1_len == int(self.p))):
            k, v = self.t1.popitem(last=False)
            self.b1[k] = v
        else:
            if len(self.t2) > 0:
                k, v = self.t2.popitem(last=False)
                self.b2[k] = v
            elif len(self.t1) > 0:
                k, v = self.t1.popitem(last=False)
                self.b1[k] = v

    def access(self, key):
        if key in self.t1:
            self.hits += 1
            self.t1_hits += 1
            val = self.t1.pop(key)
            self.t2[key] = val
            return True
        elif key in self.t2:
            self.hits += 1
            self.t2_hits += 1
            val = self.t2.pop(key)
            self.t2[key] = val
            return True

        self.misses += 1

        if key in self.b1:
            self.b1_hits += 1
            delta = max(1, len(self.b2) // max(1, len(self.b1)))
            self.p = min(float(self.c), self.p + delta)
            self._replace(in_b2=False)
            val = self.b1.pop(key)
            self.t2[key] = val
            return False

        if key in self.b2:
            self.b2_hits += 1
            delta = max(1, len(self.b1) // max(1, len(self.b2)))
            self.p = max(0.0, self.p - delta)
            self._replace(in_b2=True)
            val = self.b2.pop(key)
            self.t2[key] = val
            return False

        l1_len = len(self.t1) + len(self.b1)
        l2_len = len(self.t2) + len(self.b2)
        
        if l1_len == self.c:
            if len(self.t1) < self.c:
                if len(self.b1) > 0:
                    self.b1.popitem(last=False)
                self._replace(in_b2=False)
            else:
                if len(self.t1) > 0:
                    self.t1.popitem(last=False)
        elif l1_len < self.c:
            total_len = l1_len + l2_len
            if total_len >= self.c:
                if total_len == 2 * self.c and len(self.b2) > 0:
                    self.b2.popitem(last=False)
                self._replace(in_b2=False)

        self.t1[key] = True
        return False

    def stats(self):
        total = self.hits + self.misses
        return {
            "capacity": self.c,
            "target_p": round(self.p, 2),
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": total,
            "hit_ratio": round(self.hits / total, 4) if total > 0 else 0.0,
            "list_sizes": {
                "t1_recent": len(self.t1),
                "t2_frequent": len(self.t2),
                "b1_ghost_recent": len(self.b1),
                "b2_ghost_frequent": len(self.b2)
            },
            "ghost_hits": {
                "b1_recency_hits": self.b1_hits,
                "b2_frequency_hits": self.b2_hits
            }
        }

class StandardLRU:
    def __init__(self, c):
        self.c = max(1, int(c))
        self.cache = OrderedDict()
        self.hits = 0
        self.misses = 0

    def access(self, key):
        if key in self.cache:
            self.hits += 1
            val = self.cache.pop(key)
            self.cache[key] = val
            return True
        self.misses += 1
        if len(self.cache) >= self.c:
            self.cache.popitem(last=False)
        self.cache[key] = True
        return False

    def stats(self):
        total = self.hits + self.misses
        return {
            "capacity": self.c,
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": total,
            "hit_ratio": round(self.hits / total, 4) if total > 0 else 0.0,
            "cache_size": len(self.cache)
        }

def simulate_trace(capacity, trace, initial_p=0.0, compare_with_lru=True):
    arc = AdaptiveReplacementCache(capacity, initial_p)
    lru = StandardLRU(capacity) if compare_with_lru else None

    for item in trace:
        key = item.get("key", item.get("page_id", "K_0"))
        arc.access(key)
        if lru:
            lru.access(key)

    res = {
        "arc_stats": arc.stats()
    }
    if lru:
        res["lru_stats"] = lru.stats()
    return res

def run_scan_benchmark(capacity, working_set_size, scan_size, loops_before=5):
    c = capacity
    arc = AdaptiveReplacementCache(c)
    lru = StandardLRU(c)

    hot_keys = [f"HOT_{i}" for i in range(working_set_size)]
    scan_keys = [f"SCAN_{i}" for i in range(scan_size)]

    # Phase 1: Working set warming
    for _ in range(loops_before):
        for k in hot_keys:
            arc.access(k)
            lru.access(k)

    # Phase 2: Sequential scan (cold accesses)
    for k in scan_keys:
        arc.access(k)
        lru.access(k)

    # Measure retention after scan
    arc_retained = sum(1 for k in hot_keys if k in arc.t1 or k in arc.t2)
    lru_retained = sum(1 for k in hot_keys if k in lru.cache)

    arc_retention_pct = round((arc_retained / working_set_size) * 100.0, 2)
    lru_retention_pct = round((lru_retained / working_set_size) * 100.0, 2)

    # Phase 3: Post-scan query of working set
    for k in hot_keys:
        arc.access(k)
        lru.access(k)

    verdict = "ARC_PROTECTED_WORKING_SET" if arc_retention_pct >= 80.0 and lru_retention_pct < 20.0 else "COMPARATIVE_ANALYSIS_COMPLETE"

    return {
        "working_set_size": working_set_size,
        "scan_size": scan_size,
        "capacity": capacity,
        "retention": {
            "arc_working_set_retained_pct": arc_retention_pct,
            "lru_working_set_retained_pct": lru_retention_pct
        },
        "arc_stats": arc.stats(),
        "lru_stats": lru.stats(),
        "verdict": verdict
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    mode = data.get("mode", "SIMULATE_CACHE_TRACE")

    if mode == "SIMULATE_CACHE_TRACE":
        c = data.get("cache_capacity", 50)
        trace = data.get("trace", [])
        init_p = data.get("initial_p", 0.0)
        compare = data.get("compare_with_lru", True)
        res = simulate_trace(c, trace, init_p, compare)
        print(json.dumps(res, ensure_ascii=False))
    elif mode == "SCAN_RESISTANCE_BENCHMARK":
        c = data.get("cache_capacity", 50)
        ws_size = data.get("working_set_size", 30)
        scan_size = data.get("scan_size", 200)
        loops = data.get("loops_before", 5)
        res = run_scan_benchmark(c, ws_size, scan_size, loops)
        print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
