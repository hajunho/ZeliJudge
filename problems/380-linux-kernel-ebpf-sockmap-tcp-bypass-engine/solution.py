# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #380: Linux Kernel Network: eBPF sockmap & sk_msg Zero-Copy TCP Bypass Engine
Canonical Solution Implementation
"""
import sys
import json
import ipaddress

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class SockMapEngine:
    def __init__(self, config):
        self.map_type = config.get("map_type", "SOCKHASH")
        self.map_capacity = config.get("map_capacity", 1024)
        self.bypass_enabled = config.get("bypass_enabled", True)
        self.co_located_subnets = [ipaddress.ip_network(net) for net in config.get("co_located_subnets", ["10.244.0.0/16", "127.0.0.1/32"])]
        self.metrics_cfg = config.get("stack_metrics", {
            "tcp_ip_stack_latency_us": 28.5,
            "ebpf_bypass_latency_us": 4.2,
            "tcp_ip_cpu_cycles_per_byte": 12.0,
            "ebpf_bypass_cpu_cycles_per_byte": 1.8
        })
        self.sockmap = {}
        self.sockets = {}
        self.cork_buffers = {}
        self.history = []
        self.stats = {
            "total_messages": 0,
            "bypassed_messages": 0,
            "standard_stack_messages": 0,
            "dropped_messages": 0,
            "total_bytes": 0,
            "bypassed_bytes": 0,
            "delivered_latencies": [],
            "cpu_cycles_consumed": 0.0,
            "cpu_cycles_baseline": 0.0
        }

    def _is_ip_in_subnets(self, ip_str):
        try:
            addr = ipaddress.ip_address(ip_str)
            return any(addr in net for net in self.co_located_subnets)
        except ValueError:
            return False

    def register_sockets(self, socket_list):
        for s in socket_list:
            self.sockets[s["sock_id"]] = dict(s)

    def handle_sockops(self, event):
        ev = event["event"]
        sid = event["sock_id"]
        ts = event.get("timestamp", 0)
        sock = self.sockets.get(sid)
        if not sock:
            self.history.append({"type": "SOCKOPS", "event": ev, "sock_id": sid, "status": "SOCK_NOT_FOUND", "detail": "socket not defined"})
            return

        if ev in ("ACTIVE_ESTABLISHED", "PASSIVE_ESTABLISHED"):
            src_in = self._is_ip_in_subnets(sock["src_ip"])
            dst_in = self._is_ip_in_subnets(sock["dst_ip"])
            is_co_located = (src_in and dst_in)
            
            if is_co_located and self.bypass_enabled:
                unique_socks = len([k for k in self.sockmap if not k.startswith("sock_") and "->" in k])
                if unique_socks >= self.map_capacity:
                    self.history.append({"type": "SOCKOPS", "event": ev, "sock_id": sid, "status": "MAP_FULL", "detail": "sockmap capacity exceeded"})
                    return
                key = f"{sock['src_ip']}:{sock['src_port']}->{sock['dst_ip']}:{sock['dst_port']}"
                self.sockmap[key] = sid
                self.sockmap[sid] = key
                self.history.append({
                    "type": "SOCKOPS", "event": ev, "sock_id": sid, "status": "REGISTERED",
                    "detail": f"co-located socket registered in {self.map_type} ({key})"
                })
            else:
                self.history.append({
                    "type": "SOCKOPS", "event": ev, "sock_id": sid, "status": "BYPASS_INELIGIBLE",
                    "detail": f"socket {sid} is external or remote; standard TCP/IP stack will be used"
                })
        elif ev == "SOCK_CLOSED":
            if sid in self.sockmap:
                key = self.sockmap[sid]
                del self.sockmap[sid]
                if key in self.sockmap:
                    del self.sockmap[key]
                self.history.append({"type": "SOCKOPS", "event": ev, "sock_id": sid, "status": "REMOVED", "detail": f"socket {sid} removed from sockmap"})
            else:
                self.history.append({"type": "SOCKOPS", "event": ev, "sock_id": sid, "status": "NOOP", "detail": f"socket {sid} was not in sockmap"})

    def process_message(self, msg, rules):
        mid = msg["msg_id"]
        from_sid = msg["from_sock"]
        sender = self.sockets.get(from_sid)
        payload = msg.get("payload", "")
        nbytes = msg.get("bytes", len(payload))
        proto = msg.get("protocol", "RAW")
        ts = msg.get("timestamp", 0)

        self.stats["total_messages"] += 1
        
        to_sid = msg.get("to_sock", None)
        if not to_sid and sender:
            for s in self.sockets.values():
                if s["src_ip"] == sender["dst_ip"] and s["src_port"] == sender["dst_port"] and s["dst_ip"] == sender["src_ip"] and s["dst_port"] == sender["src_port"]:
                    to_sid = s["sock_id"]
                    break

        is_sender_in_map = (from_sid in self.sockmap)
        is_peer_in_map = (to_sid in self.sockmap) if to_sid else False
        co_located = (is_sender_in_map and is_peer_in_map and self.bypass_enabled)

        matched_action = "SK_PASS"
        cork_thresh = 0
        rule_name = "default"

        for r in rules:
            m = r.get("match", {})
            if "has_pattern" in m:
                if m["has_pattern"] not in payload:
                    continue
            if "protocol" in m:
                if m["protocol"] != proto:
                    continue
            if "co_located" in m:
                if m["co_located"] != co_located:
                    continue
            matched_action = r.get("action", "SK_PASS")
            cork_thresh = r.get("cork_bytes", 0)
            rule_name = r.get("rule_id", "matched_rule")
            break

        if matched_action == "SK_DROP":
            self.stats["dropped_messages"] += 1
            self.history.append({
                "type": "SK_MSG", "msg_id": mid, "action": "SK_DROP", "rule": rule_name,
                "latency_us": 0.5, "detail": f"message dropped by eBPF sk_msg verdict on socket {from_sid}"
            })
            return

        if cork_thresh > 0 and matched_action == "REDIRECT" and co_located:
            buf = self.cork_buffers.setdefault(from_sid, {"bytes": 0, "messages": []})
            buf["bytes"] += nbytes
            buf["messages"].append(mid)
            if buf["bytes"] < cork_thresh:
                self.history.append({
                    "type": "SK_MSG", "msg_id": mid, "action": "CORKED", "rule": rule_name,
                    "buffered_bytes": buf["bytes"], "threshold": cork_thresh,
                    "detail": f"message buffered in sk_msg cork ({buf['bytes']}/{cork_thresh} bytes)"
                })
                return
            else:
                flushed_msgs = list(buf["messages"])
                total_corked = buf["bytes"]
                buf["bytes"] = 0
                buf["messages"] = []
                lat = self.metrics_cfg["ebpf_bypass_latency_us"]
                cpu_consumed = total_corked * self.metrics_cfg["ebpf_bypass_cpu_cycles_per_byte"]
                cpu_base = total_corked * self.metrics_cfg["tcp_ip_cpu_cycles_per_byte"]
                
                self.stats["bypassed_messages"] += len(flushed_msgs)
                self.stats["bypassed_bytes"] += total_corked
                self.stats["total_bytes"] += total_corked
                self.stats["delivered_latencies"].extend([lat] * len(flushed_msgs))
                self.stats["cpu_cycles_consumed"] += cpu_consumed
                self.stats["cpu_cycles_baseline"] += cpu_base
                
                self.history.append({
                    "type": "SK_MSG", "msg_id": mid, "action": "REDIRECT_CORK_FLUSH", "rule": rule_name,
                    "flushed_messages": flushed_msgs, "flushed_bytes": total_corked,
                    "latency_us": lat, "target_sock": to_sid,
                    "detail": f"cork threshold reached ({total_corked} bytes); zero-copy redirected {len(flushed_msgs)} messages directly to {to_sid}"
                })
                return

        if matched_action == "REDIRECT" and co_located:
            lat = self.metrics_cfg["ebpf_bypass_latency_us"]
            cpu_consumed = nbytes * self.metrics_cfg["ebpf_bypass_cpu_cycles_per_byte"]
            cpu_base = nbytes * self.metrics_cfg["tcp_ip_cpu_cycles_per_byte"]
            
            self.stats["bypassed_messages"] += 1
            self.stats["bypassed_bytes"] += nbytes
            self.stats["total_bytes"] += nbytes
            self.stats["delivered_latencies"].append(lat)
            self.stats["cpu_cycles_consumed"] += cpu_consumed
            self.stats["cpu_cycles_baseline"] += cpu_base

            self.history.append({
                "type": "SK_MSG", "msg_id": mid, "action": "SK_REDIRECT", "rule": rule_name,
                "latency_us": lat, "target_sock": to_sid,
                "detail": f"zero-copy TCP bypass: redirected {nbytes} bytes directly to {to_sid} sk_receive_queue"
            })
        else: # SK_PASS or non-co-located
            lat = self.metrics_cfg["tcp_ip_stack_latency_us"]
            cpu_consumed = nbytes * self.metrics_cfg["tcp_ip_cpu_cycles_per_byte"]
            cpu_base = cpu_consumed
            
            self.stats["standard_stack_messages"] += 1
            self.stats["total_bytes"] += nbytes
            self.stats["delivered_latencies"].append(lat)
            self.stats["cpu_cycles_consumed"] += cpu_consumed
            self.stats["cpu_cycles_baseline"] += cpu_base

            self.history.append({
                "type": "SK_MSG", "msg_id": mid, "action": "SK_PASS", "rule": rule_name,
                "latency_us": lat, "target_sock": to_sid,
                "detail": f"standard TCP/IP stack path: {nbytes} bytes routed via L3/L4 stack and loopback/netfilter"
            })

    def get_summary(self):
        deliv = self.stats["delivered_latencies"]
        avg_lat = round(sum(deliv) / len(deliv), 2) if deliv else 0.0
        baseline_lat = self.metrics_cfg["tcp_ip_stack_latency_us"]
        lat_red_pct = round(((baseline_lat - avg_lat) / baseline_lat) * 100.0, 2) if baseline_lat > 0 and deliv else 0.0
        cpu_saved = round(self.stats["cpu_cycles_baseline"] - self.stats["cpu_cycles_consumed"], 1)
        
        return {
            "total_messages_processed": self.stats["total_messages"],
            "bypassed_messages_count": self.stats["bypassed_messages"],
            "standard_stack_messages_count": self.stats["standard_stack_messages"],
            "dropped_messages_count": self.stats["dropped_messages"],
            "total_bytes_transferred": self.stats["total_bytes"],
            "bypassed_bytes": self.stats["bypassed_bytes"],
            "average_latency_us": avg_lat,
            "latency_reduction_pct": lat_red_pct,
            "total_cpu_cycles_saved": cpu_saved,
            "sockmap_active_entries": len(self.sockmap) // 2
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    eng = SockMapEngine(data["config"])
    eng.register_sockets(data.get("sockets", []))
    for ev in data.get("sockops_events", []):
        eng.handle_sockops(ev)
    rules = data.get("sk_msg_rules", [])
    for msg in data.get("messages", []):
        eng.process_message(msg, rules)
    result = {
        "history": eng.history,
        "summary": eng.get_summary()
    }
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
