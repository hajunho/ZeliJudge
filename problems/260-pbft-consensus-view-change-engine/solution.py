import sys
import json
import hashlib

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]

class PBFTCluster:
    def __init__(self, config: dict):
        self.node_ids = config.get("nodes", ["node_0", "node_1", "node_2", "node_3"])
        self.R = len(self.node_ids)
        self.f = (self.R - 1) // 3
        self.byzantine_nodes = set(config.get("byzantine_nodes", []))
        self.current_view = config.get("initial_view", 0)
        self.view_timeout_ms = config.get("timeout_ms", 5000)

        self.nodes = {}
        for nid in self.node_ids:
            self.nodes[nid] = {
                "id": nid,
                "is_byzantine": nid in self.byzantine_nodes,
                "current_view": self.current_view,
                "state": "NORMAL",
                "seq_counter": 0,
                "last_executed_seq": 0,
                "pre_prepares": {},
                "prepares": {},
                "commits": {},
                "prepared_certs": {},
                "committed_certs": {},
                "executed_log": [],
                "state_store": {},
                "view_change_msgs": {}
            }

        self.security_events = []
        self.clock_ms = 0
        self.pending_timers = {}

    def get_primary(self, view: int) -> str:
        return self.node_ids[view % self.R]

    def log_event(self, evt: str):
        if evt not in self.security_events:
            self.security_events.append(evt)

    def process_client_request(self, client_req: dict):
        tx_id = client_req["tx_id"]
        primary_id = self.get_primary(self.current_view)
        primary = self.nodes[primary_id]

        primary["seq_counter"] += 1
        seq = primary["seq_counter"]
        digest = sha256(json.dumps(client_req, sort_keys=True))

        if primary["is_byzantine"] and client_req.get("equivocate", False):
            self.log_event(f"PRIMARY_EQUIVOCATION_ATTACK: primary={primary_id}, seq={seq}")
            target_a = self.node_ids[:self.R // 2]
            target_b = self.node_ids[self.R // 2:]
            digest_b = sha256(json.dumps({"tx_id": tx_id, "op": "MALICIOUS_FORGED_OP"}, sort_keys=True))

            for nid in target_a:
                self.handle_pre_prepare(nid, self.current_view, seq, digest, client_req, primary_id)
            for nid in target_b:
                self.handle_pre_prepare(nid, self.current_view, seq, digest_b, {"tx_id": tx_id, "op": "MALICIOUS_FORGED_OP"}, primary_id)
        else:
            for nid in self.node_ids:
                self.handle_pre_prepare(nid, self.current_view, seq, digest, client_req, primary_id)

        self.pending_timers[tx_id] = {
            "view": self.current_view,
            "seq": seq,
            "expiry_ms": self.clock_ms + self.view_timeout_ms
        }

    def handle_pre_prepare(self, node_id: str, view: int, seq: int, digest: str, req: dict, sender: str):
        node = self.nodes[node_id]
        if node["state"] != "NORMAL" or node["current_view"] != view:
            return

        key = (view, seq)
        if key in node["pre_prepares"]:
            existing = node["pre_prepares"][key]
            if existing["digest"] != digest:
                self.log_event(f"PRIMARY_EQUIVOCATION_DETECTED: node={node_id}, view={view}, seq={seq}")
                return
        else:
            node["pre_prepares"][key] = {"digest": digest, "req": req, "sender": sender}

        if node["is_byzantine"]:
            return

        prepare_digest = digest
        for peer_id in self.node_ids:
            self.handle_prepare(peer_id, view, seq, prepare_digest, node_id)

    def handle_prepare(self, node_id: str, view: int, seq: int, digest: str, sender: str):
        node = self.nodes[node_id]
        if node["state"] != "NORMAL" or node["current_view"] != view:
            return

        key = (view, seq, digest)
        if key not in node["prepares"]:
            node["prepares"][key] = set()
        node["prepares"][key].add(sender)

        pp_key = (view, seq)
        if pp_key in node["pre_prepares"] and node["pre_prepares"][pp_key]["digest"] == digest:
            if len(node["prepares"][key]) >= 2 * self.f and pp_key not in node["prepared_certs"]:
                node["prepared_certs"][pp_key] = digest
                if not node["is_byzantine"]:
                    for peer_id in self.node_ids:
                        self.handle_commit(peer_id, view, seq, digest, node_id)

    def handle_commit(self, node_id: str, view: int, seq: int, digest: str, sender: str):
        node = self.nodes[node_id]
        if node["state"] != "NORMAL" or node["current_view"] != view:
            return

        key = (view, seq, digest)
        if key not in node["commits"]:
            node["commits"][key] = set()
        node["commits"][key].add(sender)

        pp_key = (view, seq)
        if pp_key in node["prepared_certs"] and node["prepared_certs"][pp_key] == digest:
            if len(node["commits"][key]) >= 2 * self.f + 1 and pp_key not in node["committed_certs"]:
                node["committed_certs"][pp_key] = digest
                self.try_execute_committed(node_id)

    def try_execute_committed(self, node_id: str):
        node = self.nodes[node_id]
        while True:
            next_seq = node["last_executed_seq"] + 1
            key = (node["current_view"], next_seq)
            if key in node["committed_certs"]:
                req = node["pre_prepares"][key]["req"]
                op_parts = req["op"].split()
                cmd = op_parts[0]
                if cmd == "SET" and len(op_parts) >= 3:
                    k, v = op_parts[1], op_parts[2]
                    node["state_store"][k] = v
                elif cmd == "DEL" and len(op_parts) >= 2:
                    k = op_parts[1]
                    node["state_store"].pop(k, None)

                node["executed_log"].append({"seq": next_seq, "tx_id": req["tx_id"], "op": req["op"]})
                node["last_executed_seq"] = next_seq
            else:
                break

    def trigger_view_change(self, reason: str):
        new_view = self.current_view + 1
        self.log_event(f"VIEW_CHANGE_INITIATED: reason={reason}, target_view={new_view}")
        
        for nid, node in self.nodes.items():
            if not node["is_byzantine"]:
                node["state"] = "VIEW_CHANGE"
                for peer_id in self.node_ids:
                    peer = self.nodes[peer_id]
                    if new_view not in peer["view_change_msgs"]:
                        peer["view_change_msgs"][new_view] = set()
                    peer["view_change_msgs"][new_view].add(nid)

        new_primary_id = self.get_primary(new_view)
        new_primary = self.nodes[new_primary_id]

        if len(new_primary["view_change_msgs"].get(new_view, set())) >= 2 * self.f + 1:
            self.current_view = new_view
            for nid, node in self.nodes.items():
                node["current_view"] = new_view
                node["state"] = "NORMAL"
            self.log_event(f"VIEW_CHANGE_SUCCESSFUL: view {new_view - 1} -> {new_view}, new_primary={new_primary_id}")
            return True
        else:
            self.log_event(f"VIEW_CHANGE_QUORUM_FAILED: target_view={new_view}")
            return False

    def advance_time(self, delta_ms: int):
        self.clock_ms += delta_ms
        expired_txs = []
        for tx_id, info in list(self.pending_timers.items()):
            if self.clock_ms >= info["expiry_ms"]:
                committed_count = sum(1 for n in self.nodes.values() if any(entry["tx_id"] == tx_id for entry in n["executed_log"]))
                if committed_count < 2 * self.f + 1:
                    expired_txs.append(tx_id)

        if expired_txs:
            self.trigger_view_change(f"TIMEOUT_TX_{expired_txs[0]}")
            self.pending_timers.clear()

def run_pbft_simulation(input_data: dict) -> dict:
    cluster = PBFTCluster(input_data)
    workload = input_data.get("workload_events", [])

    for ev in workload:
        ev_type = ev["type"]
        if ev_type == "CLIENT_REQUEST":
            cluster.process_client_request(ev["request"])
        elif ev_type == "ADVANCE_TIME":
            cluster.advance_time(ev.get("delta_ms", 1000))
        elif ev_type == "TRIGGER_VIEW_CHANGE":
            cluster.trigger_view_change(ev.get("reason", "MANUAL"))

    nodes_report = {}
    for nid, node in cluster.nodes.items():
        nodes_report[nid] = {
            "current_view": node["current_view"],
            "state": node["state"],
            "is_byzantine": node["is_byzantine"],
            "last_executed_seq": node["last_executed_seq"],
            "executed_tx_ids": [entry["tx_id"] for entry in node["executed_log"]],
            "state_store": node["state_store"]
        }

    primary_id = cluster.get_primary(cluster.current_view)
    honest_nodes = [n for n in cluster.nodes.values() if not n["is_byzantine"]]
    cluster_store = honest_nodes[0]["state_store"] if honest_nodes else {}

    all_executed = {}
    for n in honest_nodes:
        for entry in n["executed_log"]:
            all_executed[entry["tx_id"]] = all_executed.get(entry["tx_id"], 0) + 1

    committed_tx_ids = [tx_id for tx_id, cnt in all_executed.items() if cnt >= 2 * cluster.f + 1]

    return {
        "cluster_size": cluster.R,
        "fault_tolerance_f": cluster.f,
        "final_view": cluster.current_view,
        "primary_node": primary_id,
        "consensus_status": "CONSENSUS_STABLE" if all(n["state"] == "NORMAL" for n in honest_nodes) else "CONSENSUS_DEGRADED",
        "total_committed_txs": len(committed_tx_ids),
        "committed_tx_ids": committed_tx_ids,
        "cluster_state_store": cluster_store,
        "nodes": nodes_report,
        "security_events": cluster.security_events
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = run_pbft_simulation(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
