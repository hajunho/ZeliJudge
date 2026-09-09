import json
import sys
from typing import Dict, List, Any, Optional

class IoUringEngine:
    def __init__(self, config: Dict[str, Any]):
        self.mode = config.get("mode", "IOURING_SQPOLL")  # EPOLL_TRADITIONAL, IOURING_BATCHED, IOURING_SQPOLL
        self.queue_depth = config.get("queue_depth", 64)   # SQ/CQ ring capacity
        self.io_latency_us = config.get("io_latency_us", 10.0) # Hardware NVMe read latency
        self.syscall_overhead_us = config.get("syscall_overhead_us", 1.5) # Context switch + trap cost
        self.use_registered_buffers = config.get("use_registered_buffers", False) # IORING_REGISTER_BUFFERS

        # Ring State
        self.sq_head = 0
        self.sq_tail = 0
        self.cq_head = 0
        self.cq_tail = 0

        # Metrics
        self.metrics = {
            "total_ios_requested": 0,
            "total_ios_completed": 0,
            "total_syscalls_issued": 0,
            "cq_overflow_count": 0,
            "total_cpu_time_us": 0.0,
            "total_io_time_us": 0.0,
            "average_latency_per_io_us": 0.0,
            "cq_utilization_peak": 0,
            "verdict": ""
        }
        self.completed_logs: List[Dict[str, Any]] = []

    def process_batches(self, batches: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Each batch dict: {"drain_cqe_count": int, "requests": [ {"io_id": str, "opcode": str, "bytes": int}, ... ]}
        for batch_item in batches:
            drain_count = batch_item.get("drain_cqe_count", 0)
            requests = batch_item.get("requests", [])

            # Userspace drains completed CQEs before or alongside submitting new SQEs
            if drain_count > 0:
                available_cqes = self.cq_tail - self.cq_head
                drained = min(drain_count, available_cqes)
                self.cq_head += drained

            if self.mode == "EPOLL_TRADITIONAL":
                self._process_epoll_requests(requests)
            elif self.mode == "IOURING_BATCHED":
                self._process_batched_requests(requests)
            elif self.mode == "IOURING_SQPOLL":
                self._process_sqpoll_requests(requests)

            # Track peak CQ utilization
            current_cq_util = self.cq_tail - self.cq_head
            self.metrics["cq_utilization_peak"] = max(self.metrics["cq_utilization_peak"], current_cq_util)

        self._finalize_metrics()
        return {
            "status": "SUCCESS",
            "mode": self.mode,
            "metrics": dict(self.metrics),
            "sample_completions": self.completed_logs[:10]
        }

    def _process_epoll_requests(self, requests: List[Dict[str, Any]]):
        # 1 syscall per I/O (e.g. preadv / pwritev)
        for req in requests:
            self.metrics["total_ios_requested"] += 1
            self.metrics["total_syscalls_issued"] += 1
            
            cpu_cost = self.syscall_overhead_us
            io_cost = self.io_latency_us
            total_io_latency = cpu_cost + io_cost

            self.metrics["total_cpu_time_us"] += cpu_cost
            self.metrics["total_io_time_us"] += io_cost
            self.metrics["total_ios_completed"] += 1

            self.completed_logs.append({
                "io_id": req["io_id"],
                "opcode": req.get("opcode", "READ"),
                "status": "COMPLETED",
                "syscalls": 1,
                "latency_us": round(total_io_latency, 2)
            })

    def _process_batched_requests(self, requests: List[Dict[str, Any]]):
        if not requests:
            return
        batch_size = len(requests)
        self.metrics["total_ios_requested"] += batch_size
        self.metrics["total_syscalls_issued"] += 1  # 1 io_uring_enter() syscall

        base_cpu_cost = self.syscall_overhead_us
        if self.use_registered_buffers:
            # Zero-copy registered buffers save 0.2us page pinning overhead per request
            per_req_cpu = max(0.02, 0.05)
        else:
            per_req_cpu = 0.25 # page pinning & mapping cost

        total_cpu_for_batch = base_cpu_cost + (per_req_cpu * batch_size)
        self.metrics["total_cpu_time_us"] += total_cpu_for_batch

        for req in requests:
            # Check CQ overflow
            pending_cq = self.cq_tail - self.cq_head
            if pending_cq >= self.queue_depth:
                self.metrics["cq_overflow_count"] += 1
                self.completed_logs.append({
                    "io_id": req["io_id"],
                    "opcode": req.get("opcode", "READ"),
                    "status": "CQ_OVERFLOW_DROPPED",
                    "syscalls": 0,
                    "latency_us": 0.0
                })
                continue

            io_cost = self.io_latency_us
            self.metrics["total_io_time_us"] += io_cost
            self.metrics["total_ios_completed"] += 1
            self.cq_tail += 1

            per_io_lat = (total_cpu_for_batch / batch_size) + io_cost
            self.completed_logs.append({
                "io_id": req["io_id"],
                "opcode": req.get("opcode", "READ"),
                "status": "COMPLETED",
                "syscalls": 1 if req == requests[0] else 0,
                "latency_us": round(per_io_lat, 2)
            })

    def _process_sqpoll_requests(self, requests: List[Dict[str, Any]]):
        if not requests:
            return
        batch_size = len(requests)
        self.metrics["total_ios_requested"] += batch_size
        self.metrics["total_syscalls_issued"] += 0  # Zero syscalls! Kernel thread polls SQ ring

        if self.use_registered_buffers:
            per_req_cpu = 0.03
        else:
            per_req_cpu = 0.15

        total_cpu_for_batch = per_req_cpu * batch_size
        self.metrics["total_cpu_time_us"] += total_cpu_for_batch

        for req in requests:
            pending_cq = self.cq_tail - self.cq_head
            if pending_cq >= self.queue_depth:
                self.metrics["cq_overflow_count"] += 1
                self.completed_logs.append({
                    "io_id": req["io_id"],
                    "opcode": req.get("opcode", "READ"),
                    "status": "CQ_OVERFLOW_DROPPED",
                    "syscalls": 0,
                    "latency_us": 0.0
                })
                continue

            io_cost = self.io_latency_us
            self.metrics["total_io_time_us"] += io_cost
            self.metrics["total_ios_completed"] += 1
            self.cq_tail += 1

            per_io_lat = per_req_cpu + io_cost
            self.completed_logs.append({
                "io_id": req["io_id"],
                "opcode": req.get("opcode", "READ"),
                "status": "COMPLETED",
                "syscalls": 0,
                "latency_us": round(per_io_lat, 2)
            })

    def _finalize_metrics(self):
        completed = self.metrics["total_ios_completed"]
        if completed > 0:
            total_time = self.metrics["total_cpu_time_us"] + self.metrics["total_io_time_us"]
            self.metrics["average_latency_per_io_us"] = round(total_time / completed, 2)
        
        self.metrics["total_cpu_time_us"] = round(self.metrics["total_cpu_time_us"], 2)
        self.metrics["total_io_time_us"] = round(self.metrics["total_io_time_us"], 2)

        # Determine verdict
        if self.metrics["cq_overflow_count"] > 0:
            self.metrics["verdict"] = "CQ_RING_BUFFER_OVERFLOW_BACKPRESSURE"
        elif self.mode == "EPOLL_TRADITIONAL" and self.metrics["total_syscalls_issued"] == self.metrics["total_ios_requested"]:
            self.metrics["verdict"] = "SYSCALL_OVERHEAD_BOTTLENECK"
        elif self.mode == "IOURING_BATCHED" and self.metrics["total_syscalls_issued"] < self.metrics["total_ios_requested"]:
            self.metrics["verdict"] = "BATCHED_IO_URING_ACCELERATION"
        elif self.mode == "IOURING_SQPOLL" and self.metrics["total_syscalls_issued"] == 0:
            self.metrics["verdict"] = "ZERO_SYSCALL_SQPOLL_LINE_RATE"
        else:
            self.metrics["verdict"] = "DEGRADED_IO_PERFORMANCE"

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    req = json.loads(raw_data)
    engine = IoUringEngine(req["config"])
    result = engine.process_batches(req["batches"])
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
