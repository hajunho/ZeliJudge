import sys
import json

def simulate_raft_conflict_resolution(input_data):
    cluster = input_data["cluster"]
    nodes = cluster["nodes"]
    leader_id = cluster["leader_id"]
    leader_term = cluster["leader_term"]
    leader_commit = cluster["leader_commit"]
    leader_log = [dict(e) for e in cluster["leader_log"]]
    
    followers_data = cluster["followers"]
    new_proposals = input_data.get("new_proposals", [])
    strategy = input_data.get("strategy", "FAST_BACKTRACKING")
    max_rtt_limit = input_data.get("options", {}).get("max_rtt_limit", 50)
    
    followers = {}
    for fid, fval in followers_data.items():
        followers[fid] = {
            "current_term": fval.get("current_term", leader_term),
            "commit_index": fval.get("commit_index", 0),
            "log": [dict(e) for e in fval["log"]],
            "truncated_count": 0,
            "rtt_rounds": 0,
            "status": "IN_PROGRESS",
            "safety_violation": False,
            "violation_reason": None
        }
        
    # Append new proposals to leader's log with leader_term
    for prop in new_proposals:
        new_idx = len(leader_log) + 1
        leader_log.append({
            "index": new_idx,
            "term": leader_term,
            "cmd": prop
        })
        
    next_index = {}
    match_index = {}
    for fid in followers:
        next_index[fid] = len(leader_log) + 1
        match_index[fid] = 0

    total_rtts = 0
    majority_quorum = (len(nodes) // 2) + 1

    for fid, fstate in followers.items():
        rounds = 0
        while rounds < max_rtt_limit:
            rounds += 1
            total_rtts += 1
            
            p_index = next_index[fid] - 1
            p_term = 0
            if p_index > 0:
                if p_index <= len(leader_log):
                    p_term = leader_log[p_index - 1]["term"]
                else:
                    p_term = leader_log[-1]["term"]
                    
            entries_to_send = leader_log[p_index:]
            
            if leader_term < fstate["current_term"]:
                fstate["status"] = "REJECTED_STALE_LEADER"
                break
                
            fstate["current_term"] = leader_term
            
            success = False
            conflict_term = None
            conflict_index = None
            
            if p_index == 0:
                success = True
            elif p_index > len(fstate["log"]):
                success = False
                conflict_term = None
                conflict_index = len(fstate["log"]) + 1
            elif fstate["log"][p_index - 1]["term"] != p_term:
                if p_index <= fstate["commit_index"]:
                    fstate["safety_violation"] = True
                    fstate["violation_reason"] = f"Leader attempted to overwrite committed entry at index {p_index} (follower commit_index={fstate['commit_index']})"
                    fstate["status"] = "SAFETY_VIOLATION"
                    break
                
                success = False
                mismatch_term = fstate["log"][p_index - 1]["term"]
                conflict_term = mismatch_term
                for i, entry in enumerate(fstate["log"], 1):
                    if entry["term"] == mismatch_term:
                        conflict_index = i
                        break
            else:
                success = True
                
            if not success:
                if strategy == "NAIVE_DECREMENT":
                    next_index[fid] = max(1, next_index[fid] - 1)
                elif strategy == "FAST_BACKTRACKING":
                    if conflict_term is not None:
                        leader_indices_with_term = [e["index"] for e in leader_log if e["term"] == conflict_term]
                        if leader_indices_with_term:
                            next_index[fid] = max(leader_indices_with_term) + 1
                        else:
                            next_index[fid] = conflict_index
                    else:
                        next_index[fid] = conflict_index
                continue
                
            for entry in entries_to_send:
                e_idx = entry["index"]
                if e_idx <= len(fstate["log"]):
                    if fstate["log"][e_idx - 1]["term"] != entry["term"]:
                        if e_idx <= fstate["commit_index"]:
                            fstate["safety_violation"] = True
                            fstate["violation_reason"] = f"Cannot truncate committed entry at index {e_idx} <= commit_index {fstate['commit_index']}"
                            fstate["status"] = "SAFETY_VIOLATION"
                            break
                        truncated = len(fstate["log"]) - (e_idx - 1)
                        fstate["truncated_count"] += truncated
                        fstate["log"] = fstate["log"][:e_idx - 1]
                        fstate["log"].append(dict(entry))
                else:
                    fstate["log"].append(dict(entry))
                    
            if fstate.get("safety_violation"):
                break
                
            match_index[fid] = len(fstate["log"])
            next_index[fid] = len(fstate["log"]) + 1
            
            if leader_commit > fstate["commit_index"]:
                fstate["commit_index"] = min(leader_commit, len(fstate["log"]))
                
            if match_index[fid] == len(leader_log):
                fstate["status"] = "SYNCHRONIZED"
                break
                
        fstate["rtt_rounds"] = rounds
        if rounds >= max_rtt_limit and fstate["status"] == "IN_PROGRESS":
            fstate["status"] = "RTT_EXCEEDED"

    leader_new_commit = leader_commit
    for idx in range(leader_commit + 1, len(leader_log) + 1):
        entry = leader_log[idx - 1]
        if entry["term"] == leader_term:
            replicated_count = 1
            for fid in followers:
                if match_index[fid] >= idx:
                    replicated_count += 1
            if replicated_count >= majority_quorum:
                leader_new_commit = idx

    if leader_new_commit > leader_commit:
        for fid, fstate in followers.items():
            if fstate["status"] == "SYNCHRONIZED":
                fstate["commit_index"] = min(leader_new_commit, len(fstate["log"]))

    committed_proposals = []
    for entry in leader_log:
        if entry["index"] <= leader_new_commit and entry["cmd"] in new_proposals:
            committed_proposals.append(entry["cmd"])

    follower_reports = {}
    any_safety_violation = False
    all_synchronized = True

    for fid in sorted(followers.keys()):
        f = followers[fid]
        if f["safety_violation"]:
            any_safety_violation = True
            all_synchronized = False
        if f["status"] != "SYNCHRONIZED":
            all_synchronized = False
            
        follower_reports[fid] = {
            "status": f["status"],
            "rtt_rounds": f["rtt_rounds"],
            "truncated_entries_count": f["truncated_count"],
            "final_log_length": len(f["log"]),
            "commit_index": f["commit_index"],
            "match_index": match_index[fid],
            "last_log_term": f["log"][-1]["term"] if f["log"] else 0
        }
        if f["safety_violation"]:
            follower_reports[fid]["violation_reason"] = f["violation_reason"]

    consensus_status = "HEALTHY"
    if any_safety_violation:
        consensus_status = "FATAL_SAFETY_VIOLATION"
    elif not all_synchronized:
        consensus_status = "PARTIAL_CONVERGENCE"

    return {
        "strategy_used": strategy,
        "leader_metrics": {
            "leader_id": leader_id,
            "leader_term": leader_term,
            "initial_commit_index": leader_commit,
            "final_commit_index": leader_new_commit,
            "total_log_entries": len(leader_log),
            "committed_proposals": committed_proposals,
            "quorum_size": majority_quorum
        },
        "followers": follower_reports,
        "cluster_summary": {
            "total_cluster_rtts": total_rtts,
            "consensus_status": consensus_status,
            "all_synchronized": all_synchronized
        }
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = simulate_raft_conflict_resolution(input_data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
