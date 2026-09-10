import sys
import json

class TwoPhaseCommitEngine:
    def __init__(self, participants):
        self.participants = list(participants)
        self.coord_wal = []
        self.participant_wal = {p: [] for p in participants}
        
        self.coord_tx = {}
        self.part_tx = {p: {} for p in participants}
        
        self.stats = {
            "transactions_started": 0,
            "transactions_committed": 0,
            "transactions_aborted": 0,
            "coord_forced_wal_writes": 0,
            "in_doubt_resolutions": 0
        }

    def start_transaction(self, tx_id):
        self.stats["transactions_started"] += 1
        self.coord_tx[tx_id] = {
            "state": "INIT",
            "votes": {},
            "participants": list(self.participants)
        }
        for p in self.participants:
            self.part_tx[p][tx_id] = {
                "state": "INIT",
                "in_doubt": False
            }
        return {"tx_id": tx_id, "status": "INITIATED"}

    def prepare_phase(self, tx_id, participant_vote_plans):
        tx = self.coord_tx[tx_id]
        tx["state"] = "PREPARING"
        
        all_commit = True
        votes_received = {}
        
        for p in self.participants:
            vote = participant_vote_plans.get(p, "VOTE_COMMIT")
            votes_received[p] = vote
            tx["votes"][p] = vote
            
            if vote == "VOTE_COMMIT":
                self.participant_wal[p].append({"tx_id": tx_id, "record": "PREPARED"})
                self.part_tx[p][tx_id]["state"] = "PREPARED"
                self.part_tx[p][tx_id]["in_doubt"] = True
            else:
                self.participant_wal[p].append({"tx_id": tx_id, "record": "ABORT"})
                self.part_tx[p][tx_id]["state"] = "ABORTED"
                self.part_tx[p][tx_id]["in_doubt"] = False
                all_commit = False
                
        if all_commit:
            self.coord_wal.append({"tx_id": tx_id, "record": "COMMIT"})
            self.stats["coord_forced_wal_writes"] += 1
            tx["state"] = "COMMITTED"
            decision = "GLOBAL_COMMIT"
            self.stats["transactions_committed"] += 1
        else:
            tx["state"] = "ABORTED"
            decision = "GLOBAL_ABORT"
            self.stats["transactions_aborted"] += 1
            
        return {
            "tx_id": tx_id,
            "votes": votes_received,
            "decision": decision
        }

    def commit_phase(self, tx_id, decision, failed_participants=None):
        failed = set(failed_participants or [])
        tx = self.coord_tx[tx_id]
        
        delivery_results = {}
        for p in self.participants:
            if p in failed:
                delivery_results[p] = "UNDELIVERED_NETWORK_OR_CRASH"
                continue
                
            if decision == "GLOBAL_COMMIT":
                self.part_tx[p][tx_id]["state"] = "COMMITTED"
                self.part_tx[p][tx_id]["in_doubt"] = False
                self.participant_wal[p].append({"tx_id": tx_id, "record": "COMMITTED"})
                delivery_results[p] = "COMMITTED"
            else:
                self.part_tx[p][tx_id]["state"] = "ABORTED"
                self.part_tx[p][tx_id]["in_doubt"] = False
                self.participant_wal[p].append({"tx_id": tx_id, "record": "ABORTED"})
                delivery_results[p] = "ABORTED"
                
        if not failed and decision == "GLOBAL_COMMIT":
            self.coord_wal.append({"tx_id": tx_id, "record": "END"})
            tx["state"] = "FORGOTTEN"
            
        return {
            "tx_id": tx_id,
            "decision": decision,
            "participant_status": delivery_results
        }

    def cooperative_termination(self, in_doubt_participant, tx_id):
        if not self.part_tx[in_doubt_participant].get(tx_id, {}).get("in_doubt", False):
            return {"status": "NOT_IN_DOUBT"}
            
        peer_states = {}
        resolved_decision = None
        
        for peer in self.participants:
            if peer == in_doubt_participant:
                continue
            st = self.part_tx[peer].get(tx_id, {}).get("state", "UNKNOWN")
            peer_states[peer] = st
            if st == "COMMITTED":
                resolved_decision = "GLOBAL_COMMIT"
                break
            elif st == "ABORTED":
                resolved_decision = "GLOBAL_ABORT"
                break
                
        if resolved_decision == "GLOBAL_COMMIT":
            self.part_tx[in_doubt_participant][tx_id]["state"] = "COMMITTED"
            self.part_tx[in_doubt_participant][tx_id]["in_doubt"] = False
            self.participant_wal[in_doubt_participant].append({"tx_id": tx_id, "record": "COMMITTED"})
            self.stats["in_doubt_resolutions"] += 1
            return {
                "in_doubt_participant": in_doubt_participant,
                "tx_id": tx_id,
                "resolution": "COMMITTED_VIA_PEER",
                "peer_states": peer_states
            }
        elif resolved_decision == "GLOBAL_ABORT":
            self.part_tx[in_doubt_participant][tx_id]["state"] = "ABORTED"
            self.part_tx[in_doubt_participant][tx_id]["in_doubt"] = False
            self.participant_wal[in_doubt_participant].append({"tx_id": tx_id, "record": "ABORTED"})
            self.stats["in_doubt_resolutions"] += 1
            return {
                "in_doubt_participant": in_doubt_participant,
                "tx_id": tx_id,
                "resolution": "ABORTED_VIA_PEER",
                "peer_states": peer_states
            }
            
        return {
            "in_doubt_participant": in_doubt_participant,
            "tx_id": tx_id,
            "resolution": "BLOCKED_ALL_PEERS_IN_DOUBT",
            "peer_states": peer_states
        }

    def coordinator_query(self, participant, tx_id):
        has_commit_wal = any(r["tx_id"] == tx_id and r["record"] == "COMMIT" for r in self.coord_wal)
        
        if has_commit_wal:
            decision = "GLOBAL_COMMIT"
            self.part_tx[participant][tx_id]["state"] = "COMMITTED"
            self.part_tx[participant][tx_id]["in_doubt"] = False
        else:
            decision = "GLOBAL_ABORT"
            self.part_tx[participant][tx_id]["state"] = "ABORTED"
            self.part_tx[participant][tx_id]["in_doubt"] = False
            
        self.stats["in_doubt_resolutions"] += 1
        return {
            "participant": participant,
            "tx_id": tx_id,
            "coordinator_presumed_decision": decision
        }

    def crash_and_recover_coordinator(self):
        commit_txs = {r["tx_id"] for r in self.coord_wal if r["record"] == "COMMIT"}
        end_txs = {r["tx_id"] for r in self.coord_wal if r["record"] == "END"}
        
        pending_commits = commit_txs - end_txs
        recovered_state = {}
        
        for tx_id in pending_commits:
            recovered_state[tx_id] = "RECOVERED_NEED_COMMIT_BROADCAST"
            for p in self.participants:
                self.part_tx[p][tx_id]["state"] = "COMMITTED"
                self.part_tx[p][tx_id]["in_doubt"] = False
                self.participant_wal[p].append({"tx_id": tx_id, "record": "COMMITTED"})
            self.coord_wal.append({"tx_id": tx_id, "record": "END"})
            
        return {
            "wal_records_scanned": len(self.coord_wal),
            "recovered_committed_transactions": sorted(list(pending_commits)),
            "status": "RECOVERY_COMPLETE"
        }

    def get_snapshot(self):
        return {
            "coordinator_state": {tx: data["state"] for tx, data in self.coord_tx.items()},
            "coordinator_wal": list(self.coord_wal),
            "participant_states": {p: {tx: data["state"] for tx, data in self.part_tx[p].items()} for p in self.participants},
            "metrics": dict(self.stats)
        }

