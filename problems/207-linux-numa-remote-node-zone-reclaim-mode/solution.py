#!/usr/bin/env python3
"""
ZeliJudge Problem #207: Linux Kernel NUMA - Remote Node Access Latency vs zone_reclaim_mode Stalls & numactl Memory Policies
리눅스 커널 NUMA: 원격 노드 접근 지연 vs zone_reclaim_mode 직접 회수 스톨과 numactl 메모리 정책

Reference Implementation
"""

import sys
import json
from typing import Dict, Any, List

def simulate_numa(data: Dict[str, Any]) -> Dict[str, Any]:
    topology = data["numa_topology"]
    nodes = topology["nodes"]
    mem_per_node_mb = topology["memory_per_node_mb"]
    if isinstance(mem_per_node_mb, int):
        node_capacity = {n: float(mem_per_node_mb) for n in nodes}
    else:
        node_capacity = {int(k): float(v) for k, v in mem_per_node_mb.items()}

    watermarks = topology.get("watermarks_mb", {"min_mb": 256.0, "low_mb": 512.0, "high_mb": 1024.0})
    low_watermark = watermarks["low_mb"]
    min_watermark = watermarks["min_mb"]

    distance_matrix = topology.get("distance_matrix", [[10, 20], [20, 10]])
    latencies = topology.get("latencies_ns", {"local_access_ns": 60.0, "remote_access_ns": 140.0})
    local_lat = latencies["local_access_ns"]

    reclaim_penalty_ms = topology.get("reclaim_penalties", {}).get("direct_reclaim_latency_ms", 50.0)
    migration_penalty_us = topology.get("reclaim_penalties", {}).get("page_migration_latency_us", 10.0)

    kernel_cfg = data["kernel_config"]
    zone_reclaim_mode = kernel_cfg.get("zone_reclaim_mode", 0)  # 0: remote fallback, 1: local reclaim
    policy_cfg = kernel_cfg.get("memory_policy", {"mode": "MPOL_DEFAULT"})
    policy_mode = policy_cfg.get("mode", "MPOL_DEFAULT")
    target_nodes = policy_cfg.get("target_nodes", nodes)
    numa_balancing = kernel_cfg.get("numa_balancing", False)

    # State tracking per node
    node_used = {n: 0.0 for n in nodes}
    node_reclaimable = {n: 0.0 for n in nodes}
    node_anon = {n: 0.0 for n in nodes}

    # Pre-populate initial usage if provided
    for n_str, usage in topology.get("initial_usage_mb", {}).items():
        n = int(n_str)
        node_anon[n] = float(usage.get("anon_mb", 0.0))
        node_reclaimable[n] = float(usage.get("page_cache_mb", 0.0))
        node_used[n] = node_anon[n] + node_reclaimable[n]

    # Metrics
    total_alloc_requests = 0
    successful_allocations = 0
    oom_events = 0
    direct_reclaim_events = 0
    direct_reclaim_total_stall_ms = 0.0
    remote_allocation_count = 0
    local_allocation_count = 0
    total_allocated_mb = 0.0

    # Access stats
    total_access_ops = 0
    local_access_ops = 0
    remote_access_ops = 0
    total_access_latency_ns = 0.0
    page_migrations = 0

    # Allocation registry: alloc_id -> dict of {node_id: size_mb, ...}
    allocations = {}

    for op in data.get("workload", []):
        op_type = op["op"]

        if op_type == "ALLOC":
            total_alloc_requests += 1
            alloc_id = op.get("alloc_id", f"alloc_{total_alloc_requests}")
            req_size = float(op["size_mb"])
            exec_node = int(op.get("node_id", 0))

            alloc_plan = {}  # node -> size_mb

            if policy_mode == "MPOL_DEFAULT":
                free_on_exec = node_capacity[exec_node] - node_used[exec_node]
                if free_on_exec - req_size >= low_watermark:
                    alloc_plan[exec_node] = req_size
                else:
                    if zone_reclaim_mode == 1:
                        reclaimable = node_reclaimable[exec_node]
                        needed_reclaim = (low_watermark + req_size) - free_on_exec
                        actual_reclaimed = min(reclaimable, needed_reclaim)

                        direct_reclaim_events += 1
                        stall = reclaim_penalty_ms * (1.0 + (actual_reclaimed / 1024.0))
                        direct_reclaim_total_stall_ms += stall

                        node_reclaimable[exec_node] -= actual_reclaimed
                        node_used[exec_node] -= actual_reclaimed
                        free_on_exec = node_capacity[exec_node] - node_used[exec_node]

                        if free_on_exec - req_size >= min_watermark:
                            alloc_plan[exec_node] = req_size
                        else:
                            oom_events += 1
                            continue
                    else:
                        local_alloc = max(0.0, free_on_exec - low_watermark)
                        remote_needed = req_size - local_alloc

                        remote_candidates = [n for n in nodes if n != exec_node]
                        remote_candidates.sort(key=lambda n: node_capacity[n] - node_used[n], reverse=True)

                        allocated_remotely = False
                        for rem_n in remote_candidates:
                            rem_free = node_capacity[rem_n] - node_used[rem_n]
                            if rem_free - remote_needed >= low_watermark:
                                alloc_plan[exec_node] = local_alloc
                                alloc_plan[rem_n] = remote_needed
                                allocated_remotely = True
                                break

                        if not allocated_remotely:
                            for rem_n in remote_candidates:
                                rem_free = node_capacity[rem_n] - node_used[rem_n]
                                if rem_free - remote_needed >= min_watermark:
                                    alloc_plan[exec_node] = local_alloc
                                    alloc_plan[rem_n] = remote_needed
                                    allocated_remotely = True
                                    break

                        if not allocated_remotely and not alloc_plan:
                            oom_events += 1
                            continue

            elif policy_mode == "MPOL_BIND":
                bound_node = target_nodes[0]
                free_bound = node_capacity[bound_node] - node_used[bound_node]
                if free_bound - req_size >= min_watermark:
                    alloc_plan[bound_node] = req_size
                else:
                    oom_events += 1
                    continue

            elif policy_mode == "MPOL_INTERLEAVE":
                n_targets = len(target_nodes)
                chunk_size = req_size / n_targets
                can_fit = True
                for n in target_nodes:
                    free_n = node_capacity[n] - node_used[n]
                    if free_n - chunk_size < min_watermark:
                        can_fit = False
                        break
                if can_fit:
                    for n in target_nodes:
                        alloc_plan[n] = chunk_size
                else:
                    oom_events += 1
                    continue

            elif policy_mode == "MPOL_PREFERRED":
                pref_node = target_nodes[0]
                free_pref = node_capacity[pref_node] - node_used[pref_node]
                if free_pref - req_size >= low_watermark:
                    alloc_plan[pref_node] = req_size
                else:
                    other_nodes = [n for n in nodes if n != pref_node]
                    other_nodes.sort(key=lambda n: node_capacity[n] - node_used[n], reverse=True)
                    fit = False
                    for n in other_nodes:
                        free_n = node_capacity[n] - node_used[n]
                        if free_n - req_size >= min_watermark:
                            alloc_plan[n] = req_size
                            fit = True
                            break
                    if not fit:
                        oom_events += 1
                        continue

            if alloc_plan:
                allocations[alloc_id] = alloc_plan
                successful_allocations += 1
                total_allocated_mb += req_size
                for n, sz in alloc_plan.items():
                    node_anon[n] += sz
                    node_used[n] += sz
                    if n == exec_node:
                        local_allocation_count += 1
                    else:
                        remote_allocation_count += 1

        elif op_type == "ACCESS":
            alloc_id = op["alloc_id"]
            exec_node = int(op.get("node_id", 0))
            access_count = int(op.get("access_count", 10000))

            if alloc_id not in allocations:
                continue

            alloc_dist = allocations[alloc_id]
            tot_alloc_mb = sum(alloc_dist.values())

            for n, sz in list(alloc_dist.items()):
                ratio = sz / tot_alloc_mb if tot_alloc_mb > 0 else 0
                ops_on_node = int(access_count * ratio)
                total_access_ops += ops_on_node

                if n == exec_node:
                    local_access_ops += ops_on_node
                    total_access_latency_ns += ops_on_node * local_lat
                else:
                    remote_access_ops += ops_on_node
                    dist = distance_matrix[exec_node][n]
                    lat = local_lat * (dist / 10.0)
                    total_access_latency_ns += ops_on_node * lat

                    if numa_balancing and ratio > 0.3:
                        free_exec = node_capacity[exec_node] - node_used[exec_node]
                        migratable_mb = min(sz * 0.5, max(0.0, free_exec - low_watermark))
                        if migratable_mb > 0:
                            node_used[n] -= migratable_mb
                            node_anon[n] -= migratable_mb
                            alloc_dist[n] -= migratable_mb

                            node_used[exec_node] += migratable_mb
                            node_anon[exec_node] += migratable_mb
                            alloc_dist[exec_node] = alloc_dist.get(exec_node, 0.0) + migratable_mb

                            migrated_pages = int((migratable_mb * 1024 * 1024) / 4096)
                            page_migrations += migrated_pages
                            total_access_latency_ns += migrated_pages * (migration_penalty_us * 1000.0)

    avg_access_latency_ns = round(total_access_latency_ns / total_access_ops, 2) if total_access_ops > 0 else 0.0
    remote_access_ratio = round((remote_access_ops / total_access_ops) * 100.0, 2) if total_access_ops > 0 else 0.0

    if oom_events > 0:
        verdict = "NUMA_NODE_BIND_OOM"
    elif direct_reclaim_events > 0 and direct_reclaim_total_stall_ms >= 50.0:
        verdict = "NUMA_ZONE_RECLAIM_DIRECT_STALL"
    elif policy_mode == "MPOL_INTERLEAVE":
        verdict = "OPTIMAL_NUMA_INTERLEAVED_BALANCED"
    elif numa_balancing and page_migrations > 0:
        verdict = "NUMA_AUTONUMA_PAGE_MIGRATED"
    elif remote_allocation_count > 0:
        verdict = "NUMA_REMOTE_SPILLOVER_NO_STALL"
    else:
        verdict = "NUMA_LOCAL_OPTIMAL"

    output = {
        "status": "SUCCESS" if oom_events == 0 else "FAILED",
        "verdict": verdict,
        "policy_mode": policy_mode,
        "metrics": {
            "total_alloc_requests": total_alloc_requests,
            "successful_allocations": successful_allocations,
            "oom_events": oom_events,
            "total_allocated_mb": round(total_allocated_mb, 2),
            "local_allocation_count": local_allocation_count,
            "remote_allocation_count": remote_allocation_count,
            "direct_reclaim_events": direct_reclaim_events,
            "direct_reclaim_total_stall_ms": round(direct_reclaim_total_stall_ms, 2),
            "total_access_ops": total_access_ops,
            "local_access_ops": local_access_ops,
            "remote_access_ops": remote_access_ops,
            "remote_access_ratio_pct": remote_access_ratio,
            "average_access_latency_ns": avg_access_latency_ns,
            "page_migrations_count": page_migrations
        },
        "node_states": {}
    }

    for n in nodes:
        output["node_states"][f"node_{n}"] = {
            "capacity_mb": node_capacity[n],
            "used_mb": round(node_used[n], 2),
            "free_mb": round(node_capacity[n] - node_used[n], 2),
            "anon_mb": round(node_anon[n], 2),
            "page_cache_mb": round(node_reclaimable[n], 2)
        }

    return output

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_numa(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
