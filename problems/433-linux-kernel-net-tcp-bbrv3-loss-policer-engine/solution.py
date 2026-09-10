# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #433 Solution:
Linux Kernel Networking: TCP BBRv3 Congestion Control, ECN Scaling & Policer-Aware Loss Headroom Engine
(net/ipv4/tcp_bbr.c, Linux Kernel 6.x+, IETF draft-ietf-ccwg-bbr-00)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class BbrV3Engine:
    def __init__(self, config):
        self.mss = config.get("mss", 1460)
        self.min_rtt_win_ms = config.get("min_rtt_win_ms", 10000)
        self.loss_headroom = config.get("loss_headroom", 0.02)
        self.ecn_alpha_gain = config.get("ecn_alpha_gain", 0.0625)
        self.policer_rtt_ratio_thresh = config.get("policer_rtt_ratio_thresh", 1.15)
        
        self.state = "PROBE_BW"
        self.probe_bw_phase = "CRUISE"
        self.min_rtt = config.get("initial_rtt_ms", 50.0)
        self.max_bw = config.get("initial_bw_bytes_per_ms", 1000.0)
        self.pacing_gain = 1.0
        self.cwnd_gain = 2.0
        
        self.ecn_alpha = 0.0
        self.policer_detected = False
        self.policed_rate = None
        
        self.total_bytes_delivered = 0
        self.total_loss_bytes = 0
        self.total_ecn_bytes = 0
        self.bbr_state_transitions = 0
        self.policer_events = 0
        self.ecn_backoff_events = 0
        self.loss_backoff_events = 0

    def _update_gains(self):
        if self.state == "STARTUP":
            self.pacing_gain = 2.885
            self.cwnd_gain = 2.885
        elif self.state == "DRAIN":
            self.pacing_gain = 0.35
            self.cwnd_gain = 2.0
        elif self.state == "PROBE_RTT":
            self.pacing_gain = 1.0
            self.cwnd_gain = 0.5
        elif self.state == "PROBE_BW":
            self.cwnd_gain = 2.0
            if self.probe_bw_phase == "UP":
                self.pacing_gain = 1.25
            elif self.probe_bw_phase == "DOWN":
                self.pacing_gain = 0.75
            elif self.probe_bw_phase == "CRUISE":
                self.pacing_gain = 1.0
            elif self.probe_bw_phase == "REFILL":
                self.pacing_gain = 1.0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "ACK_EVENT":
            return self._ack_event(cmd)
        elif op == "PHASE_STEP":
            return self._phase_step(cmd)
        elif op == "FORCE_STATE":
            return self._force_state(cmd)
        elif op == "GET_STATUS":
            return self._get_status(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _ack_event(self, cmd):
        bytes_del = cmd.get("bytes_delivered", 0)
        rtt_ms = cmd.get("rtt_ms", self.min_rtt)
        loss_bytes = cmd.get("loss_bytes", 0)
        ecn_bytes = cmd.get("ecn_bytes", 0)
        
        self.total_bytes_delivered += bytes_del
        self.total_loss_bytes += loss_bytes
        self.total_ecn_bytes += ecn_bytes
        
        if rtt_ms < self.min_rtt or self.min_rtt <= 0:
            self.min_rtt = rtt_ms

        curr_rate = bytes_del / max(1.0, rtt_ms)
        if curr_rate > self.max_bw:
            self.max_bw = curr_rate

        total_pkt_bytes = bytes_del + loss_bytes
        loss_rate = loss_bytes / max(1.0, total_pkt_bytes)

        if loss_rate > 0.10 and (rtt_ms / self.min_rtt) <= self.policer_rtt_ratio_thresh:
            if not self.policer_detected:
                self.policer_detected = True
                self.policer_events += 1
                self.policed_rate = curr_rate
                self.max_bw = min(self.max_bw, curr_rate)

        loss_penalty = 0.0
        if loss_rate > self.loss_headroom:
            self.loss_backoff_events += 1
            excess_loss = loss_rate - self.loss_headroom
            loss_penalty = min(0.5, excess_loss * 2.0)
            self.max_bw = self.max_bw * (1.0 - (loss_penalty * 0.5))

        ecn_fraction = ecn_bytes / max(1.0, bytes_del)
        self.ecn_alpha = (1.0 - self.ecn_alpha_gain) * self.ecn_alpha + (self.ecn_alpha_gain * ecn_fraction)
        if ecn_fraction > 0.05:
            self.ecn_backoff_events += 1

        bdp = self.max_bw * self.min_rtt
        pacing_rate = self.max_bw * self.pacing_gain
        
        ecn_damping = 1.0 - (self.ecn_alpha * 0.5)
        raw_cwnd = bdp * self.cwnd_gain * ecn_damping
        min_cwnd = 4 * self.mss
        final_cwnd = int(max(min_cwnd, raw_cwnd))

        return {
            "op": "ACK_EVENT",
            "state": self.state,
            "phase": self.probe_bw_phase if self.state == "PROBE_BW" else "N/A",
            "min_rtt_ms": round(self.min_rtt, 2),
            "max_bw_kbps": round((self.max_bw * 8), 2),
            "pacing_rate": round(pacing_rate, 2),
            "cwnd_bytes": final_cwnd,
            "loss_rate": round(loss_rate, 4),
            "loss_penalty": round(loss_penalty, 4),
            "ecn_alpha": round(self.ecn_alpha, 4),
            "policer_detected": self.policer_detected
        }

    def _phase_step(self, cmd):
        if self.state == "PROBE_BW":
            if self.probe_bw_phase == "UP":
                self.probe_bw_phase = "DOWN"
            elif self.probe_bw_phase == "DOWN":
                self.probe_bw_phase = "CRUISE"
            elif self.probe_bw_phase == "CRUISE":
                self.probe_bw_phase = "REFILL"
            elif self.probe_bw_phase == "REFILL":
                self.probe_bw_phase = "UP"
            self._update_gains()
            self.bbr_state_transitions += 1
            return {
                "op": "PHASE_STEP",
                "status": "PHASE_TRANSITIONED",
                "state": self.state,
                "phase": self.probe_bw_phase,
                "pacing_gain": self.pacing_gain
            }
        return {"op": "PHASE_STEP", "status": "NOT_IN_PROBE_BW"}

    def _force_state(self, cmd):
        new_state = cmd["state"]
        self.state = new_state
        if new_state == "PROBE_BW":
            self.probe_bw_phase = cmd.get("phase", "CRUISE")
        self._update_gains()
        self.bbr_state_transitions += 1
        return {
            "op": "FORCE_STATE",
            "status": "STATE_FORCED",
            "state": self.state,
            "phase": self.probe_bw_phase if self.state == "PROBE_BW" else "N/A",
            "pacing_gain": self.pacing_gain,
            "cwnd_gain": self.cwnd_gain
        }

    def _get_status(self, cmd):
        bdp = self.max_bw * self.min_rtt
        return {
            "op": "GET_STATUS",
            "state": self.state,
            "phase": self.probe_bw_phase if self.state == "PROBE_BW" else "N/A",
            "min_rtt": round(self.min_rtt, 2),
            "max_bw": round(self.max_bw, 2),
            "pacing_gain": self.pacing_gain,
            "cwnd_gain": self.cwnd_gain,
            "bdp": round(bdp, 2),
            "ecn_alpha": round(self.ecn_alpha, 4),
            "policer_detected": self.policer_detected,
            "policed_rate": round(self.policed_rate, 2) if self.policed_rate else None
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "final_state": self.state,
            "final_min_rtt": round(self.min_rtt, 2),
            "final_max_bw": round(self.max_bw, 2),
            "policer_detected": self.policer_detected,
            "total_bytes_delivered": self.total_bytes_delivered,
            "total_loss_bytes": self.total_loss_bytes,
            "total_ecn_bytes": self.total_ecn_bytes,
            "bbr_state_transitions": self.bbr_state_transitions,
            "policer_events": self.policer_events,
            "ecn_backoff_events": self.ecn_backoff_events,
            "loss_backoff_events": self.loss_backoff_events
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = BbrV3Engine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
