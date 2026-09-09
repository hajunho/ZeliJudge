# Core simulator implementation for Problem 178: LSM-Tree SSTable Bloom Filter & Point Lookup I/O Amplification
from typing import Dict, List, Any, Optional
import hashlib
import json
import math
import sys

def murmur_like_hashes(key: str):
    h = hashlib.sha256(key.encode("utf-8")).digest()
    h1 = int.from_bytes(h[0:8], byteorder="big", signed=False)
    h2 = int.from_bytes(h[8:16], byteorder="big", signed=False)
    if h2 == 0:
        h2 = 1
    return h1, h2

class SSTableBloomFilter:
    def __init__(self, keys: List[str], bits_per_key: float, use_double_hashing: bool = True):
        self.n = len(keys)
        if self.n == 0:
            self.m = 64
            self.k = 1
            self.bit_array = [0] * self.m
            return

        self.m = max(64, int(self.n * bits_per_key))
        # Optimal k = (m / n) * ln(2)
        self.k = max(1, min(30, int(round((self.m / self.n) * math.log(2)))))
        self.use_double_hashing = use_double_hashing
        self.bit_array = [0] * self.m

        for key in keys:
            self.add(key)

    def add(self, key: str):
        h1, h2 = murmur_like_hashes(key)
        for i in range(self.k):
            if self.use_double_hashing:
                # Kirsch-Mitzenmacher optimization: gi = (h1 + i * h2) % m
                bit_idx = (h1 + i * h2) % self.m
            else:
                h_sub = int.from_bytes(hashlib.md5(f"{key}:{i}".encode("utf-8")).digest()[:8], "big")
                bit_idx = h_sub % self.m
            self.bit_array[bit_idx] = 1

    def contains(self, key: str) -> bool:
        h1, h2 = murmur_like_hashes(key)
        for i in range(self.k):
            if self.use_double_hashing:
                bit_idx = (h1 + i * h2) % self.m
            else:
                h_sub = int.from_bytes(hashlib.md5(f"{key}:{i}".encode("utf-8")).digest()[:8], "big")
                bit_idx = h_sub % self.m
            if self.bit_array[bit_idx] == 0:
                return False
        return True

class SSTable:
    def __init__(self, sstable_id: str, kv_pairs: Dict[str, str], bits_per_key: float, filter_enabled: bool, use_double_hashing: bool):
        self.id = sstable_id
        self.kv_pairs = kv_pairs
        self.keys = sorted(list(kv_pairs.keys()))
        self.min_key = self.keys[0] if self.keys else ""
        self.max_key = self.keys[-1] if self.keys else ""
        self.filter_enabled = filter_enabled
        if filter_enabled:
            self.filter = SSTableBloomFilter(self.keys, bits_per_key, use_double_hashing)
        else:
            self.filter = None

    def key_in_range(self, key: str) -> bool:
        if not self.keys:
            return False
        return self.min_key <= key <= self.max_key

    def may_contain(self, key: str) -> bool:
        if not self.filter_enabled or self.filter is None:
            return True
        return self.filter.contains(key)

