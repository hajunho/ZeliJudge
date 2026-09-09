#!/usr/bin/env python3
import sys
import json

def is_key_in_range(key, start_key, end_key):
    if key < start_key:
        return False
    if end_key != "" and key >= end_key:
        return False
    return True

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)

    stores = input_data["stores"]
    initial_regions = input_data["initial_regions"]
    events = input_data["events"]

    regions = {}
    for r in initial_regions:
        rid = r["region_id"]
        regions[rid] = {
            "region_id": rid,
            "start_key": r["start_key"],
            "end_key": r["end_key"],
            "version": r.get("version", 1),
            "conf_ver": r.get("conf_ver", 1),
            "peers": r.get("peers", []),
            "leader_store_id": r.get("leader_store_id", None),
            "lease_expire_time": r.get("lease_expire_time", 0),
            "data": dict(r.get("initial_data", {})),
            "tombstone": False
        }

    current_time = input_data.get("initial_time", 0)

    successful_reads = 0
    successful_writes = 0
    stale_version_errors = 0
    stale_conf_ver_errors = 0
    not_leader_errors = 0
    key_not_in_region_errors = 0
    region_not_found_errors = 0
    lease_expired_errors = 0

    log_records = []
    fatal_anomalies = []

    for ev in events:
        ev_type = ev.get("event_type")
        timestamp = ev.get("timestamp", current_time)
        current_time = timestamp

        if ev_type == "TIME_ADVANCE":
            current_time = ev.get("new_time", current_time)

        elif ev_type == "REGION_SPLIT":
            rid = ev["region_id"]
            split_key = ev["split_key"]
            new_rid = ev["new_region_id"]

            if rid not in regions or regions[rid]["tombstone"]:
                fatal_anomalies.append(f"Split failed: Region {rid} not found or tombstoned.")
                continue

            parent = regions[rid]
            if not is_key_in_range(split_key, parent["start_key"], parent["end_key"]) or split_key == parent["start_key"]:
                fatal_anomalies.append(f"Split failed: Split key '{split_key}' invalid for region [{parent['start_key']}, {parent['end_key']}).")
                continue

            old_end = parent["end_key"]
            parent["end_key"] = split_key
            parent["version"] += 1

            left_data = {}
            right_data = {}
            for k, v in parent["data"].items():
                if k < split_key:
                    left_data[k] = v
                else:
                    right_data[k] = v
            parent["data"] = left_data

            regions[new_rid] = {
                "region_id": new_rid,
                "start_key": split_key,
                "end_key": old_end,
                "version": 1,
                "conf_ver": parent["conf_ver"],
                "peers": list(parent["peers"]),
                "leader_store_id": parent["leader_store_id"],
                "lease_expire_time": parent["lease_expire_time"],
                "data": right_data,
                "tombstone": False
            }
            log_records.append(f"[T={current_time}] Region {rid} split at '{split_key}'. New Right Region {new_rid} created.")

        elif ev_type == "REGION_MERGE":
            source_rid = ev["source_region_id"]
            target_rid = ev["target_region_id"]
            if source_rid not in regions or target_rid not in regions:
                continue
            src = regions[source_rid]
            tgt = regions[target_rid]

            if src["tombstone"] or tgt["tombstone"]:
                continue

            tgt["end_key"] = src["end_key"]
            tgt["version"] += max(src["version"], tgt["version"]) + 1
            tgt["data"].update(src["data"])
            src["tombstone"] = True
            log_records.append(f"[T={current_time}] Region {source_rid} merged into Region {target_rid}.")

        elif ev_type == "TRANSFER_LEADER":
            rid = ev["region_id"]
            new_leader = ev["new_leader_store_id"]
            lease_duration = ev.get("lease_duration", 10)
            if rid in regions and not regions[rid]["tombstone"]:
                r = regions[rid]
                r["leader_store_id"] = new_leader
                r["lease_expire_time"] = current_time + lease_duration
                log_records.append(f"[T={current_time}] Region {rid} leader transferred to Store {new_leader} with lease until {r['lease_expire_time']}.")

        elif ev_type == "CLIENT_REQUEST":
            req_id = ev.get("request_id", "")
            target_store = ev.get("target_store_id")
            rid = ev.get("region_id")
            client_epoch = ev.get("epoch", {})
            req_ver = client_epoch.get("version", 0)
            req_conf = client_epoch.get("conf_ver", 0)
            op = ev.get("op", "READ")
            key = ev.get("key", "")
            val = ev.get("value", None)

            if rid not in regions or regions[rid]["tombstone"]:
                region_not_found_errors += 1
                log_records.append(f"[{req_id}] Region {rid} not found on cluster (tombstone or invalid).")
                continue

            r = regions[rid]

            if not is_key_in_range(key, r["start_key"], r["end_key"]):
                key_not_in_region_errors += 1
                log_records.append(f"[{req_id}] Key '{key}' out of bounds for Region {rid} [{r['start_key']}, {r['end_key']}).")
                continue

            if req_ver < r["version"]:
                stale_version_errors += 1
                log_records.append(f"[{req_id}] StaleEpoch Version mismatch: Client ver={req_ver} < Server ver={r['version']}. Routing table stale.")
                continue

            if req_conf < r["conf_ver"]:
                stale_conf_ver_errors += 1
                log_records.append(f"[{req_id}] StaleEpoch ConfVer mismatch: Client conf={req_conf} < Server conf={r['conf_ver']}.")
                continue

            if target_store != r["leader_store_id"]:
                not_leader_errors += 1
                log_records.append(f"[{req_id}] Store {target_store} is not leader of Region {rid} (current leader: {r['leader_store_id']}).")
                continue

            if op == "READ":
                if current_time >= r["lease_expire_time"]:
                    lease_expired_errors += 1
                    log_records.append(f"[{req_id}] Lease expired on leader Store {target_store} for Region {rid} (current={current_time} >= expire={r['lease_expire_time']}). Linearizable read risk.")
                    continue
                successful_reads += 1
            elif op == "WRITE":
                r["data"][key] = val
                successful_writes += 1

    # Status Determination Hierarchy
    diagnostics = []
    recommended_tuning = {}

    if stale_version_errors > 0:
        status = "STALE_REGION_EPOCH_SPLIT_MISMATCH"
        diagnostics.append(f"{stale_version_errors} requests rejected due to stale Region Epoch version after dynamic split/merge.")
        recommended_tuning["action"] = "REFRESH_PD_CLIENT_CACHE"
        recommended_tuning["suggestion"] = "Intercept StaleEpoch error in client SDK and invalidate PD routing cache for affected key ranges."
    elif stale_conf_ver_errors > 0:
        status = "STALE_REGION_CONF_VER_MEMBERSHIP_MISMATCH"
        diagnostics.append(f"{stale_conf_ver_errors} requests rejected due to stale Region peer membership epoch.")
        recommended_tuning["action"] = "REFRESH_PEER_MEMBERSHIP"
        recommended_tuning["suggestion"] = "Refresh Region replica peer information from Placement Driver."
    elif lease_expired_errors > 0:
        status = "RANGE_LEASE_EXPIRED_LINEARIZABILITY_RISK"
        diagnostics.append(f"{lease_expired_errors} reads rejected due to expired Range Lease on Raft leader.")
        recommended_tuning["action"] = "HEARTBEAT_RENEW_LEASE"
        recommended_tuning["suggestion"] = "Renew leader lease proactively before 75% of lease duration elapses via Raft heartbeat quorum."
    elif not_leader_errors > 0:
        status = "NOT_LEADER_REDIRECT_REQUIRED"
        diagnostics.append(f"{not_leader_errors} requests hit non-leader peers.")
        recommended_tuning["action"] = "UPDATE_LEADER_CACHE"
        recommended_tuning["suggestion"] = "Update client leader cache using leader hint returned in NotLeader error."
    elif region_not_found_errors > 0:
        status = "TOMBSTONE_OR_INVALID_REGION_NOT_FOUND"
        diagnostics.append(f"{region_not_found_errors} requests attempted to access tombstoned or nonexistent Region.")
        recommended_tuning["action"] = "QUERY_PLACEMENT_DRIVER_ROUTING"
        recommended_tuning["suggestion"] = "Query Placement Driver to obtain the surviving merged target region ID."
    elif key_not_in_region_errors > 0:
        status = "ROUTING_KEY_RANGE_MISMATCH"
        diagnostics.append(f"{key_not_in_region_errors} requests sent to incorrect region outside key range.")
        recommended_tuning["action"] = "RELOAD_KEYSPACE_PARTITIONS"
        recommended_tuning["suggestion"] = "Reload complete keyspace region range map from Placement Driver."
    else:
        status = "HEALTHY_MULTI_RAFT_CONSISTENCY"
        diagnostics.append("All Multi-Raft operations completed with linearizable consistency and matching epochs.")
        recommended_tuning["suggestion"] = "Optimal Multi-Raft cluster state maintained."

    active_regions_count = sum(1 for r in regions.values() if not r["tombstone"])

    output = {
        "status": status,
        "metrics": {
            "total_active_regions": active_regions_count,
            "successful_reads": successful_reads,
            "successful_writes": successful_writes,
            "stale_version_errors": stale_version_errors,
            "stale_conf_ver_errors": stale_conf_ver_errors,
            "not_leader_errors": not_leader_errors,
            "key_not_in_region_errors": key_not_in_region_errors,
            "region_not_found_errors": region_not_found_errors,
            "lease_expired_errors": lease_expired_errors
        },
        "diagnostics": diagnostics,
        "recommended_tuning": recommended_tuning
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    solve()
