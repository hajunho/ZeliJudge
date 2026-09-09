#!/usr/bin/env python3
"""
ZeliJudge Problem #206: Raft Consensus - Stop-and-Wait vs Pipelined Replication & In-flight Window Flow Control
분산 합의 Raft: Stop-and-Wait 복제 병목 vs Pipelined 파이프라인 복제와 In-flight 윈도우 흐름 제어

Reference Implementation
"""

import sys
import json
import heapq
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set

@dataclass(order=True)
class Event:
    timestamp_ms: float
    event_id: int
    event_type: str = field(compare=False)
    payload: Dict[str, Any] = field(compare=False)

class InflightWindow:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.buffer: List[tuple] = []  # list of (rpc_id, end_index)

    def count(self) -> int:
        return len(self.buffer)

    def full(self) -> bool:
        return len(self.buffer) >= self.capacity

    def add(self, rpc_id: int, end_index: int):
        self.buffer.append((rpc_id, end_index))

    def free_to(self, match_index: int) -> int:
        freed = 0
        while self.buffer and self.buffer[0][1] <= match_index:
            self.buffer.pop(0)
            freed += 1
        return freed

    def reset(self):
        self.buffer.clear()

def simulate_raft_pipeline(data: Dict[str, Any]) -> Dict[str, Any]:
    cluster_cfg = data["cluster"]
    leader_id = cluster_cfg.get("leader_id", "node-1")
    nodes = cluster_cfg["nodes"]
    followers = [n for n in nodes if n != leader_id]
    quorum_size = (len(nodes) // 2) + 1
    current_term = cluster_cfg.get("current_term", 1)

    rep_cfg = data["replication_config"]
    mode = rep_cfg["mode"]  # STOP_AND_WAIT, UNBOUNDED_PIPELINING, PIPELINED_FLOW_CONTROL
    max_inflight = rep_cfg.get("max_inflight", 8)
    batch_size = rep_cfg.get("batch_size", 10)

    # Initial network latency per peer
    base_rtt = cluster_cfg.get("network", {}).get("default_rtt_ms", 10.0)
    peer_rtt = {f: base_rtt for f in followers}
    for f, rtt in cluster_cfg.get("network", {}).get("peer_rtt_ms", {}).items():
        peer_rtt[f] = rtt

    # Leader state
    leader_log = []  # list of {"index": i, "term": current_term, "data": ...}
    commit_index = 0
    proposal_times = {}  # log_index -> propose_timestamp_ms
    commit_times = {}  # log_index -> commit_timestamp_ms

    # Peer states
    peer_state = {}
    peer_metrics = {}
    for f in followers:
        init_match = cluster_cfg.get("initial_match_index", {}).get(f, 0)
        peer_state[f] = {
            "next_index": init_match + 1,
            "match_index": init_match,
            "state": "StateReplicate" if mode != "PIPELINED_FLOW_CONTROL" else "StateProbe",
            "inflights": InflightWindow(max_inflight if mode == "PIPELINED_FLOW_CONTROL" else (1 if mode == "STOP_AND_WAIT" else 999999)),
            "is_waiting_ack": False,
            "valid_rpc_ids": set(),  # rpc_ids that are currently valid
            "stall_until_ms": 0.0
        }
        peer_metrics[f] = {
            "rpc_sent_count": 0,
            "rejections_count": 0,
            "cascading_rejections": 0,
            "max_inflight_reached": 0,
            "throttled_events_count": 0
        }

    # Follower simulated logs
    follower_logs = {f: [] for f in followers}
    # Pre-populate initial matching entries if any
    for f in followers:
        for idx in range(1, peer_state[f]["match_index"] + 1):
            follower_logs[f].append({"index": idx, "term": current_term, "data": f"init_{idx}"})
            if len(leader_log) < idx:
                leader_log.append({"index": idx, "term": current_term, "data": f"init_{idx}"})

    # Event Queue
    event_queue: List[Event] = []
    event_counter = 0

    def push_event(ts: float, etype: str, payload: Dict[str, Any]):
        nonlocal event_counter
        event_counter += 1
        heapq.heappush(event_queue, Event(ts, event_counter, etype, payload))

    # Load workload events
    for op in data.get("workload", []):
        ts = float(op["timestamp_ms"])
        push_event(ts, op["type"], op)

    # RPC tracking
    next_rpc_id = 1
    total_rejections = 0
    cascading_rejection_storms = 0
    peak_inflight_overall = 0
    consecutive_rejections = {f: 0 for f in followers}

    def trigger_replication(peer_id: str, current_time: float):
        nonlocal next_rpc_id, peak_inflight_overall
        st = peer_state[peer_id]
        met = peer_metrics[peer_id]

        if mode == "STOP_AND_WAIT":
            if st["is_waiting_ack"]:
                return
            if st["next_index"] <= len(leader_log):
                start_idx = st["next_index"]
                end_idx = min(start_idx + batch_size - 1, len(leader_log))
                entries = leader_log[start_idx - 1: end_idx]
                prev_log_index = start_idx - 1
                prev_log_term = leader_log[prev_log_index - 1]["term"] if prev_log_index > 0 else 0

                rpc_id = next_rpc_id
                next_rpc_id += 1
                st["is_waiting_ack"] = True
                st["inflights"].add(rpc_id, end_idx)
                st["valid_rpc_ids"].add(rpc_id)
                met["rpc_sent_count"] += 1
                met["max_inflight_reached"] = max(met["max_inflight_reached"], 1)
                peak_inflight_overall = max(peak_inflight_overall, 1)

                transit_delay = peer_rtt[peer_id] / 2.0
                push_event(current_time + transit_delay, "RPC_APPEND_ENTRIES", {
                    "rpc_id": rpc_id,
                    "peer_id": peer_id,
                    "term": current_term,
                    "leader_id": leader_id,
                    "prev_log_index": prev_log_index,
                    "prev_log_term": prev_log_term,
                    "entries": entries,
                    "leader_commit": commit_index,
                    "end_index": end_idx
                })

        elif mode == "UNBOUNDED_PIPELINING":
            while st["next_index"] <= len(leader_log):
                start_idx = st["next_index"]
                end_idx = min(start_idx + batch_size - 1, len(leader_log))
                entries = leader_log[start_idx - 1: end_idx]
                prev_log_index = start_idx - 1
                prev_log_term = leader_log[prev_log_index - 1]["term"] if prev_log_index > 0 else 0

                rpc_id = next_rpc_id
                next_rpc_id += 1
                st["inflights"].add(rpc_id, end_idx)
                st["valid_rpc_ids"].add(rpc_id)
                st["next_index"] = end_idx + 1  # Optimistically advance
                met["rpc_sent_count"] += 1

                inf_count = st["inflights"].count()
                met["max_inflight_reached"] = max(met["max_inflight_reached"], inf_count)
                peak_inflight_overall = max(peak_inflight_overall, inf_count)

                transit_delay = peer_rtt[peer_id] / 2.0
                push_event(current_time + transit_delay, "RPC_APPEND_ENTRIES", {
                    "rpc_id": rpc_id,
                    "peer_id": peer_id,
                    "term": current_term,
                    "leader_id": leader_id,
                    "prev_log_index": prev_log_index,
                    "prev_log_term": prev_log_term,
                    "entries": entries,
                    "leader_commit": commit_index,
                    "end_index": end_idx
                })

        elif mode == "PIPELINED_FLOW_CONTROL":
            allowed_limit = 1 if st["state"] == "StateProbe" else max_inflight
            while st["inflights"].count() < allowed_limit and st["next_index"] <= len(leader_log):
                start_idx = st["next_index"]
                end_idx = min(start_idx + batch_size - 1, len(leader_log))
                entries = leader_log[start_idx - 1: end_idx]
                prev_log_index = start_idx - 1
                prev_log_term = leader_log[prev_log_index - 1]["term"] if prev_log_index > 0 else 0

                rpc_id = next_rpc_id
                next_rpc_id += 1
                st["inflights"].add(rpc_id, end_idx)
                st["valid_rpc_ids"].add(rpc_id)
                st["next_index"] = end_idx + 1  # Optimistically advance in replicate mode
                met["rpc_sent_count"] += 1

                inf_count = st["inflights"].count()
                met["max_inflight_reached"] = max(met["max_inflight_reached"], inf_count)
                peak_inflight_overall = max(peak_inflight_overall, inf_count)

                transit_delay = peer_rtt[peer_id] / 2.0
                push_event(current_time + transit_delay, "RPC_APPEND_ENTRIES", {
                    "rpc_id": rpc_id,
                    "peer_id": peer_id,
                    "term": current_term,
                    "leader_id": leader_id,
                    "prev_log_index": prev_log_index,
                    "prev_log_term": prev_log_term,
                    "entries": entries,
                    "leader_commit": commit_index,
                    "end_index": end_idx
                })

            if st["next_index"] <= len(leader_log) and st["inflights"].count() >= allowed_limit:
                met["throttled_events_count"] += 1

    def advance_commit(current_time: float):
        nonlocal commit_index
        match_indexes = [len(leader_log)]  # leader itself
        for f in followers:
            match_indexes.append(peer_state[f]["match_index"])
        match_indexes.sort(reverse=True)
        # Quorum index: index at quorum_size - 1
        quorum_match = match_indexes[quorum_size - 1]
        if quorum_match > commit_index:
            # Raft safety: only commit if entry at quorum_match is of current_term
            if leader_log[quorum_match - 1]["term"] == current_term:
                for idx in range(commit_index + 1, quorum_match + 1):
                    commit_times[idx] = current_time
                commit_index = quorum_match

    # Run event loop
    while event_queue:
        ev = heapq.heappop(event_queue)
        cur_time = ev.timestamp_ms

        if ev.event_type == "CLIENT_PROPOSE":
            entries = ev.payload.get("entries", [])
            for e in entries:
                new_idx = len(leader_log) + 1
                leader_log.append({"index": new_idx, "term": current_term, "data": e.get("data", f"val_{new_idx}")})
                proposal_times[new_idx] = cur_time
            for f in followers:
                trigger_replication(f, cur_time)

        elif ev.event_type == "NETWORK_LATENCY_CHANGE":
            peer_id = ev.payload["peer_id"]
            peer_rtt[peer_id] = float(ev.payload["new_rtt_ms"])

        elif ev.event_type == "FOLLOWER_STALL":
            peer_id = ev.payload["peer_id"]
            dur = float(ev.payload["duration_ms"])
            peer_state[peer_id]["stall_until_ms"] = cur_time + dur

        elif ev.event_type == "INJECT_LOG_CONFLICT":
            peer_id = ev.payload["peer_id"]
            div_idx = int(ev.payload["diverge_at_index"])
            div_term = int(ev.payload.get("diverge_term", 99))
            flog = follower_logs[peer_id]
            while len(flog) >= div_idx:
                flog.pop()
            flog.append({"index": div_idx, "term": div_term, "data": "conflict_data"})

        elif ev.event_type == "RPC_APPEND_ENTRIES":
            peer_id = ev.payload["peer_id"]
            rpc_id = ev.payload["rpc_id"]
            st = peer_state[peer_id]

            if cur_time < st["stall_until_ms"]:
                push_event(st["stall_until_ms"], "RPC_APPEND_ENTRIES", ev.payload)
                continue

            prev_idx = ev.payload["prev_log_index"]
            prev_term = ev.payload["prev_log_term"]
            entries = ev.payload["entries"]
            flog = follower_logs[peer_id]

            success = False
            conflict_index = 1
            conflict_term = None

            if prev_idx == 0:
                success = True
            elif prev_idx <= len(flog):
                if flog[prev_idx - 1]["term"] == prev_term:
                    success = True
                else:
                    success = False
                    conflict_term = flog[prev_idx - 1]["term"]
                    for e in flog:
                        if e["term"] == conflict_term:
                            conflict_index = e["index"]
                            break
            else:
                success = False
                conflict_index = len(flog) + 1

            if success:
                while len(flog) > prev_idx:
                    flog.pop()
                for e in entries:
                    flog.append(e)
                match_index = len(flog)
                resp_payload = {
                    "rpc_id": rpc_id,
                    "peer_id": peer_id,
                    "success": True,
                    "match_index": match_index,
                    "end_index": ev.payload["end_index"]
                }
            else:
                resp_payload = {
                    "rpc_id": rpc_id,
                    "peer_id": peer_id,
                    "success": False,
                    "conflict_index": conflict_index,
                    "conflict_term": conflict_term,
                    "end_index": ev.payload["end_index"]
                }

            transit_delay = peer_rtt[peer_id] / 2.0
            push_event(cur_time + transit_delay, "RPC_APPEND_RESPONSE", resp_payload)

        elif ev.event_type == "RPC_APPEND_RESPONSE":
            peer_id = ev.payload["peer_id"]
            rpc_id = ev.payload["rpc_id"]
            success = ev.payload["success"]
            st = peer_state[peer_id]
            met = peer_metrics[peer_id]

            st["is_waiting_ack"] = False

            if mode == "STOP_AND_WAIT":
                st["inflights"].free_to(ev.payload["end_index"])
                if success:
                    st["match_index"] = ev.payload["match_index"]
                    st["next_index"] = st["match_index"] + 1
                    consecutive_rejections[peer_id] = 0
                    advance_commit(cur_time)
                else:
                    total_rejections += 1
                    met["rejections_count"] += 1
                    consecutive_rejections[peer_id] += 1
                    if consecutive_rejections[peer_id] > 1:
                        met["cascading_rejections"] += 1
                        cascading_rejection_storms += 1
                    conf_idx = ev.payload.get("conflict_index")
                    if conf_idx and conf_idx < st["next_index"]:
                        st["next_index"] = conf_idx
                    else:
                        st["next_index"] = max(1, st["next_index"] - 1)
                trigger_replication(peer_id, cur_time)

            elif mode == "UNBOUNDED_PIPELINING":
                st["inflights"].free_to(ev.payload["end_index"])
                if success:
                    st["match_index"] = max(st["match_index"], ev.payload["match_index"])
                    st["next_index"] = max(st["next_index"], st["match_index"] + 1)
                    consecutive_rejections[peer_id] = 0
                    advance_commit(cur_time)
                else:
                    total_rejections += 1
                    met["rejections_count"] += 1
                    consecutive_rejections[peer_id] += 1
                    if consecutive_rejections[peer_id] > 1:
                        met["cascading_rejections"] += 1
                        cascading_rejection_storms += 1
                    conf_idx = ev.payload.get("conflict_index")
                    if conf_idx:
                        st["next_index"] = conf_idx
                    else:
                        st["next_index"] = max(1, st["next_index"] - 1)
                trigger_replication(peer_id, cur_time)

            elif mode == "PIPELINED_FLOW_CONTROL":
                if rpc_id not in st["valid_rpc_ids"]:
                    # Discard stale response from invalidated epoch/inflight
                    continue
                st["valid_rpc_ids"].remove(rpc_id)

                if success:
                    st["state"] = "StateReplicate"
                    st["match_index"] = max(st["match_index"], ev.payload["match_index"])
                    st["next_index"] = max(st["next_index"], st["match_index"] + 1)
                    st["inflights"].free_to(ev.payload["match_index"])
                    consecutive_rejections[peer_id] = 0
                    advance_commit(cur_time)
                    trigger_replication(peer_id, cur_time)
                else:
                    total_rejections += 1
                    met["rejections_count"] += 1
                    consecutive_rejections[peer_id] += 1
                    if consecutive_rejections[peer_id] > 1:
                        met["cascading_rejections"] += 1
                        cascading_rejection_storms += 1

                    # Reset inflights and demote to probe
                    st["state"] = "StateProbe"
                    st["inflights"].reset()
                    st["valid_rpc_ids"].clear()

                    conf_idx = ev.payload.get("conflict_index")
                    if conf_idx:
                        st["next_index"] = conf_idx
                    else:
                        st["next_index"] = max(1, st["next_index"] - 1)

                    trigger_replication(peer_id, cur_time)

    # Metrics
    total_proposals = len(leader_log)
    committed_entries = commit_index
    commit_latencies = []
    for idx in range(1, commit_index + 1):
        if idx in commit_times and idx in proposal_times:
            commit_latencies.append(commit_times[idx] - proposal_times[idx])

    avg_latency = round(sum(commit_latencies) / len(commit_latencies), 2) if commit_latencies else 0.0
    max_latency = round(max(commit_latencies), 2) if commit_latencies else 0.0
    commit_rate = round((committed_entries / total_proposals) * 100.0, 1) if total_proposals > 0 else 0.0

    total_rpc_sent = sum(m["rpc_sent_count"] for m in peer_metrics.values())

    # Verdict determination
    if mode == "STOP_AND_WAIT":
        if avg_latency >= 30.0 or max_latency >= 50.0 or commit_rate < 100.0:
            verdict = "STOP_AND_WAIT_THROUGHPUT_COLLAPSE"
        else:
            verdict = "STOP_AND_WAIT_NOMINAL"
    elif mode == "UNBOUNDED_PIPELINING":
        if cascading_rejection_storms > 0:
            verdict = "UNBOUNDED_PIPELINING_CASCADING_REJECTION_STORM"
        elif peak_inflight_overall > 16:
            verdict = "UNBOUNDED_PIPELINING_BUFFER_BLOAT"
        else:
            verdict = "UNBOUNDED_PIPELINING_STABLE"
    elif mode == "PIPELINED_FLOW_CONTROL":
        if commit_rate == 100.0 and cascading_rejection_storms == 0 and peak_inflight_overall <= max_inflight:
            verdict = "OPTIMAL_PIPELINED_FLOW_CONTROL_CONVERGENCE"
        else:
            verdict = "FLOW_CONTROL_DEGRADED"
    else:
        verdict = "UNKNOWN"

    output = {
        "status": "SUCCESS",
        "verdict": verdict,
        "replication_mode": mode,
        "metrics": {
            "total_proposals": total_proposals,
            "committed_entries": committed_entries,
            "commit_rate_pct": commit_rate,
            "total_rpc_sent": total_rpc_sent,
            "total_rejections": total_rejections,
            "cascading_rejection_storms": cascading_rejection_storms,
            "peak_inflight_messages": peak_inflight_overall,
            "average_commit_latency_ms": avg_latency,
            "max_commit_latency_ms": max_latency
        },
        "peers": {}
    }

    for f in followers:
        output["peers"][f] = {
            "final_match_index": peer_state[f]["match_index"],
            "final_next_index": peer_state[f]["next_index"],
            "final_state": peer_state[f]["state"],
            "rpc_sent_count": peer_metrics[f]["rpc_sent_count"],
            "rejections_count": peer_metrics[f]["rejections_count"],
            "cascading_rejections": peer_metrics[f]["cascading_rejections"],
            "max_inflight_reached": peer_metrics[f]["max_inflight_reached"],
            "throttled_events_count": peer_metrics[f]["throttled_events_count"]
        }

    return output

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_raft_pipeline(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
