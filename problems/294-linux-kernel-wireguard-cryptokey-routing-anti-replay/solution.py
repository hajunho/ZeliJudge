# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #294: Linux Kernel WireGuard Cryptokey Routing & Anti-Replay Sliding Window
https://github.com/hajunho/ZeliJudge
"""

import sys
import json
import ipaddress

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class Peer:
    def __init__(self, peer_id, pub_key, allowed_ips, endpoint):
        self.peer_id = peer_id
        self.pub_key = pub_key
        self.allowed_networks = [ipaddress.ip_network(cidr) for cidr in allowed_ips]
        self.endpoint = endpoint
        
        # Session state
        self.active_session_id = None
        self.session_start_time = None
        self.tx_counter = 0
        self.rx_max_counter = 0
        self.rx_window_bitmap = 0  # 64-bit integer
        
        # Stats
        self.tx_packets = 0
        self.rx_packets = 0
        self.rekey_count = 0

class WireGuardEngine:
    def __init__(self, config, peers_config):
        self.replay_window_size = config.get("replay_window_size", 64)
        self.rekey_after_time_s = config.get("rekey_after_time_s", 120.0)
        self.rekey_after_packets = config.get("rekey_after_packets", 500)
        self.reject_after_time_s = config.get("reject_after_time_s", 180.0)
        
        self.peers = {}  # peer_id -> Peer
        self.endpoint_to_peer = {} # endpoint -> peer_id
        for p in peers_config:
            peer = Peer(p["peer_id"], p["public_key"], p.get("allowed_ips", []), p.get("endpoint", ""))
            self.peers[peer.peer_id] = peer
            if peer.endpoint:
                self.endpoint_to_peer[peer.endpoint] = peer.peer_id
                
        self.event_log = []
        self.stats = {
            "tx_forwarded": 0,
            "rx_accepted": 0,
            "dropped_unroutable": 0,
            "dropped_spoofed_src": 0,
            "dropped_replay_duplicate": 0,
            "dropped_counter_too_old": 0,
            "rekey_handshakes": 0,
            "endpoint_roaming_updates": 0
        }

    def _lookup_peer_for_ip(self, ip_str):
        ip = ipaddress.ip_address(ip_str)
        best_peer = None
        best_prefix = -1
        # Deterministic peer tie-breaker: peer_id
        for p_id in sorted(self.peers.keys()):
            peer = self.peers[p_id]
            for net in peer.allowed_networks:
                if ip in net:
                    if net.prefixlen > best_prefix:
                        best_prefix = net.prefixlen
                        best_peer = peer
        return best_peer

    def handle_handshake(self, time_s, peer_id, session_id):
        peer = self.peers.get(peer_id)
        if not peer:
            return
        peer.active_session_id = session_id
        peer.session_start_time = time_s
        peer.tx_counter = 0
        peer.rx_max_counter = 0
        peer.rx_window_bitmap = 0
        peer.rekey_count += 1
        self.stats["rekey_handshakes"] += 1
        self.event_log.append({
            "time_s": time_s,
            "event": "HANDSHAKE_ESTABLISHED",
            "peer_id": peer_id,
            "session_id": session_id
        })

    def handle_tx(self, time_s, dst_ip, payload_len):
        peer = self._lookup_peer_for_ip(dst_ip)
        if not peer:
            self.stats["dropped_unroutable"] += 1
            self.event_log.append({
                "time_s": time_s,
                "event": "TX_DROP",
                "reason": "UNROUTABLE_NO_PEER",
                "dst_ip": dst_ip
            })
            return

        if not peer.active_session_id:
            self.stats["dropped_unroutable"] += 1
            self.event_log.append({
                "time_s": time_s,
                "event": "TX_DROP",
                "reason": "NO_ACTIVE_SESSION",
                "peer_id": peer.peer_id
            })
            return

        elapsed = time_s - peer.session_start_time
        if elapsed > self.reject_after_time_s:
            self.stats["dropped_unroutable"] += 1
            self.event_log.append({
                "time_s": time_s,
                "event": "TX_DROP",
                "reason": "SESSION_REJECT_EXPIRED",
                "peer_id": peer.peer_id
            })
            return

        peer.tx_counter += 1
        peer.tx_packets += 1
        self.stats["tx_forwarded"] += 1

        rekey_needed = False
        if peer.tx_counter >= self.rekey_after_packets or elapsed >= self.rekey_after_time_s:
            rekey_needed = True

        self.event_log.append({
            "time_s": time_s,
            "event": "TX_FORWARD",
            "peer_id": peer.peer_id,
            "dst_ip": dst_ip,
            "endpoint": peer.endpoint,
            "counter": peer.tx_counter,
            "rekey_required": rekey_needed
        })

    def handle_rx(self, time_s, src_endpoint, inner_src_ip, inner_dst_ip, counter, session_id):
        peer = None
        for p in self.peers.values():
            if p.active_session_id == session_id:
                peer = p
                break
        if not peer and src_endpoint in self.endpoint_to_peer:
            peer = self.peers[self.endpoint_to_peer[src_endpoint]]

        if not peer:
            self.stats["dropped_unroutable"] += 1
            self.event_log.append({
                "time_s": time_s,
                "event": "RX_DROP",
                "reason": "UNKNOWN_PEER_SESSION"
            })
            return

        # Roaming / Endpoint update
        if src_endpoint != peer.endpoint:
            old_ep = peer.endpoint
            peer.endpoint = src_endpoint
            self.endpoint_to_peer[src_endpoint] = peer.peer_id
            self.stats["endpoint_roaming_updates"] += 1
            self.event_log.append({
                "time_s": time_s,
                "event": "ROAMING_ENDPOINT_UPDATE",
                "peer_id": peer.peer_id,
                "old_endpoint": old_ep,
                "new_endpoint": src_endpoint
            })

        # Cryptokey routing check
        src_ip_obj = ipaddress.ip_address(inner_src_ip)
        allowed = any(src_ip_obj in net for net in peer.allowed_networks)
        if not allowed:
            self.stats["dropped_spoofed_src"] += 1
            self.event_log.append({
                "time_s": time_s,
                "event": "RX_DROP",
                "reason": "CRYPT_KEY_ROUTING_SPOOFED_SRC",
                "peer_id": peer.peer_id,
                "inner_src_ip": inner_src_ip
            })
            return

        # Anti-replay sliding window check
        if counter <= 0:
            self.stats["dropped_counter_too_old"] += 1
            self.event_log.append({"time_s": time_s, "event": "RX_DROP", "reason": "ZERO_OR_NEGATIVE_COUNTER"})
            return

        if counter > peer.rx_max_counter:
            diff = counter - peer.rx_max_counter
            if diff < self.replay_window_size:
                peer.rx_window_bitmap = (peer.rx_window_bitmap << diff) | 1
            else:
                peer.rx_window_bitmap = 1
            peer.rx_max_counter = counter
        else:
            diff = peer.rx_max_counter - counter
            if diff >= self.replay_window_size:
                self.stats["dropped_counter_too_old"] += 1
                self.event_log.append({
                    "time_s": time_s,
                    "event": "RX_DROP",
                    "reason": "COUNTER_TOO_OLD",
                    "counter": counter,
                    "max_counter": peer.rx_max_counter
                })
                return
            bit_mask = (1 << diff)
            if peer.rx_window_bitmap & bit_mask:
                self.stats["dropped_replay_duplicate"] += 1
                self.event_log.append({
                    "time_s": time_s,
                    "event": "RX_DROP",
                    "reason": "REPLAY_ATTACK_DUPLICATE",
                    "counter": counter
                })
                return
            peer.rx_window_bitmap |= bit_mask

        peer.rx_packets += 1
        self.stats["rx_accepted"] += 1
        self.event_log.append({
            "time_s": time_s,
            "event": "RX_ACCEPT",
            "peer_id": peer.peer_id,
            "inner_src_ip": inner_src_ip,
            "inner_dst_ip": inner_dst_ip,
            "counter": counter
        })

def simulate_wireguard(data):
    config = data.get("config", {})
    peers_config = data.get("peers", [])
    events = data.get("events", [])

    engine = WireGuardEngine(config, peers_config)

    for ev in events:
        ev_type = ev.get("type")
        time_s = ev.get("time_s", 0.0)

        if ev_type == "HANDSHAKE":
            engine.handle_handshake(time_s, ev.get("peer_id"), ev.get("session_id"))
        elif ev_type == "TX":
            engine.handle_tx(time_s, ev.get("dst_ip"), ev.get("payload_len", 1420))
        elif ev_type == "RX":
            engine.handle_rx(
                time_s,
                ev.get("src_endpoint", ""),
                ev.get("inner_src_ip", ""),
                ev.get("inner_dst_ip", ""),
                ev.get("counter", 0),
                ev.get("session_id", "")
            )

    # Compile peer summaries
    peer_summaries = {}
    for p_id in sorted(engine.peers.keys()):
        p = engine.peers[p_id]
        peer_summaries[p_id] = {
            "current_endpoint": p.endpoint,
            "active_session_id": p.active_session_id,
            "tx_packets": p.tx_packets,
            "rx_packets": p.rx_packets,
            "rx_max_counter": p.rx_max_counter,
            "rekey_count": p.rekey_count
        }

    # Diagnostics
    anomalies = []
    status = "SECURE_OPTIMAL"
    if engine.stats["dropped_replay_duplicate"] > 0:
        anomalies.append("REPLAY_ATTACK_DETECTED")
        status = "SECURITY_INCIDENT_REPLAY"
    if engine.stats["dropped_spoofed_src"] > 0:
        anomalies.append("CRYPTOKEY_ROUTING_SPOOF_ATTEMPT")
        if status == "SECURE_OPTIMAL":
            status = "SECURITY_INCIDENT_SPOOF"

    return {
        "metrics": engine.stats,
        "peer_summaries": peer_summaries,
        "diagnostics": {
            "status": status,
            "anomalies": anomalies
        },
        "event_log_sample": engine.event_log[:15]
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_wireguard(data)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
