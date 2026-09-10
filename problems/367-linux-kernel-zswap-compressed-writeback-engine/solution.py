import sys
import json

def solve():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return

    data = json.loads(raw_input)
    max_pool_pages = data.get("max_pool_pages", 4)
    page_size = data.get("page_size", 4096)
    threshold = data.get("max_compression_ratio_threshold", 0.8)
    operations = data.get("operations", [])

    pool_capacity_bytes = max_pool_pages * page_size
    current_pool_bytes = 0

    zswap_tree = {}
    lru_queue = []
    disk_swap = set()

    stats = {
        "store_requests": 0,
        "stored_zswap": 0,
        "rejected_poor_compression": 0,
        "rejected_pool_full": 0,
        "evicted_to_disk": 0,
        "load_requests": 0,
        "zswap_hits": 0,
        "disk_hits": 0,
        "load_misses": 0,
        "invalidations": 0
    }

    op_log = []

    for op in operations:
        op_type = op.get("op")

        if op_type == "SWAP_STORE":
            stats["store_requests"] += 1
            stype = op["swap_type"]
            soff = op["swap_offset"]
            key = (stype, soff)
            u_bytes = op.get("uncompressed_bytes", page_size)
            c_bytes = op.get("compressed_bytes", page_size // 2)

            if key in zswap_tree:
                old_entry = zswap_tree.pop(key)
                lru_queue.remove(key)
                current_pool_bytes -= old_entry["compressed_bytes"]
            disk_swap.discard(key)

            ratio = c_bytes / u_bytes
            if ratio > threshold:
                stats["rejected_poor_compression"] += 1
                disk_swap.add(key)
                op_log.append({
                    "op": "SWAP_STORE",
                    "key": f"{stype}:{soff}",
                    "ratio": round(ratio, 4),
                    "status": "REJECTED_POOR_COMPRESSION_TO_DISK"
                })
            else:
                evicted_this_op = []
                while current_pool_bytes + c_bytes > pool_capacity_bytes and lru_queue:
                    old_k = lru_queue.pop(0)
                    old_item = zswap_tree.pop(old_k)
                    current_pool_bytes -= old_item["compressed_bytes"]
                    disk_swap.add(old_k)
                    stats["evicted_to_disk"] += 1
                    evicted_this_op.append(f"{old_k[0]}:{old_k[1]}")

                if current_pool_bytes + c_bytes > pool_capacity_bytes:
                    stats["rejected_pool_full"] += 1
                    disk_swap.add(key)
                    op_log.append({
                        "op": "SWAP_STORE",
                        "key": f"{stype}:{soff}",
                        "status": "REJECTED_POOL_FULL_TO_DISK",
                        "evicted_keys": evicted_this_op
                    })
                else:
                    zswap_tree[key] = {
                        "swap_type": stype,
                        "swap_offset": soff,
                        "compressed_bytes": c_bytes,
                        "uncompressed_bytes": u_bytes
                    }
                    lru_queue.append(key)
                    current_pool_bytes += c_bytes
                    stats["stored_zswap"] += 1
                    op_log.append({
                        "op": "SWAP_STORE",
                        "key": f"{stype}:{soff}",
                        "compressed_bytes": c_bytes,
                        "current_pool_bytes": current_pool_bytes,
                        "status": "STORED_ZSWAP",
                        "evicted_keys": evicted_this_op
                    })

        elif op_type == "SWAP_LOAD":
            stats["load_requests"] += 1
            stype = op["swap_type"]
            soff = op["swap_offset"]
            key = (stype, soff)

            if key in zswap_tree:
                entry = zswap_tree.pop(key)
                lru_queue.remove(key)
                current_pool_bytes -= entry["compressed_bytes"]
                stats["zswap_hits"] += 1
                op_log.append({
                    "op": "SWAP_LOAD",
                    "key": f"{stype}:{soff}",
                    "status": "HIT_ZSWAP_DECOMPRESSED",
                    "decompressed_bytes": entry["uncompressed_bytes"]
                })
            elif key in disk_swap:
                stats["disk_hits"] += 1
                op_log.append({
                    "op": "SWAP_LOAD",
                    "key": f"{stype}:{soff}",
                    "status": "HIT_DISK_SWAP"
                })
            else:
                stats["load_misses"] += 1
                op_log.append({
                    "op": "SWAP_LOAD",
                    "key": f"{stype}:{soff}",
                    "status": "MISS_NOT_FOUND"
                })

        elif op_type == "SWAP_INVALIDATE":
            stype = op["swap_type"]
            soff = op["swap_offset"]
            key = (stype, soff)
            was_in_zswap = False
            was_in_disk = False

            if key in zswap_tree:
                entry = zswap_tree.pop(key)
                lru_queue.remove(key)
                current_pool_bytes -= entry["compressed_bytes"]
                was_in_zswap = True
            if key in disk_swap:
                disk_swap.remove(key)
                was_in_disk = True

            if was_in_zswap or was_in_disk:
                stats["invalidations"] += 1
                op_log.append({
                    "op": "SWAP_INVALIDATE",
                    "key": f"{stype}:{soff}",
                    "status": "INVALIDATED_OK",
                    "was_in_zswap": was_in_zswap,
                    "was_in_disk": was_in_disk
                })
            else:
                op_log.append({
                    "op": "SWAP_INVALIDATE",
                    "key": f"{stype}:{soff}",
                    "status": "NOT_FOUND"
                })

    active_zswap_entries = len(zswap_tree)
    active_disk_entries = len(disk_swap)
    pool_utilization_ratio = round(current_pool_bytes / max(1, pool_capacity_bytes), 4)

    result = {
        "max_pool_pages": max_pool_pages,
        "page_size": page_size,
        "pool_capacity_bytes": pool_capacity_bytes,
        "current_pool_bytes": current_pool_bytes,
        "pool_utilization_ratio": pool_utilization_ratio,
        "active_zswap_entries": active_zswap_entries,
        "active_disk_entries": active_disk_entries,
        "stats": stats,
        "lru_keys": [f"{k[0]}:{k[1]}" for k in lru_queue],
        "op_log": op_log
    }

    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    solve()
