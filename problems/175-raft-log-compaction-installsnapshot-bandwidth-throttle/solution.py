# Core simulator implementation for Problem 174: Raft Log Compaction & InstallSnapshot Bandwidth Throttling
from typing import Dict, List, Any
import json
import sys

class RaftLogCompactionSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.nodes: List[str] = sys_cfg.get("nodes", ["node-1", "node-2", "node-3"])
        self.leader_id: str = self.nodes[0]
        self.followers: List[str] = self.nodes[1:]
        
        self.trailing_log_margin: int = sys_cfg.get("trailing_log_margin", 0)
        self.compaction_threshold: int = sys_cfg.get("compaction_threshold_logs", 100)
        self.snapshot_throttle_bytes: int = sys_cfg.get("snapshot_throttle_bytes_per_tick", 0)  # 0 = unlimited
        self.heartbeat_loss_threshold_bytes: int = sys_cfg.get("heartbeat_loss_threshold_bytes", 20000)
        self.election_timeout_ticks: int = sys_cfg.get("election_timeout_ticks", 3)
        self.bytes_per_log_entry: int = sys_cfg.get("bytes_per_log_entry", 100)
        self.bytes_per_snapshot_entry: int = sys_cfg.get("bytes_per_snapshot_entry", 200)

        # Leader Internal State
        self.current_term: int = 1
        self.leader_logs: List[Dict[str, Any]] = []  # list of {index, term, data}
        self.first_log_index: int = 1
        self.leader_commit_index: int = 0
        self.leader_applied_index: int = 0
        self.snapshot_index: int = 0
        self.snapshot_term: int = 0
        self.leader_dethroned: bool = False

        # Follower Tracking States
        self.follower_state: Dict[str, Dict[str, Any]] = {}
        for f in self.followers:
            self.follower_state[f] = {
                "match_index": 0,
                "next_index": 1,
                "commit_index": 0,
                "applied_index": 0,
                "logs": [],
                "first_log_index": 1,
                "partitioned": False,
                "snapshot_in_progress": False,
                "snapshot_bytes_transferred": 0,
                "snapshot_total_bytes": 0,
                "snapshot_target_index": 0,
                "missed_heartbeats": 0,
                "status": "HEALTHY"
            }

        # Global Cumulative Metrics
        self.total_proposals: int = 0
        self.total_committed: int = 0
        self.compactions_executed: int = 0
        self.snapshots_transmitted: int = 0
        self.heartbeats_lost: int = 0
        self.peak_egress_bytes: int = 0
        self.election_events: int = 0
        self.timeline: List[Dict[str, Any]] = []

    def execute_tick(self, item: Dict[str, Any]):
        if self.leader_dethroned:
            return

        tick = item.get("tick", len(self.timeline) + 1)
        proposals = item.get("proposals", [])
        network_events = item.get("network_events", {})  # {node: "PARTITION" | "RECONNECT"}

        # 1. Update Network Partition Status for nodes
        for node, ev in network_events.items():
            if node in self.follower_state:
                if ev == "PARTITION":
                    self.follower_state[node]["partitioned"] = True
                    self.follower_state[node]["status"] = "PARTITIONED"
                elif ev == "RECONNECT":
                    self.follower_state[node]["partitioned"] = False
                    self.follower_state[node]["missed_heartbeats"] = 0
                    self.follower_state[node]["status"] = "RECONNECTED"

        # 2. Leader appends client proposals
        for p in proposals:
            self.total_proposals += 1
            idx = self.first_log_index + len(self.leader_logs)
            self.leader_logs.append({
                "index": idx,
                "term": self.current_term,
                "data": p
            })

        leader_last_index = self.first_log_index + len(self.leader_logs) - 1

        # 3. Quorum calculations and replication egress
        majority_count = len(self.nodes) // 2 + 1
        tick_egress_bytes = 0

        for f in self.followers:
            st = self.follower_state[f]
            if st["partitioned"]:
                continue

            # Check if follower needs snapshot or is continuing an ongoing snapshot
            if st["snapshot_in_progress"]:
                remaining = st["snapshot_total_bytes"] - st["snapshot_bytes_transferred"]
                if self.snapshot_throttle_bytes > 0:
                    send_bytes = min(remaining, self.snapshot_throttle_bytes)
                else:
                    send_bytes = remaining  # unconstrained streaming

                st["snapshot_bytes_transferred"] += send_bytes
                tick_egress_bytes += send_bytes

                if st["snapshot_bytes_transferred"] >= st["snapshot_total_bytes"]:
                    st["snapshot_in_progress"] = False
                    st["match_index"] = st["snapshot_target_index"]
                    st["next_index"] = st["snapshot_target_index"] + 1
                    st["commit_index"] = st["snapshot_target_index"]
                    st["applied_index"] = st["snapshot_target_index"]
                    st["first_log_index"] = st["snapshot_target_index"] + 1
                    st["logs"] = []
                    st["status"] = "SNAPSHOT_APPLIED"
                    self.snapshots_transmitted += 1
                else:
                    st["status"] = "SNAPSHOT_STREAMING"

            elif st["next_index"] < self.first_log_index:
                # Follower requested index has already been compacted and truncated from leader's log!
                # Leader MUST trigger InstallSnapshot RPC!
                total_snap_bytes = self.snapshot_index * self.bytes_per_snapshot_entry
                st["snapshot_in_progress"] = True
                st["snapshot_bytes_transferred"] = 0
                st["snapshot_total_bytes"] = total_snap_bytes
                st["snapshot_target_index"] = self.snapshot_index

                if self.snapshot_throttle_bytes > 0:
                    send_bytes = min(total_snap_bytes, self.snapshot_throttle_bytes)
                else:
                    send_bytes = total_snap_bytes

                st["snapshot_bytes_transferred"] += send_bytes
                tick_egress_bytes += send_bytes

                if st["snapshot_bytes_transferred"] >= st["snapshot_total_bytes"]:
                    st["snapshot_in_progress"] = False
                    st["match_index"] = self.snapshot_index
                    st["next_index"] = self.snapshot_index + 1
                    st["commit_index"] = self.snapshot_index
                    st["applied_index"] = self.snapshot_index
                    st["first_log_index"] = self.snapshot_index + 1
                    st["logs"] = []
                    st["status"] = "SNAPSHOT_APPLIED"
                    self.snapshots_transmitted += 1
                else:
                    st["status"] = "SNAPSHOT_STREAMING"

            else:
                # Delta AppendEntries replication
                entries_to_send = []
                for entry in self.leader_logs:
                    if entry["index"] >= st["next_index"]:
                        entries_to_send.append(entry)

                send_bytes = len(entries_to_send) * self.bytes_per_log_entry + 50  # 50 bytes RPC header
                tick_egress_bytes += send_bytes

                if entries_to_send:
                    st["match_index"] = entries_to_send[-1]["index"]
                    st["next_index"] = st["match_index"] + 1
                    st["commit_index"] = min(self.leader_commit_index, st["match_index"])
                    st["status"] = "DELTA_REPLICATING"
                else:
                    st["status"] = "IN_SYNC"

        # 4. Quorum Commit Progress on Leader
        match_indices = [leader_last_index] + [
            self.follower_state[f]["match_index"]
            for f in self.followers
            if not self.follower_state[f]["partitioned"]
        ]
        match_indices.sort(reverse=True)
        if len(match_indices) >= majority_count:
            quorum_commit = match_indices[majority_count - 1]
            if quorum_commit > self.leader_commit_index:
                self.leader_commit_index = quorum_commit
                self.leader_applied_index = self.leader_commit_index
                self.total_committed = self.leader_commit_index

        # 5. Log Compaction Evaluation on Leader
        if len(self.leader_logs) >= self.compaction_threshold:
            # Retain trailing_log_margin entries behind applied index
            target_compact_index = self.leader_applied_index - self.trailing_log_margin
            if target_compact_index > self.first_log_index:
                new_logs = [e for e in self.leader_logs if e["index"] >= target_compact_index]
                self.leader_logs = new_logs
                self.first_log_index = target_compact_index
                self.snapshot_index = target_compact_index - 1
                self.snapshot_term = self.current_term
                self.compactions_executed += 1

        # 6. Heartbeat Drop Evaluation due to Network Egress Saturation
        heartbeat_dropped = False
        if tick_egress_bytes > self.heartbeat_loss_threshold_bytes:
            heartbeat_dropped = True
            self.heartbeats_lost += 1

        for f in self.followers:
            st = self.follower_state[f]
            if not st["partitioned"]:
                if heartbeat_dropped:
                    st["missed_heartbeats"] += 1
                    if st["missed_heartbeats"] >= self.election_timeout_ticks:
                        self.leader_dethroned = True
                        self.election_events += 1
                else:
                    st["missed_heartbeats"] = 0

        if tick_egress_bytes > self.peak_egress_bytes:
            self.peak_egress_bytes = tick_egress_bytes

        # Calculate max follower lag across all followers
        max_lag = 0
        for f in self.followers:
            lag = leader_last_index - self.follower_state[f]["match_index"]
            if lag > max_lag:
                max_lag = lag

        self.timeline.append({
            "tick": tick,
            "proposals_count": len(proposals),
            "leader_last_index": leader_last_index,
            "leader_commit_index": self.leader_commit_index,
            "leader_first_log_index": self.first_log_index,
            "snapshot_index": self.snapshot_index,
            "egress_bytes": tick_egress_bytes,
            "heartbeat_dropped": heartbeat_dropped,
            "leader_dethroned": self.leader_dethroned,
            "max_follower_lag": max_lag,
            "followers": {
                f: {
                    "match_index": self.follower_state[f]["match_index"],
                    "status": self.follower_state[f]["status"],
                    "missed_heartbeats": self.follower_state[f]["missed_heartbeats"]
                }
                for f in self.followers
            }
        })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        had_partition = False
        for item in workload:
            net_events = item.get("network_events", {})
            if any(ev == "PARTITION" for ev in net_events.values()):
                had_partition = True
            self.execute_tick(item)

        if self.leader_dethroned:
            verdict = "LEADER_DETHRONED_CASCADING_ELECTION"
        elif self.snapshots_transmitted > 0 or any(st["snapshot_bytes_transferred"] > 0 for st in self.follower_state.values()):
            if self.snapshot_throttle_bytes > 0:
                verdict = "SNAPSHOT_BANDWIDTH_THROTTLED_STABLE"
            else:
                verdict = "SNAPSHOT_UNCONSTRAINED_RECOVERED"
        elif had_partition:
            verdict = "TRAILING_MARGIN_DELTA_CATCHUP"
        else:
            verdict = "STEADY_STATE_REPLICATION"

        return {
            "status": "FAILED" if self.leader_dethroned else "SUCCESS",
            "summary": {
                "nodes": self.nodes,
                "trailing_log_margin": self.trailing_log_margin,
                "compaction_threshold_logs": self.compaction_threshold,
                "snapshot_throttle_bytes_per_tick": self.snapshot_throttle_bytes,
                "heartbeat_loss_threshold_bytes": self.heartbeat_loss_threshold_bytes
            },
            "metrics": {
                "total_proposals": self.total_proposals,
                "total_committed": self.total_committed,
                "compactions_executed": self.compactions_executed,
                "snapshots_transmitted": self.snapshots_transmitted,
                "heartbeats_lost": self.heartbeats_lost,
                "peak_egress_bytes_per_tick": self.peak_egress_bytes,
                "election_events": self.election_events,
                "verdict": verdict
            },
            "sample_timeline": self.timeline[:20]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sim = RaftLogCompactionSimulator(input_data)
    workload = input_data.get("workload", [])
    return sim.run(workload)

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
