import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate_ceph_bluestore(input_data: dict) -> dict:
    cluster_id = input_data.get("cluster_id", "CEPH_CLUSTER_01")
    osd_id = input_data.get("osd_id", 0)
    devices = input_data.get("devices", {})
    config = input_data.get("config", {})
    ops = input_data.get("workload_ops", [])

    dev_state = {}
    for dev_name, info in devices.items():
        dev_state[dev_name] = {
            "capacity_bytes": info["capacity_bytes"],
            "used_bytes": info.get("used_bytes", 0),
            "tier": info["tier"],
            "write_latency_us": info["write_latency_us"],
            "spillover_in_bytes": 0
        }

    min_free_ratio = config.get("bluefs_min_free_ratio", 0.10)
    spill_halt_ratio = config.get("bluefs_spillover_halt_ratio", 0.02)
    heartbeat_grace_ms = config.get("osd_heartbeat_grace_ms", 20000)
    heartbeat_decoupled = config.get("heartbeat_decoupled", False)

    total_wal_spillover = 0
    total_db_spillover = 0
    latencies = []
    flapping_events = 0
    consecutive_stall_ms = 0
    is_down = False
    is_throttled = False
    diagnostics = []

    for op in ops:
        op_type = op["type"]

        if op_type == "WRITE_WAL":
            size = op["size_bytes"]
            wal_dev = dev_state["wal"]
            db_dev = dev_state["db"]
            slow_dev = dev_state["slow"]

            if wal_dev["capacity_bytes"] - wal_dev["used_bytes"] >= size:
                wal_dev["used_bytes"] += size
                lat = wal_dev["write_latency_us"]
            elif db_dev["capacity_bytes"] - db_dev["used_bytes"] >= size:
                db_dev["used_bytes"] += size
                db_dev["spillover_in_bytes"] += size
                total_wal_spillover += size
                lat = db_dev["write_latency_us"]
                if "WAL_SPILLED_TO_DB" not in diagnostics:
                    diagnostics.append("WAL_SPILLED_TO_DB")
            else:
                slow_dev["used_bytes"] += size
                slow_dev["spillover_in_bytes"] += size
                total_wal_spillover += size
                lat = slow_dev["write_latency_us"]
                if "WAL_SPILLED_TO_SLOW_TIER_CATASTROPHE" not in diagnostics:
                    diagnostics.append("WAL_SPILLED_TO_SLOW_TIER_CATASTROPHE")

            latencies.append(lat)
            lat_ms = lat / 1000.0
            if lat >= slow_dev["write_latency_us"]:
                consecutive_stall_ms += lat_ms
            else:
                consecutive_stall_ms = max(0, consecutive_stall_ms - 50)

        elif op_type == "WRITE_SST_METADATA":
            size = op["size_bytes"]
            db_dev = dev_state["db"]
            slow_dev = dev_state["slow"]

            if db_dev["capacity_bytes"] - db_dev["used_bytes"] >= size:
                db_dev["used_bytes"] += size
                lat = db_dev["write_latency_us"]
            else:
                slow_dev["used_bytes"] += size
                slow_dev["spillover_in_bytes"] += size
                total_db_spillover += size
                lat = slow_dev["write_latency_us"]
                if "DB_SST_SPILLED_TO_SLOW_TIER" not in diagnostics:
                    diagnostics.append("DB_SST_SPILLED_TO_SLOW_TIER")

            latencies.append(lat)
            lat_ms = lat / 1000.0
            if lat >= slow_dev["write_latency_us"]:
                consecutive_stall_ms += lat_ms
            else:
                consecutive_stall_ms = max(0, consecutive_stall_ms - 50)

        elif op_type == "COMPACT_L0":
            freed_db = op.get("space_freed_db_bytes", 0)
            freed_slow = op.get("space_freed_slow_bytes", 0)
            dev_state["db"]["used_bytes"] = max(0, dev_state["db"]["used_bytes"] - freed_db)
            dev_state["slow"]["used_bytes"] = max(0, dev_state["slow"]["used_bytes"] - freed_slow)
            latencies.append(dev_state["db"]["write_latency_us"] * 2)

        elif op_type == "HEARTBEAT_TICK":
            elapsed_ms = op.get("elapsed_ms", 1000)
            if not heartbeat_decoupled:
                if consecutive_stall_ms >= heartbeat_grace_ms:
                    if not is_down:
                        is_down = True
                        flapping_events += 1
                        diagnostics.append(f"OSD_HEARTBEAT_EXPIRED_PEER_DECLARED_DOWN (stall={consecutive_stall_ms:.1f}ms)")
                else:
                    if is_down:
                        is_down = False
                        flapping_events += 1
                        diagnostics.append("OSD_REVIVED_TRIGGERING_PEERING_RECOVERY_STORM")
            else:
                is_down = False

            consecutive_stall_ms = max(0, consecutive_stall_ms - elapsed_ms)

        elif op_type == "CLIENT_WRITE_REQ":
            db_free_ratio = (dev_state["db"]["capacity_bytes"] - dev_state["db"]["used_bytes"]) / dev_state["db"]["capacity_bytes"]
            if db_free_ratio < spill_halt_ratio or total_db_spillover > 0:
                is_throttled = True
                lat = dev_state["slow"]["write_latency_us"] if total_db_spillover > 0 else dev_state["db"]["write_latency_us"] * 5
            else:
                lat = dev_state["db"]["write_latency_us"]
            latencies.append(lat)

    db_free_ratio = (dev_state["db"]["capacity_bytes"] - dev_state["db"]["used_bytes"]) / dev_state["db"]["capacity_bytes"]

    if is_down or flapping_events > 1:
        osd_state = "FLAPPING_DOWN"
    elif db_free_ratio < spill_halt_ratio:
        osd_state = "STALL_HALT"
    elif is_throttled or total_wal_spillover > 0 or total_db_spillover > 0:
        osd_state = "THROTTLED_UP"
    else:
        osd_state = "HEALTHY_UP"

    latencies.sort()
    p99_idx = int(math.ceil(0.99 * len(latencies))) - 1 if latencies else 0
    p99_lat = latencies[p99_idx] if latencies else 0
    max_lat = max(latencies) if latencies else 0
    avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

    dev_summary = {}
    for d_name, d_st in dev_state.items():
        free_b = d_st["capacity_bytes"] - d_st["used_bytes"]
        dev_summary[d_name] = {
            "capacity_bytes": d_st["capacity_bytes"],
            "used_bytes": d_st["used_bytes"],
            "free_bytes": free_b,
            "usage_ratio": round(d_st["used_bytes"] / d_st["capacity_bytes"], 4),
            "spillover_in_bytes": d_st["spillover_in_bytes"]
        }

    unique_diag = []
    for d in diagnostics:
        if d not in unique_diag:
            unique_diag.append(d)

    return {
        "cluster_id": cluster_id,
        "osd_id": osd_id,
        "osd_state": osd_state,
        "heartbeat_decoupled": heartbeat_decoupled,
        "flapping_events_count": flapping_events,
        "total_wal_spillover_bytes": total_wal_spillover,
        "total_db_spillover_bytes": total_db_spillover,
        "latency_stats_us": {
            "avg_latency_us": avg_lat,
            "p99_latency_us": p99_lat,
            "max_latency_us": max_lat
        },
        "devices": dev_summary,
        "diagnostics": unique_diag
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = simulate_ceph_bluestore(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
