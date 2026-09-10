# -*- coding: utf-8 -*-
"""
ZeliJudge Pro Track Problem #310
Linux Kernel Netfilter Connection Tracking & TCP State Engine (nf_conntrack_core.c)

Operationalizes the Linux Kernel Netfilter connection tracking subsystem:
1. Bidirectional 5-tuple matching (ORIGINAL vs REPLY tuple).
2. TCP state machine tracking (SYN_SENT -> SYN_RECV -> ESTABLISHED -> FIN_WAIT/CLOSE_WAIT -> TIME_WAIT/CLOSE).
3. Status bitflags: IPS_CONFIRMED, IPS_SEEN_REPLY, IPS_ASSURED.
4. Conntrack table capacity management (nf_conntrack_max) and early_drop() eviction policy.
5. SNAT/DNAT reply tuple rewriting and out-of-state packet handling (INVALID/DROPPED).
"""

import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


DEFAULT_TIMEOUTS = {
    "SYN_SENT": 120.0,
    "SYN_RECV": 60.0,
    "ESTABLISHED": 432000.0,
    "FIN_WAIT": 120.0,
    "CLOSE_WAIT": 60.0,
    "LAST_ACK": 30.0,
    "TIME_WAIT": 120.0,
    "CLOSE": 10.0
}


