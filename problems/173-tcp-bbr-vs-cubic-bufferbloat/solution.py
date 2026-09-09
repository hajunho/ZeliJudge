import json
import sys
from typing import Dict, List, Any

class NetworkPipe:
    def __init__(self, btl_bw: int, rt_prop: int, router_buffer_max: int):
        self.btl_bw = btl_bw              # bytes per tick
        self.rt_prop = rt_prop            # ticks
        self.router_buffer_max = router_buffer_max  # bytes
        self.router_queue = 0             # current bytes in buffer
        self.bdp = btl_bw * rt_prop       # Bandwidth-Delay Product

    def get_current_rtt(self) -> float:
        queue_delay = self.router_queue / self.btl_bw if self.btl_bw > 0 else 0.0
        return self.rt_prop + queue_delay

class TcpEngine:
    def __init__(self, config: Dict[str, Any]):
        net_cfg = config.get("network", {})
        self.pipe = NetworkPipe(
            btl_bw=net_cfg.get("btl_bw_bytes_per_tick", 10000),
            rt_prop=net_cfg.get("rt_prop_ticks", 5),
            router_buffer_max=net_cfg.get("router_buffer_max_bytes", 150000)
        )

        sender_cfg = config.get("sender", {})
        self.algorithm = sender_cfg.get("algorithm", "BBR")
        self.cwnd = float(sender_cfg.get("initial_cwnd_bytes", 10000))
        self.ssthresh = float(sender_cfg.get("ssthresh_bytes", 65536))
        self.in_flight = 0

        # BBR Specific State
        self.bbr_state = "STARTUP" # STARTUP, DRAIN, PROBE_BW
        self.btl_bw_est = float(self.cwnd)
        self.rt_prop_est = float(self.pipe.rt_prop)
        self.pacing_gain = 2.89
        self.cwnd_gain = 2.0
        self.probe_bw_idx = 0
        self.cycle_tick = 0
        self.pacing_cycle = sender_cfg.get("pacing_gain_cycle", [1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])

        # Global Counters
        self.total_sent = 0
        self.total_delivered = 0
        self.total_dropped = 0
        self.peak_queue = 0
        self.rtt_records = []
        self.timeline = []

    def step_cubic(self, tick: int, app_data: int) -> Dict[str, Any]:
        can_send = max(0, int(self.cwnd) - self.in_flight)
        to_send = min(app_data, can_send)
        self.in_flight += to_send
        self.total_sent += to_send

        # Router buffering
        dropped = 0
        if self.pipe.router_queue + to_send > self.pipe.router_buffer_max:
            overflow = (self.pipe.router_queue + to_send) - self.pipe.router_buffer_max
            accepted = to_send - overflow
            dropped = overflow
            self.pipe.router_queue = self.pipe.router_buffer_max
        else:
            self.pipe.router_queue += to_send

        self.total_dropped += dropped
        if self.pipe.router_queue > self.peak_queue:
            self.peak_queue = self.pipe.router_queue

        # Destination drain
        drained = min(self.pipe.router_queue, self.pipe.btl_bw)
        self.pipe.router_queue -= drained
        self.total_delivered += drained
        self.in_flight = max(0, self.in_flight - drained)

        cur_rtt = self.pipe.get_current_rtt()
        self.rtt_records.append(cur_rtt)

        # CUBIC Window adjustments
        if dropped > 0:
            self.ssthresh = max(float(self.pipe.bdp), self.cwnd * 0.7)
            self.cwnd = max(float(self.pipe.btl_bw), self.cwnd * 0.7)
            event = "LOSS_MULTIPLICATIVE_DECREASE"
        else:
            if self.cwnd < self.ssthresh:
                self.cwnd += min(to_send, self.pipe.btl_bw)
                event = "SLOW_START_EXPONENTIAL"
            else:
                self.cwnd += max(100.0, float(self.pipe.btl_bw) * 0.1)
                event = "CONGESTION_AVOIDANCE_GROWTH"

        return {
            "tick": tick,
            "algorithm": "CUBIC",
            "state": "ACTIVE",
            "to_send_bytes": to_send,
            "delivered_bytes": drained,
            "dropped_bytes": dropped,
            "cwnd_bytes": int(self.cwnd),
            "in_flight_bytes": self.in_flight,
            "router_queue_bytes": self.pipe.router_queue,
            "rtt_ticks": round(cur_rtt, 2),
            "event": event
        }

    def step_bbr(self, tick: int, app_data: int) -> Dict[str, Any]:
        # Target cwnd based on estimated BDP
        bdp_est = self.btl_bw_est * self.rt_prop_est
        self.cwnd = max(bdp_est * self.cwnd_gain, float(self.pipe.btl_bw) * 2.0)

        # Pacing rate calculation
        pacing_rate = int(self.btl_bw_est * self.pacing_gain)
        can_send = max(0, min(pacing_rate, int(self.cwnd) - self.in_flight))
        to_send = min(app_data, can_send)
        self.in_flight += to_send
        self.total_sent += to_send

        # Router buffering
        dropped = 0
        if self.pipe.router_queue + to_send > self.pipe.router_buffer_max:
            overflow = (self.pipe.router_queue + to_send) - self.pipe.router_buffer_max
            dropped = overflow
            self.pipe.router_queue = self.pipe.router_buffer_max
        else:
            self.pipe.router_queue += to_send

        self.total_dropped += dropped
        if self.pipe.router_queue > self.peak_queue:
            self.peak_queue = self.pipe.router_queue

        # Destination drain
        drained = min(self.pipe.router_queue, self.pipe.btl_bw)
        self.pipe.router_queue -= drained
        self.total_delivered += drained
        self.in_flight = max(0, self.in_flight - drained)

        cur_rtt = self.pipe.get_current_rtt()
        self.rtt_records.append(cur_rtt)

        # Update estimates
        if drained > 0:
            self.btl_bw_est = max(self.btl_bw_est, float(drained))
        self.rt_prop_est = min(self.rt_prop_est, cur_rtt)

        # BBR State Machine transitions
        event = f"BBR_{self.bbr_state}"
        if self.bbr_state == "STARTUP":
            if self.pipe.router_queue > 0:
                self.bbr_state = "DRAIN"
                self.pacing_gain = 1.0 / 2.89
                self.cwnd_gain = 1.0
                event = "BBR_STARTUP_TO_DRAIN"
        elif self.bbr_state == "DRAIN":
            if self.pipe.router_queue == 0:
                self.bbr_state = "PROBE_BW"
                self.probe_bw_idx = 0
                self.cycle_tick = 0
                self.pacing_gain = self.pacing_cycle[self.probe_bw_idx]
                self.cwnd_gain = 2.0
                event = "BBR_DRAIN_TO_PROBE_BW"
        elif self.bbr_state == "PROBE_BW":
            self.cycle_tick += 1
            if self.cycle_tick >= max(2, int(self.rt_prop_est)):
                self.cycle_tick = 0
                self.probe_bw_idx = (self.probe_bw_idx + 1) % len(self.pacing_cycle)
                self.pacing_gain = self.pacing_cycle[self.probe_bw_idx]
                event = f"BBR_PROBE_BW_CYCLE_{self.probe_bw_idx}"

        return {
            "tick": tick,
            "algorithm": "BBR",
            "state": self.bbr_state,
            "to_send_bytes": to_send,
            "delivered_bytes": drained,
            "dropped_bytes": dropped,
            "cwnd_bytes": int(self.cwnd),
            "in_flight_bytes": self.in_flight,
            "router_queue_bytes": self.pipe.router_queue,
            "rtt_ticks": round(cur_rtt, 2),
            "pacing_gain": round(self.pacing_gain, 2),
            "event": event
        }

    def run(self, workload: List[Dict[str, Any]]) -> Dict[str, Any]:
        for w in workload:
            t = w.get("tick", len(self.timeline) + 1)
            app_bytes = w.get("app_data_bytes", 0)
            if self.algorithm == "CUBIC":
                res = self.step_cubic(t, app_bytes)
            else:
                res = self.step_bbr(t, app_bytes)
            self.timeline.append(res)

        peak_rtt = max(self.rtt_records) if self.rtt_records else float(self.pipe.rt_prop)
        avg_rtt = sum(self.rtt_records) / len(self.rtt_records) if self.rtt_records else float(self.pipe.rt_prop)
        bufferbloat_ratio = peak_rtt / float(self.pipe.rt_prop) if self.pipe.rt_prop > 0 else 1.0
        loss_rate = self.total_dropped / self.total_sent if self.total_sent > 0 else 0.0

        if self.total_dropped > 0:
            verdict = "PACKET_LOSS_TAIL_DROP"
        elif bufferbloat_ratio >= 2.0:
            verdict = "SEVERE_BUFFERBLOAT_DETECTED"
        elif self.algorithm == "BBR" and bufferbloat_ratio < 1.8:
            verdict = "OPTIMAL_BBR_RATE_PACING"
        else:
            verdict = "LINE_RATE_CONFORMANT"

        return {
            "status": "SUCCESS",
            "algorithm": self.algorithm,
            "summary": {
                "btl_bw_bytes_per_tick": self.pipe.btl_bw,
                "rt_prop_ticks": self.pipe.rt_prop,
                "bdp_bytes": self.pipe.bdp,
                "router_buffer_max_bytes": self.pipe.router_buffer_max
            },
            "metrics": {
                "total_sent_bytes": self.total_sent,
                "total_delivered_bytes": self.total_delivered,
                "total_dropped_bytes": self.total_dropped,
                "peak_router_queue_bytes": self.peak_queue,
                "peak_rtt_ticks": round(peak_rtt, 2),
                "average_rtt_ticks": round(avg_rtt, 2),
                "bufferbloat_ratio": round(bufferbloat_ratio, 2),
                "packet_loss_rate": round(loss_rate, 4),
                "verdict": verdict
            },
            "sample_timeline": self.timeline[:20]
        }

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    engine = TcpEngine(input_data)
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
