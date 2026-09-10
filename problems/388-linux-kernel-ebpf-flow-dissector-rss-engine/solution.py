# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #388: Linux Kernel eBPF Flow Dissector & RSS Hashing Engine
Implementation in Python 3.
"""
import sys
import json
import hashlib

def jhash_5tuple(ip1, ip2, port1, port2, proto, seed=0):
    low_ip, high_ip = (ip1, ip2) if ip1 <= ip2 else (ip2, ip1)
    low_p, high_p = (port1, port2) if port1 <= port2 else (port2, port1)
    data = f"{low_ip}:{high_ip}:{low_p}:{high_p}:{proto}:{seed}".encode('utf-8')
    h = int(hashlib.md5(data).hexdigest()[:8], 16)
    return h & 0xffffffff

class FlowDissectorEngine:
    def __init__(self, config):
        self.num_rx_queues = config.get("num_rx_queues", 8)
        self.hash_seed = config.get("hash_seed", 0x1337cafe)
        self.decap_vxlan = config.get("decap_vxlan", True)
        self.decap_gre = config.get("decap_gre", True)

        self.rx_queue_counts = [0] * self.num_rx_queues
        self.total_packets = 0
        self.dropped_packets = 0
        self.encapsulated_packets = 0
        self.events = []

    def dissect(self, pkt):
        self.total_packets += 1
        pid = pkt["id"]
        layers = pkt.get("layers", {})

        l2 = layers.get("ethernet")
        if not l2:
            self.dropped_packets += 1
            self.events.append({
                "packet_id": pid,
                "status": "BPF_DROP",
                "reason": "Missing Ethernet header"
            })
            return

        vlan = layers.get("vlan")
        vlan_id = vlan.get("id") if vlan else None

        outer_ip = layers.get("ipv4") or layers.get("ipv6")
        if not outer_ip:
            self.dropped_packets += 1
            self.events.append({
                "packet_id": pid,
                "status": "BPF_DROP",
                "reason": "Missing IP header"
            })
            return

        declared_len = outer_ip.get("total_len", 0)
        actual_len = pkt.get("length", declared_len)
        if actual_len < declared_len:
            self.dropped_packets += 1
            self.events.append({
                "packet_id": pid,
                "status": "BPF_DROP",
                "reason": "Packet truncated"
            })
            return

        is_encapsulated = False
        vni = None
        target_ip = outer_ip
        target_l4 = layers.get("l4", {})

        if self.decap_vxlan and layers.get("vxlan"):
            vxlan = layers["vxlan"]
            if vxlan.get("flags", 0x08) != 0x08:
                self.dropped_packets += 1
                self.events.append({
                    "packet_id": pid,
                    "status": "BPF_DROP",
                    "reason": "Invalid VXLAN flags"
                })
                return
            is_encapsulated = True
            self.encapsulated_packets += 1
            vni = vxlan.get("vni")
            inner = layers.get("inner", {})
            if "ip" in inner:
                target_ip = inner["ip"]
            if "l4" in inner:
                target_l4 = inner["l4"]

        elif self.decap_gre and layers.get("gre"):
            is_encapsulated = True
            self.encapsulated_packets += 1
            inner = layers.get("inner", {})
            if "ip" in inner:
                target_ip = inner["ip"]
            if "l4" in inner:
                target_l4 = inner["l4"]

        src_ip = target_ip.get("src", "0.0.0.0")
        dst_ip = target_ip.get("dst", "0.0.0.0")
        proto = target_ip.get("proto", 6)
        src_port = target_l4.get("src_port", 0)
        dst_port = target_l4.get("dst_port", 0)

        flow_hash = jhash_5tuple(src_ip, dst_ip, src_port, dst_port, proto, self.hash_seed)
        rx_queue = flow_hash % self.num_rx_queues
        self.rx_queue_counts[rx_queue] += 1

        flow_keys = {
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": src_port,
            "dst_port": dst_port,
            "ip_proto": proto,
            "is_encapsulated": is_encapsulated,
            "vlan_id": vlan_id,
            "vni": vni
        }

        self.events.append({
            "packet_id": pid,
            "status": "BPF_OK",
            "flow_keys": flow_keys,
            "flow_hash_hex": hex(flow_hash),
            "rx_queue": rx_queue
        })

    def run_packets(self, packets):
        for p in packets:
            self.dissect(p)

    def get_result(self):
        return {
            "total_packets": self.total_packets,
            "dropped_packets": self.dropped_packets,
            "encapsulated_packets": self.encapsulated_packets,
            "rx_queue_distribution": self.rx_queue_counts,
            "events": self.events
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    packets = data.get("packets", [])

    engine = FlowDissectorEngine(config)
    engine.run_packets(packets)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
