"""
Problem 221: Distributed Storage: Reed-Solomon Erasure Coding vs Local Reconstruction Codes (LRC) & Degraded Read Tail Latency
"""
import sys
import json
import math

def simulate_erasure_coding(data):
    config = data.get("config", {})
    scheme = config.get("storage_scheme", "REED_SOLOMON")
    chunk_size_mb = float(config.get("chunk_size_mb", 64.0))
    read_timeout_ms = float(config.get("read_timeout_ms", 150.0))
    decode_cpu_ms = float(config.get("decode_cpu_overhead_ms", 5.0))
    hedging_enabled = bool(config.get("speculative_hedged_reads_enabled", False))

    k = int(config.get("k", 10))
    m = int(config.get("m", 4))
    l = int(config.get("l", 2))
    g = int(config.get("g", 2))
    group_size = k // l if l > 0 else k

    nodes = data.get("nodes", {})
    reads = data.get("read_requests", [])

    total_reads = len(reads)
    degraded_reads = 0
    read_sla_violations = 0
    unrecoverable_failures = 0
    total_reconstruction_network_mb = 0.0
    latencies = []

    for req in reads:
        target_idx = int(req.get("target_chunk_index", 0))
        mapping = req.get("chunk_to_node_map", [])

        target_node_id = mapping[target_idx]
        target_node = nodes.get(target_node_id, {"status": "HEALTHY", "latency_ms": 15.0})

        if target_node.get("status") == "HEALTHY":
            lat = target_node.get("straggler_latency_ms", 200.0) if target_node.get("is_straggler") else target_node.get("latency_ms", 15.0)
            latencies.append(lat)
            if lat > read_timeout_ms:
                read_sla_violations += 1
            continue

        # Degraded Read
        degraded_reads += 1

        if scheme == "REED_SOLOMON":
            candidate_node_ids = [nid for i, nid in enumerate(mapping) if i != target_idx]
            healthy_lats = []
            for nid in candidate_node_ids:
                n = nodes.get(nid, {})
                if n.get("status") == "HEALTHY":
                    lat = n.get("straggler_latency_ms", 200.0) if n.get("is_straggler") else n.get("latency_ms", 15.0)
                    healthy_lats.append(lat)

            if len(healthy_lats) < k:
                unrecoverable_failures += 1
                latencies.append(read_timeout_ms * 2.0)
                read_sla_violations += 1
                continue

            if hedging_enabled and len(healthy_lats) >= k + 1:
                healthy_lats.sort()
                selected_lats = healthy_lats[:k]
            else:
                orig_lats = []
                for nid in candidate_node_ids:
                    n = nodes.get(nid, {})
                    if n.get("status") == "HEALTHY":
                        lat = n.get("straggler_latency_ms", 200.0) if n.get("is_straggler") else n.get("latency_ms", 15.0)
                        orig_lats.append(lat)
                        if len(orig_lats) == k:
                            break
                selected_lats = orig_lats

            recon_lat = max(selected_lats) + decode_cpu_ms
            latencies.append(recon_lat)
            total_reconstruction_network_mb += k * chunk_size_mb
            if recon_lat > read_timeout_ms:
                read_sla_violations += 1

        elif scheme == "LOCAL_RECONSTRUCTION_CODES":
            if target_idx < k:
                group_id = target_idx // group_size
                group_data_indices = list(range(group_id * group_size, (group_id + 1) * group_size))
                local_parity_idx = k + group_id
                local_group_indices = group_data_indices + [local_parity_idx]
            elif target_idx < k + l:
                group_id = target_idx - k
                group_data_indices = list(range(group_id * group_size, (group_id + 1) * group_size))
                local_parity_idx = target_idx
                local_group_indices = group_data_indices + [local_parity_idx]
            else:
                group_id = -1
                local_group_indices = []

            local_candidate_indices = [idx for idx in local_group_indices if idx != target_idx]
            local_healthy = []
            for idx in local_candidate_indices:
                nid = mapping[idx]
                n = nodes.get(nid, {})
                if n.get("status") == "HEALTHY":
                    lat = n.get("straggler_latency_ms", 200.0) if n.get("is_straggler") else n.get("latency_ms", 15.0)
                    local_healthy.append(lat)

            if len(local_healthy) == group_size:
                # Local reconstruction
                recon_lat = max(local_healthy) + (decode_cpu_ms * 0.5)
                latencies.append(recon_lat)
                total_reconstruction_network_mb += group_size * chunk_size_mb
                if recon_lat > read_timeout_ms:
                    read_sla_violations += 1
            else:
                # Global reconstruction
                all_candidate_indices = [idx for idx in range(len(mapping)) if idx != target_idx]
                global_healthy = []
                for idx in all_candidate_indices:
                    nid = mapping[idx]
                    n = nodes.get(nid, {})
                    if n.get("status") == "HEALTHY":
                        lat = n.get("straggler_latency_ms", 200.0) if n.get("is_straggler") else n.get("latency_ms", 15.0)
                        global_healthy.append(lat)

                if len(global_healthy) < k:
                    unrecoverable_failures += 1
                    latencies.append(read_timeout_ms * 2.0)
                    read_sla_violations += 1
                else:
                    if hedging_enabled and len(global_healthy) >= k + 1:
                        global_healthy.sort()
                        selected_lats = global_healthy[:k]
                    else:
                        selected_lats = []
                        for idx in all_candidate_indices:
                            nid = mapping[idx]
                            n = nodes.get(nid, {})
                            if n.get("status") == "HEALTHY":
                                lat = n.get("straggler_latency_ms", 200.0) if n.get("is_straggler") else n.get("latency_ms", 15.0)
                                selected_lats.append(lat)
                                if len(selected_lats) == k:
                                    break

                    recon_lat = max(selected_lats) + decode_cpu_ms
                    latencies.append(recon_lat)
                    total_reconstruction_network_mb += k * chunk_size_mb
                    if recon_lat > read_timeout_ms:
                        read_sla_violations += 1

    latencies.sort()
    p99_idx = min(len(latencies) - 1, int(math.ceil(0.99 * len(latencies))) - 1)
    p99_lat = latencies[p99_idx] if latencies else 0.0
    avg_recon_network = (total_reconstruction_network_mb / degraded_reads) if degraded_reads > 0 else 0.0

    if unrecoverable_failures > 0:
        status = "FAILED"
        verdict = "DATA_LOSS_UNRECOVERABLE"
    elif read_sla_violations > 0 or p99_lat > read_timeout_ms:
        status = "FAILED"
        verdict = "DEGRADED_READ_TAIL_LATENCY_STALL"
    elif scheme == "LOCAL_RECONSTRUCTION_CODES" and degraded_reads > 0 and avg_recon_network <= (group_size * chunk_size_mb):
        status = "SUCCESS"
        verdict = "OPTIMAL_LRC_LOCAL_RECONSTRUCTION"
    elif scheme == "LOCAL_RECONSTRUCTION_CODES" and degraded_reads > 0 and avg_recon_network > (group_size * chunk_size_mb):
        status = "SUCCESS"
        verdict = "LRC_GLOBAL_RECONSTRUCTION_FALLBACK"
    elif hedging_enabled and degraded_reads > 0 and read_sla_violations == 0:
        status = "SUCCESS"
        verdict = "OPTIMAL_HEDGED_DEGRADED_READ"
    elif scheme == "REED_SOLOMON" and avg_recon_network >= 500.0:
        status = "SUCCESS"
        verdict = "HIGH_NETWORK_AMPLIFICATION_WARNING"
    else:
        status = "SUCCESS"
        verdict = "NORMAL_READ_WORKLOAD"

    return {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "storage_scheme": scheme,
            "total_reads": total_reads,
            "degraded_reads": degraded_reads,
            "read_sla_violations": read_sla_violations,
            "unrecoverable_failures": unrecoverable_failures,
            "p99_latency_ms": round(p99_lat, 2),
            "average_reconstruction_network_mb": round(avg_recon_network, 2)
        }
    }

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            return
        data = json.loads(raw_input)
        result = simulate_erasure_coding(data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
