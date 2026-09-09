import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    driver_type = config.get("driver_type", "VIRTIO_NET")
    queue_size = int(config.get("queue_size", 256))
    hugepages_enabled = bool(config.get("hugepages_enabled", False))
    pmd_cores = int(config.get("pmd_cores", 1))
    adaptive_interrupt_enabled = bool(config.get("adaptive_interrupt_enabled", False))
    target_sla_drop_rate = float(config.get("target_sla_drop_rate", 0.001))

    workload = data.get("workload", {})
    packet_rate_mpps = float(workload.get("packet_rate_mpps", 2.0))
    packet_size_bytes = int(workload.get("packet_size_bytes", 64))
    traffic_profile = workload.get("traffic_profile", "ACTIVE")

    if driver_type == "VIRTIO_NET":
        max_capacity_mpps = 0.9 * (1.0 if queue_size >= 512 else 0.75)
        batch_size = 8
        vm_exits_per_sec = int((min(packet_rate_mpps, max_capacity_mpps) * 1000000) / batch_size)

        if packet_rate_mpps > max_capacity_mpps:
            dropped_mpps = packet_rate_mpps - max_capacity_mpps
            drop_rate = dropped_mpps / packet_rate_mpps
            actual_throughput_mpps = max_capacity_mpps
        else:
            drop_rate = 0.0
            actual_throughput_mpps = packet_rate_mpps

        avg_latency_us = 45.0 + (30.0 * (packet_rate_mpps / max_capacity_mpps))
        cpu_utilization_pct = min(100.0, (packet_rate_mpps / max_capacity_mpps) * 98.0)

        if drop_rate > target_sla_drop_rate:
            status = "FAILED"
            verdict = "PURE_VIRTIO_VM_EXIT_IO_TRAP_BOTTLENECK"
        else:
            status = "SUCCESS"
            verdict = "STANDARD_VIRTIO_NET_SUCCESS"

    elif driver_type == "VHOST_NET":
        max_capacity_mpps = 2.8 * (1.2 if queue_size >= 1024 else (1.0 if queue_size >= 512 else 0.7))
        batch_size = 32
        vm_exits_per_sec = int((min(packet_rate_mpps, max_capacity_mpps) * 1000000) / batch_size)

        if queue_size < 512 and packet_rate_mpps > 2.0:
            actual_throughput_mpps = max_capacity_mpps * 0.7
            drop_rate = (packet_rate_mpps - actual_throughput_mpps) / packet_rate_mpps
            avg_latency_us = 25.0
            status = "FAILED"
            verdict = "VHOST_NET_RING_OVERFLOW_PACKET_DROP"
        elif packet_rate_mpps > max_capacity_mpps:
            actual_throughput_mpps = max_capacity_mpps
            drop_rate = (packet_rate_mpps - actual_throughput_mpps) / packet_rate_mpps
            avg_latency_us = 20.0
            status = "FAILED"
            verdict = "VHOST_NET_KERNEL_WORKER_SATURATION"
        else:
            actual_throughput_mpps = packet_rate_mpps
            drop_rate = 0.0
            avg_latency_us = 12.0
            status = "SUCCESS"
            verdict = "VHOST_NET_STABLE_FORWARDING"

        cpu_utilization_pct = min(100.0, (packet_rate_mpps / max_capacity_mpps) * 90.0)

    elif driver_type == "VHOST_USER_DPDK":
        if not hugepages_enabled:
            result = {
                "status": "FAILED",
                "verdict": "DPDK_HUGEPAGES_DISABLED_ALLOCATION_FAILURE",
                "metrics": {
                    "driver_type": driver_type,
                    "actual_throughput_mpps": 0.0,
                    "throughput_gbps": 0.0,
                    "drop_rate": 1.0,
                    "avg_latency_us": 0.0,
                    "cpu_utilization_pct": 0.0,
                    "vm_exits_per_sec": 0
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return

        capacity_per_core = 5.5 * (1.15 if queue_size >= 1024 else 1.0)
        total_capacity_mpps = pmd_cores * capacity_per_core
        vm_exits_per_sec = 0

        if traffic_profile == "IDLE":
            if not adaptive_interrupt_enabled:
                status = "WARNING"
                verdict = "DPDK_IDLE_CPU_SPIN_ENERGY_WASTE"
                cpu_utilization_pct = 100.0
                actual_throughput_mpps = packet_rate_mpps
                avg_latency_us = 2.1
                drop_rate = 0.0
            else:
                status = "SUCCESS"
                verdict = "DPDK_ADAPTIVE_POLL_POWER_OPTIMIZED"
                cpu_utilization_pct = 3.5
                actual_throughput_mpps = packet_rate_mpps
                avg_latency_us = 8.5
                drop_rate = 0.0
        else:
            if packet_rate_mpps > total_capacity_mpps:
                actual_throughput_mpps = total_capacity_mpps
                drop_rate = (packet_rate_mpps - total_capacity_mpps) / packet_rate_mpps
                avg_latency_us = 15.0
                cpu_utilization_pct = 100.0
                status = "FAILED"
                verdict = "DPDK_PMD_CORE_STARVATION"
            else:
                actual_throughput_mpps = packet_rate_mpps
                drop_rate = 0.0
                avg_latency_us = 3.2
                cpu_utilization_pct = round((packet_rate_mpps / total_capacity_mpps) * 100.0, 1)
                status = "SUCCESS"
                verdict = "OPTIMAL_VHOST_USER_DPDK_ZERO_COPY"
    else:
        status = "FAILED"
        verdict = "UNKNOWN_DRIVER_TYPE"
        actual_throughput_mpps = 0.0
        drop_rate = 1.0
        avg_latency_us = 0.0
        cpu_utilization_pct = 0.0
        vm_exits_per_sec = 0

    throughput_gbps = (actual_throughput_mpps * 1000000.0 * (packet_size_bytes + 20) * 8.0) / 1000000000.0

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "driver_type": driver_type,
            "actual_throughput_mpps": round(actual_throughput_mpps, 2),
            "throughput_gbps": round(throughput_gbps, 2),
            "drop_rate": round(drop_rate, 4),
            "avg_latency_us": round(avg_latency_us, 2),
            "cpu_utilization_pct": round(cpu_utilization_pct, 1),
            "vm_exits_per_sec": vm_exits_per_sec
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
