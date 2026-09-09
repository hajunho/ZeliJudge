import json
import sys
from typing import Dict, List, Set, Any, Optional

class RaftNode:
    def __init__(self, node_id: int):
        self.id = node_id
        self.current_term = 0
        self.state = "FOLLOWER"  # FOLLOWER, CANDIDATE, LEADER
        self.active_config: Dict[str, Any] = {"type": "SINGLE", "nodes": set()}
        self.log: List[Dict[str, Any]] = []
        self.commit_index = 0

    def set_config(self, cfg: Dict[str, Any]):
        self.active_config = {
            "type": cfg.get("type", "SINGLE"),
            "nodes": set(cfg.get("nodes", [])),
            "old_nodes": set(cfg.get("old_nodes", [])),
            "new_nodes": set(cfg.get("new_nodes", []))
        }

    def check_quorum(self, acks: Set[int]) -> bool:
        cfg = self.active_config
        if cfg["type"] == "SINGLE":
            nodes = cfg["nodes"]
            needed = (len(nodes) // 2) + 1
            got = len(acks.intersection(nodes))
            return got >= needed
        elif cfg["type"] == "JOINT":
            old_nodes = cfg["old_nodes"]
            new_nodes = cfg["new_nodes"]
            needed_old = (len(old_nodes) // 2) + 1
            needed_new = (len(new_nodes) // 2) + 1
            got_old = len(acks.intersection(old_nodes))
            got_new = len(acks.intersection(new_nodes))
            return (got_old >= needed_old) and (got_new >= needed_new)
        return False

class RaftClusterEngine:
    def __init__(self, config: Dict[str, Any]):
        self.enable_joint_consensus = config.get("enable_joint_consensus", True)
        self.nodes: Dict[int, RaftNode] = {}
        initial_nodes = set(config.get("initial_nodes", [1, 2, 3]))
        for nid in sorted(list(initial_nodes)):
            n = RaftNode(nid)
            n.set_config({"type": "SINGLE", "nodes": initial_nodes})
            self.nodes[nid] = n

        self.metrics = {
            "reconfiguration_attempts": 0,
            "split_brain_detected": False,
            "simultaneous_leaders": [],
            "joint_consensus_commits": 0,
            "final_cnew_commits": 0,
            "client_entries_committed": 0,
            "decommissioned_nodes": [],
            "verdict": ""
        }
        self.timeline: List[Dict[str, Any]] = []

    def run_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        for ev in events:
            ev_type = ev["type"]
            if ev_type == "START_RECONFIG":
                self._handle_reconfig(ev)
            elif ev_type == "SIMULATE_SPLIT_ELECTION":
                self._handle_split_election(ev)
            elif ev_type == "CLIENT_WRITE":
                self._handle_client_write(ev)

        self._finalize_metrics()
        return {
            "status": "SUCCESS",
            "enable_joint_consensus": self.enable_joint_consensus,
            "metrics": dict(self.metrics),
            "timeline": self.timeline[:10]
        }

    def _handle_reconfig(self, ev: Dict[str, Any]):
        self.metrics["reconfiguration_attempts"] += 1
        old_nodes = set(ev["old_nodes"])
        new_nodes = set(ev["new_nodes"])

        # Register any new nodes entering cluster
        for nid in sorted(list(new_nodes)):
            if nid not in self.nodes:
                n = RaftNode(nid)
                n.set_config({"type": "SINGLE", "nodes": new_nodes})
                self.nodes[nid] = n

        if not self.enable_joint_consensus:
            # Naive 1-step reconfiguration:
            # Asymmetric network propagation causes partial nodes to switch to C_new while others stay in C_old
            partially_updated = ev.get("nodes_updated_to_cnew", [3, 4, 5])
            for nid in partially_updated:
                if nid in self.nodes:
                    self.nodes[nid].set_config({"type": "SINGLE", "nodes": new_nodes})
            self.timeline.append({
                "action": "NAIVE_RECONFIG_PARTIAL_UPDATE",
                "c_new_nodes": sorted(list(partially_updated)),
                "c_old_remaining": sorted(list(old_nodes - set(partially_updated)))
            })
        else:
            # Raft Joint Consensus:
            # Phase 1: Enter Joint Consensus C_old,new
            joint_cfg = {
                "type": "JOINT",
                "old_nodes": old_nodes,
                "new_nodes": new_nodes
            }
            all_joint_nodes = old_nodes.union(new_nodes)
            for nid in all_joint_nodes:
                self.nodes[nid].set_config(joint_cfg)

            self.metrics["joint_consensus_commits"] += 1
            self.timeline.append({
                "action": "ENTER_JOINT_CONSENSUS",
                "old_nodes": sorted(list(old_nodes)),
                "new_nodes": sorted(list(new_nodes))
            })

            # Phase 2: Once C_old,new is committed, leader commits C_new
            if ev.get("complete_phase2", True):
                cnew_cfg = {"type": "SINGLE", "nodes": new_nodes}
                for nid in new_nodes:
                    self.nodes[nid].set_config(cnew_cfg)
                self.metrics["final_cnew_commits"] += 1
                
                # Decommission nodes not in C_new
                retired = old_nodes - new_nodes
                self.metrics["decommissioned_nodes"] = sorted(list(retired))
                self.timeline.append({
                    "action": "ENTER_FINAL_CNEW",
                    "c_new_nodes": sorted(list(new_nodes)),
                    "decommissioned": sorted(list(retired))
                })

    def _handle_split_election(self, ev: Dict[str, Any]):
        cand_a = ev["candidate_a"]
        group_a = set(ev["voters_a"])
        cand_b = ev["candidate_b"]
        group_b = set(ev["voters_b"])

        server_a = self.nodes[cand_a]
        server_b = self.nodes[cand_b]

        has_quorum_a = server_a.check_quorum(group_a)
        has_quorum_b = server_b.check_quorum(group_b)

        leaders = []
        if has_quorum_a:
            leaders.append(cand_a)
        if has_quorum_b:
            leaders.append(cand_b)

        leaders.sort()

        if len(leaders) > 1:
            self.metrics["split_brain_detected"] = True
            self.metrics["simultaneous_leaders"] = leaders
            self.timeline.append({
                "action": "ELECTION_SPLIT_BRAIN_DISASTER",
                "elected_leaders": leaders,
                "reason": "Disjoint majorities elected separate leaders simultaneously!"
            })
        else:
            self.timeline.append({
                "action": "ELECTION_SAFETY_PRESERVED",
                "elected_leaders": leaders,
                "reason": "Dual quorum prevented disjoint majority election."
            })

    def _handle_client_write(self, ev: Dict[str, Any]):
        leader_id = ev.get("leader_id", 1)
        acks = set(ev.get("acks", [1, 2, 3]))
        leader = self.nodes[leader_id]
        
        if leader.check_quorum(acks):
            self.metrics["client_entries_committed"] += 1
            self.timeline.append({
                "action": "CLIENT_WRITE_COMMITTED",
                "entry": ev.get("entry", ""),
                "acks": sorted(list(acks))
            })
        else:
            self.timeline.append({
                "action": "CLIENT_WRITE_UNCOMMITTED_QUORUM_FAILED",
                "entry": ev.get("entry", ""),
                "acks": sorted(list(acks))
            })

    def _finalize_metrics(self):
        if self.metrics["split_brain_detected"]:
            self.metrics["verdict"] = "CATASTROPHIC_SPLIT_BRAIN_TWO_LEADERS"
        elif self.enable_joint_consensus and self.metrics["joint_consensus_commits"] > 0:
            self.metrics["verdict"] = "JOINT_CONSENSUS_SAFE_RECONFIGURATION"
        else:
            self.metrics["verdict"] = "STANDARD_CLUSTER_OPERATION"

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    req = json.loads(raw_data)
    engine = RaftClusterEngine(req["config"])
    result = engine.run_events(req["events"])
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
