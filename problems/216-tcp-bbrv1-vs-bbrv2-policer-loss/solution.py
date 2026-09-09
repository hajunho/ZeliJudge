import sys
import json
from collections import deque

def simulate_policer_tcp(data):
    config = data.get("config", {})
    algorithm = config.get("algorithm", "BBRV2")
    policer_rate_mbps = config.get("policer_rate_mbps", 100)
    bytes_per_us = (policer_rate_mbps * 1_000_000.0) / (8.0 * 1_000_000.0)

    bucket_capacity_bytes = config.get("policer_bucket_capacity_bytes", 15000)
    tokens_bytes = float(bucket_capacity_bytes)

    rtt_prop_us = config.get("rtt_prop_ms", 20.0) * 1000.0
    mss_bytes = config.get("mss_bytes", 1500)
    bdp_bytes = bytes_per_us * rtt_prop_us

    simulation_duration_us = config.get("simulation_duration_ms", 1000.0) * 1000.0

    cwnd = float(config.get("initial_cwnd_bytes", 10 * mss_bytes))
    ssthresh = float(bdp_bytes * 2)

    pacing_gain_cycle_v1 = [1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    bbr_cycle_idx = 0
    bbr_cycle_timer_us = 0.0
    btlbw_bytes_per_us = bytes_per_us
    inflight_hi = float(bdp_bytes * 2)
    bbrv2_policer_detected = False

    in_flight = 0
    in_flight_queue = deque()

    metrics = {
        "total_packets_sent": 0,
        "total_bytes_sent": 0,
        "total_bytes_delivered": 0,
        "total_bytes_dropped": 0,
        "packet_loss_rate_pct": 0.0,
        "average_throughput_mbps": 0.0,
        "bandwidth_utilization_pct": 0.0,
        "final_cwnd_bytes": 0,
        "policer_detected": False
    }

    current_time_us = 0.0
    window_sent_bytes = 0
    window_dropped_bytes = 0
    window_timer_us = 0.0
    next_send_time_us = 0.0

    while current_time_us < simulation_duration_us:
        next_event_time = next_send_time_us
        if in_flight_queue and in_flight_queue[0][0] < next_event_time:
            next_event_time = in_flight_queue[0][0]

        if next_event_time > current_time_us:
            elapsed = next_event_time - current_time_us
            tokens_bytes = min(float(bucket_capacity_bytes), tokens_bytes + bytes_per_us * elapsed)
            current_time_us = next_event_time
        else:
            elapsed = 1.0
            tokens_bytes = min(float(bucket_capacity_bytes), tokens_bytes + bytes_per_us * elapsed)
            current_time_us += elapsed

        delivered_this_tick = 0
        dropped_this_tick = 0
        while in_flight_queue and in_flight_queue[0][0] <= current_time_us:
            deliv_time, pkt_bytes, is_drop = in_flight_queue.popleft()
            in_flight -= pkt_bytes
            if is_drop:
                dropped_this_tick += pkt_bytes
                window_dropped_bytes += pkt_bytes
            else:
                delivered_this_tick += pkt_bytes
            window_sent_bytes += pkt_bytes

        if algorithm == "CUBIC":
            if dropped_this_tick > 0:
                ssthresh = max(2.0 * mss_bytes, cwnd * 0.7)
                cwnd = ssthresh
            elif delivered_this_tick > 0:
                if cwnd < ssthresh:
                    cwnd += mss_bytes
                else:
                    cwnd += (mss_bytes * mss_bytes) / cwnd

        elif algorithm == "BBRV1":
            bbr_cycle_timer_us += elapsed
            if bbr_cycle_timer_us >= rtt_prop_us:
                bbr_cycle_timer_us = 0.0
                bbr_cycle_idx = (bbr_cycle_idx + 1) % len(pacing_gain_cycle_v1)

        elif algorithm == "BBRV2":
            window_timer_us += elapsed
            if window_timer_us >= rtt_prop_us:
                loss_rate = (window_dropped_bytes / window_sent_bytes) if window_sent_bytes > 0 else 0.0
                if loss_rate > 0.02:
                    bbrv2_policer_detected = True
                    metrics["policer_detected"] = True
                    inflight_hi = max(float(bdp_bytes), float(in_flight))
                window_timer_us = 0.0
                window_sent_bytes = 0
                window_dropped_bytes = 0
                bbr_cycle_idx = (bbr_cycle_idx + 1) % len(pacing_gain_cycle_v1)

        can_send = False
        pacing_interval_us = (mss_bytes / bytes_per_us)

        if algorithm == "CUBIC":
            if in_flight + mss_bytes <= cwnd:
                can_send = True
                pacing_interval_us = (mss_bytes / (bytes_per_us * 1.5))
        elif algorithm == "BBRV1":
            gain = pacing_gain_cycle_v1[bbr_cycle_idx]
            current_rate = btlbw_bytes_per_us * gain
            pacing_interval_us = (mss_bytes / current_rate)
            can_send = True
        elif algorithm == "BBRV2":
            gain = pacing_gain_cycle_v1[bbr_cycle_idx]
            if bbrv2_policer_detected and gain > 1.0:
                gain = 1.0
            current_rate = btlbw_bytes_per_us * gain
            pacing_interval_us = (mss_bytes / current_rate)
            can_send = True

        if can_send and current_time_us >= next_send_time_us:
            next_send_time_us = current_time_us + pacing_interval_us
            pkt_size = mss_bytes
            metrics["total_packets_sent"] += 1
            metrics["total_bytes_sent"] += pkt_size
            in_flight += pkt_size

            if tokens_bytes >= pkt_size:
                tokens_bytes -= pkt_size
                metrics["total_bytes_delivered"] += pkt_size
                in_flight_queue.append((current_time_us + rtt_prop_us, pkt_size, False))
            else:
                metrics["total_bytes_dropped"] += pkt_size
                in_flight_queue.append((current_time_us + rtt_prop_us, pkt_size, True))

    dur_sec = simulation_duration_us / 1_000_000.0
    tput_mbps = (metrics["total_bytes_delivered"] * 8.0) / (dur_sec * 1_000_000.0)
    loss_rate = (metrics["total_bytes_dropped"] / metrics["total_bytes_sent"] * 100.0) if metrics["total_bytes_sent"] > 0 else 0.0
    util = (tput_mbps / policer_rate_mbps * 100.0) if policer_rate_mbps > 0 else 0.0

    metrics["average_throughput_mbps"] = round(tput_mbps, 2)
    metrics["packet_loss_rate_pct"] = round(loss_rate, 2)
    metrics["bandwidth_utilization_pct"] = round(min(100.0, util), 1)
    metrics["final_cwnd_bytes"] = int(cwnd)

    # Verdict Determination
    if algorithm == "CUBIC":
        if metrics["bandwidth_utilization_pct"] < 50.0:
            verdict = "CUBIC_LOSS_SENSITIVITY_THROUGHPUT_COLLAPSE"
            status = "FAILED"
        else:
            verdict = "NORMAL_CUBIC_FLOW"
            status = "SUCCESS"
    elif algorithm == "BBRV1":
        if metrics["packet_loss_rate_pct"] >= 2.5:
            verdict = "BBRV1_POLICER_EXCESSIVE_LOSS_RATE"
            status = "FAILED"
        else:
            verdict = "NORMAL_BBRV1_FLOW"
            status = "SUCCESS"
    elif algorithm == "BBRV2":
        if metrics["bandwidth_utilization_pct"] >= 85.0 and metrics["packet_loss_rate_pct"] < 2.0:
            verdict = "OPTIMAL_BBRV2_POLICER_CONGESTION_CONTROL"
            status = "SUCCESS"
        else:
            verdict = "BBRV2_SUBOPTIMAL_FLOW"
            status = "SUCCESS"
    else:
        verdict = "UNKNOWN_ALGORITHM"
        status = "FAILED"

    return {
        "status": status,
        "verdict": verdict,
        "algorithm": algorithm,
        "metrics": metrics
    }

def main():
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return
    data = json.loads(raw_input)
    result = simulate_policer_tcp(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
