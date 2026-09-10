import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def simulate_dm_thin(input_data):
    pool_config = input_data.get("pool_config", {})
    chunk_size_kb = pool_config.get("chunk_size_kb", 64)
    total_data_chunks = pool_config.get("total_data_chunks", 100)
    low_watermark_pct = pool_config.get("low_watermark_pct", 80)
    error_if_no_space = pool_config.get("error_if_no_space", True)
    
    space_map = [0] * total_data_chunks
    free_chunks = list(range(total_data_chunks))
    
    devices = {}
    for dev_id, dev_info in input_data.get("devices", {}).items():
        devices[dev_id] = {
            "mappings": {},
            "provisioned_chunks": 0,
            "max_v_chunks": dev_info.get("max_v_chunks", 1000)
        }
        
    events = input_data.get("events", [])
    deferred_writes = []
    
    stats = {
        "read_hits": 0,
        "read_sparse_zeroes": 0,
        "write_in_place": 0,
        "write_new_alloc": 0,
        "write_cow_breaks": 0,
        "write_enospc_errors": 0,
        "write_deferred": 0,
        "discards_processed": 0,
        "snapshots_created": 0,
        "pool_extensions": 0,
        "low_watermark_events": 0
    }
    
    event_logs = []
    
    def check_low_watermark():
        used = total_data_chunks - len(free_chunks)
        used_pct = (used / total_data_chunks) * 100.0
        return used_pct >= low_watermark_pct
        
    watermark_triggered = False

    for ev in events:
        etype = ev.get("type")
        
        if etype == "READ":
            dev_id = ev["dev_id"]
            v_chunk = ev["v_chunk"]
            if dev_id not in devices:
                continue
            dev = devices[dev_id]
            if v_chunk in dev["mappings"]:
                p_chunk = dev["mappings"][v_chunk]
                stats["read_hits"] += 1
                event_logs.append({
                    "event": "READ",
                    "dev_id": dev_id,
                    "v_chunk": v_chunk,
                    "result": "HIT",
                    "p_chunk": p_chunk
                })
            else:
                stats["read_sparse_zeroes"] += 1
                event_logs.append({
                    "event": "READ",
                    "dev_id": dev_id,
                    "v_chunk": v_chunk,
                    "result": "SPARSE_ZERO",
                    "p_chunk": None
                })
                
        elif etype == "WRITE":
            dev_id = ev["dev_id"]
            v_chunk = ev["v_chunk"]
            if dev_id not in devices:
                continue
            dev = devices[dev_id]
            
            if v_chunk in dev["mappings"]:
                p_chunk = dev["mappings"][v_chunk]
                if space_map[p_chunk] == 1:
                    stats["write_in_place"] += 1
                    event_logs.append({
                        "event": "WRITE",
                        "dev_id": dev_id,
                        "v_chunk": v_chunk,
                        "action": "OVERWRITE_IN_PLACE",
                        "p_chunk": p_chunk
                    })
                else:
                    if not free_chunks:
                        if error_if_no_space:
                            stats["write_enospc_errors"] += 1
                            event_logs.append({
                                "event": "WRITE",
                                "dev_id": dev_id,
                                "v_chunk": v_chunk,
                                "action": "ERROR_ENOSPC",
                                "reason": "COW_BREAK_NO_SPACE"
                            })
                        else:
                            stats["write_deferred"] += 1
                            deferred_writes.append(ev)
                            event_logs.append({
                                "event": "WRITE",
                                "dev_id": dev_id,
                                "v_chunk": v_chunk,
                                "action": "DEFERRED_QUEUE",
                                "reason": "COW_BREAK_NO_SPACE"
                            })
                    else:
                        new_p_chunk = free_chunks.pop(0)
                        space_map[new_p_chunk] = 1
                        space_map[p_chunk] -= 1
                        dev["mappings"][v_chunk] = new_p_chunk
                        stats["write_cow_breaks"] += 1
                        event_logs.append({
                            "event": "WRITE",
                            "dev_id": dev_id,
                            "v_chunk": v_chunk,
                            "action": "COW_BREAK_ALLOC",
                            "old_p_chunk": p_chunk,
                            "new_p_chunk": new_p_chunk
                        })
            else:
                if not free_chunks:
                    if error_if_no_space:
                        stats["write_enospc_errors"] += 1
                        event_logs.append({
                            "event": "WRITE",
                            "dev_id": dev_id,
                            "v_chunk": v_chunk,
                            "action": "ERROR_ENOSPC",
                            "reason": "POOL_EXHAUSTED"
                        })
                    else:
                        stats["write_deferred"] += 1
                        deferred_writes.append(ev)
                        event_logs.append({
                            "event": "WRITE",
                            "dev_id": dev_id,
                            "v_chunk": v_chunk,
                            "action": "DEFERRED_QUEUE",
                            "reason": "POOL_EXHAUSTED"
                        })
                else:
                    new_p_chunk = free_chunks.pop(0)
                    space_map[new_p_chunk] = 1
                    dev["mappings"][v_chunk] = new_p_chunk
                    dev["provisioned_chunks"] += 1
                    stats["write_new_alloc"] += 1
                    event_logs.append({
                        "event": "WRITE",
                        "dev_id": dev_id,
                        "v_chunk": v_chunk,
                        "action": "NEW_ALLOCATION",
                        "p_chunk": new_p_chunk
                    })
                    
            if not watermark_triggered and check_low_watermark():
                stats["low_watermark_events"] += 1
                watermark_triggered = True
                event_logs.append({
                    "event": "WARNING_LOW_WATERMARK",
                    "used_chunks": total_data_chunks - len(free_chunks),
                    "total_chunks": total_data_chunks
                })
                
        elif etype == "SNAPSHOT":
            origin_id = ev["origin_id"]
            snap_id = ev["snap_id"]
            if origin_id in devices and snap_id not in devices:
                origin = devices[origin_id]
                snap_mappings = dict(origin["mappings"])
                for vc, pc in snap_mappings.items():
                    space_map[pc] += 1
                devices[snap_id] = {
                    "mappings": snap_mappings,
                    "provisioned_chunks": len(snap_mappings),
                    "max_v_chunks": origin["max_v_chunks"]
                }
                stats["snapshots_created"] += 1
                event_logs.append({
                    "event": "SNAPSHOT",
                    "origin_id": origin_id,
                    "snap_id": snap_id,
                    "shared_chunks": len(snap_mappings)
                })
                
        elif etype == "DISCARD":
            dev_id = ev["dev_id"]
            v_chunk = ev["v_chunk"]
            if dev_id in devices and v_chunk in devices[dev_id]["mappings"]:
                p_chunk = devices[dev_id]["mappings"].pop(v_chunk)
                devices[dev_id]["provisioned_chunks"] -= 1
                space_map[p_chunk] -= 1
                freed = False
                if space_map[p_chunk] == 0:
                    free_chunks.append(p_chunk)
                    free_chunks.sort()
                    freed = True
                stats["discards_processed"] += 1
                event_logs.append({
                    "event": "DISCARD",
                    "dev_id": dev_id,
                    "v_chunk": v_chunk,
                    "p_chunk": p_chunk,
                    "freed_to_pool": freed
                })
                if watermark_triggered and not check_low_watermark():
                    watermark_triggered = False
                    
        elif etype == "EXTEND_POOL":
            added_chunks = ev.get("additional_chunks", 0)
            start_id = total_data_chunks
            total_data_chunks += added_chunks
            space_map.extend([0] * added_chunks)
            for cid in range(start_id, total_data_chunks):
                free_chunks.append(cid)
            free_chunks.sort()
            stats["pool_extensions"] += 1
            event_logs.append({
                "event": "EXTEND_POOL",
                "added_chunks": added_chunks,
                "new_total_chunks": total_data_chunks
            })
            
            if deferred_writes:
                flushed = []
                while deferred_writes and free_chunks:
                    dev_ev = deferred_writes.pop(0)
                    d_id = dev_ev["dev_id"]
                    v_c = dev_ev["v_chunk"]
                    dev = devices[d_id]
                    if v_c in dev["mappings"]:
                        p_old = dev["mappings"][v_c]
                        p_new = free_chunks.pop(0)
                        space_map[p_new] = 1
                        space_map[p_old] -= 1
                        dev["mappings"][v_c] = p_new
                        stats["write_cow_breaks"] += 1
                        flushed.append({"dev_id": d_id, "v_chunk": v_c, "type": "COW_FLUSH", "p_chunk": p_new})
                    else:
                        p_new = free_chunks.pop(0)
                        space_map[p_new] = 1
                        dev["mappings"][v_c] = p_new
                        dev["provisioned_chunks"] += 1
                        stats["write_new_alloc"] += 1
                        flushed.append({"dev_id": d_id, "v_chunk": v_c, "type": "NEW_ALLOC_FLUSH", "p_chunk": p_new})
                event_logs.append({
                    "event": "DEFERRED_FLUSH",
                    "processed_count": len(flushed),
                    "items": flushed
                })

    used_chunks = total_data_chunks - len(free_chunks)
    pool_utilization_pct = round((used_chunks / total_data_chunks) * 100.0, 2)
    
    total_virtual_provisioned = sum(d["provisioned_chunks"] for d in devices.values())
    overprovisioning_ratio = round(total_virtual_provisioned / max(1, total_data_chunks), 2)
    
    shared_chunks_count = sum(1 for c in space_map if c > 1)
    exclusive_chunks_count = sum(1 for c in space_map if c == 1)
    
    device_summaries = {}
    for d_id, d_data in devices.items():
        device_summaries[d_id] = {
            "provisioned_chunks": d_data["provisioned_chunks"],
            "mapped_chunks_count": len(d_data["mappings"]),
            "mappings": {str(k): v for k, v in sorted(d_data["mappings"].items())}
        }

    return {
        "pool_status": {
            "total_physical_chunks": total_data_chunks,
            "used_physical_chunks": used_chunks,
            "free_physical_chunks": len(free_chunks),
            "utilization_pct": pool_utilization_pct,
            "shared_chunks_count": shared_chunks_count,
            "exclusive_chunks_count": exclusive_chunks_count,
            "overprovisioning_ratio": overprovisioning_ratio
        },
        "stats": stats,
        "deferred_queue_remaining": len(deferred_writes),
        "devices": device_summaries,
        "event_logs": event_logs
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = simulate_dm_thin(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
