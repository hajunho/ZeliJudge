import sys
import json
import copy

def simulate_db_read_your_own_writes(data):
    data = copy.deepcopy(data)
    policy = data.get("routing_policy", "NAIVE_REPLICA_ONLY")
    config = data.get("config", {})
    pinning_window = float(config.get("master_pinning_window_sec", 2.0))
    gtid_timeout = float(config.get("gtid_wait_timeout_sec", 0.5))
    
    replicas_info = {r["replica_id"]: r.get("initial_applied_gtid", 0) for r in data.get("replicas", [])}
    timeline = data.get("timeline", [])
    
    # Sort timeline by time. For identical timestamps: REPLICATION_PROGRESS first, then WRITE, then READ
    type_priority = {"REPLICATION_PROGRESS": 0, "WRITE": 1, "READ": 2}
    timeline_sorted = sorted(timeline, key=lambda x: (float(x.get("time", 0.0)), type_priority.get(x.get("type"), 99)))
    
    repl_events = [e for e in timeline_sorted if e.get("type") == "REPLICATION_PROGRESS"]
    
    replica_gtid = dict(replicas_info)
    record_latest_write = {}
    user_last_write_time = {}
    
    read_results = []
    
    for event in timeline_sorted:
        e_type = event.get("type")
        e_time = float(event.get("time", 0.0))
        
        if e_type == "REPLICATION_PROGRESS":
            rep_id = event.get("replica_id")
            new_gtid = event.get("applied_gtid", 0)
            if rep_id in replica_gtid:
                replica_gtid[rep_id] = max(replica_gtid[rep_id], new_gtid)
                
        elif e_type == "WRITE":
            u_id = event.get("user_id")
            tbl = event.get("table")
            rec_id = event.get("record_id")
            gtid = event.get("gtid_generated", 0)
            
            record_latest_write[(tbl, rec_id)] = {
                "gtid": gtid,
                "time": e_time,
                "user_id": u_id
            }
            user_last_write_time[u_id] = max(user_last_write_time.get(u_id, 0.0), e_time)
            
        elif e_type == "READ":
            req_id = event.get("request_id", f"read_{len(read_results)+1}")
            u_id = event.get("user_id")
            tbl = event.get("table")
            rec_id = event.get("record_id")
            target_rep = event.get("target_replica_id")
            
            latest_write = record_latest_write.get((tbl, rec_id))
            is_own_write = (latest_write is not None and latest_write["user_id"] == u_id)
            needed_gtid = latest_write["gtid"] if latest_write else 0
            
            routed_to = None
            status = None
            reason = None
            anomaly = None
            wait_time_sec = 0.0
            
            if policy == "NAIVE_REPLICA_ONLY":
                routed_to = "REPLICA"
                curr_rep_gtid = replica_gtid.get(target_rep, 0)
                if is_own_write and curr_rep_gtid < needed_gtid:
                    status = "STALE_READ_ANOMALY"
                    anomaly = "ERR_READ_YOUR_OWN_WRITES_VIOLATION"
                    reason = f"Replica {target_rep} at GTID {curr_rep_gtid} behind user write GTID {needed_gtid}"
                else:
                    status = "SUCCESS_FRESH"
                    reason = "Replica read completed"
                    
            elif policy == "SESSION_MASTER_PINNING":
                last_w_time = user_last_write_time.get(u_id, -1.0)
                time_since_write = e_time - last_w_time if last_w_time >= 0 else float("inf")
                
                if is_own_write and time_since_write < pinning_window:
                    routed_to = "MASTER"
                    status = "SUCCESS_FRESH"
                    reason = f"User pinned to Master within {pinning_window}s window (elapsed: {round(time_since_write, 2)}s)"
                else:
                    routed_to = "REPLICA"
                    curr_rep_gtid = replica_gtid.get(target_rep, 0)
                    if is_own_write and curr_rep_gtid < needed_gtid:
                        status = "STALE_READ_ANOMALY"
                        anomaly = "ERR_READ_YOUR_OWN_WRITES_VIOLATION"
                        reason = f"Pinning window expired, replica {target_rep} at GTID {curr_rep_gtid} behind GTID {needed_gtid}"
                    else:
                        status = "SUCCESS_FRESH"
                        reason = "Replica read completed"
                        
            elif policy == "CAUSAL_GTID_CONSISTENCY":
                if not is_own_write:
                    routed_to = "REPLICA"
                    status = "SUCCESS_FRESH"
                    reason = "Non-author read served by replica"
                else:
                    curr_rep_gtid = replica_gtid.get(target_rep, 0)
                    if curr_rep_gtid >= needed_gtid:
                        routed_to = "REPLICA"
                        status = "SUCCESS_FRESH"
                        reason = f"Replica {target_rep} GTID {curr_rep_gtid} already satisfies needed GTID {needed_gtid}"
                    else:
                        timeout_deadline = e_time + gtid_timeout
                        caught_up_event = None
                        for rev in repl_events:
                            rev_time = float(rev.get("time", 0.0))
                            if rev.get("replica_id") == target_rep and rev_time >= e_time and rev_time <= timeout_deadline:
                                if rev.get("applied_gtid", 0) >= needed_gtid:
                                    caught_up_event = rev
                                    break
                                    
                        if caught_up_event:
                            caught_up_time = float(caught_up_event.get("time", 0.0))
                            wait_time_sec = round(caught_up_time - e_time, 2)
                            routed_to = "REPLICA"
                            status = "SUCCESS_FRESH"
                            reason = f"Replica {target_rep} caught up to GTID {needed_gtid} after {wait_time_sec}s wait"
                        else:
                            wait_time_sec = round(gtid_timeout, 2)
                            routed_to = "MASTER"
                            status = "SUCCESS_FRESH"
                            reason = f"Replica {target_rep} GTID wait timed out ({gtid_timeout}s), fallback to Master"
                            
            read_results.append({
                "request_id": req_id,
                "time": round(e_time, 2),
                "user_id": u_id,
                "table": tbl,
                "record_id": rec_id,
                "target_replica_id": target_rep,
                "routed_to": routed_to,
                "status": status,
                "reason": reason,
                "anomaly": anomaly,
                "wait_time_sec": wait_time_sec
            })
            
    total_reads = len(read_results)
    master_reads = sum(1 for r in read_results if r["routed_to"] == "MASTER")
    replica_reads = sum(1 for r in read_results if r["routed_to"] == "REPLICA")
    stale_reads = sum(1 for r in read_results if r["status"] == "STALE_READ_ANOMALY")
    fresh_reads = sum(1 for r in read_results if r["status"] == "SUCCESS_FRESH")
    master_ratio = round((master_reads / total_reads * 100.0) if total_reads > 0 else 0.0, 2)
    
    summary = {
        "routing_policy": policy,
        "total_reads": total_reads,
        "reads_routed_to_master": master_reads,
        "reads_routed_to_replica": replica_reads,
        "stale_read_anomalies": stale_reads,
        "fresh_reads": fresh_reads,
        "master_read_ratio_pct": master_ratio
    }
    
    return {
        "summary": summary,
        "read_results": read_results
    }

def main():
    input_text = sys.stdin.read().strip()
    if not input_text:
        return
    data = json.loads(input_text)
    out = simulate_db_read_your_own_writes(data)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
