import sys
import json
import zlib

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def solve(data):
    config = data.get("config", {})
    min_blob_size = config.get("min_blob_size", 128)
    max_blob_file_size = config.get("max_blob_file_size", 4096)
    blob_garbage_threshold = config.get("blob_garbage_threshold", 0.30)
    enable_gc_on_write = config.get("enable_gc_on_write", False)
    lsm_benchmark_wa = config.get("lsm_benchmark_wa", 15.0)

    files = {}
    active_fn = 1
    files[active_fn] = {
        "file_number": active_fn,
        "status": "ACTIVE",
        "total_bytes": 0,
        "live_bytes": 0,
        "garbage_bytes": 0,
        "records": []
    }
    total_files_created = 1
    purged_files = []
    lsm_index = {}

    query_results = []
    gc_runs_total = 0
    total_blobs_relocated = 0
    total_bytes_relocated = 0
    total_bytes_reclaimed = 0
    initial_blob_bytes_written = 0

    def run_gc():
        nonlocal gc_runs_total, total_blobs_relocated, total_bytes_relocated, total_bytes_reclaimed, active_fn, total_files_created
        candidates = []
        for fn in sorted(files.keys()):
            f = files[fn]
            if f["status"] == "IMMUTABLE":
                ratio = f["garbage_bytes"] / f["total_bytes"] if f["total_bytes"] > 0 else 0.0
                if ratio >= blob_garbage_threshold - 1e-9:
                    candidates.append(fn)
        
        if not candidates:
            return

        gc_runs_total += 1
        for fn in candidates:
            cand = files[fn]
            for rec in cand["records"]:
                k = rec["key"]
                lsm_entry = lsm_index.get(k)
                if (lsm_entry and 
                    lsm_entry["type"] == "BLOB_INDEX" and 
                    lsm_entry["file_number"] == fn and 
                    lsm_entry["offset"] == rec["offset"]):
                    # LIVE BLOB: Relocate
                    rec_size = rec["record_size"]
                    active_f = files[active_fn]
                    if active_f["total_bytes"] + rec_size > max_blob_file_size and active_f["total_bytes"] > 0:
                        active_f["status"] = "IMMUTABLE"
                        active_fn += 1
                        total_files_created += 1
                        files[active_fn] = {
                            "file_number": active_fn,
                            "status": "ACTIVE",
                            "total_bytes": 0,
                            "live_bytes": 0,
                            "garbage_bytes": 0,
                            "records": []
                        }
                        active_f = files[active_fn]
                    
                    new_offset = active_f["total_bytes"]
                    new_rec = {
                        "key": rec["key"],
                        "value": rec["value"],
                        "offset": new_offset,
                        "record_size": rec["record_size"],
                        "val_size": rec["val_size"],
                        "crc32": rec["crc32"]
                    }
                    active_f["records"].append(new_rec)
                    active_f["total_bytes"] += rec_size
                    active_f["live_bytes"] += rec_size

                    lsm_index[k] = {
                        "type": "BLOB_INDEX",
                        "file_number": active_fn,
                        "offset": new_offset,
                        "record_size": rec_size,
                        "val_size": rec["val_size"],
                        "crc32": rec["crc32"]
                    }
                    total_blobs_relocated += 1
                    total_bytes_relocated += rec_size
            
            cand["status"] = "PURGED"
            total_bytes_reclaimed += cand["garbage_bytes"]
            purged_files.append(fn)

    operations = data.get("operations", [])
    for op_item in operations:
        op = op_item.get("op")
        if op == "PUT":
            key = op_item["key"]
            value = op_item["value"]
            val_bytes = value.encode("utf-8")
            val_len = len(val_bytes)
            key_bytes = key.encode("utf-8")
            key_len = len(key_bytes)

            old_entry = lsm_index.get(key)
            if old_entry and old_entry["type"] == "BLOB_INDEX":
                old_fn = old_entry["file_number"]
                if old_fn in files and files[old_fn]["status"] != "PURGED":
                    files[old_fn]["live_bytes"] -= old_entry["record_size"]
                    files[old_fn]["garbage_bytes"] += old_entry["record_size"]

            if val_len >= min_blob_size:
                crc_val = f"{zlib.crc32(val_bytes) & 0xffffffff:08x}"
                rec_size = 16 + key_len + val_len

                active_f = files[active_fn]
                if active_f["total_bytes"] + rec_size > max_blob_file_size and active_f["total_bytes"] > 0:
                    active_f["status"] = "IMMUTABLE"
                    active_fn += 1
                    total_files_created += 1
                    files[active_fn] = {
                        "file_number": active_fn,
                        "status": "ACTIVE",
                        "total_bytes": 0,
                        "live_bytes": 0,
                        "garbage_bytes": 0,
                        "records": []
                    }
                    active_f = files[active_fn]

                offset = active_f["total_bytes"]
                active_f["records"].append({
                    "key": key,
                    "value": value,
                    "offset": offset,
                    "record_size": rec_size,
                    "val_size": val_len,
                    "crc32": crc_val
                })
                active_f["total_bytes"] += rec_size
                active_f["live_bytes"] += rec_size
                initial_blob_bytes_written += rec_size

                lsm_index[key] = {
                    "type": "BLOB_INDEX",
                    "file_number": active_fn,
                    "offset": offset,
                    "record_size": rec_size,
                    "val_size": val_len,
                    "crc32": crc_val
                }
            else:
                lsm_index[key] = {
                    "type": "INLINE",
                    "value": value,
                    "val_size": val_len
                }

            if enable_gc_on_write:
                run_gc()

        elif op == "DELETE":
            key = op_item["key"]
            old_entry = lsm_index.pop(key, None)
            if old_entry and old_entry["type"] == "BLOB_INDEX":
                old_fn = old_entry["file_number"]
                if old_fn in files and files[old_fn]["status"] != "PURGED":
                    files[old_fn]["live_bytes"] -= old_entry["record_size"]
                    files[old_fn]["garbage_bytes"] += old_entry["record_size"]

            if enable_gc_on_write:
                run_gc()

        elif op == "GET":
            key = op_item["key"]
            entry = lsm_index.get(key)
            if not entry:
                query_results.append({
                    "op": "GET",
                    "key": key,
                    "found": False,
                    "value": None
                })
            elif entry["type"] == "INLINE":
                query_results.append({
                    "op": "GET",
                    "key": key,
                    "found": True,
                    "source": "INLINE",
                    "value": entry["value"]
                })
            elif entry["type"] == "BLOB_INDEX":
                fn = entry["file_number"]
                offset = entry["offset"]
                f = files.get(fn)
                val_retrieved = None
                crc_verified = False
                if f and f["status"] != "PURGED":
                    for r in f["records"]:
                        if r["offset"] == offset:
                            val_retrieved = r["value"]
                            computed_crc = f"{zlib.crc32(val_retrieved.encode('utf-8')) & 0xffffffff:08x}"
                            crc_verified = (computed_crc == entry["crc32"])
                            break
                query_results.append({
                    "op": "GET",
                    "key": key,
                    "found": True,
                    "source": "BLOB",
                    "file_number": fn,
                    "offset": offset,
                    "size": entry["val_size"],
                    "crc_valid": crc_verified,
                    "value": val_retrieved
                })

        elif op == "TRIGGER_GC":
            run_gc()

    active_files_list = []
    total_blob_bytes_on_disk = 0
    total_live_bytes_on_disk = 0
    total_garbage_bytes_on_disk = 0

    for fn in sorted(files.keys()):
        f = files[fn]
        if f["status"] != "PURGED":
            tot = f["total_bytes"]
            live = f["live_bytes"]
            garb = f["garbage_bytes"]
            ratio = round(garb / tot, 4) if tot > 0 else 0.0
            active_files_list.append({
                "file_number": fn,
                "status": f["status"],
                "total_bytes": tot,
                "live_bytes": live,
                "garbage_bytes": garb,
                "garbage_ratio": ratio
            })
            total_blob_bytes_on_disk += tot
            total_live_bytes_on_disk += live
            total_garbage_bytes_on_disk += garb

    inline_keys = sum(1 for v in lsm_index.values() if v["type"] == "INLINE")
    blob_keys = sum(1 for v in lsm_index.values() if v["type"] == "BLOB_INDEX")

    space_amp = round(total_blob_bytes_on_disk / total_live_bytes_on_disk, 4) if total_live_bytes_on_disk > 0 else 1.0

    if initial_blob_bytes_written > 0:
        wisckey_wa = 1.0 + (total_bytes_relocated / initial_blob_bytes_written)
        saving_pct = max(0.0, (lsm_benchmark_wa - wisckey_wa) / lsm_benchmark_wa * 100.0)
    else:
        wisckey_wa = 1.0
        saving_pct = 0.0

    return {
        "query_results": query_results,
        "lsm_state": {
            "total_keys": len(lsm_index),
            "inline_keys": inline_keys,
            "blob_keys": blob_keys
        },
        "blob_storage_stats": {
            "active_file_number": active_fn,
            "total_files_created": total_files_created,
            "purged_files": sorted(purged_files),
            "active_files": active_files_list,
            "total_blob_bytes_on_disk": total_blob_bytes_on_disk,
            "total_live_bytes_on_disk": total_live_bytes_on_disk,
            "total_garbage_bytes_on_disk": total_garbage_bytes_on_disk
        },
        "gc_summary": {
            "gc_runs_total": gc_runs_total,
            "total_blobs_relocated": total_blobs_relocated,
            "total_bytes_relocated": total_bytes_relocated,
            "total_bytes_reclaimed": total_bytes_reclaimed
        },
        "efficiency_metrics": {
            "space_amplification": space_amp,
            "wisckey_write_amplification": round(wisckey_wa, 4),
            "lsm_write_amp_saving_pct": round(saving_pct, 2)
        }
    }

def main():
    try:
        raw_data = sys.stdin.read().strip()
        if not raw_data:
            return
        data = json.loads(raw_data)
        res = solve(data)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
