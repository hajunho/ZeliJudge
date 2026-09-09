import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    mechanism = config.get("mechanism", "ZSWAP")
    allocator = config.get("allocator", "ZSMALLOC")
    compressor = config.get("compressor", "LZ4")
    max_pool_percent = float(config.get("max_pool_percent", 20.0))
    total_ram_mb = float(config.get("total_ram_mb", 8192.0))
    swap_disk_type = config.get("swap_disk_type", "NVME")

    workload = data.get("workload", {})
    swap_candidate_pages = int(workload.get("swap_candidate_pages", 500000))
    compressible_ratio = float(workload.get("compressible_ratio", 0.40))

    total_swap_mb = (swap_candidate_pages * 4096) / (1024 * 1024)
    max_pool_mb = total_ram_mb * (max_pool_percent / 100.0)

    effective_ratio = compressible_ratio
    if compressor == "ZSTD":
        effective_ratio = round(effective_ratio * 0.85, 4)
    elif compressor == "NONE":
        effective_ratio = 1.0

    if allocator == "ZBUD":
        if effective_ratio > 0.5:
            allocator_overhead = 1.0 / max(0.01, effective_ratio)
        else:
            allocator_overhead = 0.5 / max(0.01, effective_ratio)
    elif allocator == "Z3FOLD":
        if effective_ratio > 0.66:
            allocator_overhead = 1.0 / max(0.01, effective_ratio)
        elif effective_ratio > 0.33:
            allocator_overhead = 0.5 / max(0.01, effective_ratio)
        else:
            allocator_overhead = 0.333 / max(0.01, effective_ratio)
    else:
        allocator_overhead = 1.10

    raw_compressed_mb = total_swap_mb * effective_ratio
    pool_memory_needed_mb = round(raw_compressed_mb * allocator_overhead, 2)

    if mechanism == "TRADITIONAL_SWAP":
        disk_write_mb = total_swap_mb
        zpool_used_mb = 0.0
        avg_latency_us = 120.0 if swap_disk_type == "NVME" else 850.0
        status = "WARNING"
        verdict = "TRADITIONAL_SWAP_IO_BOTTLENECK"
        writeback_count = 0
        oom_killed = False

    elif mechanism == "ZRAM":
        if pool_memory_needed_mb > max_pool_mb:
            if swap_disk_type == "NONE":
                status = "FAILED"
                verdict = "ZRAM_OUT_OF_MEMORY_NO_BACKING_STORE"
                oom_killed = True
                disk_write_mb = 0.0
                zpool_used_mb = max_pool_mb
                avg_latency_us = 9999.0
                writeback_count = 0
            else:
                status = "WARNING"
                verdict = "ZRAM_BACKING_DEV_SPILLOVER"
                oom_killed = False
                zpool_used_mb = max_pool_mb
                disk_write_mb = round(total_swap_mb * (1.0 - (max_pool_mb / pool_memory_needed_mb)), 2)
                avg_latency_us = 65.0
                writeback_count = int(swap_candidate_pages * (1.0 - (max_pool_mb / pool_memory_needed_mb)))
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_ZRAM_COMPRESSED_STORAGE"
            oom_killed = False
            zpool_used_mb = pool_memory_needed_mb
            disk_write_mb = 0.0
            avg_latency_us = 4.2
            writeback_count = 0

    elif mechanism == "ZSWAP":
        if effective_ratio >= 0.90:
            status = "FAILED"
            verdict = "INCOMPRESSIBLE_DATA_ZSWAP_BYPASS_THRASHING"
            oom_killed = False
            zpool_used_mb = 0.0
            disk_write_mb = total_swap_mb
            avg_latency_us = 150.0
            writeback_count = 0

        elif allocator == "ZBUD" and pool_memory_needed_mb > max_pool_mb:
            status = "FAILED"
            verdict = "ZBUD_ALLOCATOR_FRAGMENTATION_PREMATURE_EVICTION"
            oom_killed = False
            zpool_used_mb = max_pool_mb
            overflow_mb = pool_memory_needed_mb - max_pool_mb
            disk_write_mb = round((overflow_mb / allocator_overhead) / effective_ratio, 2)
            writeback_count = int(disk_write_mb * (1024 * 1024 / 4096))
            avg_latency_us = 75.0

        elif pool_memory_needed_mb > max_pool_mb:
            if swap_disk_type == "NONE":
                status = "FAILED"
                verdict = "ZSWAP_POOL_EXHAUSTION_NO_BACKING_SWAP"
                oom_killed = True
                zpool_used_mb = max_pool_mb
                disk_write_mb = 0.0
                writeback_count = 0
                avg_latency_us = 9999.0
            else:
                status = "WARNING"
                verdict = "ZSWAP_POOL_SATURATION_WRITEBACK_STALL"
                oom_killed = False
                zpool_used_mb = max_pool_mb
                overflow_mb = pool_memory_needed_mb - max_pool_mb
                disk_write_mb = round((overflow_mb / allocator_overhead) / effective_ratio, 2)
                writeback_count = int(disk_write_mb * (1024 * 1024 / 4096))
                avg_latency_us = 45.0
        else:
            status = "SUCCESS"
            verdict = "OPTIMAL_ZSWAP_COMPRESSED_MEMORY_POOL"
            oom_killed = False
            zpool_used_mb = pool_memory_needed_mb
            disk_write_mb = 0.0
            writeback_count = 0
            avg_latency_us = 3.5 if compressor == "LZ4" else 5.8
    else:
        status = "FAILED"
        verdict = "UNKNOWN_MECHANISM"
        oom_killed = False
        zpool_used_mb = 0.0
        disk_write_mb = 0.0
        writeback_count = 0
        avg_latency_us = 0.0

    swap_io_reduction_pct = round((1.0 - (disk_write_mb / max(0.01, total_swap_mb))) * 100.0, 1)

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "total_swap_candidate_mb": round(total_swap_mb, 2),
            "zpool_used_mb": round(zpool_used_mb, 2),
            "disk_write_mb": round(disk_write_mb, 2),
            "writeback_pages": writeback_count,
            "swap_io_reduction_pct": swap_io_reduction_pct,
            "avg_swap_latency_us": round(avg_latency_us, 1),
            "oom_killed": oom_killed
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
