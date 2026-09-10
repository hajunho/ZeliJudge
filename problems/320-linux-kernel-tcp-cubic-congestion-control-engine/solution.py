import sys
import os
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class LinuxTcpCubicEngine:
    def __init__(self, config: dict):
        self.config = copy.deepcopy(config)
        self.mss = int(self.config.get("mss", 1460))
        self.c = float(self.config.get("c_scale", 0.4))
        self.beta = float(self.config.get("beta", 0.7))
        self.fast_convergence = bool(self.config.get("fast_convergence", True))
        self.tcp_friendliness = bool(self.config.get("tcp_friendliness", True))
        self.hystart_enabled = bool(self.config.get("hystart", True))

        self.state = self.config.get("initial_state", "SLOW_START")
        self.cwnd = float(self.config.get("init_cwnd", 10.0))
        self.ssthresh = float(self.config.get("init_ssthresh", 64.0))
        self.w_max = float(self.config.get("init_w_max", 0.0))
        self.w_last_max = float(self.config.get("init_w_last_max", 0.0))

        self.rtt_min = float(self.config.get("rtt_min_ms", 50.0)) / 1000.0
        self.current_rtt = self.rtt_min
        self.epoch_start_time = 0.0
        self.current_time = 0.0
        self.k = 0.0

        self.hystart_sample_count = 0
        self.hystart_detected = False

        self.stats = {
            "loss_events": 0,
            "timeout_events": 0,
            "hystart_exits": 0,
            "max_cwnd": round(self.cwnd, 2),
            "reno_friendly_count": 0,
            "convex_count": 0,
            "concave_count": 0,
            "equilibrium_count": 0
        }
        self.event_log = []

        if self.w_max > 0:
            self._recalculate_k()

    def _recalculate_k(self):
        diff = self.w_max * (1.0 - self.beta) / self.c
        if diff <= 0:
            self.k = 0.0
        else:
            self.k = round(diff ** (1.0 / 3.0), 4)

    def _get_region(self, t: float) -> str:
        delta = t - self.k
        if abs(delta) <= 0.15:
            return "EQUILIBRIUM"
        elif delta < 0:
            return "CONCAVE"
        else:
            return "CONVEX"

    def log(self, msg: str):
        self.event_log.append(msg)

    def process_ack(self, acked_packets: int, rtt_ms: float, time_advance_ms: float) -> dict:
        self.current_time = round(self.current_time + time_advance_ms / 1000.0, 4)
        rtt_sec = round(rtt_ms / 1000.0, 4)
        self.current_rtt = rtt_sec
        if rtt_sec < self.rtt_min:
            self.rtt_min = rtt_sec

        sub_mode = "NONE"
        region = "NONE"

        if self.state == "SLOW_START":
            if self.hystart_enabled and not self.hystart_detected:
                self.hystart_sample_count += acked_packets
                delay_thresh = min(max(self.rtt_min / 8.0, 0.002), 0.016)
                if self.hystart_sample_count >= 8 and (rtt_sec - self.rtt_min) >= delay_thresh:
                    self.hystart_detected = True
                    self.state = "CONGESTION_AVOIDANCE"
                    self.ssthresh = self.cwnd
                    self.w_max = self.cwnd
                    self.epoch_start_time = self.current_time
                    self._recalculate_k()
                    self.stats["hystart_exits"] += 1
                    self.log(f"HYSTART_TRIGGERED: delay spike {round((rtt_sec - self.rtt_min)*1000, 2)}ms >= {round(delay_thresh*1000, 2)}ms at cwnd={round(self.cwnd, 2)}")

            if self.state == "SLOW_START":
                self.cwnd = round(self.cwnd + acked_packets, 4)
                if self.cwnd >= self.ssthresh:
                    self.state = "CONGESTION_AVOIDANCE"
                    self.w_max = self.cwnd
                    self.epoch_start_time = self.current_time
                    self._recalculate_k()
                    self.log(f"SLOW_START_EXIT: reached ssthresh={self.ssthresh}, entering CONGESTION_AVOIDANCE")

        elif self.state == "CONGESTION_AVOIDANCE":
            t = max(0.0, round(self.current_time - self.epoch_start_time, 4))
            region = self._get_region(t)
            w_cubic = self.c * ((t - self.k) ** 3) + self.w_max

            w_target = w_cubic
            if self.tcp_friendliness:
                reno_coeff = (3.0 * (1.0 - self.beta)) / (1.0 + self.beta)
                w_est = self.w_max * self.beta + reno_coeff * (t / max(0.001, self.current_rtt))
                if w_cubic < w_est:
                    w_target = w_est
                    sub_mode = "RENO_FRIENDLY"
                    self.stats["reno_friendly_count"] += 1
                else:
                    sub_mode = "CUBIC_NATIVE"
            else:
                sub_mode = "CUBIC_NATIVE"

            if region == "CONCAVE":
                self.stats["concave_count"] += 1
            elif region == "CONVEX":
                self.stats["convex_count"] += 1
            elif region == "EQUILIBRIUM":
                self.stats["equilibrium_count"] += 1

            if w_target > self.cwnd:
                increment = (w_target - self.cwnd) * (acked_packets / max(1.0, self.cwnd))
                self.cwnd = round(self.cwnd + max(increment, acked_packets / max(1.0, self.cwnd)), 4)
            else:
                self.cwnd = round(self.cwnd + 0.01 * acked_packets, 4)

        if self.cwnd > self.stats["max_cwnd"]:
            self.stats["max_cwnd"] = round(self.cwnd, 2)

        res = {
            "op": "PROCESS_ACK",
            "time": round(self.current_time, 4),
            "state": self.state,
            "cwnd": round(self.cwnd, 4),
            "ssthresh": round(self.ssthresh, 4),
            "w_max": round(self.w_max, 4),
            "k": round(self.k, 4),
            "region": region,
            "sub_mode": sub_mode,
            "rtt_ms": round(rtt_ms, 2)
        }
        return res

    def process_loss(self, loss_type: str = "DUPLICATE_ACK") -> dict:
        self.stats["loss_events"] += 1
        curr_cwnd = self.cwnd

        if self.fast_convergence and curr_cwnd < self.w_last_max:
            self.w_last_max = curr_cwnd
            self.w_max = round(curr_cwnd * (1.0 + self.beta) / 2.0, 4)
            fast_conv_applied = True
        else:
            self.w_last_max = curr_cwnd
            self.w_max = round(curr_cwnd, 4)
            fast_conv_applied = False

        self.ssthresh = max(2.0, round(curr_cwnd * self.beta, 4))
        self.cwnd = self.ssthresh
        self.state = "CONGESTION_AVOIDANCE"
        self.epoch_start_time = self.current_time
        self._recalculate_k()

        self.log(f"LOSS_EVENT: type={loss_type} curr_cwnd={round(curr_cwnd, 2)} -> ssthresh={round(self.ssthresh, 2)} W_max={round(self.w_max, 2)} K={self.k} fast_conv={fast_conv_applied}")
        return {
            "op": "PROCESS_LOSS",
            "time": round(self.current_time, 4),
            "loss_type": loss_type,
            "fast_convergence": fast_conv_applied,
            "ssthresh": round(self.ssthresh, 4),
            "w_max": round(self.w_max, 4),
            "cwnd": round(self.cwnd, 4),
            "k": round(self.k, 4)
        }

    def process_timeout(self) -> dict:
        self.stats["timeout_events"] += 1
        curr_cwnd = self.cwnd
        self.ssthresh = max(2.0, round(curr_cwnd * self.beta, 4))
        self.cwnd = 1.0
        self.w_max = round(curr_cwnd, 4)
        self.w_last_max = round(curr_cwnd, 4)
        self.state = "SLOW_START"
        self.hystart_detected = False
        self.hystart_sample_count = 0
        self.epoch_start_time = self.current_time
        self._recalculate_k()

        self.log(f"RTO_TIMEOUT: cwnd={round(curr_cwnd, 2)} -> ssthresh={round(self.ssthresh, 2)}, cwnd reset to 1.0")
        return {
            "op": "PROCESS_TIMEOUT",
            "time": round(self.current_time, 4),
            "ssthresh": round(self.ssthresh, 4),
            "cwnd": 1.0,
            "state": self.state,
            "w_max": round(self.w_max, 4),
            "k": round(self.k, 4)
        }

    def get_state(self) -> dict:
        return {
            "op": "GET_STATE",
            "time": round(self.current_time, 4),
            "state": self.state,
            "cwnd": round(self.cwnd, 4),
            "ssthresh": round(self.ssthresh, 4),
            "w_max": round(self.w_max, 4),
            "k": round(self.k, 4),
            "rtt_min_ms": round(self.rtt_min * 1000.0, 2)
        }

    def get_final_summary(self) -> dict:
        return {
            "current_time": round(self.current_time, 4),
            "state": self.state,
            "cwnd": round(self.cwnd, 4),
            "ssthresh": round(self.ssthresh, 4),
            "w_max": round(self.w_max, 4),
            "k": round(self.k, 4),
            "rtt_min_ms": round(self.rtt_min * 1000.0, 2),
            "stats": self.stats,
            "event_count": len(self.event_log)
        }

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    eng = LinuxTcpCubicEngine(data["config"])
    results = []
    for op in data.get("operations", []):
        cmd = op["op"]
        if cmd == "PROCESS_ACK":
            res = eng.process_ack(
                acked_packets=op.get("acked_packets", 1),
                rtt_ms=op.get("rtt_ms", 50.0),
                time_advance_ms=op.get("time_advance_ms", 50.0)
            )
            results.append(res)
        elif cmd == "PROCESS_LOSS":
            res = eng.process_loss(loss_type=op.get("loss_type", "DUPLICATE_ACK"))
            results.append(res)
        elif cmd == "PROCESS_TIMEOUT":
            res = eng.process_timeout()
            results.append(res)
        elif cmd == "GET_STATE":
            res = eng.get_state()
            results.append(res)

    output = {
        "results": results,
        "final_summary": eng.get_final_summary()
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    solve()
