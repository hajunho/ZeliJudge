# scratch/sim_188.py
import json
import sys
from typing import Dict, List, Any, Optional, Set

class Participant:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.state = "INIT" # INIT, PREPARED, PRE_COMMIT, COMMITTED, ABORTED, BLOCKED
        self.held_locks: Set[str] = set()

class DistributedTxEngine:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.protocol = sys_cfg.get("protocol", "3PC") # 2PC, 3PC
        self.participant_timeout_ms = float(sys_cfg.get("participant_timeout_ms", 200.0))

        self.coordinator_state = "INIT"
        self.participants: Dict[str, Participant] = {}
        participant_ids = sys_cfg.get("participants", ["P1", "P2", "P3"])
        for pid in participant_ids:
            self.participants[pid] = Participant(pid)

        self.metrics = {
            "protocol": self.protocol,
            "total_transactions": 0,
            "committed_transactions": 0,
            "aborted_transactions": 0,
            "blocked_participants_count": 0,
            "nonblocking_recoveries": 0,
            "coordinator_crashes": 0,
            "verdict": ""
        }
        self.events_log: List[Dict[str, Any]] = []

    def run_workload(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in workload:
            op = item["op"]
            wallclock_ms = float(item.get("wallclock_ms", 0.0))

            if op == "START_TX":
                self._handle_start_tx(item, wallclock_ms)

            elif op == "COORDINATOR_CRASH":
                self._handle_coordinator_crash(item, wallclock_ms)

            elif op == "PARTICIPANT_TIMEOUT":
                self._handle_participant_timeout(item, wallclock_ms)

        # Determine verdict
        if self.metrics["blocked_participants_count"] > 0:
            self.metrics["verdict"] = "COORDINATOR_CRASH_2PC_BLOCKING_DISASTER"
            status = "FAILED"
        elif self.metrics["nonblocking_recoveries"] > 0:
            self.metrics["verdict"] = "NON_BLOCKING_3PC_SAFE_TERMINATION"
            status = "SUCCESS"
        elif self.metrics["aborted_transactions"] > 0 and self.metrics["committed_transactions"] == 0:
            self.metrics["verdict"] = "TRANSACTION_VOTE_NO_ABORT"
            status = "SUCCESS"
        elif self.protocol == "2PC":
            self.metrics["verdict"] = "TWO_PHASE_COMMIT_SUCCESS"
            status = "SUCCESS"
        else:
            self.metrics["verdict"] = "THREE_PHASE_COMMIT_SUCCESS"
            status = "SUCCESS"

        participant_states = {pid: p.state for pid, p in self.participants.items()}

        return {
            "status": status,
            "protocol": self.protocol,
            "metrics": dict(self.metrics),
            "participant_states": participant_states,
            "events_log": self.events_log
        }

    def _handle_start_tx(self, item: Dict[str, Any], wallclock_ms: float):
        self.metrics["total_transactions"] += 1
        tx_id = item["tx_id"]
        votes = item.get("votes", {pid: "YES" for pid in self.participants})
        locks_map = item.get("resource_locks", {pid: [f"RES_{pid}"] for pid in self.participants})

        # Phase 1: Prepare / Vote
        all_yes = True
        for pid, p in self.participants.items():
            vote = votes.get(pid, "YES")
            if vote == "YES":
                p.state = "PREPARED"
                p.held_locks = set(locks_map.get(pid, []))
                self.events_log.append({
                    "wallclock_ms": wallclock_ms,
                    "action": "PARTICIPANT_VOTED_YES",
                    "participant": pid,
                    "state": "PREPARED",
                    "locks": sorted(list(p.held_locks))
                })
            else:
                p.state = "ABORTED"
                all_yes = False
                self.events_log.append({
                    "wallclock_ms": wallclock_ms,
                    "action": "PARTICIPANT_VOTED_NO",
                    "participant": pid,
                    "state": "ABORTED"
                })

        if not all_yes:
            # Any participant voted NO -> Global Abort
            for pid, p in self.participants.items():
                p.state = "ABORTED"
                p.held_locks.clear()
            self.coordinator_state = "ABORTED"
            self.metrics["aborted_transactions"] += 1
            self.events_log.append({
                "wallclock_ms": wallclock_ms + 10.0,
                "action": "COORDINATOR_GLOBAL_ABORT",
                "tx_id": tx_id
            })
            return

        # If all participants voted YES:
        if self.protocol == "2PC":
            # 2PC directly sends COMMIT unless coordinator crashes beforehand
            if item.get("crash_before_commit", False):
                return
            for pid, p in self.participants.items():
                p.state = "COMMITTED"
                p.held_locks.clear()
            self.coordinator_state = "COMMITTED"
            self.metrics["committed_transactions"] += 1
            self.events_log.append({
                "wallclock_ms": wallclock_ms + 20.0,
                "action": "COORDINATOR_GLOBAL_COMMIT",
                "tx_id": tx_id
            })

        elif self.protocol == "3PC":
            # Phase 2: Pre-Commit
            if item.get("crash_before_pre_commit", False):
                return
            for pid, p in self.participants.items():
                p.state = "PRE_COMMIT"
                self.events_log.append({
                    "wallclock_ms": wallclock_ms + 10.0,
                    "action": "PARTICIPANT_ENTER_PRE_COMMIT",
                    "participant": pid
                })
            self.coordinator_state = "PRE_COMMITTING"

            if item.get("crash_before_commit", False):
                return

            # Phase 3: Do-Commit
            for pid, p in self.participants.items():
                p.state = "COMMITTED"
                p.held_locks.clear()
            self.coordinator_state = "COMMITTED"
            self.metrics["committed_transactions"] += 1
            self.events_log.append({
                "wallclock_ms": wallclock_ms + 20.0,
                "action": "COORDINATOR_GLOBAL_COMMIT",
                "tx_id": tx_id
            })

    def _handle_coordinator_crash(self, item: Dict[str, Any], wallclock_ms: float):
        self.metrics["coordinator_crashes"] += 1
        self.coordinator_state = "CRASHED"
        self.events_log.append({
            "wallclock_ms": wallclock_ms,
            "action": "COORDINATOR_CRASHED",
            "at_phase": item.get("at_phase", "PREPARE")
        })

    def _handle_participant_timeout(self, item: Dict[str, Any], wallclock_ms: float):
        if self.protocol == "2PC":
            # In 2PC: participants in PREPARED state are indefinitely BLOCKED!
            blocked_count = 0
            for pid, p in self.participants.items():
                if p.state == "PREPARED":
                    p.state = "BLOCKED"
                    blocked_count += 1
                    self.events_log.append({
                        "wallclock_ms": wallclock_ms,
                        "action": "PARTICIPANT_BLOCKED_ON_TIMEOUT",
                        "participant": pid,
                        "held_locks": sorted(list(p.held_locks))
                    })
            self.metrics["blocked_participants_count"] += blocked_count

        elif self.protocol == "3PC":
            # In 3PC Termination Protocol:
            states = [p.state for p in self.participants.values()]
            if any(s == "PRE_COMMIT" for s in states):
                # If ANY participant is in PRE_COMMIT, all participants voted YES!
                # It is 100% safe to commit without blocking!
                for pid, p in self.participants.items():
                    p.state = "COMMITTED"
                    p.held_locks.clear()
                    self.events_log.append({
                        "wallclock_ms": wallclock_ms,
                        "action": "NONBLOCKING_TIMEOUT_COMMIT",
                        "participant": pid
                    })
                self.metrics["committed_transactions"] += 1
                self.metrics["nonblocking_recoveries"] += 1

            elif all(s == "PREPARED" for s in states):
                # If participants are in PREPARED, no node reached COMMIT!
                # It is 100% safe to abort without blocking!
                for pid, p in self.participants.items():
                    p.state = "ABORTED"
                    p.held_locks.clear()
                    self.events_log.append({
                        "wallclock_ms": wallclock_ms,
                        "action": "NONBLOCKING_TIMEOUT_ABORT",
                        "participant": pid
                    })
                self.metrics["aborted_transactions"] += 1
                self.metrics["nonblocking_recoveries"] += 1

def solve(data: Dict[str, Any]) -> Dict[str, Any]:
    engine = DistributedTxEngine(data)
    return engine.run_workload(data.get("workload", []))

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    req = json.loads(raw_data)
    res = solve(req)
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
