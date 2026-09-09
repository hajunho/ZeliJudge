# Core simulator implementation for Problem 182: Linux Network Stack Multicore Scaling, RPS/RFS, and softirq Imbalance
from typing import Dict, List, Any
import hashlib
import json
import sys

class LinuxNetworkCoreSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.num_cores: int = sys_cfg.get("num_cpu_cores", 4)
        self.steering_mode: str = sys_cfg.get("steering_mode", "RFS_AFFINITY")
        # Supported Modes: "SINGLE_CORE_IRQ", "NAIVE_ROUND_ROBIN_RPS", "HASHED_RPS", "RFS_AFFINITY"
        self.core_capacity: int = sys_cfg.get("core_softirq_capacity_packets", 500)
        self.app_flow_core_map: Dict[str, int] = sys_cfg.get("app_flow_core_map", {})

        # Flow tracking
        self.flow_last_seq: Dict[str, int] = {}
        self.rr_index: int = 0

        # Cumulative Metrics
        self.total_packets: int = 0
        self.processed_packets: int = 0
        self.dropped_packets: int = 0
        self.out_of_order_packets: int = 0
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.total_latency_us: float = 0.0
        self.core_packet_counts: List[int] = [0] * self.num_cores
        self.timeline: List[Dict[str, Any]] = []

    def get_app_core(self, flow_id: str) -> int:
        if flow_id in self.app_flow_core_map:
            return self.app_flow_core_map[flow_id] % self.num_cores
        h = int(hashlib.md5(flow_id.encode("utf-8")).hexdigest()[:8], 16)
        return h % self.num_cores

    def route_packet(self, pkt: Dict[str, Any]) -> int:
        flow_id = pkt["flow_id"]

        if self.steering_mode == "SINGLE_CORE_IRQ":
            # All hardware interrupts routed to Core 0 (/proc/irq/N/smp_affinity = 1)
            return 0

        elif self.steering_mode == "NAIVE_ROUND_ROBIN_RPS":
            # Naive round-robin splits packets of the same flow across different cores
            target_core = self.rr_index % self.num_cores
            self.rr_index += 1
            return target_core

        elif self.steering_mode == "HASHED_RPS":
            # Hashed RPS: 4-tuple flow hash ensures packets of the same flow stay on the same core
            h = int(hashlib.md5(flow_id.encode("utf-8")).hexdigest()[:8], 16)
            return h % self.num_cores

        elif self.steering_mode == "RFS_AFFINITY":
            # RFS: Routes packet to the core running the user application thread handling this socket
            return self.get_app_core(flow_id)

        return 0

    def execute_tick(self, item: Dict[str, Any]):
        tick = item.get("tick", len(self.timeline) + 1)
        packets = item.get("packets", [])
        self.total_packets += len(packets)

        tick_core_loads = [0] * self.num_cores
        tick_dropped = 0
        tick_processed = 0
        tick_ooo = 0
        tick_cache_hits = 0
        tick_cache_misses = 0
        tick_latency = 0.0

        core_queues = [[] for _ in range(self.num_cores)]
        for pkt in packets:
            target_core = self.route_packet(pkt)
            core_queues[target_core].append(pkt)

        if self.steering_mode == "NAIVE_ROUND_ROBIN_RPS":
            # Interleaved processing simulation to model cross-core processing jitter and out-of-order arrival
            interleaved = []
            max_len = max(len(q) for q in core_queues) if core_queues else 0
            for i in range(max_len):
                for offset in [1, 2, 0, 3]:
                    c_id = offset % self.num_cores
                    if i < len(core_queues[c_id]):
                        interleaved.append((c_id, core_queues[c_id][i], i))

            for c_id, pkt, q_idx in interleaved:
                tick_core_loads[c_id] = len(core_queues[c_id])
                if q_idx >= self.core_capacity:
                    tick_dropped += 1
                    self.dropped_packets += 1
                    continue

                tick_processed += 1
                self.processed_packets += 1

                flow_id = pkt["flow_id"]
                seq = pkt.get("seq", 0)
                if flow_id in self.flow_last_seq:
                    if seq < self.flow_last_seq[flow_id]:
                        tick_ooo += 1
                        self.out_of_order_packets += 1
                self.flow_last_seq[flow_id] = seq

                app_core = self.get_app_core(flow_id)
                if c_id == app_core:
                    tick_cache_hits += 1
                    self.cache_hits += 1
                    tick_latency += 10.0
                else:
                    tick_cache_misses += 1
                    self.cache_misses += 1
                    tick_latency += 50.0

            for c_id in range(self.num_cores):
                self.core_packet_counts[c_id] += len(core_queues[c_id])

        else:
            for core_id in range(self.num_cores):
                q = core_queues[core_id]
                tick_core_loads[core_id] = len(q)
                self.core_packet_counts[core_id] += len(q)

                for idx, pkt in enumerate(q):
                    if idx >= self.core_capacity:
                        tick_dropped += 1
                        self.dropped_packets += 1
                        continue

                    tick_processed += 1
                    self.processed_packets += 1

                    flow_id = pkt["flow_id"]
                    seq = pkt.get("seq", 0)
                    if flow_id in self.flow_last_seq:
                        if seq < self.flow_last_seq[flow_id]:
                            tick_ooo += 1
                            self.out_of_order_packets += 1
                    self.flow_last_seq[flow_id] = seq

                    app_core = self.get_app_core(flow_id)
                    if core_id == app_core:
                        tick_cache_hits += 1
                        self.cache_hits += 1
                        tick_latency += 10.0
                    else:
                        tick_cache_misses += 1
                        self.cache_misses += 1
                        tick_latency += 50.0

        self.total_latency_us += tick_latency

        self.timeline.append({
            "tick": tick,
            "packets_count": len(packets),
            "core_loads": tick_core_loads,
            "processed": tick_processed,
            "dropped": tick_dropped,
            "out_of_order": tick_ooo,
            "cache_hits": tick_cache_hits,
            "cache_misses": tick_cache_misses
        })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in workload:
            self.execute_tick(item)

        avg_latency = round(self.total_latency_us / self.processed_packets, 2) if self.processed_packets > 0 else 0.0
        cache_hit_rate = round(self.cache_hits / self.processed_packets, 4) if self.processed_packets > 0 else 0.0
        drop_rate = round(self.dropped_packets / self.total_packets, 4) if self.total_packets > 0 else 0.0

        max_core_count = max(self.core_packet_counts)
        peak_core_imbalance_ratio = round(max_core_count / (sum(self.core_packet_counts) / self.num_cores), 2) if sum(self.core_packet_counts) > 0 else 1.0

        if self.steering_mode == "SINGLE_CORE_IRQ":
            verdict = "CORE_ZERO_SOFTIRQ_SATURATION_COLLAPSE"
        elif self.steering_mode == "NAIVE_ROUND_ROBIN_RPS":
            verdict = "TCP_OUT_OF_ORDER_RETRANSMIT_STORM"
        elif self.steering_mode == "RFS_AFFINITY":
            verdict = "RFS_ZERO_COPY_CACHE_LOCALITY_OPTIMAL"
        else:
            verdict = "HASHED_RPS_IN_ORDER_BALANCED"

        return {
            "status": "FAILED" if self.dropped_packets > 0 or self.out_of_order_packets > 0 else "SUCCESS",
            "summary": {
                "num_cpu_cores": self.num_cores,
                "steering_mode": self.steering_mode,
                "core_softirq_capacity": self.core_capacity,
                "total_packets": self.total_packets
            },
            "metrics": {
                "total_packets": self.total_packets,
                "processed_packets": self.processed_packets,
                "dropped_packets": self.dropped_packets,
                "drop_rate": drop_rate,
                "out_of_order_packets": self.out_of_order_packets,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_hit_rate": cache_hit_rate,
                "peak_core_imbalance_ratio": peak_core_imbalance_ratio,
                "average_latency_us": avg_latency,
                "core_packet_distribution": self.core_packet_counts,
                "verdict": verdict
            },
            "sample_timeline": self.timeline[:20]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sim = LinuxNetworkCoreSimulator(input_data)
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
