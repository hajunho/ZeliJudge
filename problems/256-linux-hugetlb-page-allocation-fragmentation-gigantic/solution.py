#!/usr/bin/env python3
import sys
import json

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)

    hw = input_data["system_hardware"]
    boot = input_data.get("kernel_boot_params", {})
    runtime = input_data["runtime_state"]
    workload = input_data.get("workload_requests", [])

    total_ram_mb = hw["total_ram_mb"]
    page_size_kb = hw.get("page_size_kb", 4)

    # Boot params
    hugepages_2m_boot = boot.get("hugepages_2m_boot", 0)
    hugepages_1g_boot = boot.get("hugepages_1g_boot", 0)

    # Runtime state
    hugetlb_shm_group = runtime.get("hugetlb_shm_group", 0)
    normal_mem_used_mb = runtime.get("normal_memory_used_mb", 0)
    buddy_nodes = runtime.get("buddy_allocator_state", {})

    # Initial pool setup from boot
    pool_2m_total = hugepages_2m_boot
    pool_2m_allocated = 0
    pool_1g_total = hugepages_1g_boot
    pool_1g_allocated = 0

    # Total order-9 free blocks across NUMA nodes
    total_order_9_blocks = sum(node_info.get("order_9_free_blocks", 0) for node_info in buddy_nodes.values())

    # Calculate reserved HugeTLB memory
    hugetlb_reserved_mb = pool_2m_total * 2 + pool_1g_total * 1024
    free_normal_ram_mb = total_ram_mb - hugetlb_reserved_mb - normal_mem_used_mb

    fatal_errors = []
    warnings = []
    events = []

    status = "OPTIMAL_HUGETLB_LINE_PERFORMANCE"

    # Process workload requests
    for req in workload:
        req_id = req.get("request_id", "")
        action = req.get("action", "PROCESS_ALLOCATION")

        if action == "SYSCTL_EXPAND_HUGEPAGES":
            target_size = req.get("target_page_size", "2M")
            requested_total = req.get("requested_total_hugepages", 0)

            if target_size == "1G":
                fatal_errors.append(f"[{req_id}] 1GB gigantic pages cannot be dynamically allocated via sysctl after boot. Boot parameter 'hugepagesz=1G hugepages=N' required.")
                status = "GIGANTIC_1G_BOOT_RESERVATION_REQUIRED"
                break

            elif target_size == "2M":
                delta = requested_total - pool_2m_total
                if delta > 0:
                    needed_mb = delta * 2
                    available_normal_mb = total_ram_mb - (pool_2m_total * 2 + pool_1g_total * 1024) - normal_mem_used_mb
                    max_allocatable_by_ram = max(0, available_normal_mb // 2)
                    actual_alloc = min(delta, total_order_9_blocks, max_allocatable_by_ram)

                    if actual_alloc < delta:
                        pool_2m_total += actual_alloc
                        total_order_9_blocks -= actual_alloc
                        hugetlb_reserved_mb = pool_2m_total * 2 + pool_1g_total * 1024
                        free_normal_ram_mb = total_ram_mb - hugetlb_reserved_mb - normal_mem_used_mb

                        fatal_errors.append(f"[{req_id}] Dynamic allocation requested {delta} 2MB pages, but only {actual_alloc} could be allocated due to Buddy Allocator external fragmentation (order-9 contiguous block exhaustion).")
                        status = "FRAGMENTATION_ORDER9_CONTIGUITY_FAILURE"
                        break
                    else:
                        pool_2m_total += actual_alloc
                        total_order_9_blocks -= actual_alloc
                        hugetlb_reserved_mb = pool_2m_total * 2 + pool_1g_total * 1024
                        free_normal_ram_mb = total_ram_mb - hugetlb_reserved_mb - normal_mem_used_mb
                        events.append(f"[{req_id}] Dynamic expansion succeeded: pool_2m expanded to {pool_2m_total} pages.")
                elif delta < 0:
                    free_pages = pool_2m_total - pool_2m_allocated
                    shrink_amount = min(abs(delta), free_pages)
                    pool_2m_total -= shrink_amount
                    hugetlb_reserved_mb = pool_2m_total * 2 + pool_1g_total * 1024
                    free_normal_ram_mb = total_ram_mb - hugetlb_reserved_mb - normal_mem_used_mb
                    events.append(f"[{req_id}] Pool shrunk by {shrink_amount} pages.")

        elif action == "PROCESS_ALLOCATION":
            proc_name = req.get("process_name", "app")
            proc_gid = req.get("process_gid", 0)
            page_size_req = req.get("page_size_requested", "2M")
            pages_req = req.get("hugepages_requested", 0)
            alloc_type = req.get("allocation_type", "MMAP_HUGETLB")
            hp_setting = req.get("huge_pages_setting", "on")

            if alloc_type == "SHM_HUGETLB" and proc_gid != 0 and proc_gid != hugetlb_shm_group:
                fatal_errors.append(f"[{req_id}] Process {proc_name} (GID {proc_gid}) denied permission to allocate SHM_HUGETLB (hugetlb_shm_group is {hugetlb_shm_group}).")
                status = "PERMISSION_DENIED_SHM_GROUP"
                break

            if page_size_req == "1G":
                free_1g = pool_1g_total - pool_1g_allocated
                if pages_req <= free_1g:
                    pool_1g_allocated += pages_req
                    events.append(f"[{req_id}] {proc_name} allocated {pages_req} 1GB gigantic pages.")
                else:
                    if hp_setting == "on":
                        fatal_errors.append(f"[{req_id}] FATAL: could not map 1GB gigantic shared memory: pool exhausted (free: {free_1g}, requested: {pages_req}).")
                        status = "FATAL_HUGETLB_POOL_EXHAUSTED"
                        break
                    elif hp_setting == "try":
                        req_mb = pages_req * 1024
                        if free_normal_ram_mb >= req_mb:
                            normal_mem_used_mb += req_mb
                            free_normal_ram_mb -= req_mb
                            warnings.append(f"[{req_id}] 1GB pool exhausted. {proc_name} fell back to 4KB regular pages with high TLB miss penalty.")
                            status = "DEGRADED_4KB_PAGING_FALLBACK"
                        else:
                            fatal_errors.append(f"[{req_id}] 4KB fallback failed: insufficient host RAM ({free_normal_ram_mb}MB < {req_mb}MB).")
                            status = "HOST_OOM_DUE_TO_HUGETLB_OVERRESERVATION"
                            break

            elif page_size_req == "2M":
                free_2m = pool_2m_total - pool_2m_allocated
                if pages_req <= free_2m:
                    pool_2m_allocated += pages_req
                    events.append(f"[{req_id}] {proc_name} allocated {pages_req} 2MB huge pages.")
                else:
                    if hp_setting == "on":
                        fatal_errors.append(f"[{req_id}] FATAL: could not map anonymous 2MB shared memory: Cannot allocate memory (free: {free_2m}, requested: {pages_req}).")
                        status = "FATAL_HUGETLB_POOL_EXHAUSTED"
                        break
                    elif hp_setting == "try":
                        req_mb = pages_req * 2
                        if free_normal_ram_mb >= req_mb:
                            normal_mem_used_mb += req_mb
                            free_normal_ram_mb -= req_mb
                            warnings.append(f"[{req_id}] 2MB pool exhausted. {proc_name} fell back to 4KB regular pages.")
                            status = "DEGRADED_4KB_PAGING_FALLBACK"
                        else:
                            fatal_errors.append(f"[{req_id}] 4KB fallback failed: insufficient host RAM ({free_normal_ram_mb}MB < {req_mb}MB). Host OOM Killer invoked.")
                            status = "HOST_OOM_DUE_TO_HUGETLB_OVERRESERVATION"
                            break

    # Check host memory starvation
    hugetlb_reserved_mb = pool_2m_total * 2 + pool_1g_total * 1024
    free_normal_ram_mb = total_ram_mb - hugetlb_reserved_mb - normal_mem_used_mb
    if free_normal_ram_mb < 512 and status == "OPTIMAL_HUGETLB_LINE_PERFORMANCE":
        status = "HOST_OOM_DUE_TO_HUGETLB_OVERRESERVATION"
        fatal_errors.append(f"Host normal RAM starved ({free_normal_ram_mb}MB free < 512MB threshold). HugeTLB pool ({hugetlb_reserved_mb}MB) over-reserved and locked, triggering Linux OOM Killer on host services.")

    diagnostics = fatal_errors + warnings + events

    recommended_tuning = {}
    if status == "GIGANTIC_1G_BOOT_RESERVATION_REQUIRED":
        recommended_tuning = {
            "kernel_cmdline": "default_hugepagesz=1G hugepagesz=1G hugepages=32",
            "suggestion": "Reserve 1GB gigantic pages at boot via GRUB kernel parameters. Runtime dynamic allocation is unsupported on standard kernels."
        }
    elif status == "FRAGMENTATION_ORDER9_CONTIGUITY_FAILURE":
        recommended_tuning = {
            "sysctl": "vm.compact_memory = 1",
            "suggestion": "Trigger proactive memory compaction prior to allocation or reserve 2MB hugepages at boot time before external fragmentation occurs."
        }
    elif status == "FATAL_HUGETLB_POOL_EXHAUSTED":
        recommended_tuning = {
            "sysctl_nr_hugepages": pool_2m_allocated + 4096,
            "suggestion": "Increase /proc/sys/vm/nr_hugepages or set PostgreSQL huge_pages = try to allow temporary 4KB fallback during pool exhaustion."
        }
    elif status == "PERMISSION_DENIED_SHM_GROUP":
        recommended_tuning = {
            "sysctl": "vm.hugetlb_shm_group = 1002",
            "suggestion": "Configure /proc/sys/vm/hugetlb_shm_group to match the PostgreSQL/Oracle database process GID."
        }
    elif status == "HOST_OOM_DUE_TO_HUGETLB_OVERRESERVATION":
        safe_hugetlb_mb = int(total_ram_mb * 0.75)
        recommended_tuning = {
            "max_hugetlb_pool_mb": safe_hugetlb_mb,
            "suggestion": "Limit HugeTLB pool to at most 70-75% of physical RAM to reserve sufficient memory for kernel page cache, network buffers, and host daemons."
        }
    elif status == "DEGRADED_4KB_PAGING_FALLBACK":
        recommended_tuning = {
            "suggestion": "Increase HugeTLB pool size to eliminate 4KB paging TLB miss penalties and restore full database buffer hit performance."
        }
    else:
        recommended_tuning = {
            "suggestion": "Optimal HugeTLB configuration maintained."
        }

    output = {
        "status": status,
        "metrics": {
            "total_ram_mb": total_ram_mb,
            "hugetlb_pool_2m_total": pool_2m_total,
            "hugetlb_pool_2m_free": pool_2m_total - pool_2m_allocated,
            "hugetlb_pool_1g_total": pool_1g_total,
            "hugetlb_pool_1g_free": pool_1g_total - pool_1g_allocated,
            "hugetlb_total_reserved_mb": hugetlb_reserved_mb,
            "normal_ram_free_mb": max(0, free_normal_ram_mb),
            "normal_ram_used_mb": normal_mem_used_mb,
            "remaining_order_9_blocks": total_order_9_blocks
        },
        "diagnostics": diagnostics,
        "recommended_tuning": recommended_tuning
    }
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    solve()
