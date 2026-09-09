import json
import sys

def simulate_cephfs_mds(data):
    cfg = data["cluster_config"]
    num_ranks = cfg.get("num_mds_ranks", 2)
    balancer_interval = cfg.get("balancer_interval_sec", 10)
    imbalance_thresh = cfg.get("imbalance_threshold", 1.5)
    migration_cooldown = cfg.get("migration_cooldown_sec", 0)
    cap_revoke_timeout = cfg.get("cap_revoke_timeout_sec", 5)
    client_eviction = cfg.get("client_eviction_enabled", False)
    beacon_grace_sec = cfg.get("beacon_grace_sec", 4)
    async_cache_trim = cfg.get("async_cache_trim", False)
    max_cached_inodes = cfg.get("max_cached_inodes", 50000)

    # Subtrees: path -> dict
    subtrees = {}
    for s in data["subtrees"]:
        subtrees[s["path"]] = {
            "path": s["path"],
            "auth_rank": s["auth_rank"],
            "heat": s["heat"],
            "pinned_rank": s.get("pinned_rank"),
            "inode_count": s.get("inode_count", 1000),
            "last_migrated_sec": -9999
        }

    # Clients: id -> dict
    clients = {}
    for c in data.get("clients", []):
        clients[c["client_id"]] = {
            "client_id": c["client_id"],
            "holding_caps": set(c.get("holding_caps", [])),
            "is_responsive": c.get("is_responsive", True),
            "evicted": False
        }

    current_sec = 0
    migrations_completed = 0
    migrations_stuck = 0
    subtree_flapping_freezes = 0
    client_evictions_count = 0
    beacon_heartbeat_timeouts = 0
    mds_failovers = 0
    stuck_subtree_path = None
    evicted_clients = []
    stuck_migration_occurred = False
    flapping_occurred = False
    beacon_timeout_occurred = False

    def get_rank_load(rank):
        return sum(s["heat"] for s in subtrees.values() if s["auth_rank"] == rank)

    def get_rank_inodes(rank):
        return sum(s["inode_count"] for s in subtrees.values() if s["auth_rank"] == rank)

    def try_migrate_subtree(path, from_rank, to_rank, timestamp):
        nonlocal migrations_completed, migrations_stuck, subtree_flapping_freezes
        nonlocal client_evictions_count, stuck_subtree_path, stuck_migration_occurred, flapping_occurred

        s = subtrees[path]
        if s["pinned_rank"] is not None:
            return False

        if migration_cooldown > 0 and (timestamp - s["last_migrated_sec"]) < migration_cooldown:
            return False

        if migration_cooldown == 0 and (timestamp - s["last_migrated_sec"]) <= 30:
            subtree_flapping_freezes += 1
            flapping_occurred = True

        relevant_clients = [c for c in clients.values() if not c["evicted"] and path in c["holding_caps"]]
        unresponsive = [c for c in relevant_clients if not c["is_responsive"]]

        if unresponsive:
            if client_eviction:
                for uc in unresponsive:
                    uc["evicted"] = True
                    client_evictions_count += 1
                    evicted_clients.append(uc["client_id"])
            else:
                migrations_stuck += 1
                stuck_subtree_path = path
                stuck_migration_occurred = True
                return False

        s["auth_rank"] = to_rank
        s["last_migrated_sec"] = timestamp
        migrations_completed += 1
        return True

    def run_balancer(timestamp):
        loads = {r: get_rank_load(r) for r in range(num_ranks)}
        min_rank = min(loads, key=loads.get)
        max_rank = max(loads, key=loads.get)

        min_load = max(1, loads[min_rank])
        max_load = loads[max_rank]
        ratio = max_load / min_load

        if ratio >= imbalance_thresh:
            candidates = [s for s in subtrees.values() if s["auth_rank"] == max_rank and s["pinned_rank"] is None]
            if candidates:
                candidates.sort(key=lambda s: s["heat"], reverse=True)
                target_sub = candidates[0]
                try_migrate_subtree(target_sub["path"], max_rank, min_rank, timestamp)

    def check_cache_trim(rank, timestamp):
        nonlocal beacon_heartbeat_timeouts, mds_failovers, beacon_timeout_occurred
        inodes = get_rank_inodes(rank)
        if inodes > max_cached_inodes:
            excess = inodes - max_cached_inodes
            if not async_cache_trim:
                trim_stall_sec = excess / 10000.0
                if trim_stall_sec > beacon_grace_sec:
                    beacon_heartbeat_timeouts += 1
                    mds_failovers += 1
                    beacon_timeout_occurred = True

    events = sorted(data.get("events", []), key=lambda e: e.get("time_sec", 0))
    for ev in events:
        ev_type = ev["type"]
        current_sec = ev.get("time_sec", current_sec)

        if ev_type == "LOAD_CHANGE":
            path = ev["path"]
            if path in subtrees:
                subtrees[path]["heat"] = ev["heat"]

        elif ev_type == "INODE_BURST":
            path = ev["path"]
            if path in subtrees:
                subtrees[path]["inode_count"] += ev["count"]
                rank = subtrees[path]["auth_rank"]
                check_cache_trim(rank, current_sec)

        elif ev_type == "TRIGGER_BALANCER":
            run_balancer(current_sec)

        elif ev_type == "PIN_SUBTREE":
            path = ev["path"]
            if path in subtrees:
                subtrees[path]["pinned_rank"] = ev["pinned_rank"]
                subtrees[path]["auth_rank"] = ev["pinned_rank"]

    # Diagnosis Hierarchy
    if beacon_timeout_occurred:
        root_cause = "MDS_BEACON_HEARTBEAT_TIMEOUT_CACHE_TRIM_FAILOVER"
    elif stuck_migration_occurred:
        root_cause = "SUBTREE_MIGRATION_STUCK_CLIENT_CAP_REVOKE_TIMEOUT"
    elif flapping_occurred:
        root_cause = "SUBTREE_MIGRATION_PING_PONG_FLAPPING_FREEZE"
    else:
        root_cause = "STABLE_MDS_CLUSTER_BALANCED"

    recommendations = []
    if not client_eviction:
        recommendations.append("ENABLE_CLIENT_CAP_REVOKE_AUTO_EVICTION")
    if migration_cooldown == 0:
        recommendations.append("ENABLE_SUBTREE_MIGRATION_COOLDOWN_DAMPENING")
    if not async_cache_trim:
        recommendations.append("ENABLE_ASYNC_CHUNKED_CACHE_TRIMMING")
    if any(s["pinned_rank"] is None and s["heat"] >= 1000 for s in subtrees.values()):
        recommendations.append("PIN_HIGH_HEAT_SUBTREES_TO_SPECIFIC_MDS")

    if not recommendations:
        recommendations.append("MONITOR_MDS_BALANCER_AND_CAP_HEALTH")

    return {
        "final_state": {
            "current_sec": current_sec,
            "rank_loads": {r: get_rank_load(r) for r in range(num_ranks)},
            "rank_inodes": {r: get_rank_inodes(r) for r in range(num_ranks)},
            "subtrees": [
                {"path": s["path"], "auth_rank": s["auth_rank"], "heat": s["heat"]}
                for s in subtrees.values()
            ]
        },
        "metrics": {
            "migrations_completed": migrations_completed,
            "migrations_stuck": migrations_stuck,
            "subtree_flapping_freezes": subtree_flapping_freezes,
            "client_evictions_count": client_evictions_count,
            "evicted_clients": evicted_clients,
            "beacon_heartbeat_timeouts": beacon_heartbeat_timeouts,
            "mds_failovers": mds_failovers
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
        result = simulate_cephfs_mds(data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        sys.stderr.write(f"Error: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
