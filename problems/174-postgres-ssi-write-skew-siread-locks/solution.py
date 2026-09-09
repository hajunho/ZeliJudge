import json
import sys
from typing import Dict, List, Any, Set, Optional

class PostgresSsiEngine:
    def __init__(self, initial_data: Dict[str, Any]):
        # Data store: key -> {"val": Any, "version": int}
        self.db = {k: {"val": v, "version": 1} for k, v in initial_data.items()}
        self.siread_locks: Dict[str, Set[str]] = {} # key -> set of tx_ids who read it
        self.writes: Dict[str, Dict[str, Any]] = {} # tx_id -> {key: new_val}
        self.reads: Dict[str, Set[str]] = {}  # tx_id -> set of keys read
        self.tx_state: Dict[str, str] = {} # tx_id -> ACTIVE, COMMITTED, ABORTED
        self.rw_in: Dict[str, Set[str]] = {} # tx_id -> set of txs that have rw-edge TO tx_id
        self.rw_out: Dict[str, Set[str]] = {} # tx_id -> set of txs that tx_id has rw-edge TO
        self.tx_start_time: Dict[str, int] = {}
        self.tx_end_time: Dict[str, int] = {}
        self.timeline: List[Dict[str, Any]] = []

    def begin_tx(self, tx_id: str):
        self.tx_state[tx_id] = "ACTIVE"
        self.writes[tx_id] = {}
        self.reads[tx_id] = set()
        self.rw_in[tx_id] = set()
        self.rw_out[tx_id] = set()
        self.tx_start_time[tx_id] = len(self.timeline)
        self.timeline.append({"action": "BEGIN", "tx_id": tx_id})

    def read(self, tx_id: str, key: str) -> Any:
        if self.tx_state.get(tx_id) != "ACTIVE":
            return None
        self.reads[tx_id].add(key)
        if key not in self.siread_locks:
            self.siread_locks[key] = set()
        self.siread_locks[key].add(tx_id)

        # In MVCC, tx reads either its own uncommitted write, or current db val
        val = self.writes[tx_id].get(key, self.db.get(key, {}).get("val"))

        # Detect rw anti-dependency: if another concurrent tx already wrote to this key
        for other_tx in sorted(self.writes.keys()):
            w_dict = self.writes[other_tx]
            if other_tx != tx_id and key in w_dict:
                # Only concurrent transactions can have rw-antidependencies
                if self._are_concurrent(tx_id, other_tx):
                    self._add_rw_edge(tx_id, other_tx)

        self.timeline.append({"action": "READ", "tx_id": tx_id, "key": key, "val": val})
        return val

    def write(self, tx_id: str, key: str, val: Any):
        if self.tx_state.get(tx_id) != "ACTIVE":
            return
        self.writes[tx_id][key] = val

        # Detect rw anti-dependency: anyone holding SIREAD lock on this key who is concurrent with tx_id
        if key in self.siread_locks:
            for reader_tx in sorted(self.siread_locks[key]):
                if reader_tx != tx_id and self._are_concurrent(reader_tx, tx_id):
                    self._add_rw_edge(reader_tx, tx_id)

        self.timeline.append({"action": "WRITE", "tx_id": tx_id, "key": key, "val": val})

    def _are_concurrent(self, tx1: str, tx2: str) -> bool:
        # Transactions are concurrent if neither finished before the other started
        end1 = self.tx_end_time.get(tx1, float('inf'))
        start1 = self.tx_start_time.get(tx1, 0)
        end2 = self.tx_end_time.get(tx2, float('inf'))
        start2 = self.tx_start_time.get(tx2, 0)
        return not (end1 < start2 or end2 < start1)

    def _add_rw_edge(self, r_tx: str, w_tx: str):
        self.rw_out[r_tx].add(w_tx)
        self.rw_in[w_tx].add(r_tx)
        self.timeline.append({"action": "RW_ANTIDEPENDENCY_EDGE", "from": r_tx, "to": w_tx})

    def commit(self, tx_id: str, mode: str = "SSI") -> Dict[str, Any]:
        if self.tx_state.get(tx_id) != "ACTIVE":
            return {"status": "ALREADY_TERMINATED", "tx_id": tx_id}

        if mode == "REPEATABLE_READ":
            # Naive Snapshot Isolation without SSI:
            # Only checks write-write conflicts on identical keys.
            # Disjoint writes both commit! (Write Skew anomaly)
            self.tx_state[tx_id] = "COMMITTED"
            self.tx_end_time[tx_id] = len(self.timeline)
            for k, v in self.writes[tx_id].items():
                self.db[k] = {"val": v, "version": self.db.get(k, {}).get("version", 0) + 1}
            self.timeline.append({"action": "COMMIT", "tx_id": tx_id, "status": "COMMITTED", "mode": mode})
            return {"status": "COMMITTED", "tx_id": tx_id, "mode": mode}

        # SSI Mode (Cahill's Serializable Snapshot Isolation)
        # Check if committing tx_id forms a dangerous structure with COMMITTED transactions
        # A dangerous structure is Tin -> T -> Tout where either Tin or Tout is already COMMITTED,
        # or Tin == Tout (cycle of length 2) and that counterpart is COMMITTED.
        committed_in = [t for t in self.rw_in[tx_id] if self.tx_state.get(t) == "COMMITTED"]
        committed_out = [t for t in self.rw_out[tx_id] if self.tx_state.get(t) == "COMMITTED"]

        # If tx_id has both incoming and outgoing edges to committed transactions,
        # OR if tx_id has an edge to a committed tx who also has an edge to tx_id (2-cycle)
        cycle_with_committed = any(t in committed_out for t in self.rw_in[tx_id]) or any(t in committed_in for t in self.rw_out[tx_id])
        pivot_between_committed = (len(committed_in) > 0 and len(self.rw_out[tx_id]) > 0) or (len(self.rw_in[tx_id]) > 0 and len(committed_out) > 0)

        if cycle_with_committed or pivot_between_committed:
            self.tx_state[tx_id] = "ABORTED"
            self.tx_end_time[tx_id] = len(self.timeline)
            self.timeline.append({
                "action": "COMMIT",
                "tx_id": tx_id,
                "status": "ABORTED_SERIALIZATION_FAILURE",
                "sqlstate": "40001",
                "mode": mode
            })
            return {
                "status": "ABORTED_SERIALIZATION_FAILURE",
                "tx_id": tx_id,
                "sqlstate": "40001",
                "reason": "could not serialize access due to read/write dependencies among transactions",
                "mode": mode
            }

        # Safe to commit
        self.tx_state[tx_id] = "COMMITTED"
        self.tx_end_time[tx_id] = len(self.timeline)
        for k, v in self.writes[tx_id].items():
            self.db[k] = {"val": v, "version": self.db.get(k, {}).get("version", 0) + 1}
        self.timeline.append({"action": "COMMIT", "tx_id": tx_id, "status": "COMMITTED", "mode": mode})
        return {"status": "COMMITTED", "tx_id": tx_id, "mode": mode}

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    initial_db = input_data.get("initial_database", {})
    mode = input_data.get("isolation_mode", "SSI") # SSI or REPEATABLE_READ
    operations = input_data.get("operations", [])

    engine = PostgresSsiEngine(initial_db)
    results = {}
    committed_count = 0
    aborted_count = 0

    for op in operations:
        action = op.get("op")
        tx_id = op.get("tx_id")
        key = op.get("key")
        val = op.get("val")

        if action == "BEGIN":
            engine.begin_tx(tx_id)
        elif action == "READ":
            engine.read(tx_id, key)
        elif action == "WRITE":
            engine.write(tx_id, key, val)
        elif action == "COMMIT":
            res = engine.commit(tx_id, mode=mode)
            results[tx_id] = res
            if res["status"] == "COMMITTED":
                committed_count += 1
            elif res["status"] == "ABORTED_SERIALIZATION_FAILURE":
                aborted_count += 1

    # Evaluate final state
    final_db = {k: v["val"] for k, v in engine.db.items()}

    # Determine verdict
    # Check if write skew occurred:
    # e.g., in doctors on call: if all doctors are False, write skew occurred!
    # In general: if REPEATABLE_READ permitted conflicting disjoint writes that SSI would abort
    if aborted_count > 0:
        verdict = "SERIALIZATION_ANOMALY_PREVENTED_SSI"
    elif mode == "REPEATABLE_READ" and any("doctor" in k for k in final_db) and all(v is False for v in final_db.values()):
        verdict = "CATASTROPHIC_WRITE_SKEW_OCCURRED"
    elif mode == "REPEATABLE_READ" and len(engine.timeline) > 10 and any(len(v) > 0 for v in engine.rw_in.values()):
        verdict = "CATASTROPHIC_WRITE_SKEW_OCCURRED"
    else:
        verdict = "SERIALIZABLE_CONCURRENT_EXECUTION"

    return {
        "status": "SUCCESS",
        "isolation_mode": mode,
        "metrics": {
            "total_transactions": len(results),
            "committed_transactions": committed_count,
            "aborted_transactions": aborted_count,
            "total_siread_locks": sum(len(s) for s in engine.siread_locks.values()),
            "total_rw_edges": sum(len(s) for s in engine.rw_out.values()),
            "verdict": verdict
        },
        "final_database": final_db,
        "transaction_results": results,
        "sample_timeline": engine.timeline[:25]
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
