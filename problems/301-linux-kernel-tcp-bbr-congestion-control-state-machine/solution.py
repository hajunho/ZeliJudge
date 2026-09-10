# -*- coding: utf-8 -*-
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class BBRState:
    STARTUP = "STARTUP"
    DRAIN = "DRAIN"
    PROBE_BW = "PROBE_BW"
    PROBE_RTT = "PROBE_RTT"

class TCPBBREngine:
    PROBE_BW_GAINS = [1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

    def __init__(self, config=None):
        config = config or {}
        self.mss = config.get("mss", 1460)
        self.bw_window_len = config.get("bw_window", 10)
        self.rtprop_win_ms = config.get("rtprop_win_ms", 10000)
        self.min_pipe_cwnd_pkts = 4

        self.state = BBRState.STARTUP
        self.pacing_gain = 2.89
        self.cwnd_gain = 2.89
        self.probe_bw_idx = 0

        self.btlbw_samples = []
        self.rtprop_ms = float("inf")
        self.rtprop_stamp_ms = 0
        self.full_bw = 0
        self.full_bw_count = 0
        self.current_time_ms = 0

        self.stats = {
            "state_transitions": [],
            "samples_processed": 0,
            "bbr_cycles": 0
        }
        self.history = []

    def get_btlbw(self):
        return max(self.btlbw_samples) if self.btlbw_samples else 0

    def update_filters(self, delivery_rate_bps, rtt_ms):
        self.btlbw_samples.append(delivery_rate_bps)
        if len(self.btlbw_samples) > self.bw_window_len:
            self.btlbw_samples.pop(0)

        if rtt_ms < self.rtprop_ms or (self.current_time_ms - self.rtprop_stamp_ms > self.rtprop_win_ms):
            self.rtprop_ms = rtt_ms
            self.rtprop_stamp_ms = self.current_time_ms

    def check_startup_done(self):
        cur_bw = self.get_btlbw()
        if cur_bw >= self.full_bw * 1.25:
            self.full_bw = cur_bw
            self.full_bw_count = 0
        else:
            self.full_bw_count += 1
            if self.full_bw_count >= 3:
                self.transition_to(BBRState.DRAIN)

    def transition_to(self, new_state):
        old_state = self.state
        self.state = new_state
        self.stats["state_transitions"].append({
            "time_ms": self.current_time_ms,
            "from": old_state,
            "to": new_state
        })

        if new_state == BBRState.DRAIN:
            self.pacing_gain = 1.0 / 2.89
            self.cwnd_gain = 2.89
        elif new_state == BBRState.PROBE_BW:
            self.probe_bw_idx = 0
            self.pacing_gain = self.PROBE_BW_GAINS[0]
            self.cwnd_gain = 2.0
        elif new_state == BBRState.PROBE_RTT:
            self.pacing_gain = 1.0
            self.cwnd_gain = 1.0

    def step(self, sample):
        time_ms = sample.get("time_ms", self.current_time_ms)
        self.current_time_ms = time_ms
        delivery_rate_bps = sample.get("delivery_rate_bps", 0)
        rtt_ms = sample.get("rtt_ms", 10.0)

        self.update_filters(delivery_rate_bps, rtt_ms)
        self.stats["samples_processed"] += 1

        if self.state == BBRState.STARTUP:
            self.check_startup_done()

        elif self.state == BBRState.DRAIN:
            bdp_bytes = (self.get_btlbw() * (self.rtprop_ms / 1000.0)) / 8.0
            inflight_bytes = sample.get("inflight_bytes", bdp_bytes)
            if inflight_bytes <= bdp_bytes:
                self.transition_to(BBRState.PROBE_BW)

        elif self.state == BBRState.PROBE_BW:
            if sample.get("round_trip_done", False):
                self.probe_bw_idx = (self.probe_bw_idx + 1) % len(self.PROBE_BW_GAINS)
                self.pacing_gain = self.PROBE_BW_GAINS[self.probe_bw_idx]
                if self.probe_bw_idx == 0:
                    self.stats["bbr_cycles"] += 1

            if self.current_time_ms - self.rtprop_stamp_ms > self.rtprop_win_ms:
                self.transition_to(BBRState.PROBE_RTT)

        elif self.state == BBRState.PROBE_RTT:
            if sample.get("probe_rtt_done", False):
                self.rtprop_stamp_ms = self.current_time_ms
                self.transition_to(BBRState.PROBE_BW)

        btlbw = self.get_btlbw()
        rtprop_s = (self.rtprop_ms / 1000.0) if self.rtprop_ms != float("inf") else 0.01
        bdp_bytes = int((btlbw * rtprop_s) / 8.0)
        pacing_rate_bps = int(self.pacing_gain * btlbw)

        if self.state == BBRState.PROBE_RTT:
            cwnd_bytes = self.min_pipe_cwnd_pkts * self.mss
        else:
            cwnd_bytes = max(int(self.cwnd_gain * bdp_bytes), self.min_pipe_cwnd_pkts * self.mss)

        res = {
            "time_ms": time_ms,
            "state": self.state,
            "pacing_gain": round(self.pacing_gain, 3),
            "btlbw_bps": btlbw,
            "rtprop_ms": round(self.rtprop_ms, 2) if self.rtprop_ms != float("inf") else None,
            "bdp_bytes": bdp_bytes,
            "pacing_rate_bps": pacing_rate_bps,
            "cwnd_bytes": cwnd_bytes
        }
        self.history.append(res)
        return res

    def process_samples(self, samples):
        for s in samples:
            self.step(s)
        return {
            "history": self.history,
            "stats": self.stats,
            "final_state": {
                "state": self.state,
                "btlbw_bps": self.get_btlbw(),
                "rtprop_ms": self.rtprop_ms,
                "pacing_gain": round(self.pacing_gain, 3)
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    samples = data.get("samples", [])
    engine = TCPBBREngine(config)
    result = engine.process_samples(samples)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
