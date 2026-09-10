import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    window_size_mb = data.get("window_size_mb", 512)
    block_size_mb = data.get("block_size_mb", 128)
    subblock_size_mb = data.get("subblock_size_mb", 2)
    initial_plugged_mb = data.get("initial_plugged_mb", 0)
    operations = data.get("operations", [])
    
    total_subblocks = window_size_mb // subblock_size_mb
    subblocks = ["UNPLUGGED"] * total_subblocks
    
    init_sb_count = min(total_subblocks, initial_plugged_mb // subblock_size_mb)
    for i in range(init_sb_count):
        subblocks[i] = "PLUGGED"
        
    requested_size_mb = initial_plugged_mb
    
    stats = {
        "plug_requests": 0,
        "unplug_requests": 0,
        "subblocks_plugged": init_sb_count,
        "subblocks_unplugged": 0,
        "unplug_failures_pinned": 0
    }
    
    op_log = []
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "PIN_SUBBLOCK":
            sb_idx = op.get("subblock_idx")
            if 0 <= sb_idx < total_subblocks:
                if subblocks[sb_idx] == "PLUGGED":
                    subblocks[sb_idx] = "PINNED"
                    status = "SUBBLOCK_PINNED_UNMOVABLE"
                else:
                    status = "CANNOT_PIN_UNPLUGGED"
            else:
                status = "INDEX_OUT_OF_BOUNDS"
            op_log.append({
                "op": "PIN_SUBBLOCK",
                "subblock_idx": sb_idx,
                "status": status
            })
            
        elif op_type == "UNPIN_SUBBLOCK":
            sb_idx = op.get("subblock_idx")
            if 0 <= sb_idx < total_subblocks:
                if subblocks[sb_idx] == "PINNED":
                    subblocks[sb_idx] = "PLUGGED"
                    status = "SUBBLOCK_UNPINNED"
                else:
                    status = "NOT_PINNED"
            else:
                status = "INDEX_OUT_OF_BOUNDS"
            op_log.append({
                "op": "UNPIN_SUBBLOCK",
                "subblock_idx": sb_idx,
                "status": status
            })
            
        elif op_type == "SET_REQUESTED_SIZE":
            target_mb = op.get("target_mb", requested_size_mb)
            requested_size_mb = min(window_size_mb, max(0, target_mb))
            target_sb_count = requested_size_mb // subblock_size_mb
            
            current_plugged_count = sum(1 for s in subblocks if s in ("PLUGGED", "PINNED"))
            delta = target_sb_count - current_plugged_count
            
            plugged_in_op = 0
            unplugged_in_op = 0
            pinned_blocked_in_op = 0
            
            if delta > 0:
                stats["plug_requests"] += 1
                for i in range(total_subblocks):
                    if plugged_in_op >= delta:
                        break
                    if subblocks[i] == "UNPLUGGED":
                        subblocks[i] = "PLUGGED"
                        plugged_in_op += 1
                        stats["subblocks_plugged"] += 1
                        
            elif delta < 0:
                stats["unplug_requests"] += 1
                to_unplug = abs(delta)
                for i in range(total_subblocks - 1, -1, -1):
                    if unplugged_in_op >= to_unplug:
                        break
                    if subblocks[i] == "PLUGGED":
                        subblocks[i] = "UNPLUGGED"
                        unplugged_in_op += 1
                        stats["subblocks_unplugged"] += 1
                    elif subblocks[i] == "PINNED":
                        pinned_blocked_in_op += 1
                        stats["unplug_failures_pinned"] += 1
                        
            current_plugged_count = sum(1 for s in subblocks if s in ("PLUGGED", "PINNED"))
            current_plugged_mb = current_plugged_count * subblock_size_mb
            
            op_log.append({
                "op": "SET_REQUESTED_SIZE",
                "target_mb": requested_size_mb,
                "plugged_mb": current_plugged_mb,
                "delta_subblocks": delta,
                "plugged_subblocks": plugged_in_op,
                "unplugged_subblocks": unplugged_in_op,
                "pinned_blocked": pinned_blocked_in_op
            })

    current_plugged_count = sum(1 for s in subblocks if s in ("PLUGGED", "PINNED"))
    pinned_count = sum(1 for s in subblocks if s == "PINNED")
    current_plugged_mb = current_plugged_count * subblock_size_mb
    pinned_mb = pinned_count * subblock_size_mb
    
    stalled = (current_plugged_mb > requested_size_mb)
    
    result = {
        "window_size_mb": window_size_mb,
        "block_size_mb": block_size_mb,
        "subblock_size_mb": subblock_size_mb,
        "requested_size_mb": requested_size_mb,
        "current_plugged_mb": current_plugged_mb,
        "pinned_mb": pinned_mb,
        "plugged_subblocks_count": current_plugged_count,
        "pinned_subblocks_count": pinned_count,
        "unplug_stalled_by_pinning": stalled,
        "stats": stats,
        "op_log": op_log
    }
    
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    solve()
