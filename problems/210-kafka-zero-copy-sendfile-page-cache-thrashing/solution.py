#!/usr/bin/env python3
"""
ZeliJudge Problem #210: Kafka Storage Architecture - Zero-Copy sendfile vs User-Space Buffer Overhead & Page Cache Thrashing
분산 메시징 Kafka: OS 페이지 캐시와 Linux sendfile(2) Zero-Copy vs 유저 공간 버퍼 복사 및 지연 컨슈머 캐시 스래싱 방어

Reference Implementation
"""

import sys
import json
from typing import Dict, Any, List

def simulate_kafka_storage(data: Dict[str, Any]) -> Dict[str, Any]:
    sys_cfg = data["system_config"]
    net_bw_gbps = sys_cfg.get("network_bandwidth_gbps", 100.0)
    page_cache_gb = sys_cfg.get("page_cache_capacity_gb", 64.0)
    disk_bw_gbps = sys_cfg.get("disk_read_bandwidth_gbps", 32.0)

    tx_cfg = data["transfer_config"]
    mode = tx_cfg.get("mode", "ZERO_COPY_SENDFILE")
    fadvise_dontneed = tx_cfg.get("fadvise_dontneed", False)

    workload = data.get("workload", {})
    rt_cfg = workload.get("realtime_consumers", {"data_rate_gbps": 40.0})
    cold_cfg = workload.get("lagging_cold_consumers", {"enabled": False, "data_rate_gbps": 20.0, "total_cold_data_gb": 128.0})

    rt_rate = rt_cfg.get("data_rate_gbps", 40.0)
    cold_enabled = cold_cfg.get("enabled", False)
    cold_rate = cold_cfg.get("data_rate_gbps", 20.0) if cold_enabled else 0.0
    total_cold_data = cold_cfg.get("total_cold_data_gb", 128.0) if cold_enabled else 0.0

    total_requested_gbps = rt_rate + cold_rate

    if mode == "USER_SPACE_BUFFER":
        max_user_space_throughput_gbps = 12.0
        achieved_throughput_gbps = min(total_requested_gbps, max_user_space_throughput_gbps)
        cpu_usage_pct = 98.5
        context_switches_per_sec = int((achieved_throughput_gbps * 1e9 / 8) / (64 * 1024) * 4)
        cpu_copies_per_byte = 2
        page_cache_hit_rate_pct = 95.0
        avg_latency_ms = 45.0
        p99_latency_ms = 120.0
        verdict = "USER_SPACE_BUFFER_CPU_MEMCPY_BOTTLENECK"

    elif mode == "ZERO_COPY_SENDFILE":
        cpu_copies_per_byte = 0
        context_switches_per_sec = int((total_requested_gbps * 1e9 / 8) / (1024 * 1024) * 2)

        if cold_enabled and not fadvise_dontneed and total_cold_data > page_cache_gb:
            page_cache_hit_rate_pct = 22.4
            achieved_throughput_gbps = min(total_requested_gbps, disk_bw_gbps * 0.8)
            cpu_usage_pct = 14.5
            avg_latency_ms = 18.5
            p99_latency_ms = 48.0
            verdict = "PAGE_CACHE_THRASHING_COLD_CONSUMER_STORM"
        else:
            page_cache_hit_rate_pct = 99.2
            achieved_throughput_gbps = min(total_requested_gbps, net_bw_gbps)
            cpu_usage_pct = round(achieved_throughput_gbps * 0.12, 1)
            avg_latency_ms = 0.12
            p99_latency_ms = 0.45
            verdict = "OPTIMAL_ZERO_COPY_REALTIME_STREAMING"

    elif mode == "ZERO_COPY_WITH_CACHE_ISOLATION":
        cpu_copies_per_byte = 0
        context_switches_per_sec = int((total_requested_gbps * 1e9 / 8) / (1024 * 1024) * 2)
        page_cache_hit_rate_pct = 99.5
        achieved_rt = min(rt_rate, net_bw_gbps)
        achieved_cold = min(cold_rate, disk_bw_gbps)
        achieved_throughput_gbps = achieved_rt + achieved_cold
        cpu_usage_pct = round(achieved_throughput_gbps * 0.11, 1)
        avg_latency_ms = 0.14
        p99_latency_ms = 0.52
        verdict = "OPTIMAL_ZERO_COPY_ISOLATED_STREAMING"

    else:
        verdict = "UNKNOWN"

    network_utilization_pct = round((achieved_throughput_gbps / net_bw_gbps) * 100.0, 2)

    output = {
        "status": "SUCCESS" if verdict != "USER_SPACE_BUFFER_CPU_MEMCPY_BOTTLENECK" else "FAILED",
        "verdict": verdict,
        "transfer_mode": mode,
        "metrics": {
            "requested_bandwidth_gbps": total_requested_gbps,
            "achieved_bandwidth_gbps": round(achieved_throughput_gbps, 2),
            "network_utilization_pct": network_utilization_pct,
            "cpu_usage_pct": round(cpu_usage_pct, 1),
            "cpu_copies_per_byte": cpu_copies_per_byte,
            "context_switches_per_sec": context_switches_per_sec,
            "page_cache_hit_rate_pct": page_cache_hit_rate_pct,
            "average_latency_ms": avg_latency_ms,
            "p99_latency_ms": p99_latency_ms,
            "cold_consumer_active": cold_enabled,
            "cache_isolation_active": fadvise_dontneed or mode == "ZERO_COPY_WITH_CACHE_ISOLATION"
        }
    }
    return output

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_kafka_storage(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
