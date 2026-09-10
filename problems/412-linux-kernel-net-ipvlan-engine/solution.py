import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class IPVLANSimulation:
    def __init__(self, config):
        self.mode = config.get("mode", "L2")  # "L2", "L3", "L3S"
        self.master_mac = config.get("master_mac", "02:42:ac:11:00:01")
        self.host_ip = config.get("host_ip", "10.0.0.1")
        
        self.slaves = {}
        self.ip_to_slave = {}
        self.netfilter_rules = {}
        
        self.forwarded_ingress_packets = 0
        self.forwarded_egress_packets = 0
        self.hairpin_local_switched_packets = 0
        self.dropped_packets = 0
        self.netfilter_inspected_packets = 0
        self.packet_history = []
        self.event_logs = []

    def register_slave(self, current_time, slave_id, netns_id, ip_addr):
        self.slaves[slave_id] = {
            "slave_id": slave_id,
            "netns": netns_id,
            "ip": ip_addr
        }
        self.ip_to_slave[ip_addr] = slave_id
        if netns_id not in self.netfilter_rules:
            self.netfilter_rules[netns_id] = []
        self.event_logs.append({
            "time": current_time,
            "event": "REGISTER_SLAVE",
            "slave_id": slave_id,
            "netns": netns_id,
            "ip": ip_addr
        })

    def unregister_slave(self, current_time, slave_id):
        if slave_id in self.slaves:
            ip = self.slaves[slave_id]["ip"]
            del self.slaves[slave_id]
            if ip in self.ip_to_slave:
                del self.ip_to_slave[ip]
            self.event_logs.append({
                "time": current_time,
                "event": "UNREGISTER_SLAVE",
                "slave_id": slave_id
            })

    def set_netfilter_rule(self, current_time, netns_id, chain, action, match_ip=None, target_ip=None):
        if netns_id not in self.netfilter_rules:
            self.netfilter_rules[netns_id] = []
        rule = {
            "chain": chain,
            "action": action,
            "match_ip": match_ip,
            "target_ip": target_ip
        }
        self.netfilter_rules[netns_id].append(rule)
        self.event_logs.append({
            "time": current_time,
            "event": "SET_NETFILTER_RULE",
            "netns": netns_id,
            "chain": chain,
            "action": action
        })

    def _apply_netfilter(self, netns_id, chain, pkt):
        rules = self.netfilter_rules.get(netns_id, [])
        for r in rules:
            if r["chain"] == chain:
                if r["match_ip"] is None or r["match_ip"] == pkt["dst_ip"]:
                    if r["action"] == "DROP":
                        return "DROP", pkt
                    elif r["action"] == "DNAT":
                        pkt["dst_ip"] = r["target_ip"]
                        return "DNAT", pkt
        return "ACCEPT", pkt

    def ingress_packet(self, current_time, src_mac, dst_mac, src_ip, dst_ip, proto, payload_len):
        pkt = {
            "src_mac": src_mac,
            "dst_mac": dst_mac,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "proto": proto,
            "payload_len": payload_len
        }
        
        is_broadcast = (dst_mac.upper() == "FF:FF:FF:FF:FF:FF")
        if not is_broadcast and dst_mac.lower() != self.master_mac.lower():
            self.dropped_packets += 1
            self.packet_history.append({
                "time": current_time,
                "direction": "INGRESS",
                "status": "DROPPED",
                "reason": "DROP_INVALID_MAC",
                "src_ip": src_ip,
                "dst_ip": dst_ip
            })
            return

        if is_broadcast:
            if self.mode == "L2":
                delivered_slaves = sorted(list(self.slaves.keys()))
                self.forwarded_ingress_packets += len(delivered_slaves)
                self.packet_history.append({
                    "time": current_time,
                    "direction": "INGRESS",
                    "status": "DELIVERED_BROADCAST",
                    "mode": self.mode,
                    "delivered_slaves": delivered_slaves
                })
            else:
                self.dropped_packets += 1
                self.packet_history.append({
                    "time": current_time,
                    "direction": "INGRESS",
                    "status": "DROPPED",
                    "reason": "L3_NO_BROADCAST",
                    "mode": self.mode
                })
            return

        if dst_ip in self.ip_to_slave:
            slave_id = self.ip_to_slave[dst_ip]
            slave = self.slaves[slave_id]
            netns_id = slave["netns"]
            
            if self.mode == "L3S":
                self.netfilter_inspected_packets += 1
                verdict, pkt = self._apply_netfilter(netns_id, "PRE_ROUTING", pkt)
                if verdict == "DROP":
                    self.dropped_packets += 1
                    self.packet_history.append({
                        "time": current_time,
                        "direction": "INGRESS",
                        "status": "DROPPED",
                        "reason": "NETFILTER_DROP",
                        "slave_id": slave_id,
                        "netns": netns_id
                    })
                    return

            self.forwarded_ingress_packets += 1
            self.packet_history.append({
                "time": current_time,
                "direction": "INGRESS",
                "status": "DELIVERED_SLAVE",
                "slave_id": slave_id,
                "netns": netns_id,
                "mode": self.mode,
                "src_ip": src_ip,
                "dst_ip": pkt["dst_ip"]
            })
        elif dst_ip == self.host_ip:
            self.forwarded_ingress_packets += 1
            self.packet_history.append({
                "time": current_time,
                "direction": "INGRESS",
                "status": "DELIVERED_HOST",
                "dst_ip": dst_ip
            })
        else:
            self.dropped_packets += 1
            self.packet_history.append({
                "time": current_time,
                "direction": "INGRESS",
                "status": "DROPPED",
                "reason": "DROP_NO_ROUTE",
                "dst_ip": dst_ip
            })

    def egress_packet(self, current_time, src_slave_id, dst_ip, proto, payload_len):
        if src_slave_id not in self.slaves:
            self.dropped_packets += 1
            return
            
        src_slave = self.slaves[src_slave_id]
        src_ip = src_slave["ip"]
        src_netns = src_slave["netns"]
        
        pkt = {
            "src_slave_id": src_slave_id,
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "proto": proto,
            "payload_len": payload_len
        }
        
        if self.mode == "L3S":
            self.netfilter_inspected_packets += 1
            verdict, pkt = self._apply_netfilter(src_netns, "POST_ROUTING", pkt)
            if verdict == "DROP":
                self.dropped_packets += 1
                self.packet_history.append({
                    "time": current_time,
                    "direction": "EGRESS",
                    "status": "DROPPED",
                    "reason": "NETFILTER_DROP",
                    "src_slave_id": src_slave_id
                })
                return

        effective_dst_ip = pkt["dst_ip"]
        if effective_dst_ip in self.ip_to_slave:
            dst_slave_id = self.ip_to_slave[effective_dst_ip]
            dst_slave = self.slaves[dst_slave_id]
            dst_netns = dst_slave["netns"]
            
            if self.mode == "L3S":
                self.netfilter_inspected_packets += 1
                verdict, pkt = self._apply_netfilter(dst_netns, "PRE_ROUTING", pkt)
                if verdict == "DROP":
                    self.dropped_packets += 1
                    self.packet_history.append({
                        "time": current_time,
                        "direction": "HAIRPIN",
                        "status": "DROPPED",
                        "reason": "NETFILTER_DROP",
                        "src_slave_id": src_slave_id,
                        "dst_slave_id": dst_slave_id
                    })
                    return
                    
            self.hairpin_local_switched_packets += 1
            self.packet_history.append({
                "time": current_time,
                "direction": "HAIRPIN",
                "status": "DELIVERED_SLAVE",
                "src_slave_id": src_slave_id,
                "dst_slave_id": dst_slave_id,
                "mode": self.mode,
                "src_ip": src_ip,
                "dst_ip": pkt["dst_ip"]
            })
        else:
            self.forwarded_egress_packets += 1
            self.packet_history.append({
                "time": current_time,
                "direction": "EGRESS",
                "status": "TRANSMITTED_WIRE",
                "src_slave_id": src_slave_id,
                "master_mac": self.master_mac,
                "src_ip": src_ip,
                "dst_ip": pkt["dst_ip"]
            })

    def run_trace(self, trace):
        for ev in trace:
            ev_type = ev.get("type")
            t = ev.get("time", 0)
            if ev_type == "REGISTER_SLAVE":
                self.register_slave(t, ev["slave_id"], ev["netns_id"], ev["ip_addr"])
            elif ev_type == "UNREGISTER_SLAVE":
                self.unregister_slave(t, ev["slave_id"])
            elif ev_type == "SET_NETFILTER_RULE":
                self.set_netfilter_rule(t, ev["netns_id"], ev["chain"], ev["action"], ev.get("match_ip"), ev.get("target_ip"))
            elif ev_type == "INGRESS_PACKET":
                self.ingress_packet(t, ev["src_mac"], ev["dst_mac"], ev["src_ip"], ev["dst_ip"], ev.get("proto", "TCP"), ev.get("payload_len", 64))
            elif ev_type == "EGRESS_PACKET":
                self.egress_packet(t, ev["slave_id"], ev["dst_ip"], ev.get("proto", "TCP"), ev.get("payload_len", 64))

    def get_result(self):
        return {
            "summary": {
                "mode": self.mode,
                "forwarded_ingress_packets": self.forwarded_ingress_packets,
                "forwarded_egress_packets": self.forwarded_egress_packets,
                "hairpin_local_switched_packets": self.hairpin_local_switched_packets,
                "dropped_packets": self.dropped_packets,
                "netfilter_inspected_packets": self.netfilter_inspected_packets,
                "active_slaves_count": len(self.slaves)
            },
            "active_slaves": self.slaves,
            "packet_history": self.packet_history,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    sim = IPVLANSimulation(config)
    sim.run_trace(trace)
    result = sim.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
