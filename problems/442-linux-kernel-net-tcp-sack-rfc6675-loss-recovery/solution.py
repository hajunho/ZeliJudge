# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #442 Solution:
Linux Kernel Networking: net/ipv4/tcp_input.c TCP SACK RFC 6675 Scoreboard & Pipe Loss Recovery Engine
(net/ipv4/tcp_input.c, include/net/tcp.h, RFC 6675)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class TcpSackRecoveryEngine:
    def __init__(self, config):
        self.mss = config.get("mss", 1000)
        self.dupthresh = config.get("dupthresh", 3)
        self.cwnd = config.get("initial_cwnd", 10 * self.mss)
        self.ssthresh = config.get("initial_ssthresh", 20 * self.mss)
        
        self.snd_una = 10000
        self.snd_nxt = 10000
        self.high_seq = 10000
        self.in_fast_recovery = False
        
        self.packets = []
        
        self.fast_recovery_entries = 0
        self.packets_marked_lost = 0
        self.fast_retransmits = 0
        self.recovery_completions = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "TRANSMIT_NEW":
            return self._transmit_new(cmd)
        elif op == "RECEIVE_ACK":
            return self._receive_ack(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _transmit_new(self, cmd):
        length = cmd.get("len", self.mss)
        seq = self.snd_nxt
        self.snd_nxt += length
        
        pkt = {
            "seq": seq,
            "len": length,
            "state": "UNSACKED",
            "retransmitted": False
        }
        self.packets.append(pkt)
        
        return {
            "op": "TRANSMIT_NEW",
            "seq": seq,
            "len": length,
            "snd_nxt": self.snd_nxt,
            "status": "TRANSMITTED"
        }

    def _receive_ack(self, cmd):
        ack_seq = cmd["ack_seq"]
        sack_blocks = cmd.get("sack_blocks", [])
        
        self.snd_una = max(self.snd_una, ack_seq)
        
        retained = []
        for p in self.packets:
            if p["seq"] + p["len"] <= ack_seq:
                continue
            retained.append(p)
        self.packets = retained
        
        if self.in_fast_recovery and self.snd_una >= self.high_seq:
            self.in_fast_recovery = False
            self.cwnd = self.ssthresh
            self.recovery_completions += 1
            recovery_status = "RECOVERY_COMPLETED"
        else:
            recovery_status = "IN_FLIGHT"
            
        for p in self.packets:
            for blk in sack_blocks:
                b_start, b_end = blk[0], blk[1]
                if b_start <= p["seq"] and (p["seq"] + p["len"]) <= b_end:
                    p["state"] = "SACKED"
                    
        for p in self.packets:
            if p["state"] == "SACKED":
                continue
            sacked_after = 0
            for p_after in self.packets:
                if p_after["seq"] > p["seq"] and p_after["state"] == "SACKED":
                    sacked_after += 1
            if sacked_after >= self.dupthresh:
                if p["state"] != "LOST":
                    p["state"] = "LOST"
                    self.packets_marked_lost += 1
                    
                    if not self.in_fast_recovery:
                        self.in_fast_recovery = True
                        self.high_seq = self.snd_nxt
                        self.ssthresh = max(2 * self.mss, self.cwnd // 2)
                        self.cwnd = self.ssthresh
                        self.fast_recovery_entries += 1
                        recovery_status = "ENTERED_FAST_RECOVERY"

        unacked_bytes = sum(p["len"] for p in self.packets)
        sacked_bytes = sum(p["len"] for p in self.packets if p["state"] == "SACKED")
        lost_bytes = sum(p["len"] for p in self.packets if p["state"] == "LOST")
        retrans_bytes = sum(p["len"] for p in self.packets if p["retransmitted"] and p["state"] != "SACKED")
        pipe = unacked_bytes - sacked_bytes - lost_bytes + retrans_bytes
        
        retransmitted_pkt = None
        if self.in_fast_recovery and pipe < self.cwnd:
            for p in self.packets:
                if p["state"] == "LOST" and not p["retransmitted"]:
                    p["retransmitted"] = True
                    self.fast_retransmits += 1
                    retransmitted_pkt = p["seq"]
                    pipe += p["len"]
                    break

        return {
            "op": "RECEIVE_ACK",
            "ack_seq": ack_seq,
            "in_fast_recovery": self.in_fast_recovery,
            "pipe": pipe,
            "cwnd": self.cwnd,
            "ssthresh": self.ssthresh,
            "retransmitted_seq": retransmitted_pkt,
            "status": recovery_status
        }

    def _get_stats(self, cmd):
        return {
            "op": "GET_STATS",
            "snd_una": self.snd_una,
            "snd_nxt": self.snd_nxt,
            "high_seq": self.high_seq,
            "in_fast_recovery": self.in_fast_recovery,
            "cwnd": self.cwnd,
            "ssthresh": self.ssthresh,
            "unacked_packets": len(self.packets),
            "fast_recovery_entries": self.fast_recovery_entries,
            "packets_marked_lost": self.packets_marked_lost,
            "fast_retransmits": self.fast_retransmits,
            "recovery_completions": self.recovery_completions
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "snd_una": self.snd_una,
            "snd_nxt": self.snd_nxt,
            "in_fast_recovery": self.in_fast_recovery,
            "cwnd": self.cwnd,
            "ssthresh": self.ssthresh,
            "fast_recovery_entries": self.fast_recovery_entries,
            "packets_marked_lost": self.packets_marked_lost,
            "fast_retransmits": self.fast_retransmits,
            "recovery_completions": self.recovery_completions
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = TcpSackRecoveryEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
