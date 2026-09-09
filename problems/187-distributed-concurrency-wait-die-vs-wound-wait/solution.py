# Core model implementation for Problem 187: Distributed Concurrency Wait-Die vs Wound-Wait (Google Spanner Deadlock Avoidance)
from typing import Dict, List, Any, Optional
import json
import sys

class DistributedDeadlockAvoidanceSimulator:
    def __init__(self, data: Dict[str, Any]):
        cfg = data.get("system", {})
        self.mode: str = cfg.get("concurrency_mode", "WOUND_WAIT")
        # Supported Modes: "NAIVE_LOCK_TIMEOUT", "WAIT_DIE", "WOUND_WAIT"
        self.lock_timeout_ms: float = float(cfg.get("lock_wait_timeout_ms", 50.0))

        self.transactions: Dict[str, Dict[str, Any]] = {}
        self.resource_holders: Dict[str, Optional[str]] = {}
        self.resource_waiters: Dict[str, List[str]] = {}

        # Metrics
        self.total_lock_requests: int = 0
        self.locks_granted_immediately: int = 0
        self.waits_queued: int = 0
        self.aborts_die: int = 0
        self.aborts_wound: int = 0
        self.aborts_timeout: int = 0
        self.successful_commits: int = 0
        self.deadlock_cycles_detected: int = 0
        self.event_log: List[Dict[str, Any]] = []

    def get_or_create_tx(self, tx_id: str, ts: float) -> Dict[str, Any]:
        if tx_id not in self.transactions:
            self.transactions[tx_id] = {
                "tx_id": tx_id,
                "ts": ts,
                "status": "ACTIVE",
                "held_locks": set(),
                "waiting_for": None,
                "wait_start_ms": 0.0
            }
        return self.transactions[tx_id]

    def check_deadlock_cycle(self) -> bool:
        adj: Dict[str, List[str]] = {}
        for tx_id, tx in self.transactions.items():
            if tx["status"] == "WAITING" and tx["waiting_for"]:
                holder = self.resource_holders.get(tx["waiting_for"])
                if holder and holder != tx_id:
                    adj.setdefault(tx_id, []).append(holder)

        visited = set()
        rec_stack = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for node in list(adj.keys()):
            if node not in visited:
                if dfs(node):
                    return True
        return False

    def abort_transaction(self, tx_id: str, reason: str, t: float):
        tx = self.transactions.get(tx_id)
        if not tx or tx["status"] in ("ABORTED", "COMMITTED"):
            return

        tx["status"] = "ABORTED"
        if reason == "DIE":
            self.aborts_die += 1
        elif reason == "WOUND":
            self.aborts_wound += 1
        elif reason == "TIMEOUT":
            self.aborts_timeout += 1

        held = list(tx["held_locks"])
        tx["held_locks"].clear()
        for res in held:
            self.resource_holders[res] = None
            self.wake_next_waiter(res, t)

        if tx["waiting_for"]:
            res = tx["waiting_for"]
            tx["waiting_for"] = None
            if res in self.resource_waiters and tx_id in self.resource_waiters[res]:
                self.resource_waiters[res].remove(tx_id)

        self.event_log.append({
            "wallclock_ms": t,
            "action": f"ABORT_{reason}",
            "tx_id": tx_id,
            "details": f"Tx {tx_id} aborted by {reason}"
        })

    def wake_next_waiter(self, res_id: str, t: float):
        waiters = self.resource_waiters.get(res_id, [])
        while waiters:
            next_tx_id = waiters.pop(0)
            next_tx = self.transactions.get(next_tx_id)
            if next_tx and next_tx["status"] == "WAITING":
                next_tx["status"] = "ACTIVE"
                next_tx["waiting_for"] = None
                next_tx["held_locks"].add(res_id)
                self.resource_holders[res_id] = next_tx_id
                self.event_log.append({
                    "wallclock_ms": t,
                    "action": "LOCK_ACQUIRED_FROM_QUEUE",
                    "tx_id": next_tx_id,
                    "res_id": res_id
                })
                return

    def request_lock(self, tx_id: str, ts: float, res_id: str, t: float):
        self.total_lock_requests += 1
        tx = self.get_or_create_tx(tx_id, ts)
        if tx["status"] != "ACTIVE":
            return

        holder = self.resource_holders.get(res_id)

        if holder is None or holder == tx_id:
            self.resource_holders[res_id] = tx_id
            tx["held_locks"].add(res_id)
            self.locks_granted_immediately += 1
            self.event_log.append({
                "wallclock_ms": t,
                "action": "LOCK_GRANTED",
                "tx_id": tx_id,
                "res_id": res_id
            })
            return

        holder_tx = self.transactions[holder]

        if self.mode == "NAIVE_LOCK_TIMEOUT":
            tx["status"] = "WAITING"
            tx["waiting_for"] = res_id
            tx["wait_start_ms"] = t
            self.resource_waiters.setdefault(res_id, []).append(tx_id)
            self.waits_queued += 1
            self.event_log.append({
                "wallclock_ms": t,
                "action": "LOCK_WAIT",
                "tx_id": tx_id,
                "res_id": res_id,
                "holder": holder
            })
            if self.check_deadlock_cycle():
                self.deadlock_cycles_detected += 1

        elif self.mode == "WAIT_DIE":
            # Rule: Older waits, Younger dies
            if tx["ts"] < holder_tx["ts"]:
                tx["status"] = "WAITING"
                tx["waiting_for"] = res_id
                tx["wait_start_ms"] = t
                self.resource_waiters.setdefault(res_id, []).append(tx_id)
                self.waits_queued += 1
                self.event_log.append({
                    "wallclock_ms": t,
                    "action": "OLDER_WAITS",
                    "tx_id": tx_id,
                    "res_id": res_id,
                    "holder": holder
                })
            else:
                self.event_log.append({
                    "wallclock_ms": t,
                    "action": "YOUNGER_DIES",
                    "tx_id": tx_id,
                    "res_id": res_id,
                    "holder": holder
                })
                self.abort_transaction(tx_id, "DIE", t)

        elif self.mode == "WOUND_WAIT":
            # Rule: Younger waits, Older wounds younger
            if tx["ts"] < holder_tx["ts"]:
                self.event_log.append({
                    "wallclock_ms": t,
                    "action": "OLDER_WOUNDS_YOUNGER",
                    "tx_id": tx_id,
                    "res_id": res_id,
                    "victim": holder
                })
                self.abort_transaction(holder, "WOUND", t)
                self.resource_holders[res_id] = tx_id
                tx["held_locks"].add(res_id)
                self.locks_granted_immediately += 1
            else:
                tx["status"] = "WAITING"
                tx["waiting_for"] = res_id
                tx["wait_start_ms"] = t
                self.resource_waiters.setdefault(res_id, []).append(tx_id)
                self.waits_queued += 1
                self.event_log.append({
                    "wallclock_ms": t,
                    "action": "YOUNGER_WAITS",
                    "tx_id": tx_id,
                    "res_id": res_id,
                    "holder": holder
                })

    def commit_tx(self, tx_id: str, t: float):
        tx = self.transactions.get(tx_id)
        if not tx or tx["status"] != "ACTIVE":
            return

        tx["status"] = "COMMITTED"
        self.successful_commits += 1

        held = list(tx["held_locks"])
        tx["held_locks"].clear()
        for res in held:
            self.resource_holders[res] = None
            self.wake_next_waiter(res, t)

        self.event_log.append({
            "wallclock_ms": t,
            "action": "COMMIT",
            "tx_id": tx_id
        })

    def check_timeouts(self, t: float):
        if self.mode != "NAIVE_LOCK_TIMEOUT":
            return
        for tx_id, tx in list(self.transactions.items()):
            if tx["status"] == "WAITING":
                if t - tx["wait_start_ms"] >= self.lock_timeout_ms:
                    self.abort_transaction(tx_id, "TIMEOUT", t)

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in workload:
            t = float(item.get("wallclock_ms", 0.0))
            self.check_timeouts(t)

            op = item.get("op")
            if op == "REQUEST_LOCK":
                self.request_lock(item["tx_id"], float(item["ts"]), item["res_id"], t)
            elif op == "COMMIT":
                self.commit_tx(item["tx_id"], t)
            elif op == "ABORT":
                self.abort_transaction(item["tx_id"], "MANUAL", t)

        if workload:
            self.check_timeouts(float(workload[-1].get("wallclock_ms", 0.0)) + self.lock_timeout_ms + 1.0)

        total_aborts = self.aborts_die + self.aborts_wound + self.aborts_timeout
        total_finished = self.successful_commits + total_aborts
        commit_rate = round(self.successful_commits / total_finished, 4) if total_finished > 0 else 0.0

        if self.mode == "NAIVE_LOCK_TIMEOUT":
            verdict = "DISTRIBUTED_DEADLOCK_TIMEOUT_COLLAPSE"
        elif self.mode == "WAIT_DIE":
            verdict = "WAIT_DIE_STARVATION_CHURN"
        else:
            verdict = "OPTIMAL_WOUND_WAIT_SPANNER"

        return {
            "status": "SUCCESS" if (self.mode != "NAIVE_LOCK_TIMEOUT" or self.deadlock_cycles_detected == 0) else "FAILED",
            "summary": {
                "concurrency_mode": self.mode,
                "total_lock_requests": self.total_lock_requests,
                "successful_commits": self.successful_commits,
                "total_aborts": total_aborts,
                "commit_rate": commit_rate,
                "deadlock_cycles": self.deadlock_cycles_detected
            },
            "metrics": {
                "total_lock_requests": self.total_lock_requests,
                "locks_granted_immediately": self.locks_granted_immediately,
                "waits_queued": self.waits_queued,
                "aborts_die": self.aborts_die,
                "aborts_wound": self.aborts_wound,
                "aborts_timeout": self.aborts_timeout,
                "successful_commits": self.successful_commits,
                "commit_rate": commit_rate,
                "deadlock_cycles_detected": self.deadlock_cycles_detected,
                "verdict": verdict
            },
            "sample_events": self.event_log[:15]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sim = DistributedDeadlockAvoidanceSimulator(input_data)
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
