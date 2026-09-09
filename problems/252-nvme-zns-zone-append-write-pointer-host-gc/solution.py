import json
import sys

def simulate_zns(data):
    cfg = data["zns_config"]
    num_zones = cfg.get("num_zones", 16)
    zone_cap_mb = cfg.get("zone_capacity_mb", 1024)
    max_open = cfg.get("max_open_zones", 4)
    max_active = cfg.get("max_active_zones", 8)
    write_mode = cfg.get("write_command_mode", "ZONE_APPEND")
    gc_threshold = cfg.get("gc_threshold_ratio", 0.5)
    gc_rate_limit = cfg.get("gc_rate_limit_mb_per_sec", 512)

    zones = {}
    for z in range(num_zones):
        zones[z] = {
            "zone_id": z,
            "wp_mb": 0,
            "valid_mb": 0,
            "state": "EMPTY"
        }

    for iz in data.get("initial_zones", []):
        zid = iz["zone_id"]
        if zid in zones:
            zones[zid]["wp_mb"] = iz.get("wp_mb", 0)
            zones[zid]["valid_mb"] = iz.get("valid_mb", 0)
            zones[zid]["state"] = iz.get("state", "EMPTY")

    successful_writes = 0
    wp_violation_errors = 0
    zone_resource_errors = 0
    gc_runs = 0
    zones_reset_count = 0
    gc_relocated_mb = 0
    free_zone_exhaustion_stalls = 0

    def get_open_zones_count():
        return sum(1 for z in zones.values() if z["state"] in ("EXPLICITLY_OPEN", "IMPLICITLY_OPEN"))

    def get_active_zones_count():
        return sum(1 for z in zones.values() if z["state"] in ("EXPLICITLY_OPEN", "IMPLICITLY_OPEN", "CLOSED"))

    def write_to_zone(zid, size_mb, target_lba=None):
        nonlocal successful_writes, wp_violation_errors, zone_resource_errors

        z = zones.get(zid)
        if not z:
            return False

        if z["state"] == "FULL":
            return False

        if z["state"] in ("EMPTY", "CLOSED"):
            if get_active_zones_count() >= max_active:
                zone_resource_errors += 1
                return False
            if get_open_zones_count() >= max_open:
                zone_resource_errors += 1
                return False
            z["state"] = "IMPLICITLY_OPEN"

        if z["wp_mb"] + size_mb > zone_cap_mb:
            return False

        if write_mode == "CONVENTIONAL_WRITE":
            if target_lba is None or target_lba != z["wp_mb"]:
                wp_violation_errors += 1
                return False
            z["wp_mb"] += size_mb
            z["valid_mb"] += size_mb
            if z["wp_mb"] == zone_cap_mb:
                z["state"] = "FULL"
            successful_writes += 1
            return True

        elif write_mode == "ZONE_APPEND":
            z["wp_mb"] += size_mb
            z["valid_mb"] += size_mb
            if z["wp_mb"] == zone_cap_mb:
                z["state"] = "FULL"
            successful_writes += 1
            return True

    def run_host_gc():
        nonlocal gc_runs, zones_reset_count, gc_relocated_mb, free_zone_exhaustion_stalls

        gc_runs += 1
        candidates = []
        for z in zones.values():
            if z["state"] == "FULL":
                inv_ratio = 1.0 - (z["valid_mb"] / float(zone_cap_mb))
                if inv_ratio >= gc_threshold:
                    candidates.append((z, inv_ratio))

        if not candidates:
            return

        candidates.sort(key=lambda x: x[1], reverse=True)
        victim, _ = candidates[0]

        relocate_size = victim["valid_mb"]
        if relocate_size > 0:
            target_zones = [z for z in zones.values() if z["zone_id"] != victim["zone_id"] and z["state"] in ("EMPTY", "EXPLICITLY_OPEN", "IMPLICITLY_OPEN")]
            if target_zones:
                tz = target_zones[0]
                success = write_to_zone(tz["zone_id"], relocate_size)
                if success:
                    gc_relocated_mb += relocate_size
            else:
                free_zone_exhaustion_stalls += 1
                return

        victim["wp_mb"] = 0
        victim["valid_mb"] = 0
        victim["state"] = "EMPTY"
        zones_reset_count += 1

    events = sorted(data.get("events", []), key=lambda e: e.get("time_sec", 0))
    for ev in events:
        ev_type = ev["type"]

        if ev_type == "CONCURRENT_WRITE":
            zid = ev["zone_id"]
            writes = ev.get("writes", [])
            for w in writes:
                write_to_zone(zid, w["size_mb"], w.get("target_lba_mb"))

        elif ev_type == "ZONE_APPEND_BATCH":
            zid = ev["zone_id"]
            for w in ev.get("writes", []):
                write_to_zone(zid, w["size_mb"])

        elif ev_type == "OPEN_ZONE":
            zid = ev["zone_id"]
            z = zones.get(zid)
            if z and z["state"] == "EMPTY":
                if get_active_zones_count() >= max_active or get_open_zones_count() >= max_open:
                    zone_resource_errors += 1
                else:
                    z["state"] = "EXPLICITLY_OPEN"

        elif ev_type == "INVALIDATE_DATA":
            zid = ev["zone_id"]
            size = ev["size_mb"]
            if zid in zones:
                zones[zid]["valid_mb"] = max(0, zones[zid]["valid_mb"] - size)

        elif ev_type == "TRIGGER_HOST_GC":
            run_host_gc()

        elif ev_type == "ZONE_RESET":
            zid = ev["zone_id"]
            if zid in zones:
                zones[zid]["wp_mb"] = 0
                zones[zid]["valid_mb"] = 0
                zones[zid]["state"] = "EMPTY"
                zones_reset_count += 1

    empty_zones = sum(1 for z in zones.values() if z["state"] == "EMPTY")
    if empty_zones == 0 and sum(1 for z in zones.values() if z["state"] == "FULL") == num_zones:
        free_zone_exhaustion_stalls += 1

    # Diagnosis Hierarchy
    if wp_violation_errors > 0:
        root_cause = "ZONE_WRITE_POINTER_VIOLATION_CONVENTIONAL_WRITE_RACE"
    elif zone_resource_errors > 0:
        root_cause = "NVME_ZONE_RESOURCE_EXHAUSTION_TOO_MANY_ACTIVE_OPEN"
    elif free_zone_exhaustion_stalls > 0:
        root_cause = "HOST_GC_STARVATION_ZONE_EXHAUSTION_WRITE_STALL"
    else:
        root_cause = "STABLE_NVME_ZNS_LOCKLESS_OPERATION"

    recommendations = []
    if write_mode == "CONVENTIONAL_WRITE":
        recommendations.append("MIGRATE_TO_NVME_ZONE_APPEND_COMMAND")
    if zone_resource_errors > 0 or max_open < 8:
        recommendations.append("ENFORCE_ZONE_LIFECYCLE_CLOSE_INACTIVE_ZONES")
    if free_zone_exhaustion_stalls > 0 or zones_reset_count == 0:
        recommendations.append("CONFIGURE_BACKGROUND_HOST_ZONE_COMPACTION")

    if not recommendations:
        recommendations.append("MAINTAIN_CURRENT_ZNS_STORAGE_PIPELINE")

    return {
        "final_state": {
            "num_empty_zones": sum(1 for z in zones.values() if z["state"] == "EMPTY"),
            "num_full_zones": sum(1 for z in zones.values() if z["state"] == "FULL"),
            "num_open_zones": get_open_zones_count(),
            "total_valid_data_mb": sum(z["valid_mb"] for z in zones.values())
        },
        "metrics": {
            "successful_writes": successful_writes,
            "wp_violation_errors": wp_violation_errors,
            "zone_resource_errors": zone_resource_errors,
            "gc_runs": gc_runs,
            "zones_reset_count": zones_reset_count,
            "gc_relocated_mb": gc_relocated_mb,
            "free_zone_exhaustion_stalls": free_zone_exhaustion_stalls
        },
        "root_cause": root_cause,
        "recommendations": recommendations
    }

def main():
    try:
        input_data = sys.stdin.read().strip()
        if not input_data:
            return
        data = json.loads(input_data)
        result = simulate_zns(data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
