# Core model implementation for Problem 184: Database WAL Group Commit & fsync Batching Simulator
from typing import Dict, List, Any
import json
import sys

class WalGroupCommitSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.mode: str = sys_cfg.get("commit_mode", "PIPELINED_GROUP_COMMIT")
        # Supported Modes: "NAIVE_INDIVIDUAL_FSYNC", "STATIC_DELAY_GROUP_COMMIT", "PIPELINED_GROUP_COMMIT"
        self.fsync_latency_us: float = float(sys_cfg.get("fsync_latency_us", 200.0))
        self.log_write_per_kb_us: float = float(sys_cfg.get("log_write_per_kb_us", 1.0))
        self.commit_delay_us: float = float(sys_cfg.get("commit_delay_us", 100.0))
        self.commit_siblings_min: int = int(sys_cfg.get("commit_siblings_min", 3))
        self.max_batch_size: int = int(sys_cfg.get("max_batch_size", 64))

        # Metrics
        self.total_transactions: int = 0
        self.total_fsync_calls: int = 0
        self.total_log_bytes: int = 0
        self.total_io_time_us: float = 0.0
        self.total_latency_us: float = 0.0
        self.peak_group_size: int = 0
        self.groups_detail: List[Dict[str, Any]] = []

    def run(self, batches: List[Dict[str, Any]]) -> Dict[str, Any]:
        current_time_us: float = 0.0

        for batch in batches:
            batch_id = batch.get("batch_id", len(self.groups_detail) + 1)
            txs = batch.get("transactions", [])
            if not txs:
                continue

            self.total_transactions += len(txs)
            batch_start_time = current_time_us

            if self.mode == "NAIVE_INDIVIDUAL_FSYNC":
                # Serialized execution: each transaction locks log mutex and fsyncs individually
                for tx in txs:
                    b = tx.get("log_bytes", 1024)
                    self.total_log_bytes += b
                    w_time = (b / 1024.0) * self.log_write_per_kb_us
                    dur = w_time + self.fsync_latency_us
                    current_time_us += dur

                    self.total_fsync_calls += 1
                    self.total_io_time_us += dur
                    tx_latency = current_time_us - batch_start_time
                    self.total_latency_us += tx_latency
                    if self.peak_group_size < 1:
                        self.peak_group_size = 1

                    self.groups_detail.append({
                        "batch_id": batch_id,
                        "leader_tx": tx["tx_id"],
                        "group_size": 1,
                        "log_bytes": b,
                        "fsync_count": 1,
                        "duration_us": round(dur, 2),
                        "transactions": [tx["tx_id"]]
                    })

            elif self.mode == "STATIC_DELAY_GROUP_COMMIT":
                # Static delay: if pending txs >= commit_siblings_min, leader waits commit_delay_us
                idx = 0
                while idx < len(txs):
                    chunk = txs[idx:idx + self.max_batch_size]
                    idx += len(chunk)

                    num_siblings = len(chunk)
                    delay = self.commit_delay_us if num_siblings >= self.commit_siblings_min else 0.0
                    tot_bytes = sum(t.get("log_bytes", 1024) for t in chunk)
                    self.total_log_bytes += tot_bytes

                    w_time = (tot_bytes / 1024.0) * self.log_write_per_kb_us
                    dur = delay + w_time + self.fsync_latency_us
                    current_time_us += dur

                    self.total_fsync_calls += 1
                    self.total_io_time_us += dur

                    chunk_latency = current_time_us - batch_start_time
                    self.total_latency_us += chunk_latency * len(chunk)
                    if len(chunk) > self.peak_group_size:
                        self.peak_group_size = len(chunk)

                    self.groups_detail.append({
                        "batch_id": batch_id,
                        "leader_tx": chunk[0]["tx_id"],
                        "group_size": len(chunk),
                        "log_bytes": tot_bytes,
                        "fsync_count": 1,
                        "delay_applied_us": delay,
                        "duration_us": round(dur, 2),
                        "transactions": [t["tx_id"] for t in chunk]
                    })

            elif self.mode == "PIPELINED_GROUP_COMMIT":
                # Lock-free pipelined group commit: leader takes pending transactions up to max_batch_size immediately
                idx = 0
                while idx < len(txs):
                    chunk = txs[idx:idx + self.max_batch_size]
                    idx += len(chunk)

                    tot_bytes = sum(t.get("log_bytes", 1024) for t in chunk)
                    self.total_log_bytes += tot_bytes

                    w_time = (tot_bytes / 1024.0) * self.log_write_per_kb_us
                    dur = w_time + self.fsync_latency_us
                    current_time_us += dur

                    self.total_fsync_calls += 1
                    self.total_io_time_us += dur

                    chunk_latency = current_time_us - batch_start_time
                    self.total_latency_us += chunk_latency * len(chunk)
                    if len(chunk) > self.peak_group_size:
                        self.peak_group_size = len(chunk)

                    self.groups_detail.append({
                        "batch_id": batch_id,
                        "leader_tx": chunk[0]["tx_id"],
                        "group_size": len(chunk),
                        "log_bytes": tot_bytes,
                        "fsync_count": 1,
                        "duration_us": round(dur, 2),
                        "transactions": [t["tx_id"] for t in chunk]
                    })

        avg_latency = round(self.total_latency_us / self.total_transactions, 2) if self.total_transactions > 0 else 0.0
        avg_group_size = round(self.total_transactions / self.total_fsync_calls, 2) if self.total_fsync_calls > 0 else 0.0
        fsync_reduction_rate = round(1.0 - (self.total_fsync_calls / self.total_transactions), 4) if self.total_transactions > 0 else 0.0

        if self.mode == "NAIVE_INDIVIDUAL_FSYNC":
            verdict = "FSYNC_IO_CONVOY_BOTTLENECK"
        elif self.mode == "STATIC_DELAY_GROUP_COMMIT":
            verdict = "STATIC_DELAY_LATENCY_INFLATION"
        else:
            verdict = "OPTIMAL_PIPELINED_GROUP_COMMIT"

        return {
            "status": "SUCCESS" if (self.mode != "NAIVE_INDIVIDUAL_FSYNC" or self.total_transactions <= 2) else "FAILED",
            "summary": {
                "commit_mode": self.mode,
                "total_transactions": self.total_transactions,
                "total_fsync_calls": self.total_fsync_calls,
                "fsync_reduction_rate": fsync_reduction_rate,
                "average_group_size": avg_group_size,
                "peak_group_size": self.peak_group_size
            },
            "metrics": {
                "total_transactions": self.total_transactions,
                "total_fsync_calls": self.total_fsync_calls,
                "total_log_bytes": self.total_log_bytes,
                "total_io_time_us": round(self.total_io_time_us, 2),
                "average_commit_latency_us": avg_latency,
                "average_group_size": avg_group_size,
                "peak_group_size": self.peak_group_size,
                "fsync_reduction_rate": fsync_reduction_rate,
                "verdict": verdict
            },
            "sample_groups": self.groups_detail[:10]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sim = WalGroupCommitSimulator(input_data)
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