def run_simulation(req):
    participants = req.get("participants", ["Node-A", "Node-B", "Node-C"])
    engine = TwoPhaseCommitEngine(participants)
    
    logs = []
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "START_TX":
            tx_id = op_item["tx_id"]
            res = engine.start_transaction(tx_id)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "PREPARE":
            tx_id = op_item["tx_id"]
            votes = op_item.get("votes", {})
            res = engine.prepare_phase(tx_id, votes)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "COMMIT_PHASE":
            tx_id = op_item["tx_id"]
            decision = op_item["decision"]
            failed = op_item.get("failed_participants", [])
            res = engine.commit_phase(tx_id, decision, failed)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "COOPERATIVE_TERMINATION":
            p = op_item["participant"]
            tx_id = op_item["tx_id"]
            res = engine.cooperative_termination(p, tx_id)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "COORDINATOR_QUERY":
            p = op_item["participant"]
            tx_id = op_item["tx_id"]
            res = engine.coordinator_query(p, tx_id)
            logs.append({"step": step, "op": op, **res})
            
        elif op == "CRASH_AND_RECOVER_COORDINATOR":
            res = engine.crash_and_recover_coordinator()
            logs.append({"step": step, "op": op, **res})
            
        elif op == "GET_SNAPSHOT":
            snap = engine.get_snapshot()
            logs.append({"step": step, "op": op, "snapshot": snap})
            
    final_snap = engine.get_snapshot()
    return {
        "operations_log": logs,
        "final_state": final_snap
    }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    raw_in = sys.stdin.read().strip()
    if not raw_in:
        return
        
    req = json.loads(raw_in)
    res = run_simulation(req)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
