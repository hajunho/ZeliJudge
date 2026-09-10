import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    block_size = data.get("block_size", 4096)
    initial_file_size = data.get("initial_file_size", 0)
    operations = data.get("operations", [])
    
    file_size = initial_file_size
    next_free_pblk = 1000
    extents = []
    
    def coalesce_extents():
        nonlocal extents
        if not extents:
            return
        extents.sort(key=lambda x: x["lblk"])
        merged = []
        for ext in extents:
            if ext["len"] <= 0:
                continue
            if not merged:
                merged.append(dict(ext))
            else:
                last = merged[-1]
                if last["lblk"] + last["len"] == ext["lblk"] and last["state"] == ext["state"]:
                    if last["state"] == "HOLE":
                        last["len"] += ext["len"]
                        continue
                    elif last["pblk"] is not None and ext["pblk"] is not None and (last["pblk"] + last["len"] == ext["pblk"]):
                        last["len"] += ext["len"]
                        continue
                merged.append(dict(ext))
        extents = merged

    op_log = []
    total_blocks_freed = 0
    total_blocks_allocated = 0
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "WRITE":
            offset = op["offset"]
            length = op["length"]
            start_lblk = offset // block_size
            end_lblk = (offset + length + block_size - 1) // block_size
            nr_blocks = end_lblk - start_lblk
            
            new_extents = []
            for ext in extents:
                ext_start = ext["lblk"]
                ext_end = ext["lblk"] + ext["len"]
                if ext_end <= start_lblk or ext_start >= end_lblk:
                    new_extents.append(ext)
                else:
                    if ext_start < start_lblk:
                        new_extents.append({
                            "lblk": ext_start,
                            "len": start_lblk - ext_start,
                            "pblk": ext["pblk"],
                            "state": ext["state"]
                        })
                    if ext_end > end_lblk:
                        offset_pblk = (end_lblk - ext_start) if ext["pblk"] is not None else None
                        new_extents.append({
                            "lblk": end_lblk,
                            "len": ext_end - end_lblk,
                            "pblk": (ext["pblk"] + offset_pblk) if ext["pblk"] is not None else None,
                            "state": ext["state"]
                        })
                        
            pblk = next_free_pblk
            next_free_pblk += nr_blocks
            total_blocks_allocated += nr_blocks
            new_extents.append({
                "lblk": start_lblk,
                "len": nr_blocks,
                "pblk": pblk,
                "state": "WRITTEN"
            })
            extents = new_extents
            coalesce_extents()
            
            if offset + length > file_size:
                file_size = offset + length
                
            op_log.append({
                "op": "WRITE",
                "offset": offset,
                "length": length,
                "pblk_start": pblk,
                "nr_blocks": nr_blocks,
                "file_size": file_size
            })
            
        elif op_type == "PREALLOCATE":
            offset = op["offset"]
            length = op["length"]
            keep_size = op.get("keep_size", False)
            start_lblk = offset // block_size
            end_lblk = (offset + length + block_size - 1) // block_size
            nr_blocks = end_lblk - start_lblk
            
            new_extents = []
            for ext in extents:
                ext_start = ext["lblk"]
                ext_end = ext["lblk"] + ext["len"]
                if ext_end <= start_lblk or ext_start >= end_lblk:
                    new_extents.append(ext)
                else:
                    if ext_start < start_lblk:
                        new_extents.append({
                            "lblk": ext_start,
                            "len": start_lblk - ext_start,
                            "pblk": ext["pblk"],
                            "state": ext["state"]
                        })
                    if ext_end > end_lblk:
                        offset_pblk = (end_lblk - ext_start) if ext["pblk"] is not None else None
                        new_extents.append({
                            "lblk": end_lblk,
                            "len": ext_end - end_lblk,
                            "pblk": (ext["pblk"] + offset_pblk) if ext["pblk"] is not None else None,
                            "state": ext["state"]
                        })
            
            pblk = next_free_pblk
            next_free_pblk += nr_blocks
            total_blocks_allocated += nr_blocks
            new_extents.append({
                "lblk": start_lblk,
                "len": nr_blocks,
                "pblk": pblk,
                "state": "UNWRITTEN"
            })
            extents = new_extents
            coalesce_extents()
            
            if not keep_size and (offset + length > file_size):
                file_size = offset + length
                
            op_log.append({
                "op": "PREALLOCATE",
                "offset": offset,
                "length": length,
                "keep_size": keep_size,
                "file_size": file_size
            })
            
        elif op_type == "PUNCH_HOLE":
            offset = op["offset"]
            length = op["length"]
            start_lblk = offset // block_size
            end_lblk = (offset + length) // block_size
            punch_len = end_lblk - start_lblk
            
            freed_count = 0
            new_extents = []
            for ext in extents:
                ext_start = ext["lblk"]
                ext_end = ext["lblk"] + ext["len"]
                if ext_end <= start_lblk or ext_start >= end_lblk:
                    new_extents.append(ext)
                else:
                    overlap_start = max(ext_start, start_lblk)
                    overlap_end = min(ext_end, end_lblk)
                    if ext["state"] in ("WRITTEN", "UNWRITTEN"):
                        freed_count += (overlap_end - overlap_start)
                        
                    if ext_start < start_lblk:
                        new_extents.append({
                            "lblk": ext_start,
                            "len": start_lblk - ext_start,
                            "pblk": ext["pblk"],
                            "state": ext["state"]
                        })
                    if ext_end > end_lblk:
                        offset_pblk = (end_lblk - ext_start) if ext["pblk"] is not None else None
                        new_extents.append({
                            "lblk": end_lblk,
                            "len": ext_end - end_lblk,
                            "pblk": (ext["pblk"] + offset_pblk) if ext["pblk"] is not None else None,
                            "state": ext["state"]
                        })
                        
            new_extents.append({
                "lblk": start_lblk,
                "len": punch_len,
                "pblk": None,
                "state": "HOLE"
            })
            total_blocks_freed += freed_count
            extents = new_extents
            coalesce_extents()
            
            op_log.append({
                "op": "PUNCH_HOLE",
                "offset": offset,
                "length": length,
                "freed_blocks": freed_count,
                "file_size": file_size
            })
            
        elif op_type == "ZERO_RANGE":
            offset = op["offset"]
            length = op["length"]
            keep_size = op.get("keep_size", False)
            start_lblk = offset // block_size
            end_lblk = (offset + length) // block_size
            zero_len = end_lblk - start_lblk
            
            new_extents = []
            for ext in extents:
                ext_start = ext["lblk"]
                ext_end = ext["lblk"] + ext["len"]
                if ext_end <= start_lblk or ext_start >= end_lblk:
                    new_extents.append(ext)
                else:
                    if ext_start < start_lblk:
                        new_extents.append({
                            "lblk": ext_start,
                            "len": start_lblk - ext_start,
                            "pblk": ext["pblk"],
                            "state": ext["state"]
                        })
                    if ext_end > end_lblk:
                        offset_pblk = (end_lblk - ext_start) if ext["pblk"] is not None else None
                        new_extents.append({
                            "lblk": end_lblk,
                            "len": ext_end - end_lblk,
                            "pblk": (ext["pblk"] + offset_pblk) if ext["pblk"] is not None else None,
                            "state": ext["state"]
                        })
            
            pblk = next_free_pblk
            next_free_pblk += zero_len
            total_blocks_allocated += zero_len
            new_extents.append({
                "lblk": start_lblk,
                "len": zero_len,
                "pblk": pblk,
                "state": "UNWRITTEN"
            })
            extents = new_extents
            coalesce_extents()
            
            if not keep_size and (offset + length > file_size):
                file_size = offset + length
                
            op_log.append({
                "op": "ZERO_RANGE",
                "offset": offset,
                "length": length,
                "zero_len": zero_len,
                "file_size": file_size
            })
            
        elif op_type == "COLLAPSE_RANGE":
            offset = op["offset"]
            length = op["length"]
            start_lblk = offset // block_size
            end_lblk = (offset + length) // block_size
            shift_blocks = end_lblk - start_lblk
            
            freed_count = 0
            new_extents = []
            for ext in extents:
                ext_start = ext["lblk"]
                ext_end = ext["lblk"] + ext["len"]
                if ext_end <= start_lblk:
                    new_extents.append(ext)
                elif ext_start >= end_lblk:
                    new_extents.append({
                        "lblk": ext_start - shift_blocks,
                        "len": ext["len"],
                        "pblk": ext["pblk"],
                        "state": ext["state"]
                    })
                else:
                    if ext["state"] in ("WRITTEN", "UNWRITTEN"):
                        freed_count += ext["len"]
                        
            file_size = max(0, file_size - length)
            total_blocks_freed += freed_count
            extents = new_extents
            coalesce_extents()
            
            op_log.append({
                "op": "COLLAPSE_RANGE",
                "offset": offset,
                "length": length,
                "freed_blocks": freed_count,
                "file_size": file_size
            })
            
        elif op_type == "INSERT_RANGE":
            offset = op["offset"]
            length = op["length"]
            start_lblk = offset // block_size
            shift_blocks = length // block_size
            
            new_extents = []
            for ext in extents:
                ext_start = ext["lblk"]
                if ext_start < start_lblk:
                    new_extents.append(ext)
                else:
                    new_extents.append({
                        "lblk": ext_start + shift_blocks,
                        "len": ext["len"],
                        "pblk": ext["pblk"],
                        "state": ext["state"]
                    })
            new_extents.append({
                "lblk": start_lblk,
                "len": shift_blocks,
                "pblk": None,
                "state": "HOLE"
            })
            file_size += length
            extents = new_extents
            coalesce_extents()
            
            op_log.append({
                "op": "INSERT_RANGE",
                "offset": offset,
                "length": length,
                "inserted_blocks": shift_blocks,
                "file_size": file_size
            })

    coalesce_extents()
    
    allocated_blocks_total = sum(e["len"] for e in extents if e["state"] in ("WRITTEN", "UNWRITTEN"))
    hole_blocks_total = sum(e["len"] for e in extents if e["state"] == "HOLE")
    
    result = {
        "file_size": file_size,
        "block_size": block_size,
        "allocated_blocks": allocated_blocks_total,
        "hole_blocks": hole_blocks_total,
        "extent_count": len(extents),
        "extents": extents,
        "stats": {
            "total_blocks_allocated": total_blocks_allocated,
            "total_blocks_freed": total_blocks_freed
        },
        "op_log": op_log
    }
    
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    solve()
