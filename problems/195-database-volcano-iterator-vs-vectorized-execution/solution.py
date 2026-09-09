# scratch/sim_195.py
import json
import math
import sys
from typing import Dict, List, Any, Optional

class DatabaseQueryEngineSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.engine_mode = sys_cfg.get("execution_engine", "VECTORIZED")
        # Supported: "VOLCANO_ITERATOR", "VECTORIZED"
        self.vector_batch_size = sys_cfg.get("vector_batch_size", 1024)
        self.join_algorithm = sys_cfg.get("join_algorithm", "RADIX_PARTITIONED_HASH_JOIN")
        # Supported: "NAIVE_HASH_JOIN", "RADIX_PARTITIONED_HASH_JOIN"
        self.l3_cache_capacity_tuples = sys_cfg.get("l3_cache_capacity_tuples", 50000)

        self.query_plan = data.get("query_plan", {})
        # query_plan contains: scan_tuples_count, filter_selectivity, join_tuples_count

        self.scan_tuples = self.query_plan.get("scan_tuples_count", 100000)
        self.filter_selectivity = self.query_plan.get("filter_selectivity", 0.5)
        self.build_table_tuples = self.query_plan.get("build_table_tuples", 100000)

        # Cost parameters
        self.virtual_call_cost_ns = sys_cfg.get("virtual_call_cost_ns", 15.0) # 15ns per virtual next() call
        self.simd_speedup_factor = sys_cfg.get("simd_speedup_factor", 4.0)     # 4x faster with SIMD vectorization
        self.cache_miss_cost_ns = sys_cfg.get("cache_miss_cost_ns", 100.0)    # 100ns per L3 cache miss
        self.base_tuple_eval_ns = sys_cfg.get("base_tuple_eval_ns", 20.0)     # 20ns baseline tuple work

    def run(self) -> Dict[str, Any]:
        # 1. Operators in pipeline: Scan -> Filter -> Project -> HashJoin -> Aggregate (5 operators)
        num_operators = 5

        filtered_tuples = int(self.scan_tuples * self.filter_selectivity)
        joined_tuples = int(filtered_tuples * 0.8)

        # Calculate metrics based on engine mode
        if self.engine_mode == "VOLCANO_ITERATOR":
            # 1 function call per tuple per operator
            total_virtual_calls = self.scan_tuples * num_operators
            eval_cost_per_tuple_ns = self.base_tuple_eval_ns
            simd_applied = False
            batch_count = self.scan_tuples
        else: # VECTORIZED
            # 1 function call per BATCH of tuples per operator
            batches = math.ceil(self.scan_tuples / self.vector_batch_size)
            total_virtual_calls = batches * num_operators
            # SIMD reduces evaluation cost by simd_speedup_factor
            eval_cost_per_tuple_ns = self.base_tuple_eval_ns / self.simd_speedup_factor
            simd_applied = True
            batch_count = batches

        # Join cache behavior
        if self.join_algorithm == "NAIVE_HASH_JOIN":
            if self.build_table_tuples > self.l3_cache_capacity_tuples:
                # Cache thrashing! Almost every probe causes L3 miss
                cache_miss_rate = 0.85
            else:
                cache_miss_rate = 0.05
            radix_partitioning_applied = False
        else: # RADIX_PARTITIONED_HASH_JOIN
            # Sub-partitions fit in L1/L2 cache, 0% L3 miss
            cache_miss_rate = 0.02
            radix_partitioning_applied = True

        cache_misses = int(filtered_tuples * cache_miss_rate)

        # Execution time calculation
        virtual_call_overhead_ns = total_virtual_calls * self.virtual_call_cost_ns
        cpu_eval_time_ns = self.scan_tuples * eval_cost_per_tuple_ns
        cache_miss_stall_time_ns = cache_misses * self.cache_miss_cost_ns

        total_execution_time_ns = virtual_call_overhead_ns + cpu_eval_time_ns + cache_miss_stall_time_ns
        total_execution_time_ms = round(total_execution_time_ns / 1_000_000.0, 3)

        # Verdict evaluation
        if self.engine_mode == "VOLCANO_ITERATOR" and self.join_algorithm == "NAIVE_HASH_JOIN" and cache_miss_rate > 0.5:
            status = "FAILED"
            verdict = "VOLCANO_ITERATOR_CACHE_THRASHING_COLLAPSE"
        elif self.engine_mode == "VOLCANO_ITERATOR":
            status = "FAILED"
            verdict = "VOLCANO_ITERATOR_VIRTUAL_CALL_BOTTLENECK"
        elif self.join_algorithm == "NAIVE_HASH_JOIN" and cache_miss_rate > 0.5:
            status = "FAILED"
            verdict = "NAIVE_HASH_JOIN_CACHE_MISS_STALL"
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_VECTORIZED_RADIX_JOIN"

        return {
            "status": status,
            "engine_config": {
                "execution_engine": self.engine_mode,
                "vector_batch_size": self.vector_batch_size if self.engine_mode == "VECTORIZED" else 1,
                "join_algorithm": self.join_algorithm,
                "simd_vectorization": simd_applied,
                "radix_partitioning": radix_partitioning_applied
            },
            "metrics": {
                "total_tuples_processed": self.scan_tuples,
                "output_tuples": joined_tuples,
                "total_virtual_calls": total_virtual_calls,
                "virtual_call_overhead_ms": round(virtual_call_overhead_ns / 1_000_000.0, 3),
                "cache_misses": cache_misses,
                "cache_miss_stall_ms": round(cache_miss_stall_time_ns / 1_000_000.0, 3),
                "total_execution_time_ms": total_execution_time_ms,
                "verdict": verdict
            }
        }

if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    sim = DatabaseQueryEngineSimulator(input_data)
    res = sim.run()
    print(json.dumps(res, indent=2))
