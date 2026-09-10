import sys
import json
import ipaddress

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    spd_policies = input_data.get("spd_policies", [])
    sad_states = {sa["spi"]: sa for sa in input_data.get("sad_states", [])}
    packets = input_data.get("packets", [])
    
    sa_runtime = {}
    for spi, sa in sad_states.items():
        sa_runtime[spi] = {
            "spi": spi,
            "mode": sa.get("mode", "TUNNEL"),
            "current_seq_out": sa.get("current_seq", 0),
            "highest_seq_in": sa.get("highest_seq_seen", 0),
            "replay_window_size": sa.get("replay_window_size", 64),
            "bitmap": set(sa.get("replay_bitmap", [])),
            "lifetime": sa.get("lifetime_bytes", {"soft": 1000000, "hard": 2000000, "current": 0}),
            "soft_expired": False,
            "hard_expired": False
        }
        
    results = []
    encap_count = 0
    decap_count = 0
    replay_drops = 0
    crypto_drops = 0
    policy_blocks = 0
    
    for pkt in packets:
        pid = pkt.get("pkt_id")
        pdir = pkt.get("dir", "OUT")
        src_ip = pkt.get("src_ip")
        dst_ip = pkt.get("dst_ip")
        proto = pkt.get("proto", "TCP")
        payload = pkt.get("payload_bytes", 100)
        
        matched_policy = None
        for pol in spd_policies:
            if pol.get("dir") != pdir:
                continue
            try:
                src_net = ipaddress.ip_network(pol.get("src_cidr", "0.0.0.0/0"))
                dst_net = ipaddress.ip_network(pol.get("dst_cidr", "0.0.0.0/0"))
                if ipaddress.ip_address(src_ip) in src_net and ipaddress.ip_address(dst_ip) in dst_net:
                    p_proto = pol.get("proto", "ANY")
                    if p_proto == "ANY" or p_proto == proto:
                        matched_policy = pol
                        break
            except Exception:
                continue
                
        if not matched_policy:
            results.append({
                "pkt_id": pid,
                "status": "FORWARD_PLAINTEXT",
                "reason": "NO_MATCHING_SPD_POLICY"
            })
            continue
            
        action = matched_policy.get("action", "ALLOW")
        if action == "BLOCK":
            policy_blocks += 1
            results.append({
                "pkt_id": pid,
                "status": "DROP",
                "reason": "POLICY_DISCARD"
            })
            continue
            
        tmpl_spi = matched_policy.get("tmpl_spi")
        if not tmpl_spi:
            results.append({
                "pkt_id": pid,
                "status": "FORWARD_PLAINTEXT",
                "reason": "POLICY_ALLOW_PASSTHROUGH"
            })
            continue
            
        if tmpl_spi not in sa_runtime:
            results.append({
                "pkt_id": pid,
                "status": "DROP",
                "reason": "SAD_STATE_NOT_FOUND"
            })
            continue
            
        sa = sa_runtime[tmpl_spi]
        
        if sa["lifetime"]["current"] + payload > sa["lifetime"]["hard"]:
            sa["hard_expired"] = True
            results.append({
                "pkt_id": pid,
                "status": "DROP",
                "reason": "SA_HARD_EXPIRED"
            })
            continue
            
        sa["lifetime"]["current"] += payload
        if sa["lifetime"]["current"] >= sa["lifetime"]["soft"]:
            sa["soft_expired"] = True
            
        if pdir == "OUT":
            sa["current_seq_out"] += 1
            seq = sa["current_seq_out"]
            pad_len = (4 - ((payload + 2) % 4)) % 4
            esp_overhead = 4 + 4 + 8 + pad_len + 1 + 1 + 16
            total_esp_len = payload + esp_overhead
            encap_count += 1
            results.append({
                "pkt_id": pid,
                "status": "ESP_ENCAPSULATED",
                "spi": tmpl_spi,
                "seq": seq,
                "esp_packet_size": total_esp_len,
                "soft_rekey_alert": sa["soft_expired"]
            })
            
        elif pdir == "IN":
            in_seq = pkt.get("seq", 1)
            is_tampered = pkt.get("is_tampered", False)
            
            window = sa["replay_window_size"]
            highest = sa["highest_seq_in"]
            
            if in_seq <= 0:
                replay_drops += 1
                results.append({
                    "pkt_id": pid,
                    "status": "DROP",
                    "reason": "REPLAY_ERROR_SEQ_ZERO"
                })
                continue
                
            if in_seq > highest:
                sa["highest_seq_in"] = in_seq
                sa["bitmap"].add(in_seq)
                sa["bitmap"] = {s for s in sa["bitmap"] if s > (in_seq - window)}
            else:
                diff = highest - in_seq
                if diff >= window:
                    replay_drops += 1
                    results.append({
                        "pkt_id": pid,
                        "status": "DROP",
                        "reason": "REPLAY_ERROR_OUTSIDE_WINDOW"
                    })
                    continue
                if in_seq in sa["bitmap"]:
                    replay_drops += 1
                    results.append({
                        "pkt_id": pid,
                        "status": "DROP",
                        "reason": "REPLAY_ERROR_DUPLICATE_PACKET"
                    })
                    continue
                sa["bitmap"].add(in_seq)
                
            if is_tampered:
                crypto_drops += 1
                results.append({
                    "pkt_id": pid,
                    "status": "DROP",
                    "reason": "ICV_VERIFICATION_FAILED"
                })
                continue
                
            decap_count += 1
            results.append({
                "pkt_id": pid,
                "status": "ESP_DECAPSULATED",
                "spi": tmpl_spi,
                "seq": in_seq,
                "recovered_payload_bytes": payload
            })
            
    if replay_drops > 0 or crypto_drops > 0:
        verdict = "REPLAY_OR_CRYPTO_ATTACK_MITIGATED"
    elif policy_blocks > 0:
        verdict = "XFRM_POLICY_VIOLATION_BLOCKED"
    elif encap_count > 0 or decap_count > 0:
        verdict = "XFRM_IPSEC_TUNNEL_SECURE"
    else:
        verdict = "XFRM_ROUTING_PASSIVE"
        
    output = {
        "engine": "linux_kernel_xfrm_ipsec",
        "metrics": {
            "total_packets_processed": len(packets),
            "esp_encapsulated": encap_count,
            "esp_decapsulated": decap_count,
            "replay_drops": replay_drops,
            "crypto_integrity_drops": crypto_drops,
            "policy_blocks": policy_blocks,
            "active_sads": len(sa_runtime)
        },
        "verdict": verdict,
        "results": results
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
