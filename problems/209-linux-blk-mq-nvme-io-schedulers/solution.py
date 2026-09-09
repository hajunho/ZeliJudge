#!/usr/bin/env python3
"""
ZeliJudge Problem #209: Linux Block Layer & NVMe I/O Schedulers - none vs mq-deadline vs Kyber vs BFQ under Multi-Queue SSD
리눅스 커널 blk-mq 블록 레이어 I/O 스케줄러: none vs mq-deadline vs kyber vs bfq & NVMe 멀티큐 스케줄링 경합

Reference Implementation
"""

import sys
import json
from typing import Dict, Any, List

def simulate_blk_mq(data: Dict[str, Any]) -> Dict[str, Any]:
    dev_cfg = data["device_config"]
    sched_cfg = data["scheduler_config"]
    scheduler = sched_cfg.get("scheduler", "none")  # none, mq-deadline, kyber, bfq

    base_read_us = dev_cfg.get("device_base_latency_us", {}).get("read_us", 50.0)
    base_write_us = dev_cfg.get("device_base_latency_us", {}).get("write_us", 30.0)
    max_iops = dev_cfg.get("max_device_iops", 800000)

    workload = data.get("workload", {})
    interactive_reads = workload.get("interactive_reads", {"iops": 50000, "duration_s": 1.0})
    background_writes = workload.get("background_writes", {"iops": 200000, "duration_s": 1.0})

    read_iops_req = interactive_reads.get("iops", 0)
    write_iops_req = background_writes.get("iops", 0)
    total_iops_req = read_iops_req + write_iops_req

    read_latencies_us = []
    achieved_read_iops = 0
    achieved_write_iops = 0
    cpu_spinlock_wait_pct = 0.0
    write_throttled = False

    if scheduler == "bfq":
        effective_iops_cap = 95000
        cpu_spinlock_wait_pct = 78.5
        scale = min(1.0, effective_iops_cap / total_iops_req) if total_iops_req > 0 else 1.0
        achieved_read_iops = int(read_iops_req * scale)
        achieved_write_iops = int(write_iops_req * scale)

        avg_read_lat = base_read_us + 12000.0 * (1.0 + (total_iops_req / effective_iops_cap))
        p99_read_lat = avg_read_lat * 2.8
        read_latencies_us = [avg_read_lat, p99_read_lat]
        verdict = "BFQ_NVME_SPINLOCK_COLLAPSE"

    elif scheduler == "mq-deadline":
        effective_iops_cap = 280000
        cpu_spinlock_wait_pct = 24.0
        scale = min(1.0, effective_iops_cap / total_iops_req) if total_iops_req > 0 else 1.0
        achieved_read_iops = int(read_iops_req * scale)
        achieved_write_iops = int(write_iops_req * scale)

        avg_read_lat = base_read_us + 650.0 * (total_iops_req / effective_iops_cap)
        p99_read_lat = avg_read_lat * 2.2
        read_latencies_us = [avg_read_lat, p99_read_lat]
        verdict = "MQ_DEADLINE_LOCK_CONTENTION_THROTTLED"

    elif scheduler == "kyber":
        effective_iops_cap = 750000
        cpu_spinlock_wait_pct = 2.5
        target_read_lat = sched_cfg.get("kyber", {}).get("target_read_latency_us", 2000.0)

        if total_iops_req > max_iops * 0.5 and write_iops_req > 100000:
            write_throttled = True
            achieved_read_iops = read_iops_req
            achieved_write_iops = min(write_iops_req, effective_iops_cap - read_iops_req)
            avg_read_lat = base_read_us + 220.0
            p99_read_lat = min(target_read_lat, avg_read_lat * 1.8)
        else:
            scale = min(1.0, effective_iops_cap / total_iops_req) if total_iops_req > 0 else 1.0
            achieved_read_iops = int(read_iops_req * scale)
            achieved_write_iops = int(write_iops_req * scale)
            avg_read_lat = base_read_us + 30.0
            p99_read_lat = avg_read_lat * 1.5

        read_latencies_us = [avg_read_lat, p99_read_lat]
        verdict = "OPTIMAL_KYBER_LATENCY_THROTTLED"

    elif scheduler == "none":
        effective_iops_cap = max_iops
        cpu_spinlock_wait_pct = 0.2
        scale = min(1.0, effective_iops_cap / total_iops_req) if total_iops_req > 0 else 1.0
        achieved_read_iops = int(read_iops_req * scale)
        achieved_write_iops = int(write_iops_req * scale)

        if total_iops_req > max_iops * 0.8:
            avg_read_lat = base_read_us + 4500.0
            p99_read_lat = avg_read_lat * 3.5
            verdict = "NONE_WRITE_BURST_TAIL_SPIKE"
        else:
            avg_read_lat = base_read_us + 5.0
            p99_read_lat = avg_read_lat * 1.4
            verdict = "OPTIMAL_NONE_RAW_NVME_THROUGHPUT"

        read_latencies_us = [avg_read_lat, p99_read_lat]

    else:
        verdict = "UNKNOWN"

    total_achieved_iops = achieved_read_iops + achieved_write_iops
    throughput_efficiency_pct = round((total_achieved_iops / total_iops_req) * 100.0, 2) if total_iops_req > 0 else 100.0

    output = {
        "status": "SUCCESS" if verdict != "BFQ_NVME_SPINLOCK_COLLAPSE" else "FAILED",
        "verdict": verdict,
        "scheduler": scheduler,
        "metrics": {
            "requested_iops": total_iops_req,
            "achieved_iops": total_achieved_iops,
            "achieved_read_iops": achieved_read_iops,
            "achieved_write_iops": achieved_write_iops,
            "throughput_efficiency_pct": throughput_efficiency_pct,
            "cpu_spinlock_wait_pct": cpu_spinlock_wait_pct,
            "average_read_latency_us": round(read_latencies_us[0], 2),
            "p99_read_latency_us": round(read_latencies_us[1], 2),
            "write_throttled": write_throttled
        }
    }
    return output

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_blk_mq(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
