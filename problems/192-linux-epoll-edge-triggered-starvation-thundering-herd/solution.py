# scratch/sim_192.py
import json
import math
import sys
from typing import Dict, List, Any, Optional

class LinuxEpollSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.mode = sys_cfg.get("epoll_trigger_mode", "EDGE_TRIGGERED")
        # Supported: "LEVEL_TRIGGERED", "EDGE_TRIGGERED", "OPTIMAL_BOUNDED_ET"
        self.exclusive_flag = sys_cfg.get("use_epollexclusive", False) # EPOLLEXCLUSIVE
        self.num_worker_threads = sys_cfg.get("worker_threads", 4)
        self.max_read_budget_bytes = sys_cfg.get("max_read_budget_bytes", 65536) # 64KB per loop in bounded mode

        self.connections: Dict[str, Dict[str, Any]] = {}
        self.accept_queue: List[str] = [] # Pending connection attempts on listen socket

        self.events_input = data.get("events", [])
        self.current_time_ms = 0.0

        # Metrics
        self.total_epoll_waits = 0
        self.thundering_herd_wakeups = 0
        self.bytes_read_total = 0
        self.starved_connections_count = 0
        self.unhandled_lingering_bytes = 0
        self.max_latency_ms = 0.0

        self.log = []

    def run(self) -> Dict[str, Any]:
        for item in self.events_input:
            self.current_time_ms = item.get("timestamp_ms", self.current_time_ms)
            ev_type = item.get("type")

            if ev_type == "NEW_CONNECTION":
                conn_id = item["connection_id"]
                self.connections[conn_id] = {
                    "rx_buffer": 0,
                    "et_read_pending": False,
                    "last_active_ms": self.current_time_ms,
                    "created_ms": self.current_time_ms
                }
                # New connection ready to accept
                self.accept_queue.append(conn_id)

                # epoll_wait wakeup on listening fd
                self.total_epoll_waits += 1
                if self.exclusive_flag:
                    # Linux EPOLLEXCLUSIVE: wakes exactly 1 thread!
                    woken_threads = 1
                else:
                    # Classic Thundering herd: wakes ALL worker threads!
                    woken_threads = self.num_worker_threads
                    if woken_threads > 1:
                        self.thundering_herd_wakeups += (woken_threads - 1)

                self.log.append({
                    "time_ms": self.current_time_ms,
                    "event": "ACCEPT_EVENT",
                    "connection_id": conn_id,
                    "woken_threads": woken_threads
                })
                # First worker accepts it
                self.accept_queue.pop(0)

            elif ev_type == "DATA_ARRIVE":
                conn_id = item["connection_id"]
                data_size = item.get("bytes", 0)
                if conn_id in self.connections:
                    conn = self.connections[conn_id]
                    prev_buf = conn["rx_buffer"]
                    conn["rx_buffer"] += data_size
                    conn["last_active_ms"] = self.current_time_ms

                    # In Edge-Triggered, signal transition occurs when buffer goes from 0 to >0
                    # or new packet arrives
                    conn["et_read_pending"] = True

                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "DATA_ARRIVED",
                        "connection_id": conn_id,
                        "bytes": data_size,
                        "buffer_now": conn["rx_buffer"]
                    })

            elif ev_type == "EPOLL_DISPATCH_AND_READ":
                caller_worker = item.get("worker_id", "worker_0")
                drain_policy = item.get("drain_policy", "DEFAULT")
                # drain_policy: "NAIVE_SINGLE_READ" (reads 1 buffer), "GREEDY_INFINITE_LOOP", "BOUNDED_DRAIN"

                active_ready_conns = [cid for cid, c in self.connections.items() if c["rx_buffer"] > 0]

                for cid in active_ready_conns:
                    conn = self.connections[cid]
                    available = conn["rx_buffer"]

                    if drain_policy == "NAIVE_SINGLE_READ":
                        # Reads fixed chunk (e.g. 4KB) once and returns
                        chunk = min(available, 4096)
                        conn["rx_buffer"] -= chunk
                        self.bytes_read_total += chunk
                        # In Edge-Triggered mode, if unread data remains, NO NEW EVENT will be delivered!
                        if self.mode == "EDGE_TRIGGERED" and conn["rx_buffer"] > 0:
                            conn["et_read_pending"] = False # Lost edge notification!
                            self.starved_connections_count += 1
                            self.unhandled_lingering_bytes += conn["rx_buffer"]
                            self.log.append({
                                "time_ms": self.current_time_ms,
                                "event": "ET_STARVATION_LOST_DATA_TRAPPED",
                                "connection_id": cid,
                                "lingering_bytes": conn["rx_buffer"]
                            })

                    elif drain_policy == "GREEDY_INFINITE_LOOP":
                        # Drains completely until EAGAIN
                        # But if a greedy connection keeps pouring, it starves others in the loop
                        read_bytes = available
                        conn["rx_buffer"] = 0
                        conn["et_read_pending"] = False
                        self.bytes_read_total += read_bytes
                        self.log.append({
                            "time_ms": self.current_time_ms,
                            "event": "GREEDY_DRAIN_UNTIL_EAGAIN",
                            "connection_id": cid,
                            "bytes_read": read_bytes
                        })

                    elif drain_policy == "BOUNDED_DRAIN":
                        # Reads up to max_read_budget_bytes (e.g. 64KB), then yields to next connection
                        to_read = min(available, self.max_read_budget_bytes)
                        conn["rx_buffer"] -= to_read
                        self.bytes_read_total += to_read
                        if conn["rx_buffer"] == 0:
                            conn["et_read_pending"] = False
                        self.log.append({
                            "time_ms": self.current_time_ms,
                            "event": "BOUNDED_DRAIN_FAIR_YIELD",
                            "connection_id": cid,
                            "bytes_read": to_read,
                            "remaining": conn["rx_buffer"]
                        })

        # Calculate final verdicts
        if self.thundering_herd_wakeups > 10:
            status = "FAILED"
            verdict = "THUNDERING_HERD_CONTEXT_SWITCH_STORM"
        elif self.starved_connections_count > 0 or self.unhandled_lingering_bytes > 0:
            status = "FAILED"
            verdict = "EDGE_TRIGGERED_SOCKET_STARVATION_DATA_TRAPPED"
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_EPOLLEXCLUSIVE_BOUNDED_ET"

        return {
            "status": status,
            "metrics": {
                "total_epoll_waits": self.total_epoll_waits,
                "thundering_herd_wakeups": self.thundering_herd_wakeups,
                "bytes_read_total": self.bytes_read_total,
                "starved_connections_count": self.starved_connections_count,
                "unhandled_lingering_bytes": self.unhandled_lingering_bytes,
                "active_connections_count": len(self.connections),
                "verdict": verdict
            },
            "events_log": self.log
        }

if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    sim = LinuxEpollSimulator(input_data)
    res = sim.run()
    print(json.dumps(res, indent=2))
