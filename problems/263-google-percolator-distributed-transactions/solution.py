import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def run_percolator_simulation(input_data: dict) -> dict:
    initial_state = input_data.get("initial_state", {})
    operations = input_data["operations"]

    data_cf = {}
    lock_cf = {}
    write_cf = {}

    for item in initial_state.get("data", []):
        data_cf[(item["key"], item["start_ts"])] = item["value"]
    for item in initial_state.get("locks", []):
        lock_cf[item["key"]] = {
            "primary_key": item["primary_key"],
            "start_ts": item["start_ts"],
            "ttl": item["ttl"],
            "op": item.get("op", "PUT")
        }
    for item in initial_state.get("writes", []):
        write_cf[(item["key"], item["commit_ts"])] = {
            "start_ts": item["start_ts"],
            "write_type": item["write_type"]
        }

    op_results = []
    stats = {
        "prewrite_success": 0,
        "prewrite_conflicts": 0,
        "commit_success": 0,
        "commit_crashed": 0,
        "reads_successful": 0,
        "reads_blocked": 0,
        "roll_forwards": 0,
        "roll_backs": 0
    }

    def resolve_lock(key: str, current_time: int) -> dict:
        if key not in lock_cf:
            return {"status": "NO_LOCK"}
        lock = lock_cf[key]
        p_key = lock["primary_key"]
        p_start_ts = lock["start_ts"]

        primary_commit = None
        for (k, c_ts), meta in write_cf.items():
            if k == p_key and meta["start_ts"] == p_start_ts and meta["write_type"] != "ROLLBACK":
                primary_commit = (c_ts, meta)
                break

        if primary_commit:
            c_ts, meta = primary_commit
            write_cf[(key, c_ts)] = {
                "start_ts": p_start_ts,
                "write_type": lock["op"]
            }
            del lock_cf[key]
            stats["roll_forwards"] += 1
            return {"status": "ROLLED_FORWARD", "commit_ts": c_ts}
        else:
            del lock_cf[key]
            data_cf.pop((key, p_start_ts), None)
            write_cf[(p_key, p_start_ts)] = {
                "start_ts": p_start_ts,
                "write_type": "ROLLBACK"
            }
            stats["roll_backs"] += 1
            return {"status": "ROLLED_BACK"}

    for op_item in operations:
        op_id = op_item["id"]
        op_type = op_item["type"]

        if op_type == "READ":
            key = op_item["key"]
            read_ts = op_item["read_ts"]
            curr_time = op_item.get("current_time", read_ts)

            blocked = False
            lock_info = None
            if key in lock_cf:
                lock = lock_cf[key]
                if lock["start_ts"] <= read_ts:
                    if curr_time < lock["start_ts"] + lock["ttl"]:
                        blocked = True
                        lock_info = {
                            "primary_key": lock["primary_key"],
                            "start_ts": lock["start_ts"],
                            "ttl_remaining": (lock["start_ts"] + lock["ttl"]) - curr_time
                        }
                    else:
                        resolve_lock(key, curr_time)

            if blocked:
                stats["reads_blocked"] += 1
                op_results.append({
                    "id": op_id,
                    "type": "READ",
                    "status": "BLOCKED_BY_LOCK",
                    "key": key,
                    "value": None,
                    "lock_info": lock_info
                })
            else:
                matching = [
                    (c_ts, meta) for (k, c_ts), meta in write_cf.items()
                    if k == key and c_ts <= read_ts and meta["write_type"] != "ROLLBACK"
                ]
                if not matching:
                    op_results.append({
                        "id": op_id,
                        "type": "READ",
                        "status": "NOT_FOUND",
                        "key": key,
                        "value": None
                    })
                else:
                    matching.sort(key=lambda x: x[0], reverse=True)
                    latest_c_ts, latest_meta = matching[0]
                    if latest_meta["write_type"] == "DELETE":
                        op_results.append({
                            "id": op_id,
                            "type": "READ",
                            "status": "DELETED",
                            "key": key,
                            "value": None,
                            "commit_ts": latest_c_ts
                        })
                    else:
                        d_start_ts = latest_meta["start_ts"]
                        val = data_cf.get((key, d_start_ts))
                        stats["reads_successful"] += 1
                        op_results.append({
                            "id": op_id,
                            "type": "READ",
                            "status": "OK",
                            "key": key,
                            "value": val,
                            "commit_ts": latest_c_ts
                        })

        elif op_type == "PREWRITE":
            primary_key = op_item["primary_key"]
            start_ts = op_item["start_ts"]
            ttl = op_item.get("ttl", 100)
            mutations = op_item["mutations"]

            ordered_keys = [primary_key] + [m["key"] for m in mutations if m["key"] != primary_key]
            mut_dict = {m["key"]: m for m in mutations}

            failed = False
            failed_key = None
            conflict_reason = None
            prewritten_keys = []

            for k in ordered_keys:
                has_ww = False
                for (w_key, c_ts), meta in write_cf.items():
                    if w_key == k and c_ts >= start_ts and meta["write_type"] != "ROLLBACK":
                        has_ww = True
                        break
                if has_ww:
                    failed = True
                    failed_key = k
                    conflict_reason = "WRITE_CONFLICT"
                    break

                if k in lock_cf:
                    failed = True
                    failed_key = k
                    conflict_reason = "LOCK_CONFLICT"
                    break

                m_op = mut_dict[k].get("op", "PUT")
                if m_op == "PUT":
                    data_cf[(k, start_ts)] = mut_dict[k]["value"]

                lock_cf[k] = {
                    "primary_key": primary_key,
                    "start_ts": start_ts,
                    "ttl": ttl,
                    "op": m_op
                }
                prewritten_keys.append(k)

            if failed:
                stats["prewrite_conflicts"] += 1
                for pk in prewritten_keys:
                    del lock_cf[pk]
                    data_cf.pop((pk, start_ts), None)
                op_results.append({
                    "id": op_id,
                    "type": "PREWRITE",
                    "status": conflict_reason,
                    "failed_key": failed_key,
                    "start_ts": start_ts
                })
            else:
                stats["prewrite_success"] += 1
                op_results.append({
                    "id": op_id,
                    "type": "PREWRITE",
                    "status": "OK",
                    "primary_key": primary_key,
                    "prewritten_count": len(ordered_keys),
                    "start_ts": start_ts
                })

        elif op_type == "COMMIT":
            primary_key = op_item["primary_key"]
            start_ts = op_item["start_ts"]
            commit_ts = op_item["commit_ts"]
            keys = op_item["keys"]
            simulate_crash_after_primary = op_item.get("crash_after_primary", False)

            if primary_key not in lock_cf or lock_cf[primary_key]["start_ts"] != start_ts:
                op_results.append({
                    "id": op_id,
                    "type": "COMMIT",
                    "status": "PRIMARY_LOCK_NOT_FOUND",
                    "primary_key": primary_key,
                    "start_ts": start_ts
                })
                continue

            if (primary_key, start_ts) in write_cf and write_cf[(primary_key, start_ts)]["write_type"] == "ROLLBACK":
                op_results.append({
                    "id": op_id,
                    "type": "COMMIT",
                    "status": "ALREADY_ROLLED_BACK",
                    "primary_key": primary_key,
                    "start_ts": start_ts
                })
                continue

            p_op = lock_cf[primary_key]["op"]
            write_cf[(primary_key, commit_ts)] = {
                "start_ts": start_ts,
                "write_type": p_op
            }
            del lock_cf[primary_key]

            if simulate_crash_after_primary:
                stats["commit_crashed"] += 1
                op_results.append({
                    "id": op_id,
                    "type": "COMMIT",
                    "status": "CRASHED_AFTER_PRIMARY",
                    "primary_key": primary_key,
                    "commit_ts": commit_ts,
                    "secondary_locks_lingering": len(keys) - 1
                })
            else:
                for k in keys:
                    if k == primary_key:
                        continue
                    if k in lock_cf and lock_cf[k]["start_ts"] == start_ts:
                        sec_op = lock_cf[k]["op"]
                        write_cf[(k, commit_ts)] = {
                            "start_ts": start_ts,
                            "write_type": sec_op
                        }
                        del lock_cf[k]
                stats["commit_success"] += 1
                op_results.append({
                    "id": op_id,
                    "type": "COMMIT",
                    "status": "COMMITTED",
                    "primary_key": primary_key,
                    "commit_ts": commit_ts,
                    "committed_keys_count": len(keys)
                })

        elif op_type == "RESOLVE_LOCK":
            key = op_item["key"]
            curr_time = op_item.get("current_time", 0)
            res = resolve_lock(key, curr_time)
            op_results.append({
                "id": op_id,
                "type": "RESOLVE_LOCK",
                "key": key,
                "action": res["status"],
                "commit_ts": res.get("commit_ts")
            })

    final_active_locks = []
    for k, l in sorted(lock_cf.items()):
        final_active_locks.append({
            "key": k,
            "primary_key": l["primary_key"],
            "start_ts": l["start_ts"],
            "ttl": l["ttl"],
            "op": l["op"]
        })

    final_writes = []
    for (k, c_ts), w in sorted(write_cf.items()):
        final_writes.append({
            "key": k,
            "commit_ts": c_ts,
            "start_ts": w["start_ts"],
            "write_type": w["write_type"]
        })

    return {
        "stats": stats,
        "operation_results": op_results,
        "final_state": {
            "active_locks_count": len(lock_cf),
            "committed_versions_count": len([w for w in final_writes if w["write_type"] != "ROLLBACK"]),
            "rollback_records_count": len([w for w in final_writes if w["write_type"] == "ROLLBACK"]),
            "active_locks": final_active_locks,
            "latest_writes": final_writes
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = run_percolator_simulation(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
