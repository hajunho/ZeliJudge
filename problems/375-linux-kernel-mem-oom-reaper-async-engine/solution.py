import json
import sys

# Ensure UTF-8 input/output on Windows
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
        
    payload = json.loads(raw_data)
    config = payload.get("config", {})
    min_watermark = int(config.get("min_watermark_pages", 500))
    max_retries = int(config.get("max_reap_retries", 3))
    init_free_pages = int(config.get("initial_free_pages", 1000))
    
    tasks_input = payload.get("tasks", [])
    operations = payload.get("operations", [])
    
    tasks = {}
    for t in tasks_input:
        pid = int(t["pid"])
        anon = int(t.get("anon_pages", 100))
        file_p = int(t.get("file_pages", 20))
        pinned = int(t.get("pinned_pages", 0))
        adj = int(t.get("oom_score_adj", 0))
        tasks[pid] = {
            "pid": pid,
            "name": t.get("name", f"task_{pid}"),
            "state": t.get("state", "RUNNING"),
            "anon_pages": anon,
            "file_pages": file_p,
            "pinned_pages": pinned,
            "oom_score_adj": adj,
            "holds_mmap_lock_write": bool(t.get("holds_mmap_lock_write", False)),
            "is_oom_victim": False,
            "mmf_oom_skip": False,
            "reap_attempts": 0,
            "reaped_pages_total": 0
        }
        
    free_pages = init_free_pages
    oom_reaper_queue = []
    event_logs = []
    
    def calculate_badness(t):
        if t["state"] == "DEAD" or t["mmf_oom_skip"]:
            return -10000
        return (t["anon_pages"] + t["file_pages"]) + t["oom_score_adj"]

    def trigger_oom_killer(reason="OUT_OF_MEMORY"):
        nonlocal free_pages
        candidates = [t for t in tasks.values() if not t["mmf_oom_skip"] and t["state"] != "DEAD"]
        if not candidates:
            event_logs.append({
                "type": "OOM_PANIC",
                "reason": "NO_ELIGIBLE_VICTIMS",
                "free_pages": free_pages
            })
            return None
            
        best = max(candidates, key=lambda t: (calculate_badness(t), -t["pid"]))
        if calculate_badness(best) < 0:
            event_logs.append({
                "type": "OOM_PANIC",
                "reason": "ALL_VICTIMS_PROTECTED",
                "free_pages": free_pages
            })
            return None
            
        best["is_oom_victim"] = True
        event_logs.append({
            "type": "OOM_KILL_SELECTED",
            "victim_pid": best["pid"],
            "victim_name": best["name"],
            "badness_score": calculate_badness(best),
            "free_pages": free_pages
        })
        
        if best["pid"] not in oom_reaper_queue:
            oom_reaper_queue.append(best["pid"])
            
        return best["pid"]

    def process_reaper():
        nonlocal free_pages
        if not oom_reaper_queue:
            return
            
        pid = oom_reaper_queue.pop(0)
        t = tasks[pid]
        
        if t["holds_mmap_lock_write"]:
            t["reap_attempts"] += 1
            if t["reap_attempts"] >= max_retries:
                t["mmf_oom_skip"] = True
                event_logs.append({
                    "type": "OOM_REAP_GIVE_UP",
                    "pid": pid,
                    "attempts": t["reap_attempts"],
                    "status": "MMF_OOM_SKIP_FORCED"
                })
            else:
                oom_reaper_queue.append(pid)
                event_logs.append({
                    "type": "OOM_REAP_TRYLOCK_FAILED",
                    "pid": pid,
                    "attempts": t["reap_attempts"]
                })
        else:
            reapable = max(0, t["anon_pages"] - t["pinned_pages"])
            t["anon_pages"] = t["pinned_pages"]
            t["reaped_pages_total"] += reapable
            free_pages += reapable
            t["mmf_oom_skip"] = True
            event_logs.append({
                "type": "OOM_REAP_SUCCESS",
                "pid": pid,
                "reaped_pages": reapable,
                "remaining_anon": t["anon_pages"],
                "free_pages_now": free_pages,
                "status": "MMF_OOM_SKIP_SET"
            })

    for op in operations:
        op_type = op["type"]
        if op_type == "MEM_ALLOC":
            pid = op["pid"]
            req_pages = int(op["pages"])
            if free_pages - req_pages < min_watermark:
                event_logs.append({
                    "type": "WATERMARK_BREACH",
                    "pid": pid,
                    "requested": req_pages,
                    "free_pages": free_pages,
                    "watermark": min_watermark
                })
                trigger_oom_killer(reason="WATERMARK_BREACH")
            else:
                free_pages -= req_pages
                if pid in tasks:
                    tasks[pid]["anon_pages"] += req_pages
                    
        elif op_type == "TRIGGER_OOM":
            trigger_oom_killer(reason=op.get("reason", "MANUAL_OOM"))
            
        elif op_type == "REAPER_STEP":
            process_reaper()
            
        elif op_type == "LOCK_ACQUIRE":
            pid = op["pid"]
            if pid in tasks:
                tasks[pid]["holds_mmap_lock_write"] = True
                
        elif op_type == "LOCK_RELEASE":
            pid = op["pid"]
            if pid in tasks:
                tasks[pid]["holds_mmap_lock_write"] = False
                
        elif op_type == "TASK_STATE_CHANGE":
            pid = op["pid"]
            new_state = op["state"]
            if pid in tasks:
                tasks[pid]["state"] = new_state
                
        elif op_type == "TASK_EXIT":
            pid = op["pid"]
            if pid in tasks:
                t = tasks[pid]
                if t["state"] != "UNINTERRUPTIBLE_D_STATE":
                    released = t["anon_pages"] + t["file_pages"]
                    free_pages += released
                    t["anon_pages"] = 0
                    t["file_pages"] = 0
                    t["pinned_pages"] = 0
                    t["state"] = "DEAD"
                    t["mmf_oom_skip"] = True
                    event_logs.append({
                        "type": "TASK_EXITED_NORMAL",
                        "pid": pid,
                        "released_pages": released,
                        "free_pages_now": free_pages
                    })
                else:
                    event_logs.append({
                        "type": "TASK_EXIT_BLOCKED_D_STATE",
                        "pid": pid,
                        "state": t["state"]
                    })
                    
    task_summaries = {}
    for pid, t in tasks.items():
        task_summaries[pid] = {
            "name": t["name"],
            "state": t["state"],
            "anon_pages": t["anon_pages"],
            "file_pages": t["file_pages"],
            "pinned_pages": t["pinned_pages"],
            "is_oom_victim": t["is_oom_victim"],
            "mmf_oom_skip": t["mmf_oom_skip"],
            "reap_attempts": t["reap_attempts"],
            "reaped_pages_total": t["reaped_pages_total"]
        }
        
    result = {
        "final_free_pages": free_pages,
        "reaper_queue_remaining": len(oom_reaper_queue),
        "tasks": task_summaries,
        "events": event_logs
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
