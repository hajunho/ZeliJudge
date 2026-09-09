#!/usr/bin/env python3
"""
ZeliJudge Problem #203: 카프카 컨슈머 흐름 제어: max.poll.interval.ms 타임아웃 리밸런스 폭풍 vs Pause/Resume 리액티브 백프레셔
Solution Implementation
"""
import sys
import json

def simulate(input_data):
    cfg = input_data.get("consumer_config", {})
    mode = cfg.get("mode", "reactive_pause_resume")
    max_poll_interval_ms = cfg.get("max_poll_interval_ms", 5000.0)
    poll_batch_size = cfg.get("poll_batch_size", 50)
    buffer_capacity = cfg.get("buffer_capacity", 200)
    high_watermark = cfg.get("high_watermark", 150)
    low_watermark = cfg.get("low_watermark", 50)

    steps = input_data.get("steps", [])

    total_records_fetched = 0
    total_records_processed = 0
    rebalances_count = 0
    pause_events_count = 0
    resume_events_count = 0
    oom_crashes_count = 0
    peak_buffer_size = 0
    max_poll_lag_ms = 0.0

    current_buffer = 0
    is_paused = False
    last_poll_time_ms = 0.0
    current_time_ms = 0.0
    broker_remaining = 0

    for step in steps:
        step_time = step.get("timestamp_ms", current_time_ms)
        broker_remaining += step.get("broker_records", 0)
        delay_per_record = step.get("downstream_delay_per_record_ms", 5.0)

        current_time_ms = max(current_time_ms, step_time)

        if mode == "naive_blocking":
            if broker_remaining > 0:
                fetch_count = min(poll_batch_size, broker_remaining)
                broker_remaining -= fetch_count
                total_records_fetched += fetch_count

                interval_since_last_poll = current_time_ms - last_poll_time_ms
                max_poll_lag_ms = max(max_poll_lag_ms, interval_since_last_poll)
                last_poll_time_ms = current_time_ms

                processing_time = fetch_count * delay_per_record
                current_time_ms += processing_time
                total_records_processed += fetch_count

                time_until_next_poll = processing_time
                if time_until_next_poll > max_poll_interval_ms:
                    rebalances_count += 1
                max_poll_lag_ms = max(max_poll_lag_ms, time_until_next_poll)
            else:
                interval = current_time_ms - last_poll_time_ms
                if interval > max_poll_interval_ms and last_poll_time_ms > 0:
                    rebalances_count += 1
                max_poll_lag_ms = max(max_poll_lag_ms, interval)
                last_poll_time_ms = current_time_ms

        elif mode == "naive_unbounded_buffer":
            if broker_remaining > 0:
                fetch_count = min(poll_batch_size, broker_remaining)
                broker_remaining -= fetch_count
                total_records_fetched += fetch_count
                current_buffer += fetch_count
                peak_buffer_size = max(peak_buffer_size, current_buffer)
                last_poll_time_ms = current_time_ms

            drain_capacity = max(1, int(1000.0 / max(1.0, delay_per_record)))
            processed = min(current_buffer, drain_capacity)
            current_buffer -= processed
            total_records_processed += processed

            if current_buffer > buffer_capacity:
                oom_crashes_count += 1

        elif mode == "reactive_pause_resume":
            if not is_paused:
                if broker_remaining > 0 and current_buffer < buffer_capacity:
                    space_left = buffer_capacity - current_buffer
                    fetch_count = min(poll_batch_size, broker_remaining, space_left)
                    broker_remaining -= fetch_count
                    total_records_fetched += fetch_count
                    current_buffer += fetch_count
                    peak_buffer_size = max(peak_buffer_size, current_buffer)
                    last_poll_time_ms = current_time_ms

                    if current_buffer >= high_watermark:
                        is_paused = True
                        pause_events_count += 1
            else:
                last_poll_time_ms = current_time_ms

            drain_capacity = max(1, int(1000.0 / max(1.0, delay_per_record)))
            processed = min(current_buffer, drain_capacity)
            current_buffer -= processed
            total_records_processed += processed

            if is_paused and current_buffer <= low_watermark:
                is_paused = False
                resume_events_count += 1

            peak_buffer_size = max(peak_buffer_size, current_buffer)

    if oom_crashes_count > 0:
        status = "CONSUMER_UNBOUNDED_BUFFER_OOM_CRASH"
    elif rebalances_count > 0:
        status = "CONSUMER_REBALANCE_STORM_COLLAPSE"
    else:
        status = "OPTIMAL_KAFKA_PAUSE_RESUME_BACKPRESSURE"

    root_causes = {
        "CONSUMER_REBALANCE_STORM_COLLAPSE": (
            f"카프카 컨슈머 리밸런스 폭풍 참사: 동기식 블로킹 처리 도중 다운스트림 지연으로 poll() 호출 간격이 "
            f"{int(max_poll_lag_ms)}ms에 달해 max.poll.interval.ms({int(max_poll_interval_ms)}ms)를 초과, "
            f"코디네이터에 의해 컨슈머가 강제 퇴출되며 총 {rebalances_count}회의 리밸런스 폭풍 발생."
        ),
        "CONSUMER_UNBOUNDED_BUFFER_OOM_CRASH": (
            f"무제한 인메모리 버퍼링 OOM 연쇄 크래시 참사: 다운스트림 병목 상황에서 백프레셔 없이 poll()을 강행하여 "
            f"인메모리 버퍼가 상한선({buffer_capacity}건)을 초과 돌파(피크 {peak_buffer_size}건)하며 OOM 강제 피살 발생."
        ),
        "OPTIMAL_KAFKA_PAUSE_RESUME_BACKPRESSURE": (
            f"카프카 Pause/Resume 리액티브 백프레셔 최적화 완수: High Watermark({high_watermark}건) 도달 시 "
            f"consumer.pause()로 유입을 차단하고 poll(0) 하트비트를 유지({pause_events_count}회 일시정지, {resume_events_count}회 재개), "
            f"Low Watermark({low_watermark}건) 회복 시 자동 재개하여 리밸런스 0건 및 피크 버퍼 {peak_buffer_size}/{buffer_capacity} 안정 운용."
        )
    }

    return {
        "status": status,
        "metrics": {
            "total_records_fetched": total_records_fetched,
            "total_records_processed": total_records_processed,
            "rebalances_count": rebalances_count,
            "pause_events_count": pause_events_count,
            "resume_events_count": resume_events_count,
            "oom_crashes_count": oom_crashes_count,
            "peak_buffer_size": peak_buffer_size,
            "max_poll_lag_ms": round(max_poll_lag_ms, 1),
            "unprocessed_backlog": broker_remaining + current_buffer
        },
        "root_cause_analysis": root_causes.get(status, "")
    }

def main():
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            return
        input_data = json.loads(raw_input)
        result = simulate(input_data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
