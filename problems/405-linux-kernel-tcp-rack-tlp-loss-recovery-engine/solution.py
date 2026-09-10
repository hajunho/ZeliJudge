import sys
import json
import math
import heapq

class Segment:
    def __init__(self, seq, send_time, is_retrans=False):
        self.seq = seq
        self.send_time = send_time
        self.is_retrans = is_retrans
        self.sacked = False
        self.acked = False
        self.lost = False

class RACKSimulation:
    def __init__(self, config):
        self.initial_cwnd = config.get("initial_cwnd", 10)
        self.initial_ssthresh = config.get("initial_ssthresh", 64)
        self.initial_srtt = config.get("initial_srtt_ms", 50)
        self.min_rto = config.get("min_rto_ms", 200)
        self.max_rto = config.get("max_rto_ms", 3000)
        self.enable_rack = config.get("enable_rack", True)
        self.enable_tlp = config.get("enable_tlp", True)
        self.dupthresh = config.get("dupthresh", 3)
        self.one_way_delay = config.get("one_way_delay_ms", 25)
        self.wdelay = config.get("wdelay_ms", 5)
        
        # State
        self.cwnd = self.initial_cwnd
        self.ssthresh = self.initial_ssthresh
        self.srtt = float(self.initial_srtt)
        self.rttvar = self.initial_srtt / 2.0
        self.rto = max(self.min_rto, self.srtt + 4 * self.rttvar)
        self.ca_state = "TCP_CA_Open"
        self.recovery_high = 0
        
        # RACK State
        self.rack_rtt = self.initial_srtt
        self.rack_reo_wnd = max(1.0, self.initial_srtt / 4.0)
        self.rack_reo_wnd_min = max(1.0, self.initial_srtt / 4.0)
        
        # Window & Packets
        self.snd_una = 1
        self.snd_nxt = 1
        self.packets = {}
        self.app_queue = []
        
        # Receiver state
        self.rcv_nxt = 1
        self.received_seqs = set()
        
        # Duplicate ACK tracking
        self.last_ack_seq = 1
        self.dupack_count = 0
        
        # Timers
        self.rto_time = None
        self.rto_gen = 0
        self.tlp_time = None
        self.tlp_gen = 0
        self.tlp_sent_without_ack = False
        
        # Events: (time, priority, counter, event_type, payload)
        self.events = []
        self.event_counter = 0
        self.current_time = 0.0
        
        # Fault injection maps
        self.drop_spec = []
        self.delay_packet_seqs = {}
        
        # Logs & Metrics
        self.retransmission_log = []
        self.state_transitions = []
        self.total_transmissions = 0
        self.fast_retransmissions = 0
        self.rto_retransmissions = 0
        self.tlp_probes_sent = 0
        self.tx_counts = {}

    def schedule_event(self, time, priority, event_type, payload=None):
        heapq.heappush(self.events, (round(time, 4), priority, self.event_counter, event_type, payload))
        self.event_counter += 1

    def inflight(self):
        cnt = 0
        for seq in range(self.snd_una, self.snd_nxt):
            if seq in self.packets:
                p = self.packets[seq]
                if not p.acked and not p.sacked:
                    cnt += 1
        return cnt

    def set_ca_state(self, new_state, reason=""):
        if self.ca_state != new_state:
            self.state_transitions.append({
                "time": round(self.current_time, 2),
                "from": self.ca_state,
                "to": new_state,
                "reason": reason,
                "cwnd": self.cwnd,
                "ssthresh": self.ssthresh
            })
            self.ca_state = new_state

    def arm_timers(self):
        inf = self.inflight()
        if inf == 0:
            self.rto_time = None
            self.tlp_time = None
            self.rto_gen += 1
            self.tlp_gen += 1
            return
        
        self.rto_gen += 1
        self.rto_time = self.current_time + self.rto
        self.schedule_event(self.rto_time, 3, "RTO_EXPIRE", self.rto_gen)
        
        if self.enable_tlp and self.ca_state == "TCP_CA_Open" and not self.tlp_sent_without_ack:
            pto = max(2.0 * self.srtt, 10.0) if inf > 1 else max(2.0 * self.srtt + self.wdelay, 10.0)
            self.tlp_gen += 1
            self.tlp_time = self.current_time + pto
            self.schedule_event(self.tlp_time, 2, "TLP_EXPIRE", self.tlp_gen)
        else:
            self.tlp_time = None
            self.tlp_gen += 1

    def try_send(self):
        while self.app_queue and self.inflight() < self.cwnd:
            seq = self.app_queue.pop(0)
            self.send_packet(seq, is_retrans=False)

    def send_packet(self, seq, is_retrans=False):
        seg = Segment(seq, self.current_time, is_retrans=is_retrans)
        self.packets[seq] = seg
        self.total_transmissions += 1
        self.tx_counts[seq] = self.tx_counts.get(seq, 0) + 1
        instance = self.tx_counts[seq]
        
        if seq >= self.snd_nxt:
            self.snd_nxt = seq + 1
        
        delay = self.one_way_delay
        if str(seq) in self.delay_packet_seqs:
            delay += self.delay_packet_seqs[str(seq)]
        elif seq in self.delay_packet_seqs:
            delay += self.delay_packet_seqs[seq]
        
        is_dropped = False
        for d in self.drop_spec:
            if d["seq"] == seq and d.get("instance", 1) == instance:
                is_dropped = True
                break
        
        if not is_dropped:
            arrival_time = self.current_time + delay
            self.schedule_event(arrival_time, 1, "PKT_ARRIVE_RCVR", (seq, self.current_time))
        
        self.arm_timers()

    def handle_receiver_arrival(self, payload):
        seq, send_time = payload
        self.received_seqs.add(seq)
        
        while self.rcv_nxt in self.received_seqs:
            self.rcv_nxt += 1
        
        higher_seqs = sorted([s for s in self.received_seqs if s > self.rcv_nxt])
        sacks = []
        if higher_seqs:
            start = higher_seqs[0]
            end = higher_seqs[0]
            for s in higher_seqs[1:]:
                if s == end + 1:
                    end = s
                else:
                    sacks.append((start, end))
                    start = s
                    end = s
            sacks.append((start, end))
        
        ack_payload = {
            "ack_seq": self.rcv_nxt,
            "sacks": sacks,
            "orig_send_time": send_time,
            "delivered_seq": seq
        }
        ack_arrival_time = self.current_time + self.one_way_delay
        self.schedule_event(ack_arrival_time, 0, "ACK_ARRIVE_SNDR", ack_payload)

    def handle_ack_arrival(self, payload):
        ack_seq = payload["ack_seq"]
        sacks = payload["sacks"]
        orig_send_time = payload["orig_send_time"]
        delivered_seq = payload["delivered_seq"]
        
        self.tlp_sent_without_ack = False
        
        sample_rtt = max(1.0, float(self.current_time - orig_send_time))
        self.rttvar = 0.75 * self.rttvar + 0.25 * abs(sample_rtt - self.srtt)
        self.srtt = 0.875 * self.srtt + 0.125 * sample_rtt
        self.rto = max(self.min_rto, self.srtt + 4 * self.rttvar)
        self.rack_rtt = sample_rtt
        
        if delivered_seq > self.snd_una:
            for s in range(self.snd_una, delivered_seq):
                if s in self.packets and not self.packets[s].acked and not self.packets[s].sacked:
                    self.rack_reo_wnd = min(self.srtt, self.rack_reo_wnd + self.rack_reo_wnd_min)
                    break
        
        new_data_acked = False
        if ack_seq > self.snd_una:
            new_data_acked = True
            for s in range(self.snd_una, ack_seq):
                if s in self.packets:
                    self.packets[s].acked = True
            self.snd_una = ack_seq
            self.dupack_count = 0
            self.last_ack_seq = ack_seq
        else:
            self.dupack_count += 1
            
        for start, end in sacks:
            for s in range(start, end + 1):
                if s in self.packets:
                    self.packets[s].sacked = True

        lost_seqs = []
        if self.enable_rack:
            for s in range(self.snd_una, self.snd_nxt):
                if s in self.packets:
                    p = self.packets[s]
                    if not p.acked and not p.sacked and not p.lost:
                        if s < delivered_seq or p.send_time < orig_send_time:
                            time_elapsed = self.current_time - p.send_time
                            if time_elapsed >= self.rack_rtt + self.rack_reo_wnd:
                                p.lost = True
                                lost_seqs.append(s)
        else:
            if self.dupack_count >= self.dupthresh:
                if self.snd_una in self.packets and not self.packets[self.snd_una].lost:
                    self.packets[self.snd_una].lost = True
                    lost_seqs.append(self.snd_una)

        if lost_seqs:
            if self.ca_state != "TCP_CA_Recovery":
                self.ssthresh = max(2, self.inflight() // 2)
                self.cwnd = self.ssthresh
                self.recovery_high = self.snd_nxt - 1
                self.set_ca_state("TCP_CA_Recovery", reason=f"Loss detected: {lost_seqs}")
            
            for s in lost_seqs:
                self.fast_retransmissions += 1
                self.retransmission_log.append({
                    "time": round(self.current_time, 2),
                    "seq": s,
                    "type": "FAST_RETRANS_RACK" if self.enable_rack else "FAST_RETRANS_DUPACK",
                    "cwnd": self.cwnd,
                    "ssthresh": self.ssthresh
                })
                self.send_packet(s, is_retrans=True)

        if self.ca_state == "TCP_CA_Recovery":
            if self.snd_una > self.recovery_high:
                self.set_ca_state("TCP_CA_Open", reason="Full ACK past recovery_high")
        elif self.ca_state == "TCP_CA_Loss":
            if self.snd_una > self.recovery_high:
                self.set_ca_state("TCP_CA_Open", reason="RTO recovery complete")
        elif self.ca_state == "TCP_CA_Open" and new_data_acked:
            if self.cwnd < self.ssthresh:
                self.cwnd += 1
            else:
                self.cwnd = round(self.cwnd + 1.0 / self.cwnd, 2)

        self.arm_timers()
        self.try_send()

    def handle_tlp_expire(self, gen):
        if gen != self.tlp_gen or self.inflight() == 0 or self.ca_state != "TCP_CA_Open" or self.tlp_sent_without_ack:
            return
        
        self.tlp_probes_sent += 1
        self.tlp_sent_without_ack = True
        probe_seq = None
        is_retrans = False
        if self.app_queue:
            probe_seq = self.app_queue.pop(0)
            is_retrans = False
        else:
            for s in range(self.snd_nxt - 1, self.snd_una - 1, -1):
                if s in self.packets and not self.packets[s].acked and not self.packets[s].sacked:
                    probe_seq = s
                    is_retrans = True
                    break
        
        if probe_seq is not None:
            self.retransmission_log.append({
                "time": round(self.current_time, 2),
                "seq": probe_seq,
                "type": "TLP_PROBE",
                "cwnd": self.cwnd,
                "ssthresh": self.ssthresh
            })
            self.send_packet(probe_seq, is_retrans=is_retrans)

    def handle_rto_expire(self, gen):
        if gen != self.rto_gen or self.inflight() == 0:
            return
        
        self.rto_retransmissions += 1
        self.ssthresh = max(2, self.inflight() // 2)
        self.cwnd = 1
        self.recovery_high = self.snd_nxt - 1
        self.set_ca_state("TCP_CA_Loss", reason="RTO timeout expired")
        self.rto = min(self.max_rto, self.rto * 2)
        self.tlp_sent_without_ack = False
        
        self.retransmission_log.append({
            "time": round(self.current_time, 2),
            "seq": self.snd_una,
            "type": "RTO_RETRANS",
            "cwnd": self.cwnd,
            "ssthresh": self.ssthresh
        })
        self.send_packet(self.snd_una, is_retrans=True)

    def run(self, total_packets, fault_config):
        self.app_queue = list(range(1, total_packets + 1))
        
        raw_drops = fault_config.get("drops", [])
        normalized_drops = []
        for d in raw_drops:
            if isinstance(d, int):
                normalized_drops.append({"seq": d, "instance": 1})
            elif isinstance(d, dict):
                normalized_drops.append(d)
        self.drop_spec = normalized_drops
        self.delay_packet_seqs = fault_config.get("delays", {})
        
        self.try_send()
        
        while self.events:
            time, priority, _, event_type, payload = heapq.heappop(self.events)
            self.current_time = time
            
            if event_type == "PKT_ARRIVE_RCVR":
                self.handle_receiver_arrival(payload)
            elif event_type == "ACK_ARRIVE_SNDR":
                self.handle_ack_arrival(payload)
            elif event_type == "TLP_EXPIRE":
                self.handle_tlp_expire(payload)
            elif event_type == "RTO_EXPIRE":
                self.handle_rto_expire(payload)
            
            if self.snd_una > total_packets and self.inflight() == 0:
                break
                
        return self.generate_result(total_packets)

    def generate_result(self, total_packets):
        return {
            "summary": {
                "total_simulation_time": round(self.current_time, 2),
                "total_packets": total_packets,
                "total_transmissions": self.total_transmissions,
                "fast_retransmissions": self.fast_retransmissions,
                "rto_retransmissions": self.rto_retransmissions,
                "tlp_probes_sent": self.tlp_probes_sent,
                "final_cwnd": self.cwnd,
                "final_ssthresh": self.ssthresh,
                "final_srtt_ms": round(self.srtt, 2),
                "final_rto_ms": round(self.rto, 2),
                "final_reo_wnd_ms": round(self.rack_reo_wnd, 2)
            },
            "retransmissions": self.retransmission_log,
            "state_transitions": self.state_transitions
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    workload = input_data.get("workload", {})
    total_packets = workload.get("total_packets", 10)
    fault_config = {
        "drops": workload.get("drops", []),
        "delays": workload.get("delays", {})
    }
    
    sim = RACKSimulation(config)
    result = sim.run(total_packets, fault_config)
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
