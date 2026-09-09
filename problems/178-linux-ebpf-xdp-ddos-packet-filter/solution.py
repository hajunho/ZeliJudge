import json
import zlib
from typing import Dict, List, Any, Optional

class XdpEngine:
    def __init__(self, config: Dict[str, Any]):
        self.enable_xdp = config.get("enable_xdp", True)
        self.enable_syn_cookies = config.get("enable_syn_cookies", False)
        self.max_conntrack_entries = config.get("max_conntrack_entries", 200)
        self.skb_allocation_budget_per_tick = config.get("skb_allocation_budget_per_tick", 100)
        self.xdp_syn_rate_limit = config.get("xdp_syn_rate_limit", 20)  # max SYNs per IP per tick
        self.blacklist_ips = set(config.get("blacklist_ips", []))
        self.whitelist_ips = set(config.get("whitelist_ips", []))

        # Internal BPF Maps
        self.bpf_syn_counter: Dict[str, int] = {}       # IP -> SYN count in current tick
        self.bpf_syn_cookie_cache: Dict[str, int] = {}  # IP -> expected cookie ack
        
        # Kernel Network Stack State
        self.conntrack_table: set = set()               # 5-tuples
        self.current_tick_skb_count = 0

        # Global Metrics
        self.metrics = {
            "total_packets_received": 0,
            "xdp_dropped": 0,
            "xdp_passed": 0,
            "xdp_tx_syn_cookies": 0,
            "skb_allocated": 0,
            "kernel_conntrack_drops": 0,
            "legitimate_delivered": 0,
            "attack_blocked": 0,
            "conntrack_usage": 0,
            "verdict": ""
        }
        self.packet_logs: List[Dict[str, Any]] = []

    def simulate_ticks(self, traffic_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        for event in traffic_events:
            tick = event["tick"]
            packets = event.get("packets", [])
            
            # Reset per-tick budgets and LRU rate limiters
            self.current_tick_skb_count = 0
            self.bpf_syn_counter.clear()

            for pkt in packets:
                self._process_single_packet(pkt, tick)

        self._finalize_metrics()
        return self._build_report()

    def _process_single_packet(self, pkt: Dict[str, Any], tick: int):
        self.metrics["total_packets_received"] += 1
        src_ip = pkt.get("src_ip", "")
        dst_port = pkt.get("dst_port", 80)
        protocol = pkt.get("protocol", "TCP")
        flags = pkt.get("flags", "ACK") # SYN, ACK, RST, FIN, PSH
        seq = pkt.get("seq", 0)
        ack_seq = pkt.get("ack", 0)
        is_attack = pkt.get("is_attack", False)
        pkt_id = pkt.get("pkt_id", f"{src_ip}:{flags}")
        src_port = pkt.get("src_port", 10000)
        five_tuple = f"{src_ip}:{src_port}->{dst_port}:{protocol}"

        log_entry = {
            "pkt_id": pkt_id,
            "src_ip": src_ip,
            "flags": flags,
            "is_attack": is_attack,
            "action": "",
            "stage": "",
            "reason": ""
        }

        # -------------------------------------------------------------
        # STAGE 1: Linux eBPF XDP Hook (Driver Ring Buffer - Zero skb)
        # -------------------------------------------------------------
        if self.enable_xdp:
            # 1. Whitelist immediate pass
            if src_ip in self.whitelist_ips:
                pass
            # 2. Blacklist drop (BPF Hash Map lookup)
            elif src_ip in self.blacklist_ips:
                self.metrics["xdp_dropped"] += 1
                if is_attack:
                    self.metrics["attack_blocked"] += 1
                log_entry["action"] = "XDP_DROP"
                log_entry["stage"] = "XDP_DRIVER"
                log_entry["reason"] = "BPF_MAP_BLACKLIST_MATCH"
                self.packet_logs.append(log_entry)
                return

            # 3. SYN Flood Mitigation in XDP
            elif flags == "SYN":
                curr_count = self.bpf_syn_counter.get(src_ip, 0) + 1
                self.bpf_syn_counter[src_ip] = curr_count
                
                if curr_count > self.xdp_syn_rate_limit:
                    if self.enable_syn_cookies:
                        # Deterministic CRC32 SYN Cookie at XDP layer and TX back
                        cookie_seed = f"{src_ip}:{src_port}:{tick}".encode("utf-8")
                        cookie = (zlib.crc32(cookie_seed) & 0x7FFFFFFF) + 1
                        self.bpf_syn_cookie_cache[src_ip] = cookie + 1
                        self.metrics["xdp_tx_syn_cookies"] += 1
                        log_entry["action"] = "XDP_TX"
                        log_entry["stage"] = "XDP_DRIVER"
                        log_entry["reason"] = f"SYN_COOKIE_TRANSMITTED_COOKIE_{cookie}"
                        self.packet_logs.append(log_entry)
                        return
                    else:
                        # Rate limit exceeded -> drop
                        self.metrics["xdp_dropped"] += 1
                        if is_attack:
                            self.metrics["attack_blocked"] += 1
                        log_entry["action"] = "XDP_DROP"
                        log_entry["stage"] = "XDP_DRIVER"
                        log_entry["reason"] = "BPF_SYN_RATE_LIMIT_EXCEEDED"
                        self.packet_logs.append(log_entry)
                        return

            # 4. SYN Cookie Verification at XDP
            elif flags == "ACK" and self.enable_syn_cookies and src_ip in self.bpf_syn_cookie_cache:
                expected_ack = self.bpf_syn_cookie_cache[src_ip]
                if ack_seq == expected_ack:
                    # Valid cookie! Clear cache and allow connection into kernel
                    del self.bpf_syn_cookie_cache[src_ip]
                    log_entry["reason"] = "SYN_COOKIE_VERIFIED"
                else:
                    self.metrics["xdp_dropped"] += 1
                    if is_attack:
                        self.metrics["attack_blocked"] += 1
                    log_entry["action"] = "XDP_DROP"
                    log_entry["stage"] = "XDP_DRIVER"
                    log_entry["reason"] = "INVALID_SYN_COOKIE_ACK"
                    self.packet_logs.append(log_entry)
                    return

            self.metrics["xdp_passed"] += 1
            log_entry["stage"] = "KERNEL_NETFILTER"

        # -------------------------------------------------------------
        # STAGE 2: Linux Kernel Network Stack (sk_buff & Conntrack)
        # -------------------------------------------------------------
        # Check SKB allocation budget (CPU SoftIRQ saturation)
        if self.current_tick_skb_count >= self.skb_allocation_budget_per_tick:
            self.metrics["kernel_conntrack_drops"] += 1
            log_entry["action"] = "KERNEL_DROP"
            log_entry["stage"] = "KERNEL_SOFTIRQ"
            log_entry["reason"] = "SKB_ALLOCATION_BUDGET_EXHAUSTED"
            self.packet_logs.append(log_entry)
            return

        self.current_tick_skb_count += 1
        self.metrics["skb_allocated"] += 1

        # Check Conntrack table
        if five_tuple not in self.conntrack_table:
            if len(self.conntrack_table) >= self.max_conntrack_entries:
                self.metrics["kernel_conntrack_drops"] += 1
                log_entry["action"] = "KERNEL_DROP"
                log_entry["stage"] = "KERNEL_CONNTRACK"
                log_entry["reason"] = "CONNTRACK_TABLE_FULL"
                self.packet_logs.append(log_entry)
                return
            self.conntrack_table.add(five_tuple)

        # Successfully delivered to user application socket
        log_entry["action"] = "DELIVERED_TO_SOCKET"
        log_entry["stage"] = "USERSPACE_SOCKET"
        if not is_attack:
            self.metrics["legitimate_delivered"] += 1
        self.packet_logs.append(log_entry)

    def _finalize_metrics(self):
        self.metrics["conntrack_usage"] = len(self.conntrack_table)
        
        if not self.enable_xdp and self.metrics["kernel_conntrack_drops"] >= 20:
            self.metrics["verdict"] = "KERNEL_STACK_COLLAPSE_CONNTRACK_EXHAUSTION"
        elif self.enable_xdp and self.metrics["kernel_conntrack_drops"] == 0 and (self.metrics["xdp_dropped"] > 0 or self.metrics["xdp_tx_syn_cookies"] > 0):
            self.metrics["verdict"] = "LINE_RATE_XDP_PACKET_FILTERING_SUCCESS"
        elif self.metrics["kernel_conntrack_drops"] == 0 and self.metrics["attack_blocked"] == 0 and self.metrics["xdp_dropped"] == 0:
            self.metrics["verdict"] = "CLEAN_TRAFFIC_UNFILTERED_PASS"
        else:
            self.metrics["verdict"] = "PARTIAL_FILTERING_PERFORMANCE_DEGRADED"

    def _build_report(self) -> Dict[str, Any]:
        return {
            "status": "COMPLETED",
            "metrics": dict(self.metrics),
            "sample_packet_logs": self.packet_logs[:10]
        }

def main():
    import sys
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    req = json.loads(raw_data)
    engine = XdpEngine(req["config"])
    result = engine.simulate_ticks(req["traffic_events"])
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
