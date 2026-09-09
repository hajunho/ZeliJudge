import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    io_engine = config.get("io_engine", "IO_URING")
    direct_io = bool(config.get("direct_io", True))
    sq_entries = int(config.get("sq_entries", 512))
    sqpoll_enabled = bool(config.get("sqpoll_enabled", True))
    sqpoll_idle_timeout_ms = int(config.get("sqpoll_idle_timeout_ms", 2000))
    fixed_buffers_enabled = bool(config.get("fixed_buffers_enabled", True))
    iopoll_enabled = bool(config.get("iopoll_enabled", True))
    sla_latency_us = float(config.get("sla_latency_us", 20.0))

    workload = data.get("workload", {})
    target_iops = float(workload.get("target_iops", 500000.0))
    io_size_bytes = int(workload.get("io_size_bytes", 4096))
    traffic_profile = workload.get("traffic_profile", "ACTIVE")

    syscalls_per_sec = 0
    actual_iops = 0.0
    avg_latency_us = 0.0
    sq_overflow = False

    if io_engine == "POSIX_AIO":
        if not direct_io:
            result = {
                "status": "FAILED",
                "verdict": "POSIX_AIO_NON_DIRECT_SYNCHRONOUS_BLOCKING_FALLBACK",
                "metrics": {
                    "io_engine": io_engine,
                    "actual_iops": min(50000.0, target_iops),
                    "throughput_mbps": round((min(50000.0, target_iops) * io_size_bytes) / (1024.0 * 1024.0), 2),
                    "syscalls_per_sec": int(min(50000.0, target_iops)),
                    "avg_latency_us": 180.0,
                    "sq_overflow": False,
                    "zero_syscall_rate": 0.0
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return

        batch_size = 32
        max_capacity_iops = 320000.0
        actual_iops = min(target_iops, max_capacity_iops)
        syscalls_per_sec = int((actual_iops / batch_size) * 2)
        avg_latency_us = 35.0 + (15.0 * (actual_iops / max_capacity_iops))

        if avg_latency_us > sla_latency_us or actual_iops < target_iops:
            status = "FAILED"
            verdict = "POSIX_AIO_SYSCALL_CONTEXT_SWITCH_BOTTLENECK"
        else:
            status = "SUCCESS"
            verdict = "STANDARD_POSIX_AIO_SUCCESS"

    elif io_engine == "IO_URING":
        concurrency = target_iops * (sla_latency_us / 1000000.0)
        concurrency = max(16, concurrency)
        burst_inflight = concurrency * 2.5

        if burst_inflight > sq_entries:
            sq_overflow = True
            actual_iops = (sq_entries / burst_inflight) * target_iops
            avg_latency_us = 45.0
            throughput_mbps = (actual_iops * io_size_bytes) / (1024.0 * 1024.0)
            result = {
                "status": "FAILED",
                "verdict": "IO_URING_SQ_RING_OVERFLOW_DROP",
                "metrics": {
                    "io_engine": io_engine,
                    "actual_iops": round(actual_iops, 1),
                    "throughput_mbps": round(throughput_mbps, 2),
                    "syscalls_per_sec": 0,
                    "avg_latency_us": round(avg_latency_us, 2),
                    "sq_overflow": True,
                    "zero_syscall_rate": 1.0 if sqpoll_enabled else 0.0
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return

        if traffic_profile == "IDLE":
            if sqpoll_enabled and sqpoll_idle_timeout_ms > 5000:
                status = "WARNING"
                verdict = "IO_URING_SQPOLL_CPU_SPIN_ENERGY_WASTE"
                actual_iops = target_iops
                avg_latency_us = 3.5
                syscalls_per_sec = 0
            else:
                status = "SUCCESS"
                verdict = "IO_URING_SQPOLL_IDLE_SLEEP_OPTIMIZED"
                actual_iops = target_iops
                avg_latency_us = 6.5
                syscalls_per_sec = 0
        else:
            if sqpoll_enabled:
                syscalls_per_sec = 0
                base_latency_us = 5.0
            else:
                batch_size = 64
                syscalls_per_sec = int(target_iops / batch_size)
                base_latency_us = 12.0

            page_pin_overhead_us = 4.5 if not fixed_buffers_enabled else 0.0
            irq_latency_us = 6.0 if not iopoll_enabled else 0.0

            avg_latency_us = base_latency_us + page_pin_overhead_us + irq_latency_us
            actual_iops = target_iops

            if avg_latency_us > sla_latency_us:
                status = "FAILED"
                verdict = "IO_URING_LATENCY_SLA_EXCEEDED"
            elif sqpoll_enabled and fixed_buffers_enabled and iopoll_enabled:
                status = "SUCCESS"
                verdict = "OPTIMAL_IO_URING_ZERO_SYSCALL_FIXED_BUFFER"
            else:
                status = "SUCCESS"
                verdict = "STANDARD_IO_URING_PARTIAL_OPTIMIZED"
    else:
        status = "FAILED"
        verdict = "UNKNOWN_IO_ENGINE"

    zero_syscall_rate = 1.0 if syscalls_per_sec == 0 else 0.0
    throughput_mbps = (actual_iops * io_size_bytes) / (1024.0 * 1024.0)

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "io_engine": io_engine,
            "actual_iops": round(actual_iops, 1),
            "throughput_mbps": round(throughput_mbps, 2),
            "syscalls_per_sec": syscalls_per_sec,
            "avg_latency_us": round(avg_latency_us, 2),
            "sq_overflow": sq_overflow,
            "zero_syscall_rate": round(zero_syscall_rate, 2)
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
