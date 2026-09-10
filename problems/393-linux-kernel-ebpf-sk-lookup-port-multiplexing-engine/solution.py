# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #393: Linux Kernel eBPF sk_lookup & L4 Port Multiplexing Engine
Implementation in Python 3.
"""
import sys
import json

class SkLookupEngine:
    def __init__(self, config):
        self.sockets = {}
        self.rules = []

        self.total_packets = 0
        self.bpf_assigned_count = 0
        self.bpf_dropped_count = 0
        self.fallback_assigned_count = 0
        self.fallback_rejected_count = 0
        self.events = []

    def register_socket(self, sock_id, bind_ip, bind_port, is_listening=True):
        self.sockets[sock_id] = {
            "sock_id": sock_id,
            "bind_ip": bind_ip,
            "bind_port": bind_port,
            "is_listening": is_listening
        }
        self.events.append({
            "op": "REGISTER_SOCKET",
            "sock_id": sock_id,
            "bind_ip": bind_ip,
            "bind_port": bind_port,
            "status": "SUCCESS"
        })

    def add_rule(self, rule_id, priority, match_cfg, action, target_sock=None):
        rule = {
            "rule_id": rule_id,
            "priority": priority,
            "match": match_cfg,
            "action": action,
            "target_sock": target_sock
        }
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r["priority"])
        self.events.append({
            "op": "ADD_RULE",
            "rule_id": rule_id,
            "priority": priority,
            "action": action,
            "status": "SUCCESS"
        })

    def process_packet(self, pkt_id, src_ip, src_port, dst_ip, dst_port, proto):
        self.total_packets += 1

        matched_rule = None
        for r in self.rules:
            m = r["match"]
            if m.get("proto") and m["proto"] != proto:
                continue
            if m.get("dst_ip") and m["dst_ip"] != dst_ip:
                continue
            if m.get("dst_ip_prefix") and not dst_ip.startswith(m["dst_ip_prefix"]):
                continue
            p_start = m.get("port_start", 0)
            p_end = m.get("port_end", 65535)
            if not (p_start <= dst_port <= p_end):
                continue

            matched_rule = r
            break

        if matched_rule:
            act = matched_rule["action"]
            if act == "DROP":
                self.bpf_dropped_count += 1
                self.events.append({
                    "op": "PROCESS_PACKET",
                    "pkt_id": pkt_id,
                    "status": "BPF_DROP",
                    "matched_rule": matched_rule["rule_id"]
                })
                return
            elif act == "ASSIGN":
                target_sock = matched_rule.get("target_sock")
                if target_sock in self.sockets and self.sockets[target_sock]["is_listening"]:
                    self.bpf_assigned_count += 1
                    self.events.append({
                        "op": "PROCESS_PACKET",
                        "pkt_id": pkt_id,
                        "status": "BPF_ASSIGNED",
                        "assigned_socket": target_sock,
                        "matched_rule": matched_rule["rule_id"],
                        "bypassed_kernel_hashtable": True
                    })
                    return

        fallback_sock = None
        for sid, s in self.sockets.items():
            if s["is_listening"] and (s["bind_ip"] == "0.0.0.0" or s["bind_ip"] == dst_ip) and s["bind_port"] == dst_port:
                fallback_sock = sid
                break

        if fallback_sock:
            self.fallback_assigned_count += 1
            self.events.append({
                "op": "PROCESS_PACKET",
                "pkt_id": pkt_id,
                "status": "FALLBACK_ASSIGNED",
                "assigned_socket": fallback_sock,
                "bypassed_kernel_hashtable": False
            })
        else:
            self.fallback_rejected_count += 1
            self.events.append({
                "op": "PROCESS_PACKET",
                "pkt_id": pkt_id,
                "status": "FALLBACK_RST",
                "reason": "No listening socket found"
            })

    def run_commands(self, commands):
        for cmd in commands:
            op = cmd.get("op")
            if op == "REGISTER_SOCKET":
                self.register_socket(
                    cmd["sock_id"],
                    cmd["bind_ip"],
                    cmd["bind_port"],
                    cmd.get("is_listening", True)
                )
            elif op == "ADD_RULE":
                self.add_rule(
                    cmd["rule_id"],
                    cmd["priority"],
                    cmd.get("match", {}),
                    cmd["action"],
                    cmd.get("target_sock")
                )
            elif op == "PROCESS_PACKET":
                self.process_packet(
                    cmd["pkt_id"],
                    cmd["src_ip"],
                    cmd["src_port"],
                    cmd["dst_ip"],
                    cmd["dst_port"],
                    cmd.get("proto", "TCP")
                )

    def get_result(self):
        return {
            "total_packets": self.total_packets,
            "bpf_assigned_count": self.bpf_assigned_count,
            "bpf_dropped_count": self.bpf_dropped_count,
            "fallback_assigned_count": self.fallback_assigned_count,
            "fallback_rejected_count": self.fallback_rejected_count,
            "active_sockets": len(self.sockets),
            "active_rules": len(self.rules),
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
    commands = data.get("commands", [])

    engine = SkLookupEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
