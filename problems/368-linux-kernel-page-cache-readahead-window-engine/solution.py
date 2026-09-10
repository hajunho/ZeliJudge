import sys
import json

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    max_ra_pages = input_data.get("max_ra_pages", 32)
    initial_ra_pages = input_data.get("initial_ra_pages", 4)
    async_ratio = input_data.get("async_ratio", 0.5)
    operations = input_data.get("operations", [])
    
    start = 0
    size = 0
    async_size = 0
    lookahead_index = -1
    prev_page = None
    
    cached_pages = set()
    
    stats = {
        "read_requests": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "sync_ra_count": 0,
        "async_ra_count": 0,
        "pages_read_from_disk": 0,
        "random_seeks_detected": 0
    }
    
    op_log = []
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "FILE_READ":
            stats["read_requests"] += 1
            off = op["offset_page"]
            nr = op.get("nr_pages", 1)
            
            is_seq = (prev_page is None and off == 0) or (prev_page is not None and off == prev_page + 1)
            all_cached = all(p in cached_pages for p in range(off, off + nr))
            
            if not is_seq and (prev_page is not None and off != prev_page + 1):
                stats["random_seeks_detected"] += 1
                start = off
                size = 0
                async_size = 0
                lookahead_index = -1
                
                uncached = [p for p in range(off, off + nr) if p not in cached_pages]
                if uncached:
                    stats["cache_misses"] += len(uncached)
                    stats["pages_read_from_disk"] += len(uncached)
                    for p in uncached:
                        cached_pages.add(p)
                else:
                    stats["cache_hits"] += nr
                    
                op_log.append({
                    "op": "FILE_READ",
                    "offset_page": off,
                    "nr_pages": nr,
                    "status": "RANDOM_SEEK_SYNC_READ",
                    "ra_window_size": size,
                    "pages_fetched": len(uncached)
                })
                prev_page = off + nr - 1
                continue
                
            status = "CACHE_HIT"
            pages_fetched = 0
            
            if size > 0 and off == lookahead_index:
                stats["async_ra_count"] += 1
                new_size = min(size * 2, max_ra_pages)
                new_start = start + size
                new_async = max(1, int(new_size * async_ratio))
                
                fetch_batch = [p for p in range(new_start, new_start + new_size) if p not in cached_pages]
                stats["pages_read_from_disk"] += len(fetch_batch)
                pages_fetched = len(fetch_batch)
                for p in fetch_batch:
                    cached_pages.add(p)
                    
                start = new_start
                size = new_size
                async_size = new_async
                lookahead_index = start + size - async_size
                status = "ASYNC_READAHEAD_WINDOW_EXPANDED"
                
            elif size == 0:
                stats["sync_ra_count"] += 1
                size = min(initial_ra_pages, max_ra_pages)
                start = off
                async_size = max(1, int(size * async_ratio))
                lookahead_index = start + size - async_size
                
                fetch_batch = [p for p in range(start, start + size) if p not in cached_pages]
                stats["pages_read_from_disk"] += len(fetch_batch)
                pages_fetched = len(fetch_batch)
                for p in fetch_batch:
                    cached_pages.add(p)
                status = "SYNC_READAHEAD_INITIAL_BURST"
                
            if all_cached:
                stats["cache_hits"] += nr
            else:
                missed = sum(1 for p in range(off, off + nr) if p not in cached_pages)
                stats["cache_misses"] += missed
                stats["cache_hits"] += (nr - missed)
                
            op_log.append({
                "op": "FILE_READ",
                "offset_page": off,
                "nr_pages": nr,
                "status": status,
                "ra_window_size": size,
                "lookahead_index": lookahead_index,
                "pages_fetched": pages_fetched
            })
            prev_page = off + nr - 1
            
        elif op_type == "DROP_PAGE_CACHE":
            cached_pages.clear()
            start = 0
            size = 0
            async_size = 0
            lookahead_index = -1
            op_log.append({
                "op": "DROP_PAGE_CACHE",
                "status": "CACHE_PURGED"
            })

    res = {
        "max_ra_pages": max_ra_pages,
        "initial_ra_pages": initial_ra_pages,
        "async_ratio": async_ratio,
        "cached_pages_count": len(cached_pages),
        "final_window": {
            "start": start,
            "size": size,
            "async_size": async_size,
            "lookahead_index": lookahead_index
        },
        "stats": stats,
        "op_log": op_log
    }
    
    sys.stdout.write(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    solve()
