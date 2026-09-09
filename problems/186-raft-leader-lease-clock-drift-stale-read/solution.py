# Core model implementation for Problem 185: Raft Leader Lease Clock Drift & Stale Read Defense
from typing import Dict, List, Any
import json
import sys

class RaftLeaderLeaseSimulator:
    def __init__(self, data: Dict[str, Any]):
        cfg = data.get("system", {})
        self.policy: str = cfg.get("read_policy", "SAFE_BOUNDED_LEASE")
        # Supported Policies: "NAIVE_WALLCLOCK_LEASE", "STRICT_READ_INDEX_QUORUM", "SAFE_BOUNDED_LEASE"
        self.lease_duration_ms: float = float(cfg.get("lease_duration_ms", 500.0))
        self.clock_drift_tolerance_ms: float = float(cfg.get("clock_drift_max_tolerance_ms", 50.0))
        self.quorum_rtt_ms: float = float(cfg.get("quorum_heartbeat_rtt_ms", 20.0))
        self.local_read_latency_ms: float = float(cfg.get("local_read_latency_ms", 0.5))

        self.current_term: int = 1
        self.current_leader: str = "node_1"
        self.committed_data: Dict[str, Any] = {}
        self.node_data: Dict[str, Dict[str, Any]] = {"node_1": {}, "node_2": {}, "node_3": {}}
        self.node_leases: Dict[str, Dict[str, Any]] = {}
        self.node_drift: Dict[str, float] = {}

        # Metrics
        self.total_reads: int = 0
        self.local_lease_reads: int = 0
        self.quorum_reads: int = 0
        self.stale_reads: int = 0
        self.total_read_latency_ms: float = 0.0
        self.read_history: List[Dict[str, Any]] = []

    def execute_event(self, ev: Dict[str, Any]):
        op = ev["op"]
        t = float(ev.get("wallclock_ms", 0.0))

        if op == "LEASE_RENEW":
            ldr = ev["leader_id"]
            term = ev.get("term", self.current_term)
            self.node_leases[ldr] = {
                "term": term,
                "granted_at": t,
                "expiry": t + self.lease_duration_ms
            }

        elif op == "SET_CLOCK_DRIFT":
            nid = ev["node_id"]
            self.node_drift[nid] = float(ev["drift_ms"])

        elif op == "WRITE":
            k = ev["key"]
            v = ev["value"]
            ldr = ev.get("leader_id", self.current_leader)
            term = ev.get("term", self.current_term)
            if ldr == self.current_leader and term == self.current_term:
                self.committed_data[k] = v
                if ldr not in self.node_data:
                    self.node_data[ldr] = {}
                self.node_data[ldr][k] = v

        elif op == "NEW_LEADER_ELECTED":
            self.current_term = ev["term"]
            self.current_leader = ev["new_leader_id"]
            nl = self.current_leader
            if nl not in self.node_data:
                self.node_data[nl] = {}
            # Sync committed data to new leader
            self.node_data[nl].update(self.committed_data)
            # Followers grant lease to new leader
            self.node_leases[nl] = {
                "term": self.current_term,
                "granted_at": t,
                "expiry": t + self.lease_duration_ms
            }

        elif op == "READ":
            self.total_reads += 1
            nid = ev["node_id"]
            k = ev["key"]
            true_val = self.committed_data.get(k, None)
            drift = self.node_drift.get(nid, 0.0)
            local_clock = t + drift

            is_stale = False
            read_val = None
            latency = 0.0
            read_type = ""

            if self.policy == "NAIVE_WALLCLOCK_LEASE":
                lease = self.node_leases.get(nid)
                if lease and local_clock < lease["expiry"] and lease["term"] == self.current_term:
                    read_val = self.node_data.get(nid, {}).get(k, None)
                    latency = self.local_read_latency_ms
                    read_type = "LOCAL_LEASE"
                elif lease and local_clock < lease["expiry"] and lease["term"] < self.current_term:
                    # Deposed leader with lagging clock falsely thinks its lease is still valid
                    read_val = self.node_data.get(nid, {}).get(k, None)
                    latency = self.local_read_latency_ms
                    read_type = "STALE_LOCAL_LEASE_ANOMALY"
                else:
                    latency = self.quorum_rtt_ms + self.local_read_latency_ms
                    read_type = "FALLBACK_QUORUM"
                    if nid == self.current_leader:
                        read_val = self.node_data.get(nid, {}).get(k, None)
                    else:
                        read_val = self.committed_data.get(k, None)

            elif self.policy == "STRICT_READ_INDEX_QUORUM":
                latency = self.quorum_rtt_ms + self.local_read_latency_ms
                read_type = "QUORUM_READ_INDEX"
                if nid == self.current_leader:
                    read_val = self.node_data.get(nid, {}).get(k, None)
                else:
                    read_val = self.committed_data.get(k, None)

            elif self.policy == "SAFE_BOUNDED_LEASE":
                safe_duration = self.lease_duration_ms - (2.0 * self.clock_drift_tolerance_ms)
                lease = self.node_leases.get(nid)
                effective_expiry = (lease["granted_at"] + safe_duration) if lease else 0.0

                if (abs(drift) > self.clock_drift_tolerance_ms or
                    not lease or
                    local_clock >= effective_expiry or
                    lease["term"] != self.current_term):
                    latency = self.quorum_rtt_ms + self.local_read_latency_ms
                    read_type = "SAFE_FALLBACK_QUORUM"
                    if nid == self.current_leader:
                        read_val = self.node_data.get(nid, {}).get(k, None)
                    else:
                        read_val = self.committed_data.get(k, None)
                else:
                    read_val = self.node_data.get(nid, {}).get(k, None)
                    latency = self.local_read_latency_ms
                    read_type = "SAFE_LOCAL_LEASE"

            if read_val != true_val:
                is_stale = True
                self.stale_reads += 1

            if "LOCAL" in read_type:
                self.local_lease_reads += 1
            else:
                self.quorum_reads += 1

            self.total_read_latency_ms += latency
            self.read_history.append({
                "wallclock_ms": t,
                "node_id": nid,
                "key": k,
                "read_value": read_val,
                "expected_true_value": true_val,
                "read_type": read_type,
                "is_stale": is_stale,
                "latency_ms": round(latency, 2)
            })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for ev in workload:
            self.execute_event(ev)

        avg_latency = round(self.total_read_latency_ms / self.total_reads, 2) if self.total_reads > 0 else 0.0
        lease_read_ratio = round(self.local_lease_reads / self.total_reads, 4) if self.total_reads > 0 else 0.0
        stale_read_rate = round(self.stale_reads / self.total_reads, 4) if self.total_reads > 0 else 0.0

        if self.policy == "NAIVE_WALLCLOCK_LEASE":
            verdict = "STALE_READ_LINEARIZABILITY_VIOLATION" if self.stale_reads > 0 else "NAIVE_LEASE_TEMPORARILY_OK"
        elif self.policy == "STRICT_READ_INDEX_QUORUM":
            verdict = "LINEARIZABLE_QUORUM_HEARTBEAT_OVERHEAD"
        else:
            verdict = "OPTIMAL_SAFE_BOUNDED_LEASE"

        return {
            "status": "FAILED" if self.stale_reads > 0 else "SUCCESS",
            "summary": {
                "read_policy": self.policy,
                "total_reads": self.total_reads,
                "stale_reads": self.stale_reads,
                "stale_read_rate": stale_read_rate,
                "local_lease_reads": self.local_lease_reads,
                "quorum_reads": self.quorum_reads,
                "lease_read_ratio": lease_read_ratio,
                "average_latency_ms": avg_latency
            },
            "metrics": {
                "total_reads": self.total_reads,
                "stale_reads": self.stale_reads,
                "stale_read_rate": stale_read_rate,
                "local_lease_reads": self.local_lease_reads,
                "quorum_reads": self.quorum_reads,
                "lease_read_ratio": lease_read_ratio,
                "average_latency_ms": avg_latency,
                "verdict": verdict
            },
            "sample_reads": self.read_history[:10]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sim = RaftLeaderLeaseSimulator(input_data)
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
