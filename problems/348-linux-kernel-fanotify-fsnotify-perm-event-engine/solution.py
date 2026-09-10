import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def simulate_fanotify_engine(input_data):
    group_config = input_data.get("group_config", {})
    notification_class = group_config.get("notification_class", "FAN_CLASS_CONTENT")
    max_queue_size = group_config.get("max_queue_size", 10)
    
    marks = input_data.get("marks", [])
    daemon_rules = input_data.get("daemon_rules", {})
    events = input_data.get("events", [])
    
    event_queue = []
    overflow_triggered = False
    
    stats = {
        "perm_requests_received": 0,
        "perm_allowed": 0,
        "perm_denied": 0,
        "notif_events_queued": 0,
        "events_merged": 0,
        "queue_overflow_count": 0,
        "vfs_calls_completed": 0
    }
    
    event_logs = []
    
    def matches_mark(path, event_type):
        matched = False
        for m in marks:
            m_path = m.get("path", "")
            ignored = m.get("ignored_mask", [])
            if event_type in ignored:
                if m_path == "/" or path.startswith(m_path):
                    return False
            mask = m.get("mask", [])
            if event_type in mask:
                if m["mark_type"] == "FILESYSTEM":
                    matched = True
                elif m["mark_type"] == "MOUNT":
                    if path.startswith(m_path):
                        matched = True
                elif m["mark_type"] == "INODE":
                    if path == m_path:
                        matched = True
        return matched

    for ev in events:
        etype = ev.get("type")
        
        if etype == "VFS_ACCESS":
            pid = ev.get("pid", 1001)
            path = ev.get("path", "")
            op = ev.get("op")
            
            if op == "OPEN_EXEC":
                fan_type = "FAN_OPEN_EXEC_PERM"
            elif op == "OPEN_PERM":
                fan_type = "FAN_OPEN_PERM"
            elif op == "ACCESS_PERM":
                fan_type = "FAN_ACCESS_PERM"
            elif op == "MODIFY":
                fan_type = "FAN_MODIFY"
            elif op == "CLOSE_WRITE":
                fan_type = "FAN_CLOSE_WRITE"
            elif op == "ACCESS":
                fan_type = "FAN_ACCESS"
            else:
                fan_type = f"FAN_{op}"
                
            if not matches_mark(path, fan_type):
                stats["vfs_calls_completed"] += 1
                event_logs.append({
                    "event": "VFS_ACCESS",
                    "pid": pid,
                    "path": path,
                    "op": op,
                    "fanotify_monitored": False,
                    "vfs_outcome": "SUCCESS"
                })
                continue
                
            if fan_type.endswith("_PERM"):
                stats["perm_requests_received"] += 1
                decision = daemon_rules.get(path, "FAN_ALLOW")
                if decision == "FAN_DENY":
                    stats["perm_denied"] += 1
                    outcome = "EPERM_BLOCKED"
                else:
                    stats["perm_allowed"] += 1
                    outcome = "SUCCESS"
                    
                stats["vfs_calls_completed"] += 1
                event_logs.append({
                    "event": "FANOTIFY_PERM_INTERCEPT",
                    "pid": pid,
                    "path": path,
                    "fan_type": fan_type,
                    "daemon_decision": decision,
                    "vfs_outcome": outcome
                })
            else:
                merged = False
                if event_queue:
                    last_ev = event_queue[-1]
                    if last_ev["path"] == path and last_ev["pid"] == pid and last_ev["fan_type"] == fan_type:
                        merged = True
                        last_ev["count"] += 1
                        stats["events_merged"] += 1
                        event_logs.append({
                            "event": "FANOTIFY_EVENT_MERGED",
                            "pid": pid,
                            "path": path,
                            "fan_type": fan_type,
                            "total_coalesced": last_ev["count"]
                        })
                        
                if not merged:
                    if len(event_queue) >= max_queue_size:
                        if not overflow_triggered:
                            overflow_triggered = True
                            stats["queue_overflow_count"] += 1
                            event_logs.append({
                                "event": "FAN_Q_OVERFLOW",
                                "reason": "QUEUE_LIMIT_EXCEEDED",
                                "max_size": max_queue_size
                            })
                    else:
                        event_queue.append({
                            "pid": pid,
                            "path": path,
                            "fan_type": fan_type,
                            "count": 1
                        })
                        stats["notif_events_queued"] += 1
                        event_logs.append({
                            "event": "FANOTIFY_NOTIF_ENQUEUED",
                            "pid": pid,
                            "path": path,
                            "fan_type": fan_type
                        })
                        
                stats["vfs_calls_completed"] += 1
                
        elif etype == "DAEMON_READ_EVENTS":
            count = ev.get("count", max_queue_size)
            drained = []
            to_drain = min(count, len(event_queue))
            for _ in range(to_drain):
                drained.append(event_queue.pop(0))
            if len(event_queue) < max_queue_size:
                overflow_triggered = False
            event_logs.append({
                "event": "DAEMON_READ_EVENTS",
                "drained_count": len(drained),
                "remaining_queue": len(event_queue)
            })

    return {
        "stats": stats,
        "queue_status": {
            "current_queue_depth": len(event_queue),
            "max_queue_size": max_queue_size,
            "overflow_active": overflow_triggered
        },
        "event_logs": event_logs
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_fanotify_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
