#!/usr/bin/env python3
"""
ZeliJudge Problem #202: 분산 추적(Distributed Tracing): OpenTelemetry Head-based vs Tail-based 샘플링과 트레이스 버퍼 메모리 제어
Solution Implementation
"""
import sys
import json

def simulate(input_data):
    cfg = input_data.get("collector_config", {})
    mode = cfg.get("mode", "head_based")
    head_sample_rate = cfg.get("head_sample_rate", 0.05)
    decision_wait_ms = cfg.get("decision_wait_ms", 3000.0)
    latency_threshold_ms = cfg.get("latency_threshold_ms", 1000.0)
    normal_sample_rate = cfg.get("normal_sample_rate", 0.05)
    max_buffer_traces = cfg.get("max_buffer_traces", 100)
    memory_limiter_enabled = cfg.get("memory_limiter_enabled", True)

    spans = input_data.get("spans", [])

    total_spans_received = len(spans)
    total_traces = 0
    sampled_traces_count = 0
    dropped_traces_count = 0
    error_traces_total = 0
    error_traces_captured = 0
    error_traces_lost = 0
    slow_traces_total = 0
    slow_traces_captured = 0
    slow_traces_lost = 0

    peak_buffer_traces = 0
    buffer_overflow_occurred = False

    if mode == "head_based":
        traces = {}
        for sp in spans:
            tid = sp["trace_id"]
            if tid not in traces:
                traces[tid] = []
            traces[tid].append(sp)

        total_traces = len(traces)

        for tid, t_spans in traces.items():
            is_error = any(s.get("status_code") == "ERROR" or s.get("http_status", 200) >= 500 for s in t_spans)
            trace_start = min(s.get("start_time_ms", 0) for s in t_spans)
            trace_end = max(s.get("end_time_ms", 0) for s in t_spans)
            total_duration = trace_end - trace_start

            is_slow = total_duration >= latency_threshold_ms

            if is_error:
                error_traces_total += 1
            if is_slow:
                slow_traces_total += 1

            root_span = t_spans[0]
            sampled = root_span.get("head_sampled", False)

            if sampled:
                sampled_traces_count += 1
                if is_error:
                    error_traces_captured += 1
                if is_slow:
                    slow_traces_captured += 1
            else:
                dropped_traces_count += 1
                if is_error:
                    error_traces_lost += 1
                if is_slow:
                    slow_traces_lost += 1

    else:
        traces_buffer = {}
        completed_decisions = {}

        sorted_spans = sorted(spans, key=lambda s: s.get("arrival_time_ms", s.get("start_time_ms", 0)))
        current_time_ms = 0.0

        for sp in sorted_spans:
            arr_time = sp.get("arrival_time_ms", sp.get("start_time_ms", 0))
            current_time_ms = max(current_time_ms, arr_time)
            tid = sp["trace_id"]

            if tid in completed_decisions:
                continue

            if tid not in traces_buffer:
                if len(traces_buffer) >= max_buffer_traces:
                    if not memory_limiter_enabled:
                        buffer_overflow_occurred = True
                    else:
                        oldest_tid = min(traces_buffer.keys(), key=lambda k: traces_buffer[k]["first_arrival_ms"])
                        t_data = traces_buffer.pop(oldest_tid)
                        t_spans = t_data["spans"]
                        is_error = any(s.get("status_code") == "ERROR" or s.get("http_status", 200) >= 500 for s in t_spans)
                        trace_start = min(s.get("start_time_ms", 0) for s in t_spans)
                        trace_end = max(s.get("end_time_ms", 0) for s in t_spans)
                        is_slow = (trace_end - trace_start) >= latency_threshold_ms

                        if is_error or is_slow:
                            sampled = True
                        else:
                            sampled = t_spans[0].get("tail_sample_override", False)
                        completed_decisions[oldest_tid] = {"sampled": sampled, "is_error": is_error, "is_slow": is_slow}

                traces_buffer[tid] = {
                    "spans": [],
                    "first_arrival_ms": arr_time,
                    "last_arrival_ms": arr_time
                }

            traces_buffer[tid]["spans"].append(sp)
            traces_buffer[tid]["last_arrival_ms"] = arr_time

            peak_buffer_traces = max(peak_buffer_traces, len(traces_buffer))

            ready_to_eval = []
            for b_tid, b_data in traces_buffer.items():
                if (current_time_ms - b_data["first_arrival_ms"]) >= decision_wait_ms:
                    ready_to_eval.append(b_tid)

            for e_tid in ready_to_eval:
                b_data = traces_buffer.pop(e_tid)
                t_spans = b_data["spans"]
                is_error = any(s.get("status_code") == "ERROR" or s.get("http_status", 200) >= 500 for s in t_spans)
                trace_start = min(s.get("start_time_ms", 0) for s in t_spans)
                trace_end = max(s.get("end_time_ms", 0) for s in t_spans)
                is_slow = (trace_end - trace_start) >= latency_threshold_ms

                if is_error or is_slow:
                    sampled = True
                else:
                    sampled = t_spans[0].get("tail_sample_override", False)

                completed_decisions[e_tid] = {"sampled": sampled, "is_error": is_error, "is_slow": is_slow}

        for rem_tid, b_data in traces_buffer.items():
            t_spans = b_data["spans"]
            is_error = any(s.get("status_code") == "ERROR" or s.get("http_status", 200) >= 500 for s in t_spans)
            trace_start = min(s.get("start_time_ms", 0) for s in t_spans)
            trace_end = max(s.get("end_time_ms", 0) for s in t_spans)
            is_slow = (trace_end - trace_start) >= latency_threshold_ms

            if is_error or is_slow:
                sampled = True
            else:
                sampled = t_spans[0].get("tail_sample_override", False)

            completed_decisions[rem_tid] = {"sampled": sampled, "is_error": is_error, "is_slow": is_slow}

        total_traces = len(completed_decisions)
        for tid, dec in completed_decisions.items():
            if dec["is_error"]:
                error_traces_total += 1
            if dec["is_slow"]:
                slow_traces_total += 1

            if dec["sampled"]:
                sampled_traces_count += 1
                if dec["is_error"]:
                    error_traces_captured += 1
                if dec["is_slow"]:
                    slow_traces_captured += 1
            else:
                dropped_traces_count += 1
                if dec["is_error"]:
                    error_traces_lost += 1
                if dec["is_slow"]:
                    slow_traces_lost += 1

    if buffer_overflow_occurred:
        status = "TRACE_BUFFER_OOM_COLLAPSE"
    elif mode == "head_based" and (error_traces_lost > 0 or slow_traces_lost > 0):
        status = "HEAD_BASED_SAMPLING_CRITICAL_TRACE_LOSS"
    else:
        status = "OPTIMAL_TAIL_BASED_SAMPLING_TUNED"

    sampling_ratio_pct = round((sampled_traces_count / max(1, total_traces)) * 100.0, 1)
    error_capture_pct = round((error_traces_captured / max(1, error_traces_total)) * 100.0, 1) if error_traces_total > 0 else 100.0
    slow_capture_pct = round((slow_traces_captured / max(1, slow_traces_total)) * 100.0, 1) if slow_traces_total > 0 else 100.0

    root_causes = {
        "HEAD_BASED_SAMPLING_CRITICAL_TRACE_LOSS": (
            f"헤드 기반 샘플링(Head-based Sampling) 치명적 트레이스 유실 참사: 인그레스 유입 시 확률적 샘플링({int(head_sample_rate*100)}%)으로 인해 "
            f"장애 분석에 핵심적인 에러 트레이스 {error_traces_lost}건({round(100 - error_capture_pct, 1)}%) 및 "
            f"고지연 트레이스 {slow_traces_lost}건이 분석도 되지 못한 채 앞단에서 영구 유실됨."
        ),
        "TRACE_BUFFER_OOM_COLLAPSE": (
            f"테일 기반 샘플링 버퍼 OOM 연쇄 붕괴 참사: 트래픽 급증 상황에서 메모리 리미터(memory_limiter)가 비활성화되어 "
            f"인메모리 트레이스 버퍼가 상한선({max_buffer_traces}개)을 초과 돌파({peak_buffer_traces}개 보관 시도)하며 OOM 강제 종료 발생."
        ),
        "OPTIMAL_TAIL_BASED_SAMPLING_TUNED": (
            f"OpenTelemetry 테일 기반 샘플링 최적화 완수: 평가 대기 윈도우({int(decision_wait_ms)}ms) 동안 지연 평가를 수행하여 "
            f"에러 트레이스 100%({error_traces_captured}/{error_traces_total}건) 및 고지연 트레이스 100%({slow_traces_captured}/{slow_traces_total}건) 수집 완수, "
            f"메모리 리미터 기반 버퍼 통제로 피크 버퍼 {peak_buffer_traces}/{max_buffer_traces} 안정 유지."
        )
    }

    return {
        "status": status,
        "metrics": {
            "total_spans_received": total_spans_received,
            "total_traces": total_traces,
            "sampled_traces_count": sampled_traces_count,
            "dropped_traces_count": dropped_traces_count,
            "sampling_ratio_pct": sampling_ratio_pct,
            "error_traces_total": error_traces_total,
            "error_traces_captured": error_traces_captured,
            "error_traces_lost": error_traces_lost,
            "error_capture_pct": error_capture_pct,
            "slow_traces_total": slow_traces_total,
            "slow_traces_captured": slow_traces_captured,
            "slow_traces_lost": slow_traces_lost,
            "slow_capture_pct": slow_capture_pct,
            "peak_buffer_traces": peak_buffer_traces
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
