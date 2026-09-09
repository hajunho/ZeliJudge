import sys
import json
from collections import OrderedDict
from typing import Dict, List, Any

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    storage_config = input_data.get("storage_config", {})
    page_cache_cap_mb = storage_config.get("page_cache_capacity_mb", 256)
    ra_pages = storage_config.get("default_ra_pages", 32)
    page_size_kb = storage_config.get("page_size_kb", 4)
    ra_size_kb = ra_pages * page_size_kb

    workload = input_data.get("workload", {})
    io_strategy = workload.get("io_strategy", "DEFAULT_KERNEL_PAGE_CACHE")
    queries = workload.get("queries", [])

    cache_capacity_pages = (page_cache_cap_mb * 1024) // page_size_kb
    page_cache = OrderedDict()

    hot_pages_preload = workload.get("hot_pages_preload_kb", [])
    for hp_kb in hot_pages_preload:
        pid = hp_kb // page_size_kb
        page_cache[pid] = True

    hits = 0
    misses = 0
    total_useful_bytes_kb = 0
    total_disk_bytes_kb = 0
    evictions = 0

    for q in queries:
        q_type = q.get("type", "POINT_LOOKUP")
        offset_mb = q.get("offset_mb", 0)
        offset_kb = offset_mb * 1024
        read_kb = q.get("read_size_kb", 4)
        hint = q.get("fadvise_hint")

        start_page = int(offset_kb // page_size_kb)
        num_pages = max(1, int((read_kb + page_size_kb - 1) // page_size_kb))
        req_pages = [start_page + i for i in range(num_pages)]

        total_useful_bytes_kb += read_kb

        if io_strategy == "O_DIRECT":
            misses += 1
            total_disk_bytes_kb += read_kb
            continue

        all_hit = True
        for p in req_pages:
            if p in page_cache:
                page_cache.move_to_end(p)
            else:
                all_hit = False

        if all_hit and req_pages:
            hits += 1
        else:
            misses += 1
            is_random = (io_strategy == "POSIX_FADV_RANDOM") or (hint == "POSIX_FADV_RANDOM")
            
            if is_random:
                fetch_pages = req_pages
                fetch_kb = num_pages * page_size_kb
            else:
                if q_type == "POINT_LOOKUP":
                    ra_num_pages = max(num_pages, ra_pages)
                    fetch_pages = [start_page + i for i in range(ra_num_pages)]
                    fetch_kb = ra_num_pages * page_size_kb
                else:
                    ra_num_pages = max(num_pages, ra_pages * 2)
                    fetch_pages = [start_page + i for i in range(ra_num_pages)]
                    fetch_kb = ra_num_pages * page_size_kb

            total_disk_bytes_kb += fetch_kb

            if hint == "POSIX_FADV_DONTNEED":
                pass
            else:
                for fp in fetch_pages:
                    if fp in page_cache:
                        page_cache.move_to_end(fp)
                    else:
                        if len(page_cache) >= cache_capacity_pages:
                            page_cache.popitem(last=False)
                            evictions += 1
                        page_cache[fp] = True

    total_q = hits + misses
    hit_ratio_pct = round((hits / total_q) * 100.0, 2) if total_q > 0 else 0.0
    io_amp = round(total_disk_bytes_kb / total_useful_bytes_kb, 2) if total_useful_bytes_kb > 0 else 1.0

    useful_mb = round(total_useful_bytes_kb / 1024.0, 2)
    disk_mb = round(total_disk_bytes_kb / 1024.0, 2)
    used_cache_mb = round((len(page_cache) * page_size_kb) / 1024.0, 2)

    anomalies = []
    if io_amp >= 3.0 and io_strategy == "DEFAULT_KERNEL_PAGE_CACHE":
        anomalies.append("READAHEAD_IO_AMPLIFICATION_WASTE")

    if evictions > 500 and hit_ratio_pct < 50.0 and len(hot_pages_preload) > 0:
        anomalies.append("PAGE_CACHE_POLLUTION_WORKING_SET_EVICTION")

    recommendations = []
    if "READAHEAD_IO_AMPLIFICATION_WASTE" in anomalies:
        recommendations.append("APPLY_POSIX_FADV_RANDOM_FOR_INDEX_LOOKUPS")
    if "PAGE_CACHE_POLLUTION_WORKING_SET_EVICTION" in anomalies:
        recommendations.append("USE_POSIX_FADV_DONTNEED_FOR_BULK_SCANS")
    if io_strategy == "O_DIRECT":
        recommendations.append("O_DIRECT_BYPASS_PAGE_CACHE_ACTIVE")

    diag_parts = []
    if "READAHEAD_IO_AMPLIFICATION_WASTE" in anomalies:
        diag_parts.append(f"랜덤 포인트 룩업 시 커널의 과도한 리드어헤드로 인해 I/O 증폭비({io_amp}x) 및 대역폭 낭비 발생 (디스크 {disk_mb}MB 읽음 / 실제 필요 {useful_mb}MB).")
    if "PAGE_CACHE_POLLUTION_WORKING_SET_EVICTION" in anomalies:
        diag_parts.append(f"벌크 스캔/리드어헤드로 인해 페이지 캐시 오염 발생 ({evictions}개 핫 페이지 축출, 캐시 히트율 {hit_ratio_pct}%로 급락).")
    if not anomalies:
        if io_strategy == "O_DIRECT":
            diag_parts.append("O_DIRECT를 통해 커널 페이지 캐시 오염 및 이중 버퍼링 없이 디스크에서 직접 데이터를 안전하게 읽었습니다.")
        elif io_strategy == "POSIX_FADV_RANDOM":
            diag_parts.append("POSIX_FADV_RANDOM 힌트를 적용하여 불필요한 리드어헤드를 차단하고 I/O 증폭을 1.0x로 최적화했습니다.")
        else:
            diag_parts.append("순차 스캔 작업에서 커널 리드어헤드가 정상 작동하여 캐시 히트율이 안정적으로 유지되었습니다.")

    diagnosis = " ".join(diag_parts)

    return {
        "io_strategy": io_strategy,
        "total_queries": total_q,
        "cache_hits": hits,
        "cache_misses": misses,
        "cache_hit_ratio_pct": hit_ratio_pct,
        "total_bytes_useful_mb": useful_mb,
        "total_bytes_read_from_disk_mb": disk_mb,
        "io_amplification_ratio": io_amp,
        "evictions_count": evictions,
        "page_cache_used_mb": used_cache_mb,
        "anomalies": anomalies,
        "recommendations": recommendations,
        "diagnosis": diagnosis
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
