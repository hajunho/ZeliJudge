# Core simulator implementation for Problem 171: Epoll Reactor Socket Buffer & Watermark Flow Control
from typing import Dict, List, Any
import json
import sys

class EpollReactorSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.sndbuf_capacity: int = sys_cfg.get("sndbuf_capacity_bytes", 65536)       # 64 KB
        self.high_watermark: int = sys_cfg.get("high_watermark_bytes", 131072)        # 128 KB
        self.low_watermark: int = sys_cfg.get("low_watermark_bytes", 65536)           # 64 KB
        self.max_memory_limit: int = sys_cfg.get("max_memory_limit_bytes", 524288)   # 512 KB
        self.flow_control_mode: str = sys_cfg.get("flow_control_mode", "WATERMARK_BACKPRESSURE")

        # Dynamic State
        self.sndbuf_occupied: int = 0
        self.pending_user_buffer: int = 0
        self.upstream_paused: bool = False
        self.epollout_active: bool = False
        self.is_oom: bool = False

        # Cumulative Metrics
        self.total_upstream_offered: int = 0
        self.total_upstream_accepted: int = 0
        self.total_written_to_socket: int = 0
        self.total_delivered_to_client: int = 0
        self.peak_user_buffer: int = 0
        self.peak_kernel_sndbuf: int = 0
        self.eagain_count: int = 0
        self.backpressure_ticks: int = 0
        self.pause_events: int = 0
        self.resume_events: int = 0
        self.timeline: List[Dict[str, Any]] = []

    def execute_tick(self, item: Dict[str, Any]):
        if self.is_oom:
            return

        tick = item.get("tick", len(self.timeline) + 1)
        upstream_bytes = item.get("upstream_bytes", 0)
        client_drain = item.get("client_drain_rate_bytes", 0)

        self.total_upstream_offered += upstream_bytes

        # 1. Client ACKs / drains data from kernel socket send buffer (SO_SNDBUF)
        drained = min(self.sndbuf_occupied, client_drain)
        self.sndbuf_occupied -= drained
        self.total_delivered_to_client += drained

        # 2. Upstream Ingress & Backpressure Evaluation
        accepted = 0
        if self.flow_control_mode == "NAIVE_UNBOUNDED":
            # Naive mode never pauses upstream regardless of buffer buildup
            accepted = upstream_bytes
            self.pending_user_buffer += accepted
            self.total_upstream_accepted += accepted
            if self.pending_user_buffer > self.peak_user_buffer:
                self.peak_user_buffer = self.pending_user_buffer

            if self.pending_user_buffer > self.max_memory_limit:
                self.is_oom = True
                self.timeline.append({
                    "tick": tick,
                    "upstream_offered_bytes": upstream_bytes,
                    "upstream_accepted_bytes": accepted,
                    "written_to_socket_bytes": 0,
                    "delivered_to_client_bytes": drained,
                    "user_buffer_bytes": self.pending_user_buffer,
                    "kernel_sndbuf_bytes": self.sndbuf_occupied,
                    "upstream_paused": False,
                    "epollout_active": True,
                    "status": "OOM_CRASH"
                })
                return
        else:
            # WATERMARK_BACKPRESSURE mode
            if self.upstream_paused:
                accepted = 0
                self.backpressure_ticks += 1
            else:
                accepted = upstream_bytes
                self.pending_user_buffer += accepted
                self.total_upstream_accepted += accepted

                # High Watermark Breach check
                if self.pending_user_buffer > self.high_watermark:
                    self.upstream_paused = True
                    self.pause_events += 1

        if self.pending_user_buffer > self.peak_user_buffer:
            self.peak_user_buffer = self.pending_user_buffer

        # 3. Non-blocking Socket Write (Reactor EPOLLOUT Drain)
        written = 0
        space_in_sndbuf = self.sndbuf_capacity - self.sndbuf_occupied
        if self.pending_user_buffer > 0:
            if space_in_sndbuf > 0:
                written = min(self.pending_user_buffer, space_in_sndbuf)
                self.sndbuf_occupied += written
                self.pending_user_buffer -= written
                self.total_written_to_socket += written

            if self.pending_user_buffer > 0:
                # Still remaining data in user buffer -> Socket send buffer is full, EAGAIN/EWOULDBLOCK
                self.eagain_count += 1
                self.epollout_active = True
            else:
                # All pending user buffer data successfully flushed into kernel socket buffer
                self.epollout_active = False
        else:
            self.epollout_active = False

        if self.sndbuf_occupied > self.peak_kernel_sndbuf:
            self.peak_kernel_sndbuf = self.sndbuf_occupied

        # 4. Low Watermark Check for resuming upstream ingress
        if self.upstream_paused and self.flow_control_mode != "NAIVE_UNBOUNDED":
            if self.pending_user_buffer < self.low_watermark:
                self.upstream_paused = False
                self.resume_events += 1

        # Determine tick lifecycle status
        if self.upstream_paused:
            status = "BACKPRESSURE_ACTIVE"
        elif self.epollout_active:
            status = "EAGAIN_PENDING"
        elif self.pending_user_buffer == 0 and self.sndbuf_occupied == 0:
            status = "IDLE_DRAINED"
        else:
            status = "STREAMING_FLOWING"

        self.timeline.append({
            "tick": tick,
            "upstream_offered_bytes": upstream_bytes,
            "upstream_accepted_bytes": accepted,
            "written_to_socket_bytes": written,
            "delivered_to_client_bytes": drained,
            "user_buffer_bytes": self.pending_user_buffer,
            "kernel_sndbuf_bytes": self.sndbuf_occupied,
            "upstream_paused": self.upstream_paused,
            "epollout_active": self.epollout_active,
            "status": status
        })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in workload:
            self.execute_tick(item)

        if self.is_oom:
            verdict = "OOM_CRASH_UNBOUNDED_BUFFER"
        elif self.pause_events > 0:
            verdict = "BACKPRESSURE_FLOW_CONTROLLED"
        elif self.eagain_count > 0:
            verdict = "BUFFERED_EAGAIN_RECOVERED"
        else:
            verdict = "PERFECT_LINE_RATE_STREAMING"

        return {
            "status": "FAILED" if self.is_oom else "SUCCESS",
            "summary": {
                "sndbuf_capacity_bytes": self.sndbuf_capacity,
                "high_watermark_bytes": self.high_watermark,
                "low_watermark_bytes": self.low_watermark,
                "max_memory_limit_bytes": self.max_memory_limit,
                "flow_control_mode": self.flow_control_mode
            },
            "metrics": {
                "total_upstream_offered_bytes": self.total_upstream_offered,
                "total_upstream_accepted_bytes": self.total_upstream_accepted,
                "total_written_to_socket_bytes": self.total_written_to_socket,
                "total_delivered_to_client_bytes": self.total_delivered_to_client,
                "peak_user_buffer_bytes": self.peak_user_buffer,
                "peak_kernel_sndbuf_bytes": self.peak_kernel_sndbuf,
                "eagain_count": self.eagain_count,
                "backpressure_ticks": self.backpressure_ticks,
                "pause_events": self.pause_events,
                "resume_events": self.resume_events,
                "final_user_buffer_bytes": self.pending_user_buffer,
                "final_kernel_sndbuf_bytes": self.sndbuf_occupied,
                "verdict": verdict
            },
            "sample_timeline": self.timeline[:20]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sim = EpollReactorSimulator(input_data)
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
