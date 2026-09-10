import sys
import json

# Ensure UTF-8 IO
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

STATE_FOLLOWER = "FOLLOWER"
STATE_PRECANDIDATE = "PRECANDIDATE"
STATE_CANDIDATE = "CANDIDATE"
STATE_LEADER = "LEADER"

def get_last_log(log):
    if log:
        return log[-1]["term"], log[-1]["index"]
    return 0, 0

def is_log_up_to_date(c_term, c_idx, my_term, my_idx):
    if c_term != my_term:
        return c_term > my_term
    return c_idx >= my_idx

def run_raft_simulation(req):
    cluster_cfg = req["cluster"]
    node_ids = cluster_cfg["nodes"]
    min_to = cluster_cfg.get("min_election_timeout", 150)
    drift = cluster_cfg.get("clock_drift_bound", 0.05)
    enable_prevote = cluster_cfg.get("enable_prevote", True)
    
    quorum = (len(node_ids) // 2) + 1
    lease_duration = min_to * (1.0 - drift)
    
    nodes = {}
    init_states = req.get("initial_states", {})
    for nid in node_ids:
        st = init_states.get(nid, {})
        peers = [p for p in node_ids if p != nid]
        nodes[nid] = {
            "node_id": nid,
            "peers": peers,
            "state": st.get("state", STATE_FOLLOWER),
            "term": st.get("term", 1),
            "voted_for": st.get("voted_for", None),
            "log": st.get("log", []),
            "last_heartbeat_time": st.get("last_heartbeat_time", 0),
            "lease_valid_until": st.get("lease_valid_until", 0),
            "pre_votes": set(),
            "votes": set()
        }
        
    timeline_logs = []
    
    for ev in req.get("timeline", []):
        t = ev["time"]
        etype = ev["event"]
        
        if etype == "HEARTBEAT_QUORUM_ACK":
            lid = ev["leader_id"]
            acks = set(ev["acks"])
            ldr = nodes[lid]
            if ldr["state"] == STATE_LEADER:
                for a in acks:
                    if a in nodes and a != lid:
                        nodes[a]["last_heartbeat_time"] = t
                if len(acks) >= quorum:
                    new_lease = round(t + lease_duration, 2)
                    ldr["lease_valid_until"] = new_lease
                    timeline_logs.append({
                        "time": t,
                        "event": etype,
                        "leader_id": lid,
                        "quorum_acks": list(sorted(acks)),
                        "lease_renewed": True,
                        "lease_valid_until": new_lease
                    })
                else:
                    timeline_logs.append({
                        "time": t,
                        "event": etype,
                        "leader_id": lid,
                        "quorum_acks": list(sorted(acks)),
                        "lease_renewed": False,
                        "lease_valid_until": ldr["lease_valid_until"]
                    })
            else:
                timeline_logs.append({
                    "time": t,
                    "event": etype,
                    "leader_id": lid,
                    "error": "NOT_LEADER"
                })

        elif etype == "CLIENT_READ":
            nid = ev["node_id"]
            rid = ev["read_id"]
            node = nodes[nid]
            if node["state"] != STATE_LEADER:
                timeline_logs.append({
                    "time": t,
                    "event": etype,
                    "read_id": rid,
                    "node_id": nid,
                    "status": "REJECTED_NOT_LEADER",
                    "served_via": "REJECT"
                })
            elif t <= node["lease_valid_until"]:
                rem = round(node["lease_valid_until"] - t, 2)
                timeline_logs.append({
                    "time": t,
                    "event": etype,
                    "read_id": rid,
                    "node_id": nid,
                    "status": "SUCCESS",
                    "served_via": "LOCAL_LEASE_READ",
                    "lease_remaining_ms": rem
                })
            else:
                timeline_logs.append({
                    "time": t,
                    "event": etype,
                    "read_id": rid,
                    "node_id": nid,
                    "status": "FALLBACK_REQUIRED",
                    "served_via": "QUORUM_READ_INDEX",
                    "lease_remaining_ms": 0.0
                })

        elif etype == "ELECTION_TIMEOUT":
            nid = ev["node_id"]
            node = nodes[nid]
            if node["state"] == STATE_LEADER:
                continue
                
            reachable_peers = ev.get("reachable_peers", node["peers"])
            
            if enable_prevote:
                node["state"] = STATE_PRECANDIDATE
                node["pre_votes"] = {nid}
                cand_term = node["term"] + 1
                cand_log_term, cand_log_idx = get_last_log(node["log"])
                
                granted_peers = []
                rejected_peers = []
                
                for p in reachable_peers:
                    peer = nodes[p]
                    if (t - peer["last_heartbeat_time"]) < min_to:
                        rejected_peers.append({"peer": p, "reason": "ACTIVE_LEADER_EXISTS"})
                        continue
                    p_term, p_idx = get_last_log(peer["log"])
                    if not is_log_up_to_date(cand_log_term, cand_log_idx, p_term, p_idx):
                        rejected_peers.append({"peer": p, "reason": "LOG_INCOMPLETE"})
                        continue
                    if cand_term < peer["term"] + 1:
                        rejected_peers.append({"peer": p, "reason": "STALE_TERM"})
                        continue
                        
                    node["pre_votes"].add(p)
                    granted_peers.append(p)
                    
                prevote_won = (len(node["pre_votes"]) >= quorum)
                
                if prevote_won:
                    node["state"] = STATE_CANDIDATE
                    node["term"] += 1
                    node["voted_for"] = nid
                    node["votes"] = {nid}
                    
                    real_granted = []
                    for p in reachable_peers:
                        peer = nodes[p]
                        if peer["term"] < node["term"]:
                            peer["term"] = node["term"]
                            peer["state"] = STATE_FOLLOWER
                            peer["voted_for"] = None
                        if peer["voted_for"] is None or peer["voted_for"] == nid:
                            peer["voted_for"] = nid
                            node["votes"].add(p)
                            real_granted.append(p)
                            
                    election_won = (len(node["votes"]) >= quorum)
                    if election_won:
                        node["state"] = STATE_LEADER
                        node["lease_valid_until"] = round(t + lease_duration, 2)
                        
                    timeline_logs.append({
                        "time": t,
                        "event": etype,
                        "node_id": nid,
                        "phase": "PREVOTE_SUCCESS_AND_ELECTION",
                        "prevote_granted_by": list(sorted(node["pre_votes"])),
                        "real_votes_granted_by": list(sorted(node["votes"])),
                        "new_state": node["state"],
                        "new_term": node["term"],
                        "elected_leader": election_won
                    })
                else:
                    timeline_logs.append({
                        "time": t,
                        "event": etype,
                        "node_id": nid,
                        "phase": "PREVOTE_REJECTED",
                        "pre_votes_collected": len(node["pre_votes"]),
                        "quorum_required": quorum,
                        "rejections": rejected_peers,
                        "term_preserved": node["term"],
                        "new_state": node["state"]
                    })
            else:
                node["state"] = STATE_CANDIDATE
                node["term"] += 1
                node["voted_for"] = nid
                node["votes"] = {nid}
                cand_log_term, cand_log_idx = get_last_log(node["log"])
                
                for p in reachable_peers:
                    peer = nodes[p]
                    if node["term"] > peer["term"]:
                        peer["term"] = node["term"]
                        peer["state"] = STATE_FOLLOWER
                        peer["voted_for"] = None
                    p_term, p_idx = get_last_log(peer["log"])
                    if is_log_up_to_date(cand_log_term, cand_log_idx, p_term, p_idx):
                        if peer["voted_for"] is None or peer["voted_for"] == nid:
                            peer["voted_for"] = nid
                            node["votes"].add(p)
                            
                election_won = (len(node["votes"]) >= quorum)
                if election_won:
                    node["state"] = STATE_LEADER
                    node["lease_valid_until"] = round(t + lease_duration, 2)
                    
                timeline_logs.append({
                    "time": t,
                    "event": etype,
                    "node_id": nid,
                    "phase": "NAIVE_ELECTION",
                    "new_term": node["term"],
                    "votes_collected": len(node["votes"]),
                    "new_state": node["state"],
                    "elected_leader": election_won
                })

        elif etype == "NETWORK_RECONNECT":
            nid = ev["node_id"]
            targets = ev.get("targets", nodes[nid]["peers"])
            disrupted_node = nodes[nid]
            disrupted_term = disrupted_node["term"]
            
            stepped_down_nodes = []
            rejected_targets = []
            
            for tid in targets:
                target = nodes[tid]
                if disrupted_term > target["term"]:
                    old_state = target["state"]
                    target["term"] = disrupted_term
                    target["state"] = STATE_FOLLOWER
                    target["voted_for"] = None
                    stepped_down_nodes.append({"node_id": tid, "previous_state": old_state})
                else:
                    rejected_targets.append(tid)
                    
            timeline_logs.append({
                "time": t,
                "event": etype,
                "reconnected_node": nid,
                "reconnected_term": disrupted_term,
                "stepped_down_nodes": stepped_down_nodes,
                "undisturbed_nodes": rejected_targets
            })

    final_cluster_states = {}
    for nid, node in nodes.items():
        final_cluster_states[nid] = {
            "state": node["state"],
            "term": node["term"],
            "voted_for": node["voted_for"],
            "lease_valid_until": node["lease_valid_until"]
        }

    return {
        "enable_prevote": enable_prevote,
        "quorum_size": quorum,
        "lease_duration_ms": lease_duration,
        "timeline_events": timeline_logs,
        "final_cluster_states": final_cluster_states
    }

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    req = json.loads(raw)
    res = run_raft_simulation(req)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
