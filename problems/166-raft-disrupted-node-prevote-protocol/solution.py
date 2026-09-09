# Complete simulator implementation for Problem 166: Raft Consensus Pre-Vote
from typing import Dict, List, Any, Optional, Set, Tuple
import json
import sys

class RaftEngine:
    def __init__(self, data: Dict[str, Any]):
        config = data.get("config", {})
        self.node_ids: List[str] = sorted(config.get("cluster_nodes", []))
        self.majority_count: int = (len(self.node_ids) // 2) + 1
        self.heartbeat_interval: int = config.get("heartbeat_interval", 50)
        self.election_timeout: int = config.get("election_timeout", 150)
        self.enable_prevote: bool = config.get("enable_prevote", False)

        initial_state = data.get("initial_state", {})
        init_leader = initial_state.get("leader_id", None)
        init_term = initial_state.get("term", 1)

        self.roles: Dict[str, str] = {nid: "FOLLOWER" for nid in self.node_ids}
        self.current_terms: Dict[str, int] = {nid: init_term for nid in self.node_ids}
        self.voted_for: Dict[str, Optional[str]] = {nid: None for nid in self.node_ids}
        self.leader_ids: Dict[str, Optional[str]] = {nid: None for nid in self.node_ids}
        self.logs: Dict[str, List[Dict[str, Any]]] = {nid: [] for nid in self.node_ids}
        self.commit_indexes: Dict[str, int] = {nid: 0 for nid in self.node_ids}

        self.last_heartbeat_received: Dict[str, int] = {nid: 0 for nid in self.node_ids}
        self.last_election_timer_reset: Dict[str, int] = {nid: 0 for nid in self.node_ids}

        self.active_leader: Optional[str] = None
        if init_leader and init_leader in self.node_ids:
            self.roles[init_leader] = "LEADER"
            self.active_leader = init_leader
            for nid in self.node_ids:
                self.leader_ids[nid] = init_leader

        # Prepopulate initial logs if provided
        if "initial_logs" in initial_state:
            for nid, entries in initial_state["initial_logs"].items():
                if nid in self.logs:
                    self.logs[nid] = list(entries)
                    self.commit_indexes[nid] = len(entries)

        self.blocked_edges: Set[Tuple[str, str]] = set()

        # Metrics
        self.current_time = 0
        self.leader_demotions = 0
        self.elections_started = 0
        self.prevote_rounds_started = 0
        self.prevotes_rejected_by_lease = 0
        self.prevotes_rejected_by_log = 0
        self.client_writes_committed = 0
        self.client_writes_failed = 0
        self.timeline: List[Dict[str, Any]] = []

    def get_last_log_info(self, nid: str) -> Tuple[int, int]:
        log = self.logs[nid]
        if not log:
            return 0, 0
        return log[-1]["term"], log[-1]["index"]

    def is_log_up_to_date(self, cand_last_term: int, cand_last_index: int, receiver_id: str) -> bool:
        recv_term, recv_index = self.get_last_log_info(receiver_id)
        if cand_last_term != recv_term:
            return cand_last_term > recv_term
        return cand_last_index >= recv_index

    def can_send(self, sender: str, receiver: str) -> bool:
        return (sender, receiver) not in self.blocked_edges

    def log_event(self, event_type: str, details: Dict[str, Any]):
        entry = {"time": self.current_time, "event": event_type, **details}
        self.timeline.append(entry)

    def trigger_heartbeat(self, leader_id: str):
        if self.roles.get(leader_id) != "LEADER":
            return
        term = self.current_terms[leader_id]

        for peer in self.node_ids:
            if peer == leader_id:
                continue
            if not self.can_send(leader_id, peer):
                continue

            peer_term = self.current_terms[peer]
            if term < peer_term:
                self.roles[leader_id] = "FOLLOWER"
                self.leader_ids[leader_id] = None
                self.active_leader = None
                self.current_terms[leader_id] = peer_term
                self.leader_demotions += 1
                self.log_event("LEADER_DEMOTED_BY_HEARTBEAT", {"leader": leader_id, "peer": peer, "peer_term": peer_term})
                return

            if term > peer_term:
                self.current_terms[peer] = term
                self.roles[peer] = "FOLLOWER"
                self.voted_for[peer] = None

            self.leader_ids[peer] = leader_id
            self.last_heartbeat_received[peer] = self.current_time
            self.last_election_timer_reset[peer] = self.current_time

    def trigger_election_timeout(self, nid: str):
        if self.roles.get(nid) == "LEADER":
            return

        if self.enable_prevote:
            self.roles[nid] = "PRE_CANDIDATE"
            self.prevote_rounds_started += 1
            target_term = self.current_terms[nid] + 1
            last_term, last_index = self.get_last_log_info(nid)
            prevotes_granted = {nid}

            self.log_event("PREVOTE_STARTED", {"candidate": nid, "target_term": target_term})

            for peer in self.node_ids:
                if peer == nid:
                    continue
                if not self.can_send(nid, peer):
                    continue

                is_active_leader = (self.roles[peer] == "LEADER")
                peer_heard_leader = (self.current_time - self.last_heartbeat_received[peer]) < self.election_timeout
                has_active_leader = (self.active_leader is not None and self.leader_ids[peer] == self.active_leader)
                lease_active = is_active_leader or (peer_heard_leader and has_active_leader)

                if lease_active:
                    self.prevotes_rejected_by_lease += 1
                    self.log_event("PREVOTE_REJECTED_LEASE", {"candidate": nid, "peer": peer})
                    continue

                if not self.is_log_up_to_date(last_term, last_index, peer):
                    self.prevotes_rejected_by_log += 1
                    self.log_event("PREVOTE_REJECTED_LOG", {"candidate": nid, "peer": peer})
                    continue

                if self.can_send(peer, nid):
                    prevotes_granted.add(peer)
                    self.log_event("PREVOTE_GRANTED", {"candidate": nid, "peer": peer})

            if len(prevotes_granted) >= self.majority_count:
                self.log_event("PREVOTE_WON", {"candidate": nid, "votes": len(prevotes_granted)})
                self._start_real_election(nid)
            else:
                self.log_event("PREVOTE_LOST", {"candidate": nid, "votes": len(prevotes_granted)})
                self.roles[nid] = "FOLLOWER"
        else:
            self._start_real_election(nid)

    def _start_real_election(self, nid: str):
        self.roles[nid] = "CANDIDATE"
        self.current_terms[nid] += 1
        cand_term = self.current_terms[nid]
        self.voted_for[nid] = nid
        votes_granted = {nid}
        self.elections_started += 1
        last_term, last_index = self.get_last_log_info(nid)

        self.log_event("ELECTION_STARTED", {"candidate": nid, "term": cand_term})

        for peer in self.node_ids:
            if peer == nid:
                continue
            if not self.can_send(nid, peer):
                continue

            peer_term = self.current_terms[peer]

            if cand_term > peer_term:
                if self.roles[peer] == "LEADER":
                    self.leader_demotions += 1
                    self.active_leader = None
                    self.log_event("LEADER_DEMOTED_BY_REQUEST_VOTE", {"old_leader": peer, "candidate": nid, "term": cand_term})
                self.current_terms[peer] = cand_term
                self.roles[peer] = "FOLLOWER"
                self.voted_for[peer] = None
                self.leader_ids[peer] = None

            if self.current_terms[peer] == cand_term:
                vote_granted = False
                if (self.voted_for[peer] is None or self.voted_for[peer] == nid) and self.is_log_up_to_date(last_term, last_index, peer):
                    self.voted_for[peer] = nid
                    vote_granted = True
                    self.last_election_timer_reset[peer] = self.current_time
                    self.log_event("VOTE_GRANTED", {"candidate": nid, "peer": peer, "term": cand_term})

                if vote_granted and self.can_send(peer, nid):
                    votes_granted.add(peer)

        if len(votes_granted) >= self.majority_count:
            self.roles[nid] = "LEADER"
            self.active_leader = nid
            for n in self.node_ids:
                if self.can_send(nid, n):
                    self.leader_ids[n] = nid
            self.log_event("LEADER_ELECTED", {"leader": nid, "term": cand_term, "votes": len(votes_granted)})
            # New leader asserts authority with initial heartbeat
            self.trigger_heartbeat(nid)
        else:
            self.log_event("ELECTION_FAILED", {"candidate": nid, "votes": len(votes_granted)})

    def client_write(self, data: str) -> Dict[str, Any]:
        if not self.active_leader or self.roles.get(self.active_leader) != "LEADER":
            self.client_writes_failed += 1
            self.log_event("CLIENT_WRITE_FAILED", {"reason": "NO_LEADER", "data": data})
            return {"success": False, "reason": "NO_LEADER"}

        leader = self.active_leader
        term = self.current_terms[leader]
        new_index = len(self.logs[leader]) + 1
        entry = {"term": term, "index": new_index, "data": data}
        self.logs[leader].append(entry)

        acks = {leader}
        for peer in self.node_ids:
            if peer == leader:
                continue
            if not self.can_send(leader, peer) or not self.can_send(peer, leader):
                continue

            self.logs[peer].append(entry)
            acks.add(peer)

        if len(acks) >= self.majority_count:
            self.commit_indexes[leader] = new_index
            for p in acks:
                self.commit_indexes[p] = new_index
            self.client_writes_committed += 1
            self.log_event("CLIENT_WRITE_COMMITTED", {"index": new_index, "data": data, "acks": len(acks)})
            return {"success": True, "index": new_index}
        else:
            self.client_writes_failed += 1
            self.log_event("CLIENT_WRITE_FAILED", {"reason": "MAJORITY_ACK_FAILED", "index": new_index, "acks": len(acks)})
            return {"success": False, "reason": "MAJORITY_ACK_FAILED"}

    def execute_command(self, cmd: Dict[str, Any]):
        self.current_time = cmd.get("time", self.current_time)
        cmd_type = cmd.get("type")

        if cmd_type == "HEARTBEAT":
            leader = cmd.get("leader_id", self.active_leader)
            if leader:
                self.trigger_heartbeat(leader)

        elif cmd_type == "ELECTION_TIMEOUT":
            node = cmd.get("node")
            if node:
                self.trigger_election_timeout(node)

        elif cmd_type == "BLOCK_EDGE":
            sender = cmd.get("sender")
            receiver = cmd.get("receiver")
            if sender and receiver:
                self.blocked_edges.add((sender, receiver))
                self.log_event("EDGE_BLOCKED", {"sender": sender, "receiver": receiver})

        elif cmd_type == "UNBLOCK_EDGE":
            sender = cmd.get("sender")
            receiver = cmd.get("receiver")
            if sender and receiver:
                self.blocked_edges.discard((sender, receiver))
                self.log_event("EDGE_UNBLOCKED", {"sender": sender, "receiver": receiver})

        elif cmd_type == "ISOLATE_NODE":
            node = cmd.get("node")
            if node:
                for peer in self.node_ids:
                    if peer != node:
                        self.blocked_edges.add((node, peer))
                        self.blocked_edges.add((peer, node))
                self.log_event("NODE_ISOLATED", {"node": node})

        elif cmd_type == "RECONNECT_NODE":
            node = cmd.get("node")
            if node:
                for peer in self.node_ids:
                    self.blocked_edges.discard((node, peer))
                    self.blocked_edges.discard((peer, node))
                self.log_event("NODE_RECONNECTED", {"node": node})

        elif cmd_type == "ISOLATE_PARTITION":
            nodes = set(cmd.get("nodes", []))
            other_nodes = set(self.node_ids) - nodes
            for n in nodes:
                for o in other_nodes:
                    self.blocked_edges.add((n, o))
                    self.blocked_edges.add((o, n))
            self.log_event("PARTITION_ISOLATED", {"nodes": sorted(nodes)})

        elif cmd_type == "HEAL_ALL_PARTITIONS":
            self.blocked_edges.clear()
            self.log_event("ALL_PARTITIONS_HEALED", {})

        elif cmd_type == "CLIENT_WRITE":
            data = cmd.get("data", "")
            self.client_write(data)

    def run_simulation(self, commands: List[Dict[str, Any]]) -> Dict[str, Any]:
        for cmd in commands:
            self.execute_command(cmd)

        max_term = max(self.current_terms.values()) if self.current_terms else 1
        node_states = {}
        for nid in self.node_ids:
            node_states[nid] = {
                "role": self.roles[nid],
                "term": self.current_terms[nid],
                "commit_index": self.commit_indexes[nid],
                "log_length": len(self.logs[nid])
            }

        return {
            "status": "SUCCESS",
            "metrics": {
                "leader_demotions": self.leader_demotions,
                "elections_started": self.elections_started,
                "prevote_rounds_started": self.prevote_rounds_started,
                "prevotes_rejected_by_lease": self.prevotes_rejected_by_lease,
                "prevotes_rejected_by_log": self.prevotes_rejected_by_log,
                "max_term": max_term,
                "client_writes_committed": self.client_writes_committed,
                "client_writes_failed": self.client_writes_failed,
                "final_leader": self.active_leader
            },
            "node_states": node_states,
            "timeline": self.timeline
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    engine = RaftEngine(input_data)
    commands = input_data.get("commands", [])
    return engine.run_simulation(commands)

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
