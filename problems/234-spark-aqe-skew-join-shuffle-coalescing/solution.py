import sys
import json
import math
import statistics

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    aqe_enabled = bool(config.get("aqe_enabled", True))
    coalesce_shuffle_partitions_enabled = bool(config.get("coalesce_shuffle_partitions_enabled", True))
    skew_join_enabled = bool(config.get("skew_join_enabled", True))
    advisory_size_mb = float(config.get("advisory_partition_size_mb", 64.0))
    min_partition_size_mb = float(config.get("min_partition_size_mb", 1.0))
    skew_threshold_mb = float(config.get("skew_partition_threshold_mb", 256.0))
    skew_factor = float(config.get("skew_partition_factor", 5.0))
    auto_broadcast_threshold_mb = float(config.get("auto_broadcast_join_threshold_mb", 10.0))

    workload = data.get("workload", {})
    join_type = workload.get("join_type", "SORT_MERGE_JOIN")
    left_table_size_mb = float(workload.get("left_table_size_mb", 8.0))
    right_partitions = [float(x) for x in workload.get("right_table_partitions_mb", [15.0, 18.0, 20.0, 16.0, 600.0, 17.0, 19.0, 14.0])]
    driver_memory_mb = float(workload.get("driver_memory_mb", 4096.0))
    executor_memory_mb = float(workload.get("executor_memory_mb", 2048.0))

    num_initial_partitions = len(right_partitions)
    total_right_size_mb = sum(right_partitions)

    final_join_type = join_type
    broadcast_converted = False

    if aqe_enabled and join_type == "SORT_MERGE_JOIN" and left_table_size_mb <= auto_broadcast_threshold_mb:
        if left_table_size_mb * 3.0 > driver_memory_mb or left_table_size_mb * 2.0 > executor_memory_mb:
            result = {
                "status": "FAILED",
                "verdict": "BROADCAST_JOIN_OOM_CRASH",
                "metrics": {
                    "final_join_type": "BROADCAST_HASH_JOIN",
                    "final_num_partitions": num_initial_partitions,
                    "skewed_partitions_detected": 0,
                    "skew_splits_created": 0,
                    "max_task_duration_sec": 9999.0,
                    "disk_spill_mb": 0.0,
                    "straggler_ratio": 1.0
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return
        else:
            final_join_type = "BROADCAST_HASH_JOIN"
            broadcast_converted = True

    if broadcast_converted:
        max_part = max(right_partitions)
        max_duration = round(max_part / 30.0, 2)
        result = {
            "status": "SUCCESS",
            "verdict": "OPTIMAL_AQE_DYNAMIC_BROADCAST_HASH_JOIN",
            "metrics": {
                "final_join_type": final_join_type,
                "final_num_partitions": num_initial_partitions,
                "skewed_partitions_detected": 0,
                "skew_splits_created": 0,
                "max_task_duration_sec": max_duration,
                "disk_spill_mb": 0.0,
                "straggler_ratio": 1.0
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    median_size = statistics.median(right_partitions)
    skewed_partitions = []
    for idx, p_size in enumerate(right_partitions):
        if p_size >= skew_threshold_mb and p_size >= median_size * skew_factor:
            skewed_partitions.append((idx, p_size))

    avg_size = total_right_size_mb / max(1, num_initial_partitions)
    if num_initial_partitions > 50 and avg_size < min_partition_size_mb and (not aqe_enabled or not coalesce_shuffle_partitions_enabled):
        result = {
            "status": "WARNING",
            "verdict": "SMALL_SHUFFLE_PARTITIONS_SCHEDULING_OVERHEAD",
            "metrics": {
                "final_join_type": final_join_type,
                "final_num_partitions": num_initial_partitions,
                "skewed_partitions_detected": len(skewed_partitions),
                "skew_splits_created": 0,
                "max_task_duration_sec": 45.0,
                "disk_spill_mb": 0.0,
                "straggler_ratio": 1.0
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    final_num_partitions = num_initial_partitions
    skew_splits_created = 0
    disk_spill_mb = 0.0

    if skewed_partitions:
        if not aqe_enabled or not skew_join_enabled:
            worst_skew = max(p[1] for p in skewed_partitions)
            normal_max = max([p for i, p in enumerate(right_partitions) if (i, p) not in skewed_partitions] or [median_size])
            if worst_skew > executor_memory_mb * 0.25:
                disk_spill_mb = round(worst_skew * 1.5, 2)
                worst_duration = round((worst_skew / 10.0) * 3.5, 2)
            else:
                disk_spill_mb = 0.0
                worst_duration = round(worst_skew / 10.0, 2)
            normal_duration = max(1.0, round(normal_max / 10.0, 2))
            straggler_ratio = round(worst_duration / normal_duration, 2)

            result = {
                "status": "FAILED",
                "verdict": "SKEW_PARTITION_DISK_SPILL_STRAGGLER_STALL",
                "metrics": {
                    "final_join_type": final_join_type,
                    "final_num_partitions": final_num_partitions,
                    "skewed_partitions_detected": len(skewed_partitions),
                    "skew_splits_created": 0,
                    "max_task_duration_sec": worst_duration,
                    "disk_spill_mb": disk_spill_mb,
                    "straggler_ratio": straggler_ratio
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return
        else:
            extra_partitions = 0
            sub_partition_sizes = []
            for idx, p_size in skewed_partitions:
                num_splits = math.ceil(p_size / advisory_size_mb)
                skew_splits_created += num_splits
                extra_partitions += (num_splits - 1)
                sub_partition_sizes.extend([p_size / num_splits] * num_splits)

            final_num_partitions += extra_partitions
            all_final_sizes = [p for i, p in enumerate(right_partitions) if (i, p) not in skewed_partitions] + sub_partition_sizes
            max_task_size = max(all_final_sizes)
            max_duration = round(max_task_size / 10.0, 2)
            median_final = statistics.median(all_final_sizes)
            straggler_ratio = round(max_task_size / max(1.0, median_final), 2)

            result = {
                "status": "SUCCESS",
                "verdict": "OPTIMAL_AQE_SKEW_JOIN_PARALLEL_SPLIT",
                "metrics": {
                    "final_join_type": final_join_type,
                    "final_num_partitions": final_num_partitions,
                    "skewed_partitions_detected": len(skewed_partitions),
                    "skew_splits_created": skew_splits_created,
                    "max_task_duration_sec": max_duration,
                    "disk_spill_mb": 0.0,
                    "straggler_ratio": straggler_ratio
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return
    else:
        if aqe_enabled and coalesce_shuffle_partitions_enabled:
            coalesced_parts = math.ceil(total_right_size_mb / advisory_size_mb)
            final_num_partitions = min(num_initial_partitions, max(1, coalesced_parts))
            status = "SUCCESS"
            verdict = "OPTIMAL_AQE_SHUFFLE_PARTITION_COALESCED"
        else:
            status = "SUCCESS"
            verdict = "STATIC_SORT_MERGE_JOIN_BASELINE"

        max_duration = round(max(right_partitions) / 10.0, 2)
        straggler_ratio = round(max(right_partitions) / max(1.0, median_size), 2)

        result = {
            "status": status,
            "verdict": verdict,
            "metrics": {
                "final_join_type": final_join_type,
                "final_num_partitions": final_num_partitions,
                "skewed_partitions_detected": 0,
                "skew_splits_created": 0,
                "max_task_duration_sec": max_duration,
                "disk_spill_mb": 0.0,
                "straggler_ratio": straggler_ratio
            }
        }
        print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
