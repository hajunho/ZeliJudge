import sys
import json
import copy

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class DCTCPFlow:
    def __init__(self, flow_id, config):
        self.flow_id = flow_id
        self.cwnd = float(config.get("initial_cwnd", 10))
        self.ssthresh = float(config.get("initial_ssthresh", 100))
        self.g = float(config.get("g", 0.0625))
        self.mss = int(config.get("mss", 1460))
        self.min_cwnd = float(config.get("min_cwnd", 2))
        
        self.alpha = 0.0
        self.state = "SLOW_START" if self.cwnd < self.ssthresh else "CONGESTION_AVOIDANCE"
        
        self.rtt_bytes_total = 0
        self.rtt_bytes_ce = 0
        
        self.total_acks = 0
        self.total_ce_marked_acks = 0
        self.rtt_cycles = 0
        self.proportional_reductions = 0
        self.loss_events = 0
        
        self.rtt_logs = []

    def on_ack(self, current_time, bytes_acked, ce_marked=False):
        self.total_acks += 1
        self.rtt_bytes_total += bytes_acked
        if ce_marked:
            self.total_ce_marked_acks += 1
            self.rtt_bytes_ce += bytes_acked
            
        if self.cwnd < self.ssthresh:
            self.cwnd += (bytes_acked / self.mss)
            self.state = "SLOW_START"
        else:
            self.cwnd += (bytes_acked / self.mss) / self.cwnd
            self.state = "CONGESTION_AVOIDANCE"

    def on_rtt_completed(self, current_time):
        self.rtt_cycles += 1
        if self.rtt_bytes_total > 0:
            F = self.rtt_bytes_ce / self.rtt_bytes_total
        else:
            F = 0.0
            
        old_alpha = self.alpha
        old_cwnd = self.cwnd
        
        self.alpha = (1.0 - self.g) * self.alpha + self.g * F
        
        reduced = False
        if self.rtt_bytes_ce > 0:
            self.proportional_reductions += 1
            reduced = True
            reduction_factor = 1.0 - (self.alpha / 2.0)
            self.cwnd = max(self.min_cwnd, self.cwnd * reduction_factor)
            self.ssthresh = self.cwnd
            self.state = "CONGESTION_AVOIDANCE"
            
        log_entry = {
            "rtt_cycle": self.rtt_cycles,
            "time": current_time,
            "bytes_total": self.rtt_bytes_total,
            "bytes_ce": self.rtt_bytes_ce,
            "fraction_F": round(F, 4),
            "old_alpha": round(old_alpha, 4),
            "new_alpha": round(self.alpha, 4),
            "old_cwnd": round(old_cwnd, 4),
            "new_cwnd": round(self.cwnd, 4),
            "reduced": reduced
        }
        self.rtt_logs.append(log_entry)
        
        self.rtt_bytes_total = 0
        self.rtt_bytes_ce = 0

    def on_loss(self, current_time):
        self.loss_events += 1
        self.ssthresh = max(self.min_cwnd, self.cwnd / 2.0)
        self.cwnd = self.ssthresh
        self.state = "CONGESTION_AVOIDANCE"

class DCTCPEngine:
    def __init__(self, config):
        self.config = config
        self.flows = {}
        self.event_logs = []

    def init_flow(self, current_time, flow_id, initial_cwnd=10, initial_ssthresh=100):
        cfg = dict(self.config)
        cfg["initial_cwnd"] = initial_cwnd
        cfg["initial_ssthresh"] = initial_ssthresh
        self.flows[flow_id] = DCTCPFlow(flow_id, cfg)
        self.event_logs.append({
            "time": current_time,
            "event": "INIT_FLOW",
            "flow_id": flow_id,
            "initial_cwnd": initial_cwnd,
            "initial_ssthresh": initial_ssthresh
        })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            fid = ev.get("flow_id", 1)
            
            if ev_type == "INIT_FLOW":
                self.init_flow(t, fid, ev.get("initial_cwnd", 10), ev.get("initial_ssthresh", 100))
            elif ev_type == "ACK_EVENT":
                if fid not in self.flows:
                    self.init_flow(t, fid)
                self.flows[fid].on_ack(t, ev.get("bytes_acked", 1460), ev.get("ce_marked", False))
            elif ev_type == "RTT_WINDOW_COMPLETED":
                if fid in self.flows:
                    self.flows[fid].on_rtt_completed(t)
            elif ev_type == "PACKET_LOSS_EVENT":
                if fid in self.flows:
                    self.flows[fid].on_loss(t)

    def get_result(self):
        flow_results = {}
        for fid, fl in self.flows.items():
            flow_results[str(fid)] = {
                "flow_id": fid,
                "final_cwnd": round(fl.cwnd, 4),
                "final_ssthresh": round(fl.ssthresh, 4),
                "final_alpha": round(fl.alpha, 4),
                "state": fl.state,
                "total_acks": fl.total_acks,
                "total_ce_marked_acks": fl.total_ce_marked_acks,
                "rtt_cycles": fl.rtt_cycles,
                "proportional_reductions": fl.proportional_reductions,
                "loss_events": fl.loss_events,
                "rtt_logs": fl.rtt_logs
            }
            
        total_acks = sum(fl.total_acks for fl in self.flows.values())
        total_ce = sum(fl.total_ce_marked_acks for fl in self.flows.values())
        total_reductions = sum(fl.proportional_reductions for fl in self.flows.values())
        total_losses = sum(fl.loss_events for fl in self.flows.values())
        
        return {
            "summary": {
                "active_flows": len(self.flows),
                "total_acks": total_acks,
                "total_ce_marked_acks": total_ce,
                "total_proportional_reductions": total_reductions,
                "total_loss_events": total_losses
            },
            "flows": flow_results,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = DCTCPEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
