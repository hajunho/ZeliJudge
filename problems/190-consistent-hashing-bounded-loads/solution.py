import sys
import json
import math
import hashlib
from typing import Dict, List, Any, Tuple

def stable_hash(key: str) -> int:
    # 32-bit stable hash from MD5
    return int(hashlib.md5(key.encode('utf-8')).hexdigest()[:8], 16)

class BoundedLoadsConsistentHashSimulator:
    def __init__(self, data: Dict[str, Any]):
        cfg = data.get("system", {})
        self.mode = cfg.get("mode", "BOUNDED_LOADS")
        # Supported: "BOUNDED_LOADS", "STANDARD_CONSISTENT_HASH", "POWER_OF_TWO_CHOICES"
        self.epsilon = float(cfg.get("epsilon", 0.25))  # 25% max overhead
        self.vnodes_per_node = int(cfg.get("vnodes_per_node", 50))
        self.node_max_capacity = int(cfg.get("node_max_capacity", 100))  # Hard crash limit
        self.initial_nodes = list(cfg.get("nodes", ["node_1", "node_2", "node_3", "node_4"]))

        self.active_nodes: List[str] = list(self.initial_nodes)
        self.crashed_nodes: List[str] = []
        self.ring: List[Tuple[int, str]] = []  # sorted list of (hash_val, physical_node)
        self.rebuild_ring()

        self.node_loads: Dict[str, int] = {node: 0 for node in self.initial_nodes}
        self.key_primary_owner: Dict[str, str] = {}  # For cache hit tracking: key -> first hashed node

        # Metrics
        self.total_requests = 0
        self.assigned_primary_count = 0
        self.spillover_count = 0
        self.crashed_node_count = 0
        self.cascading_failure = False
        self.cache_hits = 0
        self.event_timeline: List[Dict[str, Any]] = []

    def rebuild_ring(self):
        self.ring = []
        for node in self.active_nodes:
            for v in range(self.vnodes_per_node):
                v_key = f"{node}#vn{v}"
                h = stable_hash(v_key)
                self.ring.append((h, node))
        self.ring.sort(key=lambda x: x[0])

    def get_successor_index(self, h: int) -> int:
        # Binary search for first ring entry >= h, or wrap around to 0
        low = 0
        high = len(self.ring) - 1
        ans = 0
        found = False
        while low <= high:
            mid = (low + high) // 2
            if self.ring[mid][0] >= h:
                ans = mid
                found = True
                high = mid - 1
            else:
                low = mid + 1
        return ans if found else 0

    def route_request(self, req_id: str, key: str, expected_active_load: int, t: float):
        self.total_requests += 1
        if not self.active_nodes:
            # Cluster completely down!
            self.cascading_failure = True
            return

        h = stable_hash(key)
        start_idx = self.get_successor_index(h)
        primary_node = self.ring[start_idx][1]

        # First time seen key?
        if key not in self.key_primary_owner:
            self.key_primary_owner[key] = primary_node

        assigned_node = None
        spillover = False

        if self.mode == "STANDARD_CONSISTENT_HASH":
            assigned_node = primary_node
            # Check if primary_node exceeds hard capacity
            if self.node_loads[assigned_node] + 1 > self.node_max_capacity:
                # Node crashes!
                self.crashed_nodes.append(assigned_node)
                self.active_nodes.remove(assigned_node)
                self.crashed_node_count += 1
                # Trigger failover to next node on ring
                if not self.active_nodes:
                    self.cascading_failure = True
                    return
                self.rebuild_ring()
                # Re-route to new successor
                new_start = self.get_successor_index(h)
                assigned_node = self.ring[new_start][1]
                # Check cascading crash
                if self.node_loads[assigned_node] + 1 > self.node_max_capacity:
                    self.crashed_nodes.append(assigned_node)
                    self.active_nodes.remove(assigned_node)
                    self.crashed_node_count += 1
                    self.cascading_failure = True
                    return

        elif self.mode == "POWER_OF_TWO_CHOICES":
            # Pick 2 nodes pseudo-randomly using hash of key + req_id
            n = len(self.active_nodes)
            h1 = stable_hash(f"{key}:1:{req_id}") % n
            h2 = stable_hash(f"{key}:2:{req_id}") % n
            n1 = self.active_nodes[h1]
            n2 = self.active_nodes[h2]
            assigned_node = n1 if self.node_loads[n1] <= self.node_loads[n2] else n2

        elif self.mode == "BOUNDED_LOADS":
            # Google Bounded Loads algorithm
            # Capacity bound C = ceil((1 + epsilon) * M / N)
            m = max(expected_active_load, sum(self.node_loads.values()) + 1)
            n = len(self.active_nodes)
            bounded_capacity = max(1, math.ceil((1.0 + self.epsilon) * m / n))

            ring_len = len(self.ring)
            visited_nodes = set()
            curr_idx = start_idx

            for step in range(ring_len):
                candidate_node = self.ring[curr_idx][1]
                if candidate_node in self.active_nodes:
                    if self.node_loads[candidate_node] < bounded_capacity:
                        assigned_node = candidate_node
                        if candidate_node != primary_node:
                            spillover = True
                        break
                    visited_nodes.add(candidate_node)
                    if len(visited_nodes) >= n:
                        # All nodes checked
                        break
                curr_idx = (curr_idx + 1) % ring_len

            if assigned_node is None:
                # All active nodes are at capacity, pick node with minimum load
                assigned_node = min(self.active_nodes, key=lambda nd: self.node_loads[nd])
                if assigned_node != primary_node:
                    spillover = True

        if assigned_node:
            self.node_loads[assigned_node] += 1
            if assigned_node == self.key_primary_owner.get(key):
                self.cache_hits += 1
                self.assigned_primary_count += 1
            else:
                if spillover:
                    self.spillover_count += 1

            self.event_timeline.append({
                "wallclock_ms": t,
                "op": "ROUTE",
                "req_id": req_id,
                "key": key,
                "primary_node": primary_node,
                "assigned_node": assigned_node,
                "spillover": spillover,
                "current_node_load": self.node_loads[assigned_node]
            })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_in_flight = 0
        for item in workload:
            if item.get("op") == "ROUTE":
                total_in_flight += 1

        for item in workload:
            t = float(item.get("wallclock_ms", 0.0))
            op = item.get("op")
            if op == "ROUTE":
                self.route_request(item["req_id"], item["key"], total_in_flight, t)
            elif op == "NODE_DOWN":
                down_node = item["node"]
                if down_node in self.active_nodes:
                    self.active_nodes.remove(down_node)
                    self.crashed_nodes.append(down_node)
                    self.rebuild_ring()

        # Compute load distribution stats
        active_loads = [self.node_loads[nd] for nd in self.initial_nodes]
        max_load = max(active_loads) if active_loads else 0
        min_load = min(active_loads) if active_loads else 0
        avg_load = sum(active_loads) / len(active_loads) if active_loads else 0.0
        load_imbalance_ratio = round(max_load / avg_load, 2) if avg_load > 0 else 1.0

        cache_hit_rate = round(self.cache_hits / self.total_requests, 3) if self.total_requests > 0 else 0.0

        if self.cascading_failure or self.crashed_node_count >= 2:
            verdict = "CASCADING_CLUSTER_COLLAPSE"
            status = "FAILED"
        elif self.mode == "POWER_OF_TWO_CHOICES" and cache_hit_rate < 0.5:
            verdict = "CACHE_LOCALITY_COLLAPSE"
            status = "FAILED"
        elif self.mode == "BOUNDED_LOADS":
            verdict = "OPTIMAL_BOUNDED_LOADS_CONSISTENT_HASH"
            status = "SUCCESS"
        else:
            verdict = "STANDARD_CONSISTENT_HASH_HOTSPOT_VULNERABLE"
            status = "FAILED" if max_load > self.node_max_capacity else "SUCCESS"

        return {
            "status": status,
            "summary": {
                "mode": self.mode,
                "total_requests": self.total_requests,
                "active_nodes_remaining": len(self.active_nodes),
                "crashed_nodes": self.crashed_nodes,
                "spillover_count": self.spillover_count,
                "cache_hit_rate": cache_hit_rate
            },
            "metrics": {
                "total_requests": self.total_requests,
                "primary_assignments": self.assigned_primary_count,
                "spillover_count": self.spillover_count,
                "crashed_node_count": len(self.crashed_nodes),
                "max_node_load": max_load,
                "min_node_load": min_load,
                "average_node_load": round(avg_load, 2),
                "load_imbalance_ratio": load_imbalance_ratio,
                "cache_hit_rate": cache_hit_rate,
                "verdict": verdict
            },
            "node_loads": self.node_loads,
            "sample_events": self.event_timeline[:15]
        }

def solve():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    input_data = json.loads(raw_data)
    simulator = BoundedLoadsConsistentHashSimulator(input_data)
    workload = input_data.get("workload", [])
    output = simulator.run(workload)
    print(json.dumps(output, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    solve()