class LSMStorageEngine:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.bits_per_key: float = sys_cfg.get("bits_per_key", 10.0)
        self.filter_enabled: bool = sys_cfg.get("enable_bloom_filter", True)
        self.use_double_hashing: bool = sys_cfg.get("use_double_hashing", True)
        self.cache_capacity: int = sys_cfg.get("block_cache_capacity_blocks", 100)
        self.disk_read_latency_us: float = sys_cfg.get("disk_read_latency_us", 200.0)
        self.cache_read_latency_us: float = sys_cfg.get("cache_read_latency_us", 5.0)
        self.filter_check_latency_us: float = sys_cfg.get("filter_check_latency_us", 0.5)

        sstables_data = data.get("sstables", [])
        self.sstables: List[SSTable] = []
        for sst in sstables_data:
            self.sstables.append(SSTable(
                sst["id"],
                sst["data"],
                self.bits_per_key,
                self.filter_enabled,
                self.use_double_hashing
            ))

        self.block_cache = set()

        # Cumulative Metrics
        self.total_queries: int = 0
        self.range_checks: int = 0
        self.filter_checks: int = 0
        self.true_negatives_filtered: int = 0
        self.false_positives_wasted: int = 0
        self.true_positives: int = 0
        self.disk_io_reads: int = 0
        self.cache_hits: int = 0
        self.total_latency_us: float = 0.0
        self.query_results: List[Dict[str, Any]] = []

    def query(self, key: str):
        self.total_queries += 1
        found_value = None
        query_latency = 0.0
        sstable_lookups = 0

        # Point lookup: search from newest to oldest SSTable (reversed order)
        for sst in reversed(self.sstables):
            self.range_checks += 1
            if not sst.key_in_range(key):
                continue

            sstable_lookups += 1
            # Step 1: Bloom filter evaluation
            if sst.filter_enabled:
                self.filter_checks += 1
                query_latency += self.filter_check_latency_us
                may_exist = sst.may_contain(key)
                if not may_exist:
                    # True Negative: Key definitively not in SSTable! Zero disk I/O!
                    self.true_negatives_filtered += 1
                    continue

            # Step 2: Key may exist (Filter returned True or filter disabled)
            cache_key = f"{sst.id}:{key}"
            if cache_key in self.block_cache:
                self.cache_hits += 1
                query_latency += self.cache_read_latency_us
            else:
                self.disk_io_reads += 1
                query_latency += self.disk_read_latency_us
                if len(self.block_cache) < self.cache_capacity:
                    self.block_cache.add(cache_key)

            # Step 3: Check actual key presence
            if key in sst.kv_pairs:
                found_value = sst.kv_pairs[key]
                self.true_positives += 1
                break  # Point lookup succeeds, terminate search
            else:
                # False Positive: Filter said True, but key does not exist! Wasted disk I/O!
                if sst.filter_enabled:
                    self.false_positives_wasted += 1

        self.total_latency_us += query_latency
        self.query_results.append({
            "key": key,
            "found": found_value is not None,
            "value": found_value,
            "latency_us": round(query_latency, 2),
            "sstable_lookups": sstable_lookups
        })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for q in workload:
            self.query(q["key"])

        total_negative_checks = self.true_negatives_filtered + self.false_positives_wasted
        if total_negative_checks > 0:
            empirical_fpr = round(self.false_positives_wasted / total_negative_checks, 4)
        else:
            empirical_fpr = 0.0

        avg_latency = round(self.total_latency_us / self.total_queries, 2) if self.total_queries > 0 else 0.0

        if self.filter_enabled and self.bits_per_key > 0:
            theoretical_fpr = round(math.pow(0.6185, self.bits_per_key), 4)
        else:
            theoretical_fpr = 1.0

        if not self.filter_enabled:
            verdict = "CATASTROPHIC_READ_AMPLIFICATION_NO_FILTER"
        elif self.bits_per_key < 4.0:
            verdict = "HIGH_FALSE_POSITIVE_CACHE_POLLUTION"
        elif self.false_positives_wasted > 0:
            verdict = "OPTIMAL_BLOOM_FILTER_BOUNDED_FPR"
        elif self.true_negatives_filtered > 0:
            verdict = "PERFECT_NEGATIVE_FILTERING"
        else:
            verdict = "ALL_TRUE_POSITIVES"

        return {
            "status": "SUCCESS",
            "summary": {
                "enable_bloom_filter": self.filter_enabled,
                "bits_per_key": self.bits_per_key,
                "use_double_hashing": self.use_double_hashing,
                "total_sstables": len(self.sstables),
                "theoretical_fpr": theoretical_fpr,
                "empirical_fpr": empirical_fpr
            },
            "metrics": {
                "total_queries": self.total_queries,
                "range_checks": self.range_checks,
                "filter_checks": self.filter_checks,
                "true_negatives_filtered": self.true_negatives_filtered,
                "false_positives_wasted_io": self.false_positives_wasted,
                "true_positives": self.true_positives,
                "disk_io_reads": self.disk_io_reads,
                "cache_hits": self.cache_hits,
                "total_latency_us": round(self.total_latency_us, 2),
                "average_latency_us": avg_latency,
                "verdict": verdict
            },
            "sample_queries": self.query_results[:20]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sim = LSMStorageEngine(input_data)
    workload = input_data.get("workload", [])
    return sim.run(workload)

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
