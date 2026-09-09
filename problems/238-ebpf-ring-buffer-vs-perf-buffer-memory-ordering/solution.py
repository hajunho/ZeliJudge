import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    buffer_type = config.get("buffer_type", "RINGBUF")
    num_cpus = int(config.get("num_cpu_cores", 128))
    buffer_per_cpu_mb = float(config.get("buffer_size_per_cpu_mb", 8.0))
    shared_ringbuf_size_mb = float(config.get("shared_ringbuf_size_mb", 16.0))
    consumer_drain_mbps = float(config.get("consumer_drain_rate_mbps", 500.0))
    kernel_version = config.get("kernel_version", "5.15")

    workload = data.get("workload", {})
    total_events = int(workload.get("total_events", 500000))
    event_size = int(workload.get("event_size_bytes", 128))
    core_dist = workload.get("core_distribution", "SKEWED_CORE_ZERO")
    duration_sec = float(workload.get("duration_sec", 1.0))
    reserve_leak = bool(workload.get("uncommitted_reserve_leak", False))

    kv_parts = [int(x) for x in kernel_version.split(".")[:2]]
    if buffer_type == "RINGBUF" and (kv_parts[0] < 5 or (kv_parts[0] == 5 and kv_parts[1] < 8)):
        result = {
            "status": "FAILED",
            "verdict": "RINGBUF_UNSUPPORTED_KERNEL_VERSION",
            "metrics": {
                "total_memory_allocated_mb": 0.0,
                "dropped_events_count": total_events,
                "memory_reduction_pct": 0.0,
                "strict_ordering_guaranteed": False,
                "core_skew_drop_detected": False
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    total_data_mb = (total_events * event_size) / (1024 * 1024)

    if buffer_type == "PERF_BUFFER":
        total_mem_mb = round(num_cpus * buffer_per_cpu_mb, 2)
        if core_dist == "SKEWED_CORE_ZERO":
            core0_data_mb = total_data_mb * 0.80
            core0_drain_mb = (consumer_drain_mbps / num_cpus) * duration_sec * 4.0
            core0_accumulated = core0_data_mb - core0_drain_mb
            if core0_accumulated > buffer_per_cpu_mb:
                overflow_mb = core0_accumulated - buffer_per_cpu_mb
                dropped_events = int((overflow_mb * 1024 * 1024) / event_size)
                result = {
                    "status": "FAILED",
                    "verdict": "PERF_BUFFER_CORE_SKEW_EVENT_DROPS",
                    "metrics": {
                        "total_memory_allocated_mb": total_mem_mb,
                        "dropped_events_count": dropped_events,
                        "memory_reduction_pct": 0.0,
                        "strict_ordering_guaranteed": False,
                        "core_skew_drop_detected": True
                    }
                }
                print(json.dumps(result, ensure_ascii=False))
                return

        dropped_events = 0
        if total_mem_mb >= 512.0:
            status = "WARNING"
            verdict = "PERF_BUFFER_MASSIVE_MEMORY_BLOAT"
        else:
            status = "SUCCESS"
            verdict = "PERF_BUFFER_BALANCED_BASELINE"

        result = {
            "status": status,
            "verdict": verdict,
            "metrics": {
                "total_memory_allocated_mb": total_mem_mb,
                "dropped_events_count": dropped_events,
                "memory_reduction_pct": 0.0,
                "strict_ordering_guaranteed": False,
                "core_skew_drop_detected": False
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    elif buffer_type == "RINGBUF":
        total_mem_mb = round(shared_ringbuf_size_mb, 2)
        baseline_perf_mem = num_cpus * buffer_per_cpu_mb
        mem_reduction_pct = round((1.0 - (total_mem_mb / max(0.01, baseline_perf_mem))) * 100.0, 1)

        if reserve_leak:
            result = {
                "status": "FAILED",
                "verdict": "RINGBUF_RESERVATION_LEAK_DEADLOCK",
                "metrics": {
                    "total_memory_allocated_mb": total_mem_mb,
                    "dropped_events_count": total_events,
                    "memory_reduction_pct": mem_reduction_pct,
                    "strict_ordering_guaranteed": False,
                    "core_skew_drop_detected": False
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return

        drained_total_mb = consumer_drain_mbps * duration_sec
        accumulated_mb = total_data_mb - drained_total_mb
        if accumulated_mb > shared_ringbuf_size_mb:
            overflow_mb = accumulated_mb - shared_ringbuf_size_mb
            dropped_events = int((overflow_mb * 1024 * 1024) / event_size)
            result = {
                "status": "FAILED",
                "verdict": "RINGBUF_SHARED_BUFFER_OVERFLOW",
                "metrics": {
                    "total_memory_allocated_mb": total_mem_mb,
                    "dropped_events_count": dropped_events,
                    "memory_reduction_pct": mem_reduction_pct,
                    "strict_ordering_guaranteed": False,
                    "core_skew_drop_detected": False
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return

        result = {
            "status": "SUCCESS",
            "verdict": "OPTIMAL_EBPF_RINGBUF_STREAMING",
            "metrics": {
                "total_memory_allocated_mb": total_mem_mb,
                "dropped_events_count": 0,
                "memory_reduction_pct": mem_reduction_pct,
                "strict_ordering_guaranteed": True,
                "core_skew_drop_detected": False
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

if __name__ == "__main__":
    solve()
