# scratch/sim_193.py
import json
import math
import sys
from typing import Dict, List, Any, Optional, Tuple

class Record:
    def __init__(self, key: str, value: Optional[str], vector_clock: Dict[str, int], timestamp_ms: float, is_tombstone: bool = False):
        self.key = key
        self.value = value
        self.vector_clock = dict(sorted(vector_clock.items()))
        self.timestamp_ms = timestamp_ms
        self.is_tombstone = is_tombstone
        self.tombstone_created_ms = timestamp_ms if is_tombstone else None

    def clone(self) -> 'Record':
        rec = Record(self.key, self.value, self.vector_clock, self.timestamp_ms, self.is_tombstone)
        rec.tombstone_created_ms = self.tombstone_created_ms
        return rec

def compare_vector_clocks(vc_a: Dict[str, int], vc_b: Dict[str, int]) -> str:
    """
    Returns:
    'A_DOMINATES' if A > B
    'B_DOMINATES' if B > A
    'EQUAL' if A == B
    'CONCURRENT' if conflict
    """
    all_keys = sorted(set(vc_a.keys()).union(set(vc_b.keys())))
    a_greater_or_equal = True
    b_greater_or_equal = True
    has_a_strictly_greater = False
    has_b_strictly_greater = False

    for k in all_keys:
        val_a = vc_a.get(k, 0)
        val_b = vc_b.get(k, 0)
        if val_a < val_b:
            a_greater_or_equal = False
            has_b_strictly_greater = True
        elif val_a > val_b:
            b_greater_or_equal = False
            has_a_strictly_greater = True

    if not has_a_strictly_greater and not has_b_strictly_greater:
        return 'EQUAL'
    if a_greater_or_equal and has_a_strictly_greater:
        return 'A_DOMINATES'
    if b_greater_or_equal and has_b_strictly_greater:
        return 'B_DOMINATES'
    return 'CONCURRENT'

class DistributedGossipStorageSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.node_ids = sys_cfg.get("nodes", ["N1", "N2", "N3"])
        self.replication_factor = sys_cfg.get("replication_factor", len(self.node_ids))
        self.read_quorum = sys_cfg.get("read_quorum", 2)
        self.write_quorum = sys_cfg.get("write_quorum", 2)
        self.gc_grace_ms = sys_cfg.get("gc_grace_ms", 50.0)
        self.enable_tombstones = sys_cfg.get("enable_tombstones", True)
        self.conflict_resolution = sys_cfg.get("conflict_resolution", "LWW") # LWW or NONE

        # Node storage: node_id -> {key: Record}
        self.nodes_data: Dict[str, Dict[str, Record]] = {nid: {} for nid in self.node_ids}
        self.partitioned_nodes: set = set()

        self.events_input = data.get("events", [])
        self.current_time_ms = 0.0

        # Metrics
        self.total_writes = 0
        self.total_reads = 0
        self.read_repairs_count = 0
        self.zombie_resurrections_count = 0
        self.conflicts_detected = 0
        self.tombstones_purged = 0

        self.log = []

    def _resolve_records(self, rec_a: Optional[Record], rec_b: Optional[Record]) -> Optional[Record]:
        if rec_a is None and rec_b is None:
            return None
        if rec_a is None:
            return rec_b.clone()
        if rec_b is None:
            return rec_a.clone()

        cmp_res = compare_vector_clocks(rec_a.vector_clock, rec_b.vector_clock)
        if cmp_res == 'A_DOMINATES':
            return rec_a.clone()
        elif cmp_res == 'B_DOMINATES':
            return rec_b.clone()
        elif cmp_res == 'EQUAL':
            return rec_a.clone()
        else:
            # CONCURRENT
            self.conflicts_detected += 1
            if self.conflict_resolution == "LWW":
                # Last Write Wins by timestamp
                winner = rec_a if rec_a.timestamp_ms >= rec_b.timestamp_ms else rec_b
                res = winner.clone()
                # Merge vector clocks
                all_keys = sorted(set(rec_a.vector_clock.keys()).union(set(rec_b.vector_clock.keys())))
                merged_vc = {k: max(rec_a.vector_clock.get(k, 0), rec_b.vector_clock.get(k, 0)) for k in all_keys}
                res.vector_clock = dict(sorted(merged_vc.items()))
                return res
            else:
                # Unresolved concurrent divergence
                return rec_a.clone()

    def run(self) -> Dict[str, Any]:
        for item in self.events_input:
            self.current_time_ms = item.get("timestamp_ms", self.current_time_ms)
            ev_type = item.get("type")

            if ev_type == "PARTITION_START":
                nid = item["node_id"]
                self.partitioned_nodes.add(nid)
                self.log.append({
                    "time_ms": self.current_time_ms,
                    "event": "NODE_PARTITIONED",
                    "node_id": nid
                })

            elif ev_type == "PARTITION_END":
                nid = item["node_id"]
                if nid in self.partitioned_nodes:
                    self.partitioned_nodes.remove(nid)
                self.log.append({
                    "time_ms": self.current_time_ms,
                    "event": "NODE_RECOVERED",
                    "node_id": nid
                })

            elif ev_type == "WRITE":
                key = item["key"]
                val = item["value"]
                coord = item.get("coordinator", self.node_ids[0])
                self.total_writes += 1

                # Gather current VC from accessible replicas
                accessible_nodes = [nid for nid in self.node_ids if nid not in self.partitioned_nodes]
                cur_vc: Dict[str, int] = {}
                for nid in accessible_nodes:
                    if key in self.nodes_data[nid]:
                        rec = self.nodes_data[nid][key]
                        for k, v in rec.vector_clock.items():
                            cur_vc[k] = max(cur_vc.get(k, 0), v)

                # Increment coordinator clock
                cur_vc[coord] = cur_vc.get(coord, 0) + 1
                cur_vc = dict(sorted(cur_vc.items()))
                new_rec = Record(key, val, cur_vc, self.current_time_ms, is_tombstone=False)

                # Write to accessible replicas up to quorum
                written_count = 0
                for nid in accessible_nodes:
                    self.nodes_data[nid][key] = new_rec.clone()
                    written_count += 1

                self.log.append({
                    "time_ms": self.current_time_ms,
                    "event": "WRITE_COMMITTED",
                    "key": key,
                    "value": val,
                    "vector_clock": dict(cur_vc),
                    "replicas_written": written_count
                })

            elif ev_type == "DELETE":
                key = item["key"]
                coord = item.get("coordinator", self.node_ids[0])
                accessible_nodes = [nid for nid in self.node_ids if nid not in self.partitioned_nodes]

                if not self.enable_tombstones:
                    # Naive physical delete on accessible nodes!
                    for nid in accessible_nodes:
                        if key in self.nodes_data[nid]:
                            del self.nodes_data[nid][key]
                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "NAIVE_PHYSICAL_DELETE",
                        "key": key
                    })
                else:
                    # Tombstone deletion with Vector Clock increment
                    cur_vc: Dict[str, int] = {}
                    for nid in accessible_nodes:
                        if key in self.nodes_data[nid]:
                            rec = self.nodes_data[nid][key]
                            for k, v in rec.vector_clock.items():
                                cur_vc[k] = max(cur_vc.get(k, 0), v)

                    cur_vc[coord] = cur_vc.get(coord, 0) + 1
                    cur_vc = dict(sorted(cur_vc.items()))
                    tombstone = Record(key, None, cur_vc, self.current_time_ms, is_tombstone=True)

                    for nid in accessible_nodes:
                        self.nodes_data[nid][key] = tombstone.clone()

                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "TOMBSTONE_CREATED",
                        "key": key,
                        "vector_clock": dict(cur_vc)
                    })

            elif ev_type == "READ":
                key = item["key"]
                coord = item.get("coordinator", self.node_ids[0])
                self.total_reads += 1
                accessible_nodes = [nid for nid in self.node_ids if nid not in self.partitioned_nodes]

                # Quorum read: inspect records on accessible replicas
                collected_records: List[Tuple[str, Optional[Record]]] = []
                for nid in accessible_nodes[:self.read_quorum]:
                    rec = self.nodes_data[nid].get(key)
                    collected_records.append((nid, rec))

                # Check for discrepancies and resolve dominant
                resolved_rec: Optional[Record] = None
                for nid, rec in collected_records:
                    resolved_rec = self._resolve_records(resolved_rec, rec)

                # Check if Read Repair is needed
                discrepancy = False
                for nid, rec in collected_records:
                    if rec is None and resolved_rec is not None:
                        discrepancy = True
                    elif rec is not None and resolved_rec is None:
                        discrepancy = True
                    elif rec is not None and resolved_rec is not None:
                        if rec.is_tombstone != resolved_rec.is_tombstone or rec.value != resolved_rec.value or rec.vector_clock != resolved_rec.vector_clock:
                            discrepancy = True

                if discrepancy and resolved_rec is not None:
                    # Perform Read Repair
                    self.read_repairs_count += 1
                    for nid, rec in collected_records:
                        self.nodes_data[nid][key] = resolved_rec.clone()
                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "READ_REPAIR_PERFORMED",
                        "key": key,
                        "resolved_value": resolved_rec.value,
                        "is_tombstone": resolved_rec.is_tombstone
                    })

            elif ev_type == "GOSSIP_SYNC":
                node_a = item["node_a"]
                node_b = item["node_b"]
                if node_a not in self.partitioned_nodes and node_b not in self.partitioned_nodes:
                    all_keys = sorted(set(self.nodes_data[node_a].keys()).union(set(self.nodes_data[node_b].keys())))
                    for k in all_keys:
                        rec_a = self.nodes_data[node_a].get(k)
                        rec_b = self.nodes_data[node_b].get(k)

                        # Detect resurrection: if one node had physical delete (None) and other has old active data
                        if not self.enable_tombstones:
                            if (rec_a is None and rec_b is not None and not rec_b.is_tombstone) or \
                               (rec_b is None and rec_a is not None and not rec_a.is_tombstone):
                                self.zombie_resurrections_count += 1

                        merged = self._resolve_records(rec_a, rec_b)
                        if merged is not None:
                            self.nodes_data[node_a][k] = merged.clone()
                            self.nodes_data[node_b][k] = merged.clone()

                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "GOSSIP_EXCHANGED",
                        "node_a": node_a,
                        "node_b": node_b
                    })

            elif ev_type == "PURGE_TOMBSTONES":
                for nid in sorted(self.node_ids):
                    if nid not in self.partitioned_nodes:
                        to_purge = []
                        for k in sorted(self.nodes_data[nid].keys()):
                            rec = self.nodes_data[nid][k]
                            if rec.is_tombstone and rec.tombstone_created_ms is not None:
                                age = self.current_time_ms - rec.tombstone_created_ms
                                if age >= self.gc_grace_ms:
                                    to_purge.append(k)
                        for k in to_purge:
                            del self.nodes_data[nid][k]
                            self.tombstones_purged += 1

                self.log.append({
                    "time_ms": self.current_time_ms,
                    "event": "TOMBSTONES_PURGED_GC",
                    "count": self.tombstones_purged
                })

        # Final state evaluation with sorted keys
        final_node_states = {}
        for nid in sorted(self.node_ids):
            final_node_states[nid] = {
                k: {
                    "val": self.nodes_data[nid][k].value,
                    "tombstone": self.nodes_data[nid][k].is_tombstone,
                    "vc": dict(sorted(self.nodes_data[nid][k].vector_clock.items()))
                }
                for k in sorted(self.nodes_data[nid].keys())
            }

        if self.zombie_resurrections_count > 0:
            status = "FAILED"
            verdict = "ZOMBIE_DATA_RESURRECTION_DISASTER"
        elif self.conflicts_detected > 0 and self.conflict_resolution == "NONE":
            status = "FAILED"
            verdict = "CONCURRENT_VECTOR_CLOCK_DIVERGENCE"
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_GOSSIP_VECTOR_CLOCK_REPAIR"

        return {
            "status": status,
            "metrics": {
                "total_writes": self.total_writes,
                "total_reads": self.total_reads,
                "read_repairs_count": self.read_repairs_count,
                "zombie_resurrections_count": self.zombie_resurrections_count,
                "conflicts_detected": self.conflicts_detected,
                "tombstones_purged": self.tombstones_purged,
                "verdict": verdict
            },
            "nodes_state": final_node_states,
            "events_log": self.log
        }

if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    sim = DistributedGossipStorageSimulator(input_data)
    res = sim.run()
    print(json.dumps(res, indent=2))
