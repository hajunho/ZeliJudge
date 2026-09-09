# Core simulator implementation for Problem 169: Linux Page Cache Dirty Throttling
from typing import Dict, List, Any, Optional
import json
import math
import sys

class LinuxStorageEngine:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.total_memory_mb: int = sys_cfg.get("total_memory_mb", 16384)
        self.disk_speed_mb_s: int = sys_cfg.get("disk_write_speed_mb_s", 100)
        self.io_mode: str = sys_cfg.get("io_mode", "BUFFERED")
        self.sync_chunk_mb: int = sys_cfg.get("streaming_sync_chunk_mb", 64)

        # Calculate effective thresholds
        if "dirty_background_bytes_mb" in sys_cfg:
            self.bg_threshold_mb = sys_cfg["dirty_background_bytes_mb"]
        else:
            bg_ratio = sys_cfg.get("dirty_background_ratio", 0.10)
            self.bg_threshold_mb = int(self.total_memory_mb * bg_ratio)

        if "dirty_bytes_mb" in sys_cfg:
            self.throttle_threshold_mb = sys_cfg["dirty_bytes_mb"]
        else:
            d_ratio = sys_cfg.get("dirty_ratio", 0.20)
            self.throttle_threshold_mb = int(self.total_memory_mb * d_ratio)

        # State
        self.dirty_mb = 0
        self.uncommitted_sync_mb = 0
        self.total_written_mb = 0
        self.total_flushed_mb = 0
        self.peak_dirty_mb = 0

        # Metrics
        self.latencies_ms: List[float] = []
        self.max_write_stall_ms = 0.0
        self.total_stall_time_ms = 0.0
        self.d_state_stall_count = 0
        self.fsync_stall_ms = 0.0
        self.timeline: List[Dict[str, Any]] = []

    def execute_tick(self, item: Dict[str, Any]):
        tick = item.get("tick", len(self.timeline) + 1)
        op = item.get("op", "IDLE")
        size_mb = item.get("size_mb", 0)

        latency_ms = 0.0
        state = "NORMAL_FAST"

        if self.io_mode == "DIRECT_IO":
            if op == "WRITE":
                # Direct DMA to disk. Bypasses page cache.
                # Latency = size / speed * 1000 ms
                latency_ms = round((size_mb / self.disk_speed_mb_s) * 1000.0, 2)
                self.total_written_mb += size_mb
                self.total_flushed_mb += size_mb
                state = "DIRECT_DMA"
            elif op == "FSYNC":
                latency_ms = 1.0
                state = "FSYNC_NOOP"
            else:
                latency_ms = 0.0
                state = "IDLE"

            self.latencies_ms.append(latency_ms)
            self.timeline.append({
                "tick": tick,
                "op": op,
                "size_mb": size_mb,
                "dirty_memory_mb": 0,
                "latency_ms": latency_ms,
                "state": state
            })
            return

        # Buffered I/O modes (BUFFERED, STREAMING_SYNC)
        # Step 1: Disk flusher works asynchronously during this 1-second tick
        flushed_capacity = self.disk_speed_mb_s
        flushed = min(self.dirty_mb, flushed_capacity)
        self.dirty_mb -= flushed
        self.total_flushed_mb += flushed

        if op == "WRITE":
            self.total_written_mb += size_mb
            self.dirty_mb += size_mb
            self.uncommitted_sync_mb += size_mb

            if self.dirty_mb > self.peak_dirty_mb:
                self.peak_dirty_mb = self.dirty_mb

            if self.io_mode == "STREAMING_SYNC" and self.uncommitted_sync_mb >= self.sync_chunk_mb:
                # Proactive sync: wait for excess above chunk threshold to drain
                drain_amount = self.uncommitted_sync_mb
                drain_flushed = min(self.dirty_mb, drain_amount)
                drain_time_s = drain_flushed / self.disk_speed_mb_s
                latency_ms = round(drain_time_s * 1000.0, 2)
                self.dirty_mb -= drain_flushed
                self.total_flushed_mb += drain_flushed
                self.uncommitted_sync_mb = 0
                state = "STREAMING_SYNC_DRAIN"

            elif self.dirty_mb >= self.throttle_threshold_mb:
                # Linux Kernel balance_dirty_pages_ratelimited:
                # Task is throttled until dirty pages drop back to background threshold
                excess = self.dirty_mb - self.bg_threshold_mb
                drain_time_s = excess / self.disk_speed_mb_s
                latency_ms = round(drain_time_s * 1000.0, 2)
                drained = min(self.dirty_mb, excess)
                self.dirty_mb -= drained
                self.total_flushed_mb += drained
                self.d_state_stall_count += 1
                state = "D_STATE_THROTTLED"

            elif self.dirty_mb >= self.bg_threshold_mb:
                # Background flusher is active, but writer only takes fast RAM copy latency (0.5ms)
                latency_ms = 0.5
                state = "BACKGROUND_FLUSHING"
            else:
                latency_ms = 0.5
                state = "NORMAL_FAST"

            if latency_ms > self.max_write_stall_ms:
                self.max_write_stall_ms = latency_ms

        elif op == "FSYNC":
            # fsync() blocks synchronously until ALL currently dirty pages in page cache are flushed to disk!
            if self.dirty_mb > 0:
                fsync_time_s = self.dirty_mb / self.disk_speed_mb_s
                latency_ms = round(fsync_time_s * 1000.0, 2)
                self.total_flushed_mb += self.dirty_mb
                self.dirty_mb = 0
                self.uncommitted_sync_mb = 0
            else:
                latency_ms = 1.0  # Metadata flush
            self.fsync_stall_ms += latency_ms
            state = "FSYNC_WAIT"

        else:  # IDLE
            latency_ms = 0.0
            state = "BACKGROUND_FLUSHING" if self.dirty_mb > 0 else "IDLE"

        self.latencies_ms.append(latency_ms)
        self.total_stall_time_ms += latency_ms

        self.timeline.append({
            "tick": tick,
            "op": op,
            "size_mb": size_mb,
            "dirty_memory_mb": self.dirty_mb,
            "latency_ms": latency_ms,
            "state": state
        })

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for item in workload:
            self.execute_tick(item)

        # Calculate P99 latency
        sorted_lats = sorted(self.latencies_ms)
        if sorted_lats:
            idx = int(len(sorted_lats) * 0.99)
            idx = min(idx, len(sorted_lats) - 1)
            p99 = sorted_lats[idx]
        else:
            p99 = 0.0

        # Determine verdict
        if self.io_mode == "DIRECT_IO":
            verdict = "DIRECT_IO_PREDICTABLE"
        elif self.max_write_stall_ms >= 5000.0:
            verdict = "CATASTROPHIC_DIRTY_STALL"
        elif self.max_write_stall_ms >= 1000.0:
            verdict = "MODERATE_THROTTLE_SPIKE"
        elif self.peak_dirty_mb > 0:
            verdict = "SMOOTH_BACKGROUND_WRITEBACK"
        else:
            verdict = "IDLE_CLEAN"

        return {
            "status": "SUCCESS",
            "summary": {
                "total_memory_mb": self.total_memory_mb,
                "disk_write_speed_mb_s": self.disk_speed_mb_s,
                "effective_dirty_bg_threshold_mb": self.bg_threshold_mb,
                "effective_dirty_throttle_threshold_mb": self.throttle_threshold_mb,
                "io_mode": self.io_mode
            },
            "metrics": {
                "total_written_mb": self.total_written_mb,
                "total_flushed_mb": self.total_flushed_mb,
                "max_dirty_memory_mb": self.peak_dirty_mb,
                "max_write_stall_ms": self.max_write_stall_ms,
                "total_stall_time_ms": round(self.total_stall_time_ms, 2),
                "d_state_stall_count": self.d_state_stall_count,
                "fsync_stall_ms": round(self.fsync_stall_ms, 2),
                "p99_latency_ms": round(p99, 2),
                "verdict": verdict
            },
            "sample_timeline": self.timeline[:20]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    engine = LinuxStorageEngine(input_data)
    workload = input_data.get("workload", [])
    return engine.run(workload)

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
