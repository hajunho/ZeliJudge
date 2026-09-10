import sys
import json
from collections import deque

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    pool_size = input_data.get("pool_size", 32)
    alloc_cache_size = input_data.get("alloc_cache_size", 8)
    refill_batch_size = input_data.get("refill_batch_size", 4)
    dma_sync_enabled = input_data.get("dma_sync_enabled", True)
    operations = input_data.get("operations", [])
    
    alloc_cache = []
    ptr_ring = deque()
    
    in_flight_pages = set()
    dma_mapped = set()
    next_page_id = 1
    
    stats = {
        "alloc_requests": 0,
        "alloc_fast_cache_hit": 0,
        "alloc_ptr_ring_refill": 0,
        "alloc_buddy_allocator_fallback": 0,
        "recycle_fast_cache": 0,
        "recycle_ptr_ring": 0,
        "recycle_ring_overflow_drops": 0,
        "dma_map_count": 0,
        "dma_unmap_count": 0,
        "dma_sync_count": 0
    }
    
    op_log = []
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "ALLOC_PAGE":
            stats["alloc_requests"] += 1
            allocated_page_id = None
            source = None
            
            if alloc_cache:
                allocated_page_id = alloc_cache.pop()
                stats["alloc_fast_cache_hit"] += 1
                source = "FAST_CACHE"
                if dma_sync_enabled:
                    stats["dma_sync_count"] += 1
            else:
                refilled = 0
                while ptr_ring and refilled < refill_batch_size and len(alloc_cache) < alloc_cache_size:
                    alloc_cache.append(ptr_ring.popleft())
                    refilled += 1
                    
                if alloc_cache:
                    stats["alloc_ptr_ring_refill"] += 1
                    allocated_page_id = alloc_cache.pop()
                    source = "PTR_RING_REFILL"
                    if dma_sync_enabled:
                        stats["dma_sync_count"] += 1
                else:
                    allocated_page_id = next_page_id
                    next_page_id += 1
                    stats["alloc_buddy_allocator_fallback"] += 1
                    stats["dma_map_count"] += 1
                    dma_mapped.add(allocated_page_id)
                    source = "BUDDY_ALLOCATOR_FALLBACK"
                    if dma_sync_enabled:
                        stats["dma_sync_count"] += 1
                        
            in_flight_pages.add(allocated_page_id)
            op_log.append({
                "op": "ALLOC_PAGE",
                "page_id": allocated_page_id,
                "source": source,
                "alloc_cache_count": len(alloc_cache),
                "ptr_ring_count": len(ptr_ring)
            })
            
        elif op_type == "RECYCLE_DIRECT":
            page_id = op["page_id"]
            if page_id not in in_flight_pages:
                op_log.append({
                    "op": "RECYCLE_DIRECT",
                    "page_id": page_id,
                    "status": "ERROR_PAGE_NOT_IN_FLIGHT"
                })
                continue
                
            in_flight_pages.remove(page_id)
            status = None
            if len(alloc_cache) < alloc_cache_size:
                alloc_cache.append(page_id)
                stats["recycle_fast_cache"] += 1
                status = "RECYCLED_TO_FAST_CACHE"
            elif len(ptr_ring) < pool_size:
                ptr_ring.append(page_id)
                stats["recycle_ptr_ring"] += 1
                status = "RECYCLED_TO_PTR_RING"
            else:
                stats["recycle_ring_overflow_drops"] += 1
                stats["dma_unmap_count"] += 1
                if page_id in dma_mapped:
                    dma_mapped.remove(page_id)
                status = "RELEASED_TO_BUDDY_OVERFLOW"
                
            op_log.append({
                "op": "RECYCLE_DIRECT",
                "page_id": page_id,
                "status": status,
                "alloc_cache_count": len(alloc_cache),
                "ptr_ring_count": len(ptr_ring)
            })
            
        elif op_type == "RECYCLE_REMOTE":
            page_id = op["page_id"]
            if page_id not in in_flight_pages:
                op_log.append({
                    "op": "RECYCLE_REMOTE",
                    "page_id": page_id,
                    "status": "ERROR_PAGE_NOT_IN_FLIGHT"
                })
                continue
                
            in_flight_pages.remove(page_id)
            status = None
            if len(ptr_ring) < pool_size:
                ptr_ring.append(page_id)
                stats["recycle_ptr_ring"] += 1
                status = "RECYCLED_TO_PTR_RING_REMOTE"
            else:
                stats["recycle_ring_overflow_drops"] += 1
                stats["dma_unmap_count"] += 1
                if page_id in dma_mapped:
                    dma_mapped.remove(page_id)
                status = "RELEASED_TO_BUDDY_OVERFLOW"
                
            op_log.append({
                "op": "RECYCLE_REMOTE",
                "page_id": page_id,
                "status": status,
                "alloc_cache_count": len(alloc_cache),
                "ptr_ring_count": len(ptr_ring)
            })
            
        elif op_type == "DRAIN_POOL":
            drained_pages = len(alloc_cache) + len(ptr_ring)
            for pid in alloc_cache:
                if pid in dma_mapped:
                    dma_mapped.remove(pid)
                    stats["dma_unmap_count"] += 1
            for pid in ptr_ring:
                if pid in dma_mapped:
                    dma_mapped.remove(pid)
                    stats["dma_unmap_count"] += 1
            alloc_cache.clear()
            ptr_ring.clear()
            op_log.append({
                "op": "DRAIN_POOL",
                "drained_pages_count": drained_pages,
                "status": "POOL_DRAINED"
            })

    res = {
        "pool_size": pool_size,
        "alloc_cache_size": alloc_cache_size,
        "refill_batch_size": refill_batch_size,
        "dma_sync_enabled": dma_sync_enabled,
        "final_state": {
            "alloc_cache": alloc_cache,
            "ptr_ring": list(ptr_ring),
            "in_flight_pages_count": len(in_flight_pages),
            "dma_mapped_pages_count": len(dma_mapped)
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
