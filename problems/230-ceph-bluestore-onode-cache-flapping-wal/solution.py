import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    onode_cache_size_mb = float(config.get("onode_cache_size_mb", 1024.0))
    rocksdb_shared_cache_mb = float(config.get("rocksdb_shared_cache_mb", 2048.0))
    bluefs_dedicated_nvme = bool(config.get("bluefs_dedicated_nvme", True))
    max_background_compactions = int(config.get("max_background_compactions", 4))
    heartbeat_grace_sec = float(config.get("osd_heartbeat_grace_sec", 20.0))
    dedicated_heartbeat_thread = bool(config.get("dedicated_heartbeat_thread", True))
    sla_latency_ms = float(config.get("sla_latency_ms", 50.0))

    workload = data.get("workload", {})
    object_count = int(workload.get("object_count", 500000))
    ops_per_sec = float(workload.get("ops_per_sec", 15000.0))
    write_ratio = float(workload.get("write_ratio", 0.4))
    metadata_mutation_burst = bool(workload.get("metadata_mutation_burst", False))

    needed_onode_memory_mb = (object_count * 1024.0) / (1024.0 * 1024.0)
    onode_cache_hit_ratio = min(1.0, onode_cache_size_mb / max(1.0, needed_onode_memory_mb * 1.5))

    if bluefs_dedicated_nvme:
        rocksdb_miss_penalty_ms = 4.5
    else:
        rocksdb_miss_penalty_ms = 22.0

    read_latency_ms = 0.8 + ((1.0 - onode_cache_hit_ratio) * rocksdb_miss_penalty_ms)

    compaction_stall_duration_sec = 0.0
    if metadata_mutation_burst:
        if not bluefs_dedicated_nvme:
            compaction_stall_duration_sec = 25.0
        elif max_background_compactions <= 1:
            compaction_stall_duration_sec = 12.0
        else:
            compaction_stall_duration_sec = 1.2

    osd_down_declared = False
    flapping_detected = False

    if compaction_stall_duration_sec > heartbeat_grace_sec:
        osd_down_declared = True
        flapping_detected = True
    elif compaction_stall_duration_sec > 10.0 and not dedicated_heartbeat_thread:
        osd_down_declared = True
        flapping_detected = True

    effective_latency_ms = read_latency_ms + (compaction_stall_duration_sec * 10.0)

    if flapping_detected:
        status = "FAILED"
        verdict = "OSD_HEARTBEAT_TIMEOUT_FLAPPING_STORM"
    elif compaction_stall_duration_sec >= 8.0:
        status = "FAILED"
        verdict = "ROCKSDB_BLUEFS_COMPACTION_STALL_SPIKE"
    elif onode_cache_hit_ratio < 0.5:
        status = "FAILED"
        verdict = "ONODE_CACHE_EVICTION_THRASHING"
    elif effective_latency_ms > sla_latency_ms:
        status = "FAILED"
        verdict = "CEPH_LATENCY_SLA_EXCEEDED"
    elif bluefs_dedicated_nvme and onode_cache_hit_ratio >= 0.8 and compaction_stall_duration_sec <= 2.0:
        status = "SUCCESS"
        verdict = "OPTIMAL_BLUESTORE_TUNED_STEADY_STATE"
    else:
        status = "SUCCESS"
        verdict = "STANDARD_BLUESTORE_ACCEPTABLE"

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "onode_cache_hit_ratio": round(onode_cache_hit_ratio, 4),
            "effective_latency_ms": round(effective_latency_ms, 2),
            "compaction_stall_sec": round(compaction_stall_duration_sec, 2),
            "osd_down_declared": osd_down_declared,
            "flapping_detected": flapping_detected
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
