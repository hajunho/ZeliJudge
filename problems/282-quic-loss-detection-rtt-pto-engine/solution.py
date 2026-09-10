import sys
import json

class QuicLossRecovery:
    def __init__(self, config=None):
        if config is None:
            config = {}
        self.k_packet_threshold = config.get("k_packet_threshold", 3)
        self.k_time_threshold_mult = config.get("k_time_threshold_mult", 9.0 / 8.0)
        self.k_granularity = config.get("k_granularity", 1.0)
        self.max_ack_delay = config.get("max_ack_delay", 25.0)
        
        self.latest_rtt = 0.0
        self.smoothed_rtt = None
        self.rttvar = None
        self.min_rtt = float('inf')
        
        self.pto_count = 0
        self.largest_acked_packet = -1
        
        self.sent_packets = {}
        self.lost_packets = []
        self.acked_packets = []
        
    def get_pto(self):
        if self.smoothed_rtt is None:
            base_pto = 333.0
        else:
            base_pto = self.smoothed_rtt + max(4.0 * self.rttvar, self.k_granularity) + self.max_ack_delay
        return base_pto * (2 ** self.pto_count)
        
    def on_packet_sent(self, pn, time_sent, bytes_sent, ack_eliciting=True):
        self.sent_packets[pn] = {
            "pn": pn,
            "time_sent": time_sent,
            "bytes": bytes_sent,
            "ack_eliciting": ack_eliciting
        }
        
    def update_rtt(self, latest_rtt, ack_delay):
        self.latest_rtt = latest_rtt
        if self.min_rtt == float('inf') or latest_rtt < self.min_rtt:
            self.min_rtt = latest_rtt
            
        if self.smoothed_rtt is None:
            self.smoothed_rtt = latest_rtt
            self.rttvar = latest_rtt / 2.0
            return
            
        ack_delay = min(ack_delay, self.max_ack_delay)
        adjusted_rtt = latest_rtt
        if latest_rtt >= self.min_rtt + ack_delay:
            adjusted_rtt = latest_rtt - ack_delay
            
        self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.smoothed_rtt - adjusted_rtt)
        self.smoothed_rtt = 0.875 * self.smoothed_rtt + 0.125 * adjusted_rtt
        
    def on_ack_received(self, t_now, largest_acked, ack_delay, ack_ranges):
        newly_acked = []
        for r_start, r_end in ack_ranges:
            for pn in range(r_start, r_end + 1):
                if pn in self.sent_packets:
                    newly_acked.append(self.sent_packets.pop(pn))
                    self.acked_packets.append(pn)
                    
        if not newly_acked:
            return {"newly_acked": [], "newly_lost": []}
            
        if largest_acked > self.largest_acked_packet:
            self.largest_acked_packet = largest_acked
            
        largest_acked_info = None
        for p in newly_acked:
            if p["pn"] == largest_acked:
                largest_acked_info = p
                break
                
        if largest_acked_info is not None:
            latest_rtt = t_now - largest_acked_info["time_sent"]
            self.update_rtt(latest_rtt, ack_delay)
            self.pto_count = 0
            
        newly_lost = self.detect_lost_packets(t_now)
        return {
            "newly_acked": [p["pn"] for p in newly_acked],
            "newly_lost": newly_lost
        }
        
    def detect_lost_packets(self, t_now):
        if self.smoothed_rtt is None:
            loss_delay = self.k_time_threshold_mult * self.k_granularity
        else:
            loss_delay = self.k_time_threshold_mult * max(self.latest_rtt, self.smoothed_rtt)
        loss_delay = max(loss_delay, self.k_granularity)
        
        lost = []
        for pn in sorted(list(self.sent_packets.keys())):
            if pn > self.largest_acked_packet:
                continue
            p = self.sent_packets[pn]
            time_since_sent = t_now - p["time_sent"]
            
            packet_threshold_exceeded = (self.largest_acked_packet - pn >= self.k_packet_threshold)
            time_threshold_exceeded = (time_since_sent >= loss_delay)
            
            if packet_threshold_exceeded or time_threshold_exceeded:
                lost.append(pn)
                reason = "PACKET_THRESHOLD" if packet_threshold_exceeded else "TIME_THRESHOLD"
                p["loss_reason"] = reason
                self.lost_packets.append(pn)
                del self.sent_packets[pn]
                
        return lost

def solve():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    line = sys.stdin.read().strip()
    if not line:
        return
    req = json.loads(line)
    
    cfg = req.get("quic_config", {})
    q = QuicLossRecovery(cfg)
    
    logs = []
    stats = {
        "packets_sent": 0,
        "packets_acked": 0,
        "packets_lost_threshold": 0,
        "packets_lost_time": 0,
        "pto_events": 0,
        "rtt_updates": 0
    }
    
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        t = op_item["time"]
        
        if op == "PACKET_SENT":
            pn = op_item["pn"]
            bytes_sent = op_item.get("bytes", 1200)
            q.on_packet_sent(pn, t, bytes_sent)
            stats["packets_sent"] += 1
            logs.append({
                "step": step,
                "op": op,
                "time": t,
                "pn": pn,
                "bytes": bytes_sent,
                "in_flight_count": len(q.sent_packets)
            })
            
        elif op == "ACK_RECEIVED":
            largest_acked = op_item["largest_acked"]
            ack_delay = op_item.get("ack_delay", 0.0)
            ack_ranges = op_item["ack_ranges"]
            
            res = q.on_ack_received(t, largest_acked, ack_delay, ack_ranges)
            stats["packets_acked"] += len(res["newly_acked"])
            for l_pn in res["newly_lost"]:
                stats["packets_lost_threshold"] += 1
            if q.latest_rtt > 0:
                stats["rtt_updates"] += 1
                
            logs.append({
                "step": step,
                "op": op,
                "time": t,
                "largest_acked": largest_acked,
                "newly_acked": res["newly_acked"],
                "newly_lost": res["newly_lost"],
                "latest_rtt": round(q.latest_rtt, 4) if q.latest_rtt else None,
                "smoothed_rtt": round(q.smoothed_rtt, 4) if q.smoothed_rtt else None,
                "rttvar": round(q.rttvar, 4) if q.rttvar else None,
                "pto": round(q.get_pto(), 4)
            })
            
        elif op == "PTO_EXPIRED":
            q.pto_count += 1
            stats["pto_events"] += 1
            logs.append({
                "step": step,
                "op": op,
                "time": t,
                "pto_count": q.pto_count,
                "next_pto": round(q.get_pto(), 4),
                "status": "PROBE_TRIGGERED"
            })
            
    res = {
        "operations_log": logs,
        "final_state": {
            "smoothed_rtt": round(q.smoothed_rtt, 4) if q.smoothed_rtt else None,
            "rttvar": round(q.rttvar, 4) if q.rttvar else None,
            "min_rtt": round(q.min_rtt, 4) if q.min_rtt != float('inf') else None,
            "pto": round(q.get_pto(), 4),
            "unacked_pns": sorted(list(q.sent_packets.keys())),
            "total_lost_pns": sorted(q.lost_packets)
        },
        "statistics": stats
    }
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