def tuple_key(t):
    return (t["src_ip"], t["dst_ip"], int(t["src_port"]), int(t["dst_port"]), str(t["protocol"]).upper())


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)

    config = data.get("config", {})
    max_entries = int(config.get("nf_conntrack_max", 65536))
    timeouts = dict(DEFAULT_TIMEOUTS)
    timeouts.update(config.get("timeouts", {}))
    nat_rules = data.get("nat_rules", [])

    packets = data.get("packets", [])

    conns = {}
    orig_index = {}
    reply_index = {}

    peak_size = 0
    early_drop_count = 0
    accepted_count = 0
    dropped_count = 0
    invalid_count = 0

    verdicts = []
    next_conn_num = 1
    last_ts = 0.0

    for idx, pkt in enumerate(packets, start=1):
        ts = float(pkt.get("timestamp", 0.0))
        last_ts = ts
        sip = pkt["src_ip"]
        dip = pkt["dst_ip"]
        sport = int(pkt["src_port"])
        dport = int(pkt["dst_port"])
        proto = pkt.get("protocol", "TCP").upper()
        flags = set(pkt.get("tcp_flags", []))
        payload_bytes = int(pkt.get("payload_bytes", 0))

        # 1. Expire timed-out connections prior to current packet timestamp
        expired_ids = [cid for cid, c in conns.items() if c["timeout_expires"] <= ts]
        for cid in expired_ids:
            c = conns.pop(cid)
            orig_index.pop(tuple_key(c["orig_tuple"]), None)
            reply_index.pop(tuple_key(c["reply_tuple"]), None)

        cur_tuple = {
            "src_ip": sip,
            "dst_ip": dip,
            "src_port": sport,
            "dst_port": dport,
            "protocol": proto
        }
        cur_k = tuple_key(cur_tuple)

        # 2. Lookup existing connection by tuple
        cid = None
        direction = None
        if cur_k in orig_index:
            cid = orig_index[cur_k]
            direction = "ORIGINAL"
        elif cur_k in reply_index:
            cid = reply_index[cur_k]
            direction = "REPLY"

        verdict = "ACCEPTED"
        ct_state = "INVALID"
        tcp_st = "NONE"
        reason = ""

        if cid is not None:
            conn = conns[cid]
            tcp_st = conn["tcp_state"]

            if direction == "ORIGINAL":
                conn["packets_orig"] += 1
                conn["bytes_orig"] += payload_bytes

                if tcp_st == "SYN_SENT" and "SYN" in flags and "ACK" not in flags:
                    pass
                elif tcp_st == "SYN_RECV" and "ACK" in flags:
                    tcp_st = "ESTABLISHED"
                    conn["status_flags"].add("IPS_ASSURED")
                elif tcp_st == "ESTABLISHED":
                    if "FIN" in flags:
                        tcp_st = "FIN_WAIT"
                    elif "RST" in flags:
                        tcp_st = "CLOSE"
                elif tcp_st == "CLOSE_WAIT":
                    if "FIN" in flags:
                        tcp_st = "LAST_ACK"
                elif tcp_st == "LAST_ACK" and "ACK" in flags:
                    tcp_st = "CLOSE"
                elif tcp_st == "TIME_WAIT" and "RST" in flags:
                    tcp_st = "CLOSE"
            else:  # REPLY
                conn["packets_reply"] += 1
                conn["bytes_reply"] += payload_bytes
                conn["status_flags"].add("IPS_SEEN_REPLY")

                if tcp_st == "SYN_SENT":
                    if "SYN" in flags and "ACK" in flags:
                        tcp_st = "SYN_RECV"
                    elif "RST" in flags:
                        tcp_st = "CLOSE"
                elif tcp_st == "ESTABLISHED":
                    if "FIN" in flags:
                        tcp_st = "CLOSE_WAIT"
                    elif "RST" in flags:
                        tcp_st = "CLOSE"
                elif tcp_st == "FIN_WAIT":
                    if "FIN" in flags or "ACK" in flags:
                        tcp_st = "TIME_WAIT"
                elif tcp_st == "LAST_ACK" and "ACK" in flags:
                    tcp_st = "CLOSE"

            conn["tcp_state"] = tcp_st
            conn["timeout_expires"] = ts + timeouts.get(tcp_st, 120.0)
            conn["last_updated_time"] = ts

            ct_state = "ESTABLISHED"
            accepted_count += 1
            reason = f"Direction {direction}, state transitioned to {tcp_st}"
        else:
            # 3. New connection attempt
            if "SYN" in flags and "ACK" not in flags:
                # Capacity check and early_drop
                if len(conns) >= max_entries:
                    candidates = []
                    for c_id, c in conns.items():
                        priority = 99
                        if c["tcp_state"] in ("TIME_WAIT", "CLOSE"):
                            priority = 1
                        elif "IPS_ASSURED" not in c["status_flags"]:
                            priority = 2
                        candidates.append((priority, c["last_updated_time"], c_id))

                    candidates.sort(key=lambda x: (x[0], x[1]))
                    if candidates and candidates[0][0] < 99:
                        drop_cid = candidates[0][2]
                        drop_conn = conns.pop(drop_cid)
                        orig_index.pop(tuple_key(drop_conn["orig_tuple"]), None)
                        reply_index.pop(tuple_key(drop_conn["reply_tuple"]), None)
                        early_drop_count += 1
                        reason_prefix = f"early_drop evicted {drop_cid}; "
                    else:
                        verdict = "DROPPED"
                        ct_state = "INVALID"
                        dropped_count += 1
                        reason = "nf_conntrack: table full, dropping packet"
                        verdicts.append({
                            "packet_index": idx,
                            "verdict": verdict,
                            "ct_state": ct_state,
                            "tcp_state": "NONE",
                            "reason": reason
                        })
                        peak_size = max(peak_size, len(conns))
                        continue
                else:
                    reason_prefix = ""

                cid = f"ct-{next_conn_num:04d}"
                next_conn_num += 1

                orig_t = dict(cur_tuple)
                reply_t = {
                    "src_ip": dip,
                    "dst_ip": sip,
                    "src_port": dport,
                    "dst_port": sport,
                    "protocol": proto
                }

                # NAT rule evaluation (SNAT)
                for nrule in nat_rules:
                    if nrule.get("type") == "SNAT" and sip == nrule.get("match_src_ip"):
                        new_snat_ip = nrule.get("to_source_ip", sip)
                        new_snat_port = int(nrule.get("to_source_port", sport))
                        reply_t["dst_ip"] = new_snat_ip
                        reply_t["dst_port"] = new_snat_port
                        break

                new_conn = {
                    "conn_id": cid,
                    "orig_tuple": orig_t,
                    "reply_tuple": reply_t,
                    "tcp_state": "SYN_SENT",
                    "status_flags": {"IPS_CONFIRMED"},
                    "timeout_expires": ts + timeouts.get("SYN_SENT", 120.0),
                    "last_updated_time": ts,
                    "packets_orig": 1,
                    "bytes_orig": payload_bytes,
                    "packets_reply": 0,
                    "bytes_reply": 0
                }

                conns[cid] = new_conn
                orig_index[tuple_key(orig_t)] = cid
                reply_index[tuple_key(reply_t)] = cid

                verdict = "ACCEPTED"
                ct_state = "NEW"
                tcp_st = "SYN_SENT"
                accepted_count += 1
                reason = reason_prefix + "New connection tracked"
            else:
                verdict = "INVALID"
                ct_state = "INVALID"
                invalid_count += 1
                reason = "Out of state non-SYN packet without established conntrack entry"

        peak_size = max(peak_size, len(conns))
        verdicts.append({
            "packet_index": idx,
            "verdict": verdict,
            "ct_state": ct_state,
            "tcp_state": tcp_st,
            "reason": reason
        })

    active_conns = []
    for cid in sorted(conns.keys()):
        c = conns[cid]
        active_conns.append({
            "conn_id": cid,
            "orig_tuple": c["orig_tuple"],
            "reply_tuple": c["reply_tuple"],
            "tcp_state": c["tcp_state"],
            "status_flags": sorted(list(c["status_flags"])),
            "packets_orig": c["packets_orig"],
            "bytes_orig": c["bytes_orig"],
            "packets_reply": c["packets_reply"],
            "bytes_reply": c["bytes_reply"],
            "remaining_ttl": round(max(0.0, c["timeout_expires"] - last_ts), 2) if packets else 0.0
        })

    established_cnt = sum(1 for c in conns.values() if c["tcp_state"] == "ESTABLISHED")

    output = {
        "summary": {
            "total_packets_processed": len(packets),
            "accepted_packets": accepted_count,
            "dropped_packets": dropped_count,
            "invalid_packets": invalid_count,
            "conntrack_table_peak_size": peak_size,
            "conntrack_table_final_size": len(conns),
            "early_drop_evictions_count": early_drop_count,
            "active_established_count": established_cnt
        },
        "packet_verdicts": verdicts,
        "active_connections": active_conns
    }

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    solve()
