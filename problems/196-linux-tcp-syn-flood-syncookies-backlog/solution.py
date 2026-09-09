# scratch/sim_196.py
import json
import math
import sys
import hashlib
from typing import Dict, List, Any, Optional

class LinuxTCPSyncookiesSimulator:
    def __init__(self, data: Dict[str, Any]):
        sys_cfg = data.get("system", {})
        self.max_syn_backlog = sys_cfg.get("tcp_max_syn_backlog", 128)
        self.somaxconn = sys_cfg.get("net_core_somaxconn", 128)
        self.listen_backlog = sys_cfg.get("app_listen_backlog", 128)
        self.accept_queue_limit = min(self.somaxconn, self.listen_backlog)

        self.tcp_syncookies_enabled = sys_cfg.get("tcp_syncookies", 1) # 0 = disabled, 1 = enabled
        self.tcp_abort_on_overflow = sys_cfg.get("tcp_abort_on_overflow", 0) # 0 = drop ACK, 1 = send RST

        # Kernel State
        # syn_queue: dict client_id -> {'created_ms': float, 'is_syn_cookie': bool}
        self.syn_queue: Dict[str, Dict[str, Any]] = {}
        # accept_queue: list of client_ids
        self.accept_queue: List[str] = []

        self.events_input = data.get("traffic", [])
        self.current_time_ms = 0.0

        # Metrics
        self.total_syn_received = 0
        self.syn_floods_dropped = 0
        self.syn_cookies_generated = 0
        self.syn_cookies_validated = 0
        self.legitimate_connections_established = 0
        self.legitimate_connections_rejected = 0
        self.accept_queue_overflow_drops = 0

        self.log = []

    def _generate_syn_cookie(self, client_id: str) -> int:
        secret = "kernel_syn_cookie_secret_key"
        h = hashlib.sha256(f"{client_id}:{secret}:{int(self.current_time_ms / 1000)}".encode()).hexdigest()
        return int(h[:8], 16)

    def run(self) -> Dict[str, Any]:
        for item in self.events_input:
            self.current_time_ms = item.get("timestamp_ms", self.current_time_ms)
            ev_type = item.get("type")
            client_id = item.get("client_id", "")
            is_legitimate = item.get("is_legitimate", True)

            if ev_type == "RECV_SYN":
                self.total_syn_received += 1
                # Check SYN queue status
                current_syn_len = len(self.syn_queue)

                if current_syn_len < self.max_syn_backlog:
                    # Normal allocation in SYN queue (state SYN_RECV)
                    self.syn_queue[client_id] = {
                        "created_ms": self.current_time_ms,
                        "is_syn_cookie": False,
                        "is_legitimate": is_legitimate
                    }
                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "SYN_ACK_NORMAL_SENT",
                        "client_id": client_id,
                        "syn_queue_len": len(self.syn_queue)
                    })
                else:
                    # SYN Queue is full!
                    if self.tcp_syncookies_enabled == 1:
                        # Stateless SYN Cookie generated!
                        cookie_val = self._generate_syn_cookie(client_id)
                        self.syn_cookies_generated += 1
                        # Crucial: NO memory is allocated in syn_queue!
                        self.log.append({
                            "time_ms": self.current_time_ms,
                            "event": "SYN_COOKIE_SENT",
                            "client_id": client_id,
                            "cookie": cookie_val
                        })
                    else:
                        # SYN Cookies disabled -> Drop SYN packet!
                        self.syn_floods_dropped += 1
                        if is_legitimate:
                            self.legitimate_connections_rejected += 1
                        self.log.append({
                            "time_ms": self.current_time_ms,
                            "event": "SYN_PACKET_DROPPED_QUEUE_FULL",
                            "client_id": client_id,
                            "is_legitimate": is_legitimate
                        })

            elif ev_type == "RECV_FINAL_ACK":
                # Final ACK from 3-way handshake
                # 1. Check if client was in syn_queue
                was_in_syn_queue = client_id in self.syn_queue

                if was_in_syn_queue:
                    entry = self.syn_queue.pop(client_id)
                    cookie_valid = True
                else:
                    # Not in syn_queue. Must be validated via SYN Cookie!
                    if self.tcp_syncookies_enabled == 1:
                        # Cookie verified statelessly!
                        self.syn_cookies_validated += 1
                        cookie_valid = True
                    else:
                        cookie_valid = False

                if cookie_valid:
                    # Check Accept Queue capacity
                    if len(self.accept_queue) < self.accept_queue_limit:
                        self.accept_queue.append(client_id)
                        if is_legitimate:
                            self.legitimate_connections_established += 1
                        self.log.append({
                            "time_ms": self.current_time_ms,
                            "event": "CONNECTION_ESTABLISHED_IN_ACCEPT_QUEUE",
                            "client_id": client_id,
                            "accept_queue_len": len(self.accept_queue)
                        })
                    else:
                        # Accept Queue Overflow!
                        self.accept_queue_overflow_drops += 1
                        if is_legitimate:
                            self.legitimate_connections_rejected += 1
                        action = "RST_SENT" if self.tcp_abort_on_overflow == 1 else "ACK_IGNORED_DROP"
                        self.log.append({
                            "time_ms": self.current_time_ms,
                            "event": "ACCEPT_QUEUE_OVERFLOW",
                            "client_id": client_id,
                            "action": action
                        })

            elif ev_type == "APP_ACCEPT":
                # Application calls accept() to drain connection
                count = item.get("count", 1)
                accepted = 0
                while self.accept_queue and accepted < count:
                    self.accept_queue.pop(0)
                    accepted += 1
                self.log.append({
                    "time_ms": self.current_time_ms,
                    "event": "APP_ACCEPT_DRAINED",
                    "drained": accepted,
                    "remaining_in_accept_queue": len(self.accept_queue)
                })

            elif ev_type == "SYN_TIMEOUT_EXPIRE":
                # Simulated half-open SYN timeout for spoofed attackers who never ACK
                expired = []
                timeout_duration = item.get("timeout_ms", 3000.0)
                for cid, info in self.syn_queue.items():
                    if not info["is_legitimate"] and (self.current_time_ms - info["created_ms"] >= timeout_duration):
                        expired.append(cid)
                for cid in expired:
                    del self.syn_queue[cid]
                if expired:
                    self.log.append({
                        "time_ms": self.current_time_ms,
                        "event": "SYN_QUEUE_TIMEOUT_PURGED",
                        "purged_count": len(expired)
                    })

        # Verdict evaluation
        if self.legitimate_connections_rejected > 0 and self.tcp_syncookies_enabled == 0:
            status = "FAILED"
            verdict = "TCP_SYN_FLOOD_QUEUE_EXHAUSTION_COLLAPSE"
        elif self.accept_queue_overflow_drops > 0 and self.accept_queue_limit < 64:
            status = "FAILED"
            verdict = "ACCEPT_QUEUE_OVERFLOW_BACKLOG_BOTTLENECK"
        elif self.legitimate_connections_rejected > 0:
            status = "FAILED"
            verdict = "LEGITIMATE_CLIENT_HANDSHAKE_DROPPED"
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_SYN_COOKIES_DEFENSE"

        return {
            "status": status,
            "kernel_config": {
                "tcp_max_syn_backlog": self.max_syn_backlog,
                "net_core_somaxconn": self.somaxconn,
                "app_listen_backlog": self.listen_backlog,
                "effective_accept_limit": self.accept_queue_limit,
                "tcp_syncookies": self.tcp_syncookies_enabled
            },
            "metrics": {
                "total_syn_received": self.total_syn_received,
                "syn_floods_dropped": self.syn_floods_dropped,
                "syn_cookies_generated": self.syn_cookies_generated,
                "syn_cookies_validated": self.syn_cookies_validated,
                "legitimate_connections_established": self.legitimate_connections_established,
                "legitimate_connections_rejected": self.legitimate_connections_rejected,
                "accept_queue_overflow_drops": self.accept_queue_overflow_drops,
                "verdict": verdict
            },
            "events_log": self.log
        }

if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    sim = LinuxTCPSyncookiesSimulator(input_data)
    res = sim.run()
    print(json.dumps(res, indent=2))
