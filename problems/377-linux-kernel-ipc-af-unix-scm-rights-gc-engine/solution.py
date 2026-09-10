import json
import sys
from collections import deque

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
    initial_state = payload.get("initial_state", {})
    events = payload.get("events", [])
    
    default_rcvbuf = int(config.get("default_rcvbuf", 65536))
    
    sockets = {}
    init_sockets = initial_state.get("sockets", [])
    for s_id in init_sockets:
        sockets[s_id] = {
            "external_refs": 1,
            "inflight_refs": 0,
            "rcv_queue": deque(),
            "rcv_buf_used": 0,
            "alive": True
        }
        
    history = []
    total_gc_purged = 0
    total_overflow_drops = 0
    
    def free_socket(s_id):
        nonlocal total_gc_purged
        if s_id not in sockets or not sockets[s_id]["alive"]:
            return
        sockets[s_id]["alive"] = False
        while sockets[s_id]["rcv_queue"]:
            msg = sockets[s_id]["rcv_queue"].popleft()
            for passed_id in msg["fds_passed"]:
                if passed_id in sockets:
                    sockets[passed_id]["inflight_refs"] = max(0, sockets[passed_id]["inflight_refs"] - 1)
                    if sockets[passed_id]["external_refs"] == 0 and sockets[passed_id]["inflight_refs"] == 0:
                        free_socket(passed_id)
        sockets[s_id]["rcv_buf_used"] = 0

    for ep_idx, ev in enumerate(events):
        ev_type = ev["type"]
        ev_params = ev.get("params", {})
        
        status = "OK"
        detail = ""
        purged_in_step = []
        
        if ev_type == "CREATE_SOCKET":
            s_id = ev_params["socket_id"]
            sockets[s_id] = {
                "external_refs": 1,
                "inflight_refs": 0,
                "rcv_queue": deque(),
                "rcv_buf_used": 0,
                "alive": True
            }
            status = "SOCKET_CREATED"
            detail = f"Socket {s_id} created."
            
        elif ev_type == "SEND_MSG_SCM_RIGHTS":
            src_id = ev_params.get("src_socket", "")
            dst_id = ev_params.get("dst_socket", "")
            data_bytes = int(ev_params.get("data_bytes", 128))
            passed_fds = ev_params.get("passed_fds", [])
            msg_id = ev_params.get("msg_id", f"m_{ep_idx}")
            
            if dst_id not in sockets or not sockets[dst_id]["alive"]:
                status = "DESTINATION_DEAD"
                detail = f"Destination socket {dst_id} does not exist or dead."
            elif sockets[dst_id]["rcv_buf_used"] + data_bytes > default_rcvbuf:
                total_overflow_drops += 1
                status = "BUFFER_OVERFLOW_DROPPED"
                detail = f"Destination {dst_id} buffer full ({sockets[dst_id]['rcv_buf_used']}/{default_rcvbuf})."
            else:
                sockets[dst_id]["rcv_queue"].append({
                    "msg_id": msg_id,
                    "data_bytes": data_bytes,
                    "fds_passed": list(passed_fds)
                })
                sockets[dst_id]["rcv_buf_used"] += data_bytes
                for p_id in passed_fds:
                    if p_id in sockets:
                        sockets[p_id]["inflight_refs"] += 1
                status = "MSG_SENT"
                detail = f"Sent msg {msg_id} to {dst_id} with FDs {passed_fds}."
                
        elif ev_type == "RECV_MSG":
            dst_id = ev_params.get("socket_id", "")
            if dst_id not in sockets or not sockets[dst_id]["alive"] or not sockets[dst_id]["rcv_queue"]:
                status = "QUEUE_EMPTY"
                detail = f"Socket {dst_id} has no messages."
            else:
                msg = sockets[dst_id]["rcv_queue"].popleft()
                sockets[dst_id]["rcv_buf_used"] = max(0, sockets[dst_id]["rcv_buf_used"] - msg["data_bytes"])
                for p_id in msg["fds_passed"]:
                    if p_id in sockets:
                        sockets[p_id]["inflight_refs"] = max(0, sockets[p_id]["inflight_refs"] - 1)
                        sockets[p_id]["external_refs"] += 1
                status = "MSG_RECEIVED"
                detail = f"Received msg {msg['msg_id']} on {dst_id}, restored FDs {msg['fds_passed']}."
                
        elif ev_type == "CLOSE_FD":
            s_id = ev_params.get("socket_id", "")
            if s_id in sockets and sockets[s_id]["alive"]:
                sockets[s_id]["external_refs"] = max(0, sockets[s_id]["external_refs"] - 1)
                if sockets[s_id]["external_refs"] == 0 and sockets[s_id]["inflight_refs"] == 0:
                    free_socket(s_id)
                    status = "SOCKET_FREED"
                    detail = f"Socket {s_id} has 0 external and 0 inflight refs. Immediately freed."
                elif sockets[s_id]["external_refs"] == 0:
                    status = "ORPHANED_IN_FLIGHT"
                    detail = f"Socket {s_id} closed by user but held inflight ({sockets[s_id]['inflight_refs']})."
                else:
                    status = "FD_CLOSED"
                    detail = f"Socket {s_id} external_refs decremented to {sockets[s_id]['external_refs']}."
            else:
                status = "SOCKET_NOT_FOUND"
                detail = f"Socket {s_id} not found or already dead."
                
        elif ev_type == "RUN_UNIX_GC":
            reachable = set()
            queue = deque()
            for s_id, s_data in sockets.items():
                if s_data["alive"] and s_data["external_refs"] > 0:
                    reachable.add(s_id)
                    queue.append(s_id)
                    
            while queue:
                curr = queue.popleft()
                if curr in sockets and sockets[curr]["alive"]:
                    for msg in sockets[curr]["rcv_queue"]:
                        for p_id in msg["fds_passed"]:
                            if p_id in sockets and sockets[p_id]["alive"] and p_id not in reachable:
                                reachable.add(p_id)
                                queue.append(p_id)
                                
            dead_candidates = [s_id for s_id, s_data in sockets.items() if s_data["alive"] and s_id not in reachable]
            dead_candidates.sort()
            
            for dead_id in dead_candidates:
                free_socket(dead_id)
                purged_in_step.append(dead_id)
                total_gc_purged += 1
                
            status = "GC_RUN_COMPLETED"
            detail = f"unix_gc completed. Purged {len(dead_candidates)} cyclic orphan sockets: {dead_candidates}."
            
        alive_count = sum(1 for s in sockets.values() if s["alive"])
        
        history.append({
            "epoch": ep_idx + 1,
            "event": ev_type,
            "status": status,
            "alive_socket_count": alive_count,
            "purged_sockets": purged_in_step,
            "detail": detail
        })
        
    result = {
        "alive_socket_count": sum(1 for s in sockets.values() if s["alive"]),
        "total_gc_purged": total_gc_purged,
        "total_overflow_drops": total_overflow_drops,
        "sockets": {
            s_id: {
                "alive": s["alive"],
                "external_refs": s["external_refs"],
                "inflight_refs": s["inflight_refs"],
                "rcv_buf_used": s["rcv_buf_used"],
                "queue_len": len(s["rcv_queue"])
            } for s_id, s in sorted(sockets.items())
        },
        "history": history
    }
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    simulate()
