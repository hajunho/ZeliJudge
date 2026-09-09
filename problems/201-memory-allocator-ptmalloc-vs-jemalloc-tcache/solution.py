#!/usr/bin/env python3
"""
ZeliJudge Problem #201: 메모리 할당자 내부 아키텍처: Glibc Ptmalloc 아레나 락 경합 vs Jemalloc tcache(Thread Cache)와 지연 퍼징(Decay-based Purging)
Solution Implementation
"""
import sys
import json

SIZE_CLASSES = [16, 32, 64, 128, 256, 512, 1024, 2048, 4096]

def get_size_class(size):
    for sc in SIZE_CLASSES:
        if size <= sc:
            return sc
    return ((size + 4095) // 4096) * 4096

def simulate(input_data):
    cfg = input_data.get("allocator_config", {})
    alloc_type = cfg.get("type", "ptmalloc")
    num_arenas = max(1, cfg.get("arenas_count", 4))
    tcache_enabled = cfg.get("tcache_enabled", True) if alloc_type == "jemalloc" else False
    tcache_max_per_bin = cfg.get("tcache_max_per_bin", 32)
    batch_refill_count = cfg.get("batch_refill_count", 16)
    decay_interval_ops = cfg.get("decay_interval_ops", 0)
    page_size = cfg.get("page_size", 4096)

    threads = input_data.get("threads", [])
    events = input_data.get("events", [])

    thread_arena = {}
    for idx, t in enumerate(threads):
        thread_arena[t] = idx % num_arenas

    total_alloc_requests = 0
    total_free_requests = 0
    arena_lock_acquisitions = 0
    tcache_hits = 0
    pages_purged_to_os = 0

    thread_stats = {
        t: {"allocs": 0, "frees": 0, "lock_acquisitions": 0} for t in threads
    }

    objects = {} # obj_id -> {"size": size, "sc": sc, "thread": t, "page_id": page_id}
    next_page_id = 1
    os_pages = {} # page_id -> {"total_slots": N, "sc": sc, "used_slots": M, "arena_id": A, "purged": False}

    tcaches = {t: {sc: [] for sc in SIZE_CLASSES} for t in threads}
    arena_free_pools = {a: {sc: [] for sc in SIZE_CLASSES} for a in range(num_arenas)}
    arena_pages = {a: set() for a in range(num_arenas)}

    current_active_bytes = 0
    op_counter = 0

    def purge_decay_pages():
        nonlocal pages_purged_to_os
        if alloc_type != "jemalloc":
            return
        for pid, pdata in list(os_pages.items()):
            if not pdata["purged"] and pdata["used_slots"] == 0:
                pdata["purged"] = True
                pages_purged_to_os += 1
                a_id = pdata["arena_id"]
                sc = pdata["sc"]
                arena_free_pools[a_id][sc] = [s for s in arena_free_pools[a_id][sc] if s["page_id"] != pid]
                for th in threads:
                    tcaches[th][sc] = [s for s in tcaches[th][sc] if s["page_id"] != pid]

    for ev in events:
        op_counter += 1
        op = ev.get("op")
        t = ev.get("thread_id")

        if t not in thread_stats and t is not None:
            thread_stats[t] = {"allocs": 0, "frees": 0, "lock_acquisitions": 0}
            thread_arena[t] = len(thread_arena) % num_arenas
            if alloc_type == "jemalloc":
                tcaches[t] = {sc: [] for sc in SIZE_CLASSES}

        arena_id = thread_arena.get(t, 0)

        if op == "malloc":
            total_alloc_requests += 1
            thread_stats[t]["allocs"] += 1
            obj_id = ev.get("id")
            size = ev.get("size", 16)
            sc = get_size_class(size)
            current_active_bytes += size

            if alloc_type == "jemalloc" and tcache_enabled and sc in tcaches[t]:
                if len(tcaches[t][sc]) > 0:
                    slot = tcaches[t][sc].pop()
                    tcache_hits += 1
                    page_id = slot["page_id"]
                    os_pages[page_id]["used_slots"] += 1
                    objects[obj_id] = {"size": size, "sc": sc, "thread": t, "page_id": page_id}
                else:
                    arena_lock_acquisitions += 1
                    thread_stats[t]["lock_acquisitions"] += 1

                    pool = arena_free_pools[arena_id][sc]
                    needed = batch_refill_count

                    while len(pool) < needed:
                        page_id = next_page_id
                        next_page_id += 1
                        slots_in_page = page_size // sc
                        os_pages[page_id] = {
                            "total_slots": slots_in_page,
                            "sc": sc,
                            "used_slots": 0,
                            "arena_id": arena_id,
                            "purged": False
                        }
                        arena_pages[arena_id].add(page_id)
                        for _ in range(slots_in_page):
                            pool.append({"page_id": page_id})

                    refilled = [pool.pop() for _ in range(needed)]
                    slot = refilled.pop()
                    page_id = slot["page_id"]
                    os_pages[page_id]["used_slots"] += 1
                    objects[obj_id] = {"size": size, "sc": sc, "thread": t, "page_id": page_id}
                    tcaches[t][sc].extend(refilled)
            else:
                arena_lock_acquisitions += 1
                thread_stats[t]["lock_acquisitions"] += 1

                pool = arena_free_pools[arena_id].get(sc, [])
                if len(pool) == 0:
                    page_id = next_page_id
                    next_page_id += 1
                    slots_in_page = page_size // sc
                    os_pages[page_id] = {
                        "total_slots": slots_in_page,
                        "sc": sc,
                        "used_slots": 0,
                        "arena_id": arena_id,
                        "purged": False
                    }
                    arena_pages[arena_id].add(page_id)
                    for _ in range(slots_in_page):
                        pool.append({"page_id": page_id})
                    arena_free_pools[arena_id][sc] = pool

                slot = pool.pop()
                page_id = slot["page_id"]
                os_pages[page_id]["used_slots"] += 1
                objects[obj_id] = {"size": size, "sc": sc, "thread": t, "page_id": page_id}

        elif op == "free":
            total_free_requests += 1
            thread_stats[t]["frees"] += 1
            obj_id = ev.get("id")
            if obj_id in objects:
                info = objects.pop(obj_id)
                size = info["size"]
                sc = info["sc"]
                page_id = info["page_id"]
                current_active_bytes -= size
                os_pages[page_id]["used_slots"] -= 1

                slot = {"page_id": page_id}

                if alloc_type == "jemalloc" and tcache_enabled and sc in tcaches[t]:
                    if len(tcaches[t][sc]) < tcache_max_per_bin:
                        tcaches[t][sc].append(slot)
                        tcache_hits += 1
                    else:
                        arena_lock_acquisitions += 1
                        thread_stats[t]["lock_acquisitions"] += 1
                        flush_count = min(batch_refill_count, len(tcaches[t][sc]))
                        to_flush = [tcaches[t][sc].pop() for _ in range(flush_count)]
                        arena_free_pools[arena_id][sc].extend(to_flush)
                        tcaches[t][sc].append(slot)
                else:
                    arena_lock_acquisitions += 1
                    thread_stats[t]["lock_acquisitions"] += 1
                    arena_free_pools[arena_id][sc].append(slot)

        elif op == "decay_tick":
            purge_decay_pages()

        if decay_interval_ops > 0 and op_counter % decay_interval_ops == 0:
            purge_decay_pages()

    if decay_interval_ops > 0:
        purge_decay_pages()

    active_pages = sum(1 for p in os_pages.values() if not p["purged"])
    current_rss_bytes = active_pages * page_size

    total_requests = total_alloc_requests + total_free_requests
    tcache_hit_ratio_pct = round((tcache_hits / total_requests * 100.0), 1) if total_requests > 0 else 0.0

    if current_rss_bytes > 0:
        fragmentation_ratio = round((current_rss_bytes - current_active_bytes) / current_rss_bytes, 2)
    else:
        fragmentation_ratio = 0.0

    unpurged_empty_pages = sum(1 for p in os_pages.values() if not p["purged"] and p["used_slots"] == 0)

    if alloc_type == "ptmalloc":
        if unpurged_empty_pages >= 1 and total_free_requests >= (total_alloc_requests * 0.3):
            status = "PTMALLOC_FRAGMENTATION_RSS_BLOAT"
        else:
            status = "PTMALLOC_ARENA_LOCK_COLLAPSE"
    else:
        if not tcache_enabled or tcache_hit_ratio_pct < 60.0:
            status = "PTMALLOC_ARENA_LOCK_COLLAPSE"
        elif unpurged_empty_pages >= 2 and pages_purged_to_os == 0:
            status = "PTMALLOC_FRAGMENTATION_RSS_BLOAT"
        else:
            status = "OPTIMAL_JEMALLOC_TCACHE_TUNED"

    root_causes = {
        "PTMALLOC_ARENA_LOCK_COLLAPSE": (
            f"Glibc Ptmalloc 아레나 락 경합 참사: 스레드 로컬 캐시(tcache)의 부재로 인해 총 {total_requests}건의 요청 중 "
            f"{arena_lock_acquisitions}회({round(arena_lock_acquisitions/max(1,total_requests)*100, 1)}%)의 공유 아레나 뮤텍스 락을 강제 획득하여 "
            "스레드 간 락 경합과 futex 컨텍스트 스위칭 지연 스파이크 발생."
        ),
        "PTMALLOC_FRAGMENTATION_RSS_BLOAT": (
            f"Glibc Ptmalloc 외적 단편화 및 RSS 비대화 참사: 대규모 할당 후 해제({total_free_requests}건)에도 지연 퍼징(Decay-based Purge) 부재로 "
            f"{unpurged_empty_pages}개의 완전히 비어있는 OS 물리 페이지가 반환되지 않아 활성 메모리는 {current_active_bytes}B인데 반해 RSS는 {current_rss_bytes}B(단편화율 {int(fragmentation_ratio*100)}%)로 폭증."
        ),
        "OPTIMAL_JEMALLOC_TCACHE_TUNED": (
            f"Jemalloc tcache 및 지연 퍼징 최적화 완수: 스레드 로컬 캐시를 통한 무락(Lock-free) 처리(tcache 적중률 {tcache_hit_ratio_pct}%, "
            f"아레나 락 획득 단 {arena_lock_acquisitions}회)와 배치 리필/플러시, decay 기반 {pages_purged_to_os}개 미사용 페이지 OS 반환으로 RSS 최적화 완수."
        )
    }

    return {
        "status": status,
        "metrics": {
            "total_alloc_requests": total_alloc_requests,
            "total_free_requests": total_free_requests,
            "arena_lock_acquisitions": arena_lock_acquisitions,
            "tcache_hits": tcache_hits,
            "tcache_hit_ratio_pct": tcache_hit_ratio_pct,
            "current_active_bytes": current_active_bytes,
            "current_rss_bytes": current_rss_bytes,
            "fragmentation_ratio": fragmentation_ratio,
            "pages_purged_to_os": pages_purged_to_os
        },
        "thread_stats": thread_stats,
        "root_cause_analysis": root_causes.get(status, "")
    }

def main():
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            return
        input_data = json.loads(raw_input)
        result = simulate(input_data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
