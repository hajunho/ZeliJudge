# -*- coding: utf-8 -*-
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PAGE_SIZE = 4096

def simulate_ksm(ksmd_config, vms, scan_passes=3):
    pages_to_scan = ksmd_config.get("pages_to_scan", 200)
    sleep_millisecs = ksmd_config.get("sleep_millisecs", 20)
    merge_across_nodes = ksmd_config.get("merge_across_nodes", False)
    max_page_sharing = ksmd_config.get("max_page_sharing", 256)
    cow_break_cost_us = ksmd_config.get("cow_break_cost_us", 4.0)
    scan_cost_us = ksmd_config.get("scan_cost_us", 0.4)

    all_pages = []
    for vm in vms:
        vm_id = vm["vm_id"]
        numa = vm.get("numa_node", 0)
        for p in vm["pages"]:
            all_pages.append({
                "vm_id": vm_id,
                "numa_node": numa,
                "page_id": p["page_id"],
                "content_hash": p["content_hash"],
                "write_frequency": p.get("write_frequency", 0.0),
                "is_mergeable": p.get("is_mergeable", True),
                "is_shared": False,
                "canonical_ksm_id": None
            })

    total_mergeable = len([p for p in all_pages if p["is_mergeable"]])
    if total_mergeable == 0:
        return {
            "metrics": {
                "total_mergeable_pages": 0,
                "pages_shared": 0,
                "pages_sharing": 0,
                "pages_unshared": 0,
                "cow_breaks": 0,
                "memory_saved_mb": 0.0,
                "dedup_ratio": 0.0,
                "cpu_overhead_pct": 0.0,
                "cross_node_accesses": 0
            },
            "status": "NO_MERGEABLE_PAGES",
            "bottlenecks": [],
            "stable_tree_summary": []
        }

    stable_tree = {}
    unstable_tree = {}

    total_scanned_count = 0
    total_cow_breaks = 0
    total_cross_node_accesses = 0

    effective_scan_capacity = pages_to_scan * scan_passes
    scan_starvation = effective_scan_capacity < total_mergeable

    for pass_idx in range(scan_passes):
        unstable_tree.clear()
        
        if scan_starvation:
            start_idx = (pass_idx * pages_to_scan) % total_mergeable
            end_idx = min(total_mergeable, start_idx + pages_to_scan)
            scanned_pages = [p for p in all_pages if p["is_mergeable"]][start_idx:end_idx]
        else:
            scanned_pages = [p for p in all_pages if p["is_mergeable"]]

        for p in scanned_pages:
            total_scanned_count += 1
            if p["is_shared"]:
                continue

            key = p["content_hash"] if merge_across_nodes else (p["numa_node"], p["content_hash"])

            if key in stable_tree:
                st_entry = stable_tree[key]
                if len(st_entry["members"]) < max_page_sharing:
                    st_entry["members"].add((p["vm_id"], p["page_id"]))
                    p["is_shared"] = True
                    p["canonical_ksm_id"] = st_entry["canonical_id"]
                    if merge_across_nodes and st_entry["numa_node"] != p["numa_node"]:
                        total_cross_node_accesses += 1
            elif key in unstable_tree:
                prev_vm, prev_pid, prev_numa = unstable_tree.pop(key)
                canonical_id = f"KSM_PAGE_{len(stable_tree)+1:04d}"
                stable_tree[key] = {
                    "canonical_id": canonical_id,
                    "numa_node": prev_numa,
                    "content_hash": p["content_hash"],
                    "members": {(prev_vm, prev_pid), (p["vm_id"], p["page_id"])}
                }
                p["is_shared"] = True
                p["canonical_ksm_id"] = canonical_id
                for op in all_pages:
                    if op["vm_id"] == prev_vm and op["page_id"] == prev_pid:
                        op["is_shared"] = True
                        op["canonical_ksm_id"] = canonical_id
                        break
                if merge_across_nodes and prev_numa != p["numa_node"]:
                    total_cross_node_accesses += 1
            else:
                unstable_tree[key] = (p["vm_id"], p["page_id"], p["numa_node"])

        # CoW Break Simulation at end of pass
        for p in all_pages:
            if p["is_shared"] and p["write_frequency"] > 0:
                write_prob = p["write_frequency"] * (sleep_millisecs / 100.0)
                if write_prob >= 0.4:
                    total_cow_breaks += 1
                    p["is_shared"] = False
                    key = p["content_hash"] if merge_across_nodes else (p["numa_node"], p["content_hash"])
                    if key in stable_tree:
                        st_entry = stable_tree[key]
                        st_entry["members"].discard((p["vm_id"], p["page_id"]))
                        if len(st_entry["members"]) <= 1:
                            for rem_vm, rem_pid in list(st_entry["members"]):
                                for op in all_pages:
                                    if op["vm_id"] == rem_vm and op["page_id"] == rem_pid:
                                        op["is_shared"] = False
                                        op["canonical_ksm_id"] = None
                            del stable_tree[key]
                    p["canonical_ksm_id"] = None

    pages_shared = len(stable_tree)
    pages_sharing = sum(len(entry["members"]) - 1 for entry in stable_tree.values())
    pages_unshared = total_mergeable - sum(len(entry["members"]) for entry in stable_tree.values())

    memory_saved_bytes = pages_sharing * PAGE_SIZE
    memory_saved_mb = round(memory_saved_bytes / (1024.0 * 1024.0), 2)
    dedup_ratio = round(pages_sharing / total_mergeable, 4) if total_mergeable > 0 else 0.0

    total_cpu_time_us = (total_scanned_count * scan_cost_us) + (total_cow_breaks * cow_break_cost_us)
    total_wall_time_us = max(1000.0, scan_passes * sleep_millisecs * 1000.0)
    cpu_overhead_pct = round(min(100.0, (total_cpu_time_us / total_wall_time_us) * 100.0), 2)

    status = "HEALTHY_OPTIMAL_DEDUP"
    bottlenecks = []
    if total_cow_breaks > max(1, pages_sharing):
        bottlenecks.append("COW_BREAK_THRASHING_CPU_SPIKE")
        status = "COW_BREAK_THRASHING"
    elif scan_starvation and pages_sharing < (total_mergeable * 0.25):
        bottlenecks.append("KSMD_SCAN_STARVATION")
        status = "KSMD_SCAN_STARVATION"
    elif total_cross_node_accesses > 0 and merge_across_nodes:
        bottlenecks.append("CROSS_NUMA_MEMORY_LATENCY_SPIKE")
        status = "CROSS_NUMA_DEGRADATION"

    stable_summary = []
    for k, v in sorted(stable_tree.items(), key=lambda item: item[1]["canonical_id"]):
        stable_summary.append({
            "canonical_id": v["canonical_id"],
            "content_hash": v["content_hash"],
            "numa_node": v["numa_node"],
            "sharing_count": len(v["members"]) - 1
        })

    return {
        "metrics": {
            "total_mergeable_pages": total_mergeable,
            "pages_shared": pages_shared,
            "pages_sharing": pages_sharing,
            "pages_unshared": pages_unshared,
            "cow_breaks": total_cow_breaks,
            "memory_saved_mb": memory_saved_mb,
            "dedup_ratio": dedup_ratio,
            "cpu_overhead_pct": cpu_overhead_pct,
            "cross_node_accesses": total_cross_node_accesses
        },
        "status": status,
        "bottlenecks": bottlenecks,
        "stable_tree_summary": stable_summary
    }

