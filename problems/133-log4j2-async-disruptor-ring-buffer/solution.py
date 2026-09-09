import json
import sys

LEVEL_SEVERITY = {
    "DEBUG": 1,
    "INFO": 2,
    "WARN": 3,
    "ERROR": 4
}

def solve(data):
    logger_type = data.get("logger_type", "SYNC_LOGGER")
    disk_io_latency_ms = data.get("disk_io_latency_ms", 10)
    events = data.get("log_events", [])
    
    # Sort events by timestamp_ms if not already sorted
    events = sorted(events, key=lambda x: x.get("timestamp_ms", 0))
    
    worker_latencies = []
    max_worker_blocked = 0
    written_logs = []
    discarded_logs = []
    
    if logger_type == "SYNC_LOGGER":
        # Synchronous logger: single synchronized lock on appender
        lock_available_time = 0
        
        for ev in events:
            t_id = ev.get("thread_id", "main")
            req_time = ev.get("timestamp_ms", 0)
            level = ev.get("level", "INFO")
            
            start_write = max(req_time, lock_available_time)
            finish_write = start_write + disk_io_latency_ms
            lock_available_time = finish_write
            
            blocked_time = finish_write - req_time
            worker_latencies.append(blocked_time)
            max_worker_blocked = max(max_worker_blocked, blocked_time)
            
            written_logs.append({
                "event_id": ev["event_id"],
                "thread_id": t_id,
                "level": level,
                "written_at_ms": finish_write,
                "blocked_ms": blocked_time
            })
            
        peak_buffer_usage = 0
        batch_flushes = len(written_logs)
        overflow_policy = "NONE"
        
    elif logger_type == "ASYNC_DISRUPTOR":
        buffer_size = data.get("buffer_size", 16)
        overflow_policy = data.get("overflow_policy", "BLOCK")
        discard_threshold_pct = data.get("discard_threshold_pct", 75)
        discard_below_level = data.get("discard_below_level", "WARN")
        batch_flush_size = data.get("batch_flush_size", 8)
        
        threshold_count = int(buffer_size * (discard_threshold_pct / 100.0))
        min_retained_severity = LEVEL_SEVERITY.get(discard_below_level, 3)
        
        ring_buffer = [] # list of (enqueue_time, ev_dict)
        consumer_available_time = 0
        peak_buffer_usage = 0
        batch_flushes = 0
        
        def advance_consumer_completed(current_time):
            nonlocal consumer_available_time, batch_flushes, ring_buffer
            while ring_buffer:
                first_item_time = ring_buffer[0][0]
                start_time = max(first_item_time, consumer_available_time)
                finish_time = start_time + disk_io_latency_ms
                if finish_time <= current_time:
                    # Batch can be fully written before or at current_time
                    batch = []
                    while ring_buffer and len(batch) < batch_flush_size and ring_buffer[0][0] <= start_time:
                        batch.append(ring_buffer.pop(0))
                    if not batch and ring_buffer:
                        batch.append(ring_buffer.pop(0))
                    consumer_available_time = finish_time
                    batch_flushes += 1
                    for enq_t, ev_item in batch:
                        written_logs.append({
                            "event_id": ev_item["event_id"],
                            "thread_id": ev_item["thread_id"],
                            "level": ev_item.get("level", "INFO"),
                            "written_at_ms": finish_time,
                            "blocked_ms": ev_item.get("worker_blocked_ms", 0)
                        })
                else:
                    break

        def force_consumer_drain_one_batch():
            nonlocal consumer_available_time, batch_flushes, ring_buffer
            if not ring_buffer:
                return
            first_item_time = ring_buffer[0][0]
            start_time = max(first_item_time, consumer_available_time)
            finish_time = start_time + disk_io_latency_ms
            batch = []
            while ring_buffer and len(batch) < batch_flush_size:
                batch.append(ring_buffer.pop(0))
            consumer_available_time = finish_time
            batch_flushes += 1
            for enq_t, ev_item in batch:
                written_logs.append({
                    "event_id": ev_item["event_id"],
                    "thread_id": ev_item["thread_id"],
                    "level": ev_item.get("level", "INFO"),
                    "written_at_ms": finish_time,
                    "blocked_ms": ev_item.get("worker_blocked_ms", 0)
                })
                
        for ev in events:
            req_time = ev.get("timestamp_ms", 0)
            level = ev.get("level", "INFO")
            sev = LEVEL_SEVERITY.get(level, 2)
            
            # 1. Advance consumer for batches completed by req_time
            advance_consumer_completed(req_time)
            
            curr_buffer_len = len(ring_buffer)
            peak_buffer_usage = max(peak_buffer_usage, curr_buffer_len)
            
            # 2. Check DISCARD_LOW_PRIORITY
            if overflow_policy == "DISCARD_LOW_PRIORITY" and curr_buffer_len >= threshold_count and sev < min_retained_severity:
                discarded_logs.append({
                    "event_id": ev["event_id"],
                    "thread_id": ev["thread_id"],
                    "level": level,
                    "reason": "DISCARDED_RING_BUFFER_PRESSURE"
                })
                worker_latencies.append(0)
                continue
                
            # 3. Check buffer full
            if curr_buffer_len >= buffer_size:
                if overflow_policy == "BLOCK" or (overflow_policy == "DISCARD_LOW_PRIORITY" and sev >= min_retained_severity):
                    # Force consumer to drain until there is room
                    while len(ring_buffer) >= buffer_size:
                        force_consumer_drain_one_batch()
                    blocked_ms = max(0, consumer_available_time - req_time)
                    ev_copy = dict(ev)
                    ev_copy["worker_blocked_ms"] = blocked_ms
                    worker_latencies.append(blocked_ms)
                    max_worker_blocked = max(max_worker_blocked, blocked_ms)
                    ring_buffer.append((consumer_available_time, ev_copy))
                    peak_buffer_usage = max(peak_buffer_usage, len(ring_buffer))
                elif overflow_policy == "SYNCHRONOUS_FALLBACK":
                    # Caller runs
                    direct_start = max(req_time, consumer_available_time)
                    direct_finish = direct_start + disk_io_latency_ms
                    consumer_available_time = direct_finish
                    blocked_ms = direct_finish - req_time
                    worker_latencies.append(blocked_ms)
                    max_worker_blocked = max(max_worker_blocked, blocked_ms)
                    written_logs.append({
                        "event_id": ev["event_id"],
                        "thread_id": ev["thread_id"],
                        "level": level,
                        "written_at_ms": direct_finish,
                        "blocked_ms": blocked_ms
                    })
            else:
                # Room available! CAS write takes ~0ms
                ev_copy = dict(ev)
                ev_copy["worker_blocked_ms"] = 0
                worker_latencies.append(0)
                ring_buffer.append((req_time, ev_copy))
                peak_buffer_usage = max(peak_buffer_usage, len(ring_buffer))
                
        # Drain all remaining items in ring buffer
        while ring_buffer:
            force_consumer_drain_one_batch()
            
    avg_latency = round(sum(worker_latencies) / len(worker_latencies), 2) if worker_latencies else 0.0
    
    if logger_type == "SYNC_LOGGER":
        verdict = "SYNC_LOGGING_THREAD_STARVATION" if max_worker_blocked >= 50 else "SYNC_LOGGING_ACCEPTABLE"
    else:
        if discarded_logs:
            verdict = "ASYNC_DISCARD_UNDER_BURST"
        elif max_worker_blocked >= 50:
            verdict = "ASYNC_RING_BUFFER_OVERFLOW_BLOCKED"
        else:
            verdict = "ASYNC_HIGH_THROUGHPUT_OPTIMAL"
            
    summary = {
        "logger_type": logger_type,
        "overflow_policy": overflow_policy,
        "total_log_events": len(events),
        "written_logs": len(written_logs),
        "discarded_logs": len(discarded_logs),
        "max_worker_blocked_ms": max_worker_blocked,
        "avg_worker_latency_ms": avg_latency,
        "peak_buffer_usage": peak_buffer_usage,
        "batch_flushes": batch_flushes,
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary,
        "discarded_details": discarded_logs,
        "written_logs_sample": written_logs[:10]
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            sys.exit(0)
        input_data = json.loads(raw_input)
        result = solve(input_data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
