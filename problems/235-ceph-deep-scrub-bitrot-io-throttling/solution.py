import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    deep_scrub_enabled = bool(config.get("deep_scrub_enabled", True))
    scrub_time_window_enabled = bool(config.get("scrub_time_window_enabled", True))
    current_cluster_hour = int(config.get("current_cluster_hour", 2))
    scrub_sleep_sec = float(config.get("scrub_sleep_sec", 0.1))
    io_priority_class = config.get("io_priority_class", "IDLE")
    disk_max_bandwidth_mb = float(config.get("disk_max_bandwidth_mb", 250.0))
    client_sla_latency_ms = float(config.get("client_sla_latency_ms", 50.0))

    cluster_state = data.get("cluster_state", {})
    total_objects_scanned = int(cluster_state.get("total_objects_scanned", 100000))
    object_size_kb = int(cluster_state.get("object_size_kb", 4096))
    client_traffic_load = cluster_state.get("client_traffic_load", "OFF_PEAK")
    crc_mismatches = int(cluster_state.get("primary_replica_crc_mismatches", 0))
    healthy_replicas = int(cluster_state.get("secondary_healthy_replicas", 2))

    is_off_peak_hour = (current_cluster_hour >= 23 or current_cluster_hour < 6)

    if not deep_scrub_enabled:
        if crc_mismatches > 0:
            result = {
                "status": "FAILED",
                "verdict": "SILENT_BIT_ROT_UNDETECTED_DATA_CORRUPTION",
                "metrics": {
                    "corrupted_objects_detected": 0,
                    "objects_repaired": 0,
                    "scrub_disk_bandwidth_mb": 0.0,
                    "client_p99_latency_ms": 12.0,
                    "sla_violated": False
                }
            }
        else:
            result = {
                "status": "WARNING",
                "verdict": "DEEP_SCRUB_DISABLED_AUDIT_RISK",
                "metrics": {
                    "corrupted_objects_detected": 0,
                    "objects_repaired": 0,
                    "scrub_disk_bandwidth_mb": 0.0,
                    "client_p99_latency_ms": 12.0,
                    "sla_violated": False
                }
            }
        print(json.dumps(result, ensure_ascii=False))
        return

    if io_priority_class == "REALTIME" or scrub_sleep_sec <= 0.01:
        scrub_bw = disk_max_bandwidth_mb * 0.85
    elif io_priority_class == "BEST_EFFORT":
        scrub_bw = disk_max_bandwidth_mb * 0.50
    else:
        scrub_bw = disk_max_bandwidth_mb * 0.20

    is_peak_run = (client_traffic_load == "PEAK") and (not scrub_time_window_enabled or not is_off_peak_hour)

    if is_peak_run:
        client_base_latency = 35.0
        client_p99_latency = round(client_base_latency + (scrub_bw / disk_max_bandwidth_mb) * 120.0, 1)
    else:
        client_base_latency = 8.0
        client_p99_latency = round(client_base_latency + (scrub_bw / disk_max_bandwidth_mb) * 15.0, 1)

    sla_violated = (client_p99_latency > client_sla_latency_ms)

    if is_peak_run and sla_violated:
        result = {
            "status": "FAILED",
            "verdict": "SCRUBBING_IO_PEAK_SATURATION_SLA_VIOLATION",
            "metrics": {
                "corrupted_objects_detected": crc_mismatches,
                "objects_repaired": crc_mismatches if healthy_replicas > 0 else 0,
                "scrub_disk_bandwidth_mb": round(scrub_bw, 1),
                "client_p99_latency_ms": client_p99_latency,
                "sla_violated": True
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    if is_peak_run and not sla_violated and io_priority_class != "IDLE":
        result = {
            "status": "WARNING",
            "verdict": "SCRUBBING_IO_BURST_CLIENT_LATENCY_DEGRADATION",
            "metrics": {
                "corrupted_objects_detected": crc_mismatches,
                "objects_repaired": crc_mismatches if healthy_replicas > 0 else 0,
                "scrub_disk_bandwidth_mb": round(scrub_bw, 1),
                "client_p99_latency_ms": client_p99_latency,
                "sla_violated": False
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    if crc_mismatches > 0:
        if healthy_replicas == 0:
            result = {
                "status": "FAILED",
                "verdict": "BIT_ROT_DETECTED_PERMANENT_DATA_LOSS",
                "metrics": {
                    "corrupted_objects_detected": crc_mismatches,
                    "objects_repaired": 0,
                    "scrub_disk_bandwidth_mb": round(scrub_bw, 1),
                    "client_p99_latency_ms": client_p99_latency,
                    "sla_violated": sla_violated
                }
            }
        else:
            result = {
                "status": "SUCCESS",
                "verdict": "OPTIMAL_THROTTLED_DEEP_SCRUB_AUTO_REPAIRED",
                "metrics": {
                    "corrupted_objects_detected": crc_mismatches,
                    "objects_repaired": crc_mismatches,
                    "scrub_disk_bandwidth_mb": round(scrub_bw, 1),
                    "client_p99_latency_ms": client_p99_latency,
                    "sla_violated": sla_violated
                }
            }
    else:
        result = {
            "status": "SUCCESS",
            "verdict": "OPTIMAL_THROTTLED_DEEP_SCRUB_CLEAN",
            "metrics": {
                "corrupted_objects_detected": 0,
                "objects_repaired": 0,
                "scrub_disk_bandwidth_mb": round(scrub_bw, 1),
                "client_p99_latency_ms": client_p99_latency,
                "sla_violated": sla_violated
            }
        }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