def tune_adaptive_ksm(profile):
    workload = profile.get("target_workload_type", "READ_HEAVY_VMS")
    numa_nodes = profile.get("numa_nodes_count", 1)
    total_mem_gb = profile.get("total_host_memory_gb", 64)

    if workload == "WRITE_INTENSIVE_DATABASE":
        pages_to_scan = 50
        sleep_millisecs = 200
        merge_across = False
        max_sharing = 64
        risk = "HIGH"
        proj_savings = round(total_mem_gb * 0.05 * 1024, 2)
        proj_cpu = 0.5
        run_val = 0
    elif workload == "MULTI_NUMA_HPC":
        pages_to_scan = 1000
        sleep_millisecs = 20
        merge_across = False
        max_sharing = 256
        risk = "MINIMAL"
        proj_savings = round(total_mem_gb * 0.35 * 1024, 2)
        proj_cpu = 2.4
        run_val = 1
    elif workload == "READ_HEAVY_VMS":
        pages_to_scan = 2000
        sleep_millisecs = 10
        merge_across = False if numa_nodes > 1 else True
        max_sharing = 512
        risk = "MINIMAL"
        proj_savings = round(total_mem_gb * 0.55 * 1024, 2)
        proj_cpu = 3.2
        run_val = 1
    else: # BALANCED_CONTAINERS
        pages_to_scan = 500
        sleep_millisecs = 20
        merge_across = False
        max_sharing = 256
        risk = "MODERATE"
        proj_savings = round(total_mem_gb * 0.25 * 1024, 2)
        proj_cpu = 1.8
        run_val = 1

    sysfs_cmds = [
        f"echo {pages_to_scan} > /sys/kernel/mm/ksm/pages_to_scan",
        f"echo {sleep_millisecs} > /sys/kernel/mm/ksm/sleep_millisecs",
        f"echo {1 if merge_across else 0} > /sys/kernel/mm/ksm/merge_across_nodes",
        f"echo {max_sharing} > /sys/kernel/mm/ksm/max_page_sharing",
        f"echo {run_val} > /sys/kernel/mm/ksm/run"
    ]

    return {
        "recommended_config": {
            "pages_to_scan": pages_to_scan,
            "sleep_millisecs": sleep_millisecs,
            "merge_across_nodes": merge_across,
            "max_page_sharing": max_sharing,
            "ksm_run": run_val
        },
        "expected_improvement": {
            "projected_memory_saved_mb": proj_savings,
            "projected_cpu_overhead_pct": proj_cpu,
            "cow_break_risk": risk
        },
        "kernel_sysfs_commands": sysfs_cmds
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    mode = data.get("mode", "SIMULATE_KSM")

    if mode == "SIMULATE_KSM":
        ksmd_conf = data.get("ksmd_config", {})
        vms = data.get("vms", [])
        passes = data.get("scan_passes", 3)
        res = simulate_ksm(ksmd_conf, vms, passes)
        print(json.dumps(res, ensure_ascii=False))
    elif mode == "ADAPTIVE_KSM_TUNER":
        profile = data.get("system_profile", {})
        res = tune_adaptive_ksm(profile)
        print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
