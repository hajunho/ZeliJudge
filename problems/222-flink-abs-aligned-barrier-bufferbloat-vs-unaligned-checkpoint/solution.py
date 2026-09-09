"""
Problem 222: Distributed Stream Processing: Apache Flink Asynchronous Barrier Snapshotting (ABS), Aligned Barrier Bufferbloat vs Unaligned Checkpoints & Kafka 2PC Timeout
"""
import sys
import json

def simulate_stream_checkpoint(data):
    config = data.get("config", {})
    mode = config.get("checkpoint_mode", "ALIGNED")
    checkpoint_timeout_ms = float(config.get("checkpoint_timeout_ms", 30000.0))
    kafka_txn_timeout_ms = float(config.get("kafka_transaction_timeout_ms", 60000.0))
    buffer_capacity_mb = float(config.get("input_channel_buffer_capacity_mb", 256.0))
    base_snapshot_ms = float(config.get("state_snapshot_base_duration_ms", 500.0))

    channels = data.get("channels", [])

    if not channels:
        return {
            "status": "SUCCESS",
            "verdict": "BALANCED_ALIGNED_CHECKPOINT_NORMAL",
            "metrics": {
                "checkpoint_mode": mode,
                "total_channels": 0,
                "alignment_duration_ms": 0.0,
                "total_buffered_mb": 0.0,
                "total_checkpoint_duration_ms": 0.0,
                "buffer_utilization_ratio": 0.0,
                "kafka_transaction_timeout_ms": kafka_txn_timeout_ms
            }
        }

    delays = [float(c.get("barrier_arrival_delay_ms", 100.0)) for c in channels]
    data_rates = [float(c.get("data_rate_mb_per_sec", 10.0)) for c in channels]

    t_first = min(delays)
    t_last = max(delays)

    if mode == "ALIGNED":
        alignment_duration_ms = t_last - t_first
        total_buffered_mb = 0.0
        for delay, rate in zip(delays, data_rates):
            wait_time_sec = max(0.0, (t_last - delay) / 1000.0)
            total_buffered_mb += rate * wait_time_sec

        total_checkpoint_duration_ms = t_last + base_snapshot_ms
    else: # UNALIGNED
        alignment_duration_ms = 0.0
        total_buffered_mb = 0.0
        channel_state_overhead_ms = sum(data_rates) * 0.5
        total_checkpoint_duration_ms = t_first + base_snapshot_ms + channel_state_overhead_ms

    buffer_overflow = total_buffered_mb > buffer_capacity_mb
    checkpoint_timeout = total_checkpoint_duration_ms > checkpoint_timeout_ms
    kafka_txn_timeout = total_checkpoint_duration_ms > kafka_txn_timeout_ms

    if kafka_txn_timeout:
        status = "FAILED"
        verdict = "KAFKA_2PC_TRANSACTION_TIMEOUT_ABORT"
    elif buffer_overflow or checkpoint_timeout:
        status = "FAILED"
        verdict = "BARRIER_ALIGNMENT_BUFFERBLOAT_STALL"
    elif mode == "UNALIGNED":
        status = "SUCCESS"
        verdict = "OPTIMAL_UNALIGNED_CHECKPOINT_EOS"
    elif mode == "ALIGNED" and alignment_duration_ms <= 1000.0 and total_buffered_mb <= (buffer_capacity_mb * 0.2):
        status = "SUCCESS"
        verdict = "BALANCED_ALIGNED_CHECKPOINT_NORMAL"
    else:
        status = "SUCCESS"
        verdict = "MODERATE_ALIGNMENT_BACKPRESSURE_WARNING"

    return {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "checkpoint_mode": mode,
            "total_channels": len(channels),
            "alignment_duration_ms": round(alignment_duration_ms, 2),
            "total_buffered_mb": round(total_buffered_mb, 2),
            "total_checkpoint_duration_ms": round(total_checkpoint_duration_ms, 2),
            "buffer_utilization_ratio": round(total_buffered_mb / buffer_capacity_mb, 4) if buffer_capacity_mb > 0 else 0.0,
            "kafka_transaction_timeout_ms": kafka_txn_timeout_ms
        }
    }

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            return
        data = json.loads(raw_input)
        result = simulate_stream_checkpoint(data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
