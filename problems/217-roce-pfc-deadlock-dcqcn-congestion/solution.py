import sys
import json
from collections import deque

def simulate_roce_fabric(data):
    config = data.get("config", {})
    mode = config.get("mode", "PFC_ONLY")  # "PFC_ONLY", "PFC_WATCHDOG", "DCQCN", "NO_FLOW_CONTROL"
    sim_duration_us = float(config.get("simulation_duration_us", 5000.0))
    time_step_us = float(config.get("time_step_us", 10.0))

    queue_capacity_kb = float(config.get("queue_capacity_kb", 512))
    pfc_pause_thresh_kb = float(config.get("pfc_pause_thresh_kb", 256))
    pfc_resume_thresh_kb = float(config.get("pfc_resume_thresh_kb", 128))
    watchdog_timeout_us = float(config.get("watchdog_timeout_us", 1000.0))

    k_min_kb = float(config.get("dcqcn_k_min_kb", 80))
    k_max_kb = float(config.get("dcqcn_k_max_kb", 180))
    cnp_interval_us = float(config.get("dcqcn_cnp_interval_us", 50.0))
    dcqcn_alpha_g = float(config.get("dcqcn_alpha_g", 0.25))
    dcqcn_rai_gbps = float(config.get("dcqcn_rai_gbps", 2.0))

    topology = data.get("topology", {})
    links_cfg = topology.get("links", [])
    flows_cfg = data.get("flows", [])

    links = {}
    for l in links_cfg:
        lid = l["id"]
        bw = float(l.get("bandwidth_gbps", 100.0))
        links[lid] = {
            "id": lid,
            "src": l["src"],
            "dst": l["dst"],
            "bandwidth_gbps": bw,
            "kb_per_us": bw * (1000.0 / 8192.0),
            "queue_kb": 0.0,
            "is_paused": False,
            "is_pausing_upstream": False,
            "paused_since_us": None,
            "pfc_pause_sent_count": 0,
            "pfc_resume_sent_count": 0,
            "total_bytes_transmitted": 0,
            "total_bytes_dropped": 0,
            "watchdog_triggered_count": 0,
            "packet_queue": deque()
        }

    flows = {}
    for f in flows_cfg:
        fid = f["id"]
        init_rate = float(f.get("target_rate_gbps", 100.0))
        flows[fid] = {
            "id": fid,
            "src": f["src"],
            "dst": f["dst"],
            "path": f["path"],
            "target_rate_gbps": init_rate,
            "current_rate_gbps": init_rate,
            "is_source_paused": False,
            "dcqcn_alpha": 1.0,
            "last_cnp_received_us": -9999.0,
            "total_bytes_sent": 0,
            "total_bytes_delivered": 0,
            "packet_loss_count": 0
        }

    upstream_links = {lid: set() for lid in links}
    ingress_flows = {lid: set() for lid in links}
    for fid, fl in flows.items():
        path = fl["path"]
        if path:
            ingress_flows[path[0]].add(fid)
            for i in range(len(path) - 1):
                upstream_links[path[i+1]].add(path[i])

    current_time_us = 0.0
    deadlock_detected = False
    deadlock_start_time_us = None
    allreduce_frozen = False

    while current_time_us < sim_duration_us:
        current_time_us += time_step_us

        # 1. Flow packet generation (at host ingress)
        for fid, fl in flows.items():
            first_link_id = fl["path"][0]
            first_link = links[first_link_id]

            rate_kb_per_us = fl["current_rate_gbps"] * (1000.0 / 8192.0)
            generated_kb = rate_kb_per_us * time_step_us

            if mode in ["PFC_ONLY", "PFC_WATCHDOG"] and fl["is_source_paused"]:
                continue

            fl["total_bytes_sent"] += int(generated_kb * 1024)

            if first_link["queue_kb"] + generated_kb <= queue_capacity_kb:
                first_link["queue_kb"] += generated_kb
                is_ecn = False
                if mode == "DCQCN":
                    if first_link["queue_kb"] >= k_max_kb:
                        is_ecn = True
                    elif first_link["queue_kb"] >= k_min_kb:
                        is_ecn = True
                first_link["packet_queue"].append({"flow_id": fid, "hop_idx": 0, "size_kb": generated_kb, "ecn": is_ecn})
            else:
                first_link["total_bytes_dropped"] += int(generated_kb * 1024)
                fl["packet_loss_count"] += 1

        # 2. Check PFC Thresholds and Watchdog on all links
        for lid, lk in links.items():
            if mode in ["PFC_ONLY", "PFC_WATCHDOG"]:
                if lk["queue_kb"] >= pfc_pause_thresh_kb and not lk["is_pausing_upstream"]:
                    lk["is_pausing_upstream"] = True
                    lk["pfc_pause_sent_count"] += 1

                    for u_lid in upstream_links[lid]:
                        links[u_lid]["is_paused"] = True
                        if links[u_lid]["paused_since_us"] is None:
                            links[u_lid]["paused_since_us"] = current_time_us
                    for u_fid in ingress_flows[lid]:
                        flows[u_fid]["is_source_paused"] = True

                elif lk["queue_kb"] <= pfc_resume_thresh_kb and lk["is_pausing_upstream"]:
                    lk["is_pausing_upstream"] = False
                    lk["pfc_resume_sent_count"] += 1

                    for u_lid in upstream_links[lid]:
                        other_pause = any(links[d]["is_pausing_upstream"] for d in links if u_lid in upstream_links[d] and d != lid)
                        if not other_pause:
                            links[u_lid]["is_paused"] = False
                            links[u_lid]["paused_since_us"] = None
                    for u_fid in ingress_flows[lid]:
                        flows[u_fid]["is_source_paused"] = False

                # Watchdog check
                if mode == "PFC_WATCHDOG" and lk["is_paused"] and lk["paused_since_us"] is not None:
                    paused_dur = current_time_us - lk["paused_since_us"]
                    if paused_dur >= watchdog_timeout_us:
                        lk["watchdog_triggered_count"] += 1
                        dropped_kb = lk["queue_kb"]
                        lk["total_bytes_dropped"] += int(dropped_kb * 1024)
                        lk["queue_kb"] = 0.0
                        lk["packet_queue"].clear()
                        lk["is_paused"] = False
                        lk["paused_since_us"] = None
                        lk["is_pausing_upstream"] = False
                        for u_lid in upstream_links[lid]:
                            links[u_lid]["is_paused"] = False
                            links[u_lid]["paused_since_us"] = None
                        for u_fid in ingress_flows[lid]:
                            flows[u_fid]["is_source_paused"] = False

        # Deadlock check
        paused_count = sum(1 for l in links.values() if l["is_paused"])
        if paused_count >= len(links) and len(links) >= 3:
            if deadlock_start_time_us is None:
                deadlock_start_time_us = current_time_us
            elif (current_time_us - deadlock_start_time_us) >= 400.0:
                deadlock_detected = True
                if mode == "PFC_ONLY":
                    allreduce_frozen = True
        else:
            deadlock_start_time_us = None

        # 3. Process Link Transmissions (Egress draining)
        for lid, lk in links.items():
            if lk["is_paused"] and mode in ["PFC_ONLY", "PFC_WATCHDOG"]:
                continue

            avail_kb = lk["kb_per_us"] * time_step_us
            transmitted_kb = 0.0

            while lk["packet_queue"] and transmitted_kb < avail_kb:
                pkt = lk["packet_queue"][0]
                tx_kb = min(pkt["size_kb"], avail_kb - transmitted_kb)

                fid = pkt["flow_id"]
                fl = flows[fid]
                hop_idx = pkt["hop_idx"]

                if hop_idx + 1 >= len(fl["path"]):
                    transmitted_kb += tx_kb
                    pkt["size_kb"] -= tx_kb
                    fl["total_bytes_delivered"] += int(tx_kb * 1024)
                    if mode == "DCQCN" and pkt["ecn"]:
                        if current_time_us - fl["last_cnp_received_us"] >= cnp_interval_us:
                            fl["last_cnp_received_us"] = current_time_us
                            alpha = fl["dcqcn_alpha"]
                            fl["current_rate_gbps"] = max(10.0, fl["current_rate_gbps"] * (1.0 - alpha / 2.0))
                            fl["dcqcn_alpha"] = min(1.0, (1.0 - dcqcn_alpha_g) * alpha + dcqcn_alpha_g)
                    if pkt["size_kb"] <= 0.001:
                        lk["packet_queue"].popleft()
                else:
                    next_link_id = fl["path"][hop_idx + 1]
                    next_link = links[next_link_id]

                    if mode in ["PFC_ONLY", "PFC_WATCHDOG"]:
                        if next_link["queue_kb"] + tx_kb <= queue_capacity_kb:
                            transmitted_kb += tx_kb
                            pkt["size_kb"] -= tx_kb
                            next_link["queue_kb"] += tx_kb
                            next_link["packet_queue"].append({"flow_id": fid, "hop_idx": hop_idx + 1, "size_kb": tx_kb, "ecn": pkt["ecn"]})
                            if pkt["size_kb"] <= 0.001:
                                lk["packet_queue"].popleft()
                        else:
                            break
                    elif mode == "DCQCN":
                        if next_link["queue_kb"] + tx_kb <= queue_capacity_kb:
                            transmitted_kb += tx_kb
                            pkt["size_kb"] -= tx_kb
                            next_link["queue_kb"] += tx_kb
                            is_ecn = pkt["ecn"]
                            if next_link["queue_kb"] >= k_min_kb:
                                is_ecn = True
                            next_link["packet_queue"].append({"flow_id": fid, "hop_idx": hop_idx + 1, "size_kb": tx_kb, "ecn": is_ecn})
                            if pkt["size_kb"] <= 0.001:
                                lk["packet_queue"].popleft()
                        else:
                            break
                    else:
                        transmitted_kb += tx_kb
                        pkt["size_kb"] -= tx_kb
                        if next_link["queue_kb"] + tx_kb <= queue_capacity_kb:
                            next_link["queue_kb"] += tx_kb
                            next_link["packet_queue"].append({"flow_id": fid, "hop_idx": hop_idx + 1, "size_kb": tx_kb, "ecn": False})
                        else:
                            next_link["total_bytes_dropped"] += int(tx_kb * 1024)
                            fl["packet_loss_count"] += 1
                        if pkt["size_kb"] <= 0.001:
                            lk["packet_queue"].popleft()

            lk["queue_kb"] = max(0.0, lk["queue_kb"] - transmitted_kb)
            lk["total_bytes_transmitted"] += int(transmitted_kb * 1024)

        # 4. DCQCN Rate Recovery (Additive Increase)
        if mode == "DCQCN":
            for fid, fl in flows.items():
                if current_time_us - fl["last_cnp_received_us"] > cnp_interval_us:
                    if fl["current_rate_gbps"] < fl["target_rate_gbps"]:
                        fl["current_rate_gbps"] = min(fl["target_rate_gbps"], fl["current_rate_gbps"] + dcqcn_rai_gbps * (time_step_us / 100.0))
                        fl["dcqcn_alpha"] = max(0.01, fl["dcqcn_alpha"] * (1.0 - dcqcn_alpha_g))

    dur_sec = sim_duration_us / 1_000_000.0
    total_sent_bytes = sum(f["total_bytes_sent"] for f in flows.values())
    total_deliv_bytes = sum(f["total_bytes_delivered"] for f in flows.values())
    total_drop_bytes = sum(l["total_bytes_dropped"] for l in links.values())
    total_pfc_pause = sum(l["pfc_pause_sent_count"] for l in links.values())
    total_watchdog_triggers = sum(l["watchdog_triggered_count"] for l in links.values())

    tput_gbps = (total_deliv_bytes * 8.0) / (dur_sec * 1e9)
    loss_rate_pct = (total_drop_bytes / total_sent_bytes * 100.0) if total_sent_bytes > 0 else 0.0

    if mode == "PFC_ONLY":
        if allreduce_frozen:
            verdict = "PFC_DEADLOCK_DETECTED_ALLREDUCE_FREEZE"
            status = "FAILED"
        elif total_pfc_pause >= 20:
            verdict = "PFC_PAUSE_STORM_HOL_BLOCKING"
            status = "FAILED"
        else:
            verdict = "NORMAL_PFC_OPERATION"
            status = "SUCCESS"
    elif mode == "PFC_WATCHDOG":
        if total_watchdog_triggers > 0:
            verdict = "PFC_DEADLOCK_RESOLVED_WATCHDOG_DRAIN"
            status = "SUCCESS"
        else:
            verdict = "NORMAL_PFC_WATCHDOG_MONITORING"
            status = "SUCCESS"
    elif mode == "DCQCN":
        if total_pfc_pause == 0 and loss_rate_pct == 0.0 and tput_gbps >= 35.0:
            verdict = "OPTIMAL_DCQCN_LOSSLESS_TRANSMISSION"
            status = "SUCCESS"
        else:
            verdict = "DCQCN_SUBOPTIMAL"
            status = "SUCCESS"
    elif mode == "NO_FLOW_CONTROL":
        verdict = "NO_FLOW_CONTROL_PACKET_LOSS_STORM"
        status = "FAILED"
    else:
        verdict = "UNKNOWN_MODE"
        status = "FAILED"

    return {
        "status": status,
        "verdict": verdict,
        "mode": mode,
        "metrics": {
            "total_sent_bytes": total_sent_bytes,
            "total_delivered_bytes": total_deliv_bytes,
            "total_dropped_bytes": total_drop_bytes,
            "packet_loss_rate_pct": round(min(100.0, loss_rate_pct), 2),
            "effective_throughput_gbps": round(tput_gbps, 2),
            "total_pfc_pause_frames": total_pfc_pause,
            "total_watchdog_recoveries": total_watchdog_triggers,
            "deadlock_detected": deadlock_detected,
            "allreduce_frozen": allreduce_frozen
        }
    }

def main():
    raw_input = sys.stdin.read()
    if not raw_input.strip():
        return
    data = json.loads(raw_input)
    result = simulate_roce_fabric(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
