import sys
import json
import heapq

def simulate_db_migration(config):
    mode = config.get("mode", "VERSION_FENCED_CDC") # "NAIVE_DUAL_WRITE", "VERSION_FENCED_DUAL_WRITE", "VERSION_FENCED_CDC"
    backfill_chunk_size = config.get("backfill_chunk_size", 2)
    live_write_latency = config.get("live_write_latency_ticks", 2)
    backfill_latency = config.get("backfill_latency_ticks", 10)
    timeline_events = config.get("timeline_events", [])

    # Databases: id -> {"id": str, "balance": int, "version": int, "updated_at": int}
    db_old = {}
    db_new = {}
    wal_queue = []

    metrics = {
        "total_live_writes": 0,
        "backfill_rows_read": 0,
        "backfill_rows_written": 0,
        "cdc_events_emitted": 0,
        "cdc_events_applied": 0,
        "stale_writes_fenced": 0,
        "lost_updates_detected": 0,
        "partial_failures_occurred": 0,
        "drift_records_count": 0,
        "reconciled_heals_count": 0,
        "cutover_success": False,
        "cutover_tick": None,
        "verdict": ""
    }

    timeline_log = []
    backfill_cursor = 0
    backfill_in_progress = False
    backfill_keys_order = []
    failed_targets = set()

    event_pq = []
    event_counter = 0

    def schedule_event(tick, priority, ev_type, data):
        nonlocal event_counter
        event_counter += 1
        heapq.heappush(event_pq, (tick, priority, event_counter, ev_type, data))

    for ev in timeline_events:
        schedule_event(ev["tick"], 1, ev["type"], ev)

    def trigger_backfill_step(tick):
        nonlocal backfill_cursor, backfill_in_progress
        if not backfill_in_progress:
            return
        if backfill_cursor >= len(backfill_keys_order):
            timeline_log.append({
                "tick": tick,
                "event": "BACKFILL_COMPLETED",
                "total_rows": len(backfill_keys_order)
            })
            backfill_in_progress = False
            return

        chunk_keys = backfill_keys_order[backfill_cursor : backfill_cursor + backfill_chunk_size]
        backfill_cursor += len(chunk_keys)
        snapshot_records = [dict(db_old[k]) for k in chunk_keys if k in db_old]
        metrics["backfill_rows_read"] += len(snapshot_records)

        timeline_log.append({
            "tick": tick,
            "event": "BACKFILL_CHUNK_READ",
            "keys": [r["id"] for r in snapshot_records],
            "records": snapshot_records
        })

        schedule_event(tick + backfill_latency, 2, "BACKFILL_CHUNK_WRITE", {
            "records": snapshot_records
        })

    current_tick = 0

    while event_pq:
        tick, priority, _, ev_type, data = heapq.heappop(event_pq)
        current_tick = tick

        if ev_type == "SEED_OLD_DB":
            for rec in data["records"]:
                r = {
                    "id": rec["id"],
                    "balance": rec["balance"],
                    "version": rec.get("version", 1),
                    "updated_at": tick
                }
                db_old[r["id"]] = r
            backfill_keys_order = sorted(list(db_old.keys()))
            timeline_log.append({
                "tick": tick,
                "event": "SEED_OLD_DB",
                "count": len(data["records"])
            })

        elif ev_type == "NETWORK_PARTIAL_FAILURE":
            target = data.get("target", "DB_NEW")
            record_id = data.get("id")
            failed_targets.add((target, record_id))
            timeline_log.append({
                "tick": tick,
                "event": "ARM_NETWORK_PARTIAL_FAILURE",
                "target": target,
                "id": record_id
            })

        elif ev_type == "LIVE_WRITE":
            rec_id = data["id"]
            delta = data.get("delta", 0)
            custom_delay = data.get("custom_delay", live_write_latency)
            metrics["total_live_writes"] += 1

            if rec_id not in db_old:
                cur_bal = 0
                cur_ver = 0
            else:
                cur_bal = db_old[rec_id]["balance"]
                cur_ver = db_old[rec_id]["version"]

            new_rec = {
                "id": rec_id,
                "balance": cur_bal + delta,
                "version": cur_ver + 1,
                "updated_at": tick
            }
            db_old[rec_id] = new_rec
            timeline_log.append({
                "tick": tick,
                "event": "LIVE_WRITE_OLD_DB",
                "id": rec_id,
                "new_balance": new_rec["balance"],
                "version": new_rec["version"]
            })

            if mode in ("NAIVE_DUAL_WRITE", "VERSION_FENCED_DUAL_WRITE"):
                if ("DB_NEW", rec_id) in failed_targets:
                    failed_targets.remove(("DB_NEW", rec_id))
                    metrics["partial_failures_occurred"] += 1
                    timeline_log.append({
                        "tick": tick,
                        "event": "DUAL_WRITE_PARTIAL_FAILURE",
                        "id": rec_id,
                        "target": "DB_NEW"
                    })
                else:
                    schedule_event(tick + custom_delay, 3, "APPLY_LIVE_WRITE_NEW_DB", {
                        "record": dict(new_rec)
                    })
            else:
                # VERSION_FENCED_CDC
                wal_queue.append(dict(new_rec))
                metrics["cdc_events_emitted"] += 1
                timeline_log.append({
                    "tick": tick,
                    "event": "CDC_WAL_EMITTED",
                    "id": rec_id,
                    "version": new_rec["version"]
                })

        elif ev_type == "APPLY_LIVE_WRITE_NEW_DB":
            rec = data["record"]
            rec_id = rec["id"]
            if mode == "NAIVE_DUAL_WRITE":
                if rec_id in db_new:
                    existing = db_new[rec_id]
                    if existing["version"] > rec["version"]:
                        metrics["lost_updates_detected"] += 1
                        timeline_log.append({
                            "tick": tick,
                            "event": "LOST_UPDATE_OUT_OF_ORDER_LIVE_WRITE",
                            "id": rec_id,
                            "existing_version": existing["version"],
                            "overwriting_version": rec["version"]
                        })
                db_new[rec_id] = rec
            else:
                # VERSION_FENCED_DUAL_WRITE
                if rec_id in db_new:
                    existing = db_new[rec_id]
                    if existing["version"] >= rec["version"]:
                        metrics["stale_writes_fenced"] += 1
                        timeline_log.append({
                            "tick": tick,
                            "event": "STALE_LIVE_WRITE_FENCED",
                            "id": rec_id,
                            "existing_version": existing["version"],
                            "fenced_version": rec["version"]
                        })
                        continue
                db_new[rec_id] = rec

            timeline_log.append({
                "tick": tick,
                "event": "DUAL_WRITE_APPLIED_NEW_DB",
                "id": rec_id,
                "balance": rec["balance"],
                "version": rec["version"]
            })

        elif ev_type == "START_BACKFILL":
            backfill_in_progress = True
            backfill_cursor = 0
            backfill_keys_order = sorted(list(db_old.keys()))
            timeline_log.append({
                "tick": tick,
                "event": "START_BACKFILL",
                "total_records": len(backfill_keys_order)
            })
            trigger_backfill_step(tick)

        elif ev_type == "BACKFILL_CHUNK_WRITE":
            records = data["records"]
            for rec in records:
                rec_id = rec["id"]
                if mode == "NAIVE_DUAL_WRITE":
                    if rec_id in db_new:
                        existing = db_new[rec_id]
                        if existing["version"] > rec["version"]:
                            metrics["lost_updates_detected"] += 1
                            timeline_log.append({
                                "tick": tick,
                                "event": "BACKFILL_OVERWROTE_NEWER_LIVE_WRITE",
                                "id": rec_id,
                                "lost_version": existing["version"],
                                "regressed_version": rec["version"],
                                "lost_balance": existing["balance"],
                                "regressed_balance": rec["balance"]
                            })
                    db_new[rec_id] = rec
                    metrics["backfill_rows_written"] += 1
                else:
                    # VERSION_FENCED (DUAL_WRITE or CDC)
                    if rec_id in db_new:
                        existing = db_new[rec_id]
                        if existing["version"] >= rec["version"]:
                            metrics["stale_writes_fenced"] += 1
                            timeline_log.append({
                                "tick": tick,
                                "event": "STALE_BACKFILL_WRITE_FENCED",
                                "id": rec_id,
                                "existing_version": existing["version"],
                                "fenced_version": rec["version"]
                            })
                            continue
                    db_new[rec_id] = rec
                    metrics["backfill_rows_written"] += 1

            trigger_backfill_step(tick)

        elif ev_type == "CDC_FLUSH":
            events_to_apply = list(wal_queue)
            wal_queue.clear()
            for rec in events_to_apply:
                rec_id = rec["id"]
                metrics["cdc_events_applied"] += 1
                if mode == "VERSION_FENCED_CDC":
                    if rec_id in db_new:
                        existing = db_new[rec_id]
                        if existing["version"] >= rec["version"]:
                            metrics["stale_writes_fenced"] += 1
                            timeline_log.append({
                                "tick": tick,
                                "event": "STALE_CDC_EVENT_FENCED",
                                "id": rec_id,
                                "existing_version": existing["version"],
                                "cdc_version": rec["version"]
                            })
                            continue
                    db_new[rec_id] = rec
                    timeline_log.append({
                        "tick": tick,
                        "event": "CDC_EVENT_APPLIED",
                        "id": rec_id,
                        "balance": rec["balance"],
                        "version": rec["version"]
                    })
                else:
                    db_new[rec_id] = rec

        elif ev_type == "RUN_RECONCILIATION":
            drift_keys = []
            for k, old_r in db_old.items():
                if k not in db_new:
                    drift_keys.append(k)
                else:
                    new_r = db_new[k]
                    if old_r["balance"] != new_r["balance"] or old_r["version"] != new_r["version"]:
                        drift_keys.append(k)

            metrics["drift_records_count"] = len(drift_keys)
            timeline_log.append({
                "tick": tick,
                "event": "RECONCILIATION_CHECK",
                "drift_count": len(drift_keys),
                "drift_keys": drift_keys
            })

            if mode in ("VERSION_FENCED_CDC", "VERSION_FENCED_DUAL_WRITE") and drift_keys:
                for k in drift_keys:
                    auth_rec = dict(db_old[k])
                    if k in db_new:
                        if db_new[k]["version"] >= auth_rec["version"]:
                            continue
                    db_new[k] = auth_rec
                    metrics["reconciled_heals_count"] += 1
                remaining_drift = [k for k in db_old if k not in db_new or db_old[k]["version"] != db_new[k]["version"] or db_old[k]["balance"] != db_new[k]["balance"]]
                metrics["drift_records_count"] = len(remaining_drift)
                timeline_log.append({
                    "tick": tick,
                    "event": "RECONCILIATION_HEAL_COMPLETED",
                    "healed_count": metrics["reconciled_heals_count"],
                    "remaining_drift": len(remaining_drift)
                })

        elif ev_type == "ATTEMPT_CUTOVER":
            is_backfill_done = (backfill_cursor >= len(backfill_keys_order)) and not backfill_in_progress
            is_cdc_empty = len(wal_queue) == 0
            has_no_lost_updates = metrics["lost_updates_detected"] == 0
            
            current_drift = 0
            for k, old_r in db_old.items():
                if k not in db_new:
                    current_drift += 1
                else:
                    new_r = db_new[k]
                    if old_r["balance"] != new_r["balance"] or old_r["version"] != new_r["version"]:
                        current_drift += 1

            metrics["drift_records_count"] = current_drift

            if is_backfill_done and is_cdc_empty and has_no_lost_updates and current_drift == 0:
                metrics["cutover_success"] = True
                metrics["cutover_tick"] = tick
                metrics["verdict"] = "ZERO_DOWNTIME_CUTOVER_SUCCESS"
                timeline_log.append({
                    "tick": tick,
                    "event": "CUTOVER_SUCCESSFUL",
                    "total_records": len(db_new)
                })
            else:
                metrics["cutover_success"] = False
                metrics["cutover_tick"] = None
                if metrics["lost_updates_detected"] > 0:
                    metrics["verdict"] = "MIGRATION_FAILED_LOST_UPDATES"
                elif current_drift > 0:
                    metrics["verdict"] = "MIGRATION_FAILED_DATA_DRIFT"
                else:
                    metrics["verdict"] = "MIGRATION_FAILED_BACKLOG_REMAINING"
                timeline_log.append({
                    "tick": tick,
                    "event": "CUTOVER_REJECTED",
                    "verdict": metrics["verdict"],
                    "backfill_done": is_backfill_done,
                    "cdc_empty": is_cdc_empty,
                    "drift": current_drift,
                    "lost_updates": metrics["lost_updates_detected"]
                })

    return {
        "metrics": metrics,
        "sample_timeline": timeline_log[:20]
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    config = json.loads(raw)
    result = simulate_db_migration(config)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
