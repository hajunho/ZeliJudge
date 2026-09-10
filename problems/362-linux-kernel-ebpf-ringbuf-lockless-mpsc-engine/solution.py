import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def round_up(val, align):
    return (val + align - 1) & ~(align - 1)

def solve():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    ringbuf_size = data.get("ringbuf_size", 1024)
    operations = data.get("operations", [])
    
    producer_pos = 0
    consumer_pos = 0
    
    reservations = {}
    next_res_id = 1
    slots = {}
    
    stats = {
        "records_reserved": 0,
        "records_committed": 0,
        "records_discarded": 0,
        "records_dropped": 0,
        "records_consumed": 0,
        "bytes_reserved": 0,
        "bytes_consumed": 0,
        "wakeups_triggered": 0
    }
    
    op_log = []
    
    for op in operations:
        op_type = op.get("op")
        
        if op_type == "RESERVE":
            pid = op.get("producer_id", "cpu_0")
            payload_len = op.get("len", 16)
            data_str = op.get("data", f"event_{next_res_id}")
            
            total_len = round_up(8 + payload_len, 8)
            
            if (producer_pos - consumer_pos + total_len) > ringbuf_size:
                stats["records_dropped"] += 1
                op_log.append({
                    "op": "RESERVE",
                    "producer_id": pid,
                    "status": "DROPPED_BUFFER_FULL",
                    "len": payload_len,
                    "producer_pos": producer_pos,
                    "consumer_pos": consumer_pos
                })
            else:
                res_id = next_res_id
                next_res_id += 1
                
                pos = producer_pos
                producer_pos += total_len
                
                reservations[res_id] = {
                    "res_id": res_id,
                    "producer_id": pid,
                    "pos": pos,
                    "len": payload_len,
                    "total_len": total_len,
                    "state": "BUSY",
                    "data": data_str
                }
                slots[pos] = res_id
                
                stats["records_reserved"] += 1
                stats["bytes_reserved"] += total_len
                
                op_log.append({
                    "op": "RESERVE",
                    "res_id": res_id,
                    "producer_id": pid,
                    "status": "RESERVED_BUSY",
                    "pos": pos,
                    "total_len": total_len,
                    "producer_pos": producer_pos
                })
                
        elif op_type == "COMMIT":
            res_id = op.get("res_id")
            flags = op.get("flags", 0)
            
            if res_id in reservations:
                res = reservations[res_id]
                res["state"] = "COMMITTED"
                stats["records_committed"] += 1
                
                wakeup = (flags == 0)
                if wakeup:
                    stats["wakeups_triggered"] += 1
                    
                op_log.append({
                    "op": "COMMIT",
                    "res_id": res_id,
                    "status": "COMMITTED",
                    "wakeup": wakeup
                })
            else:
                op_log.append({
                    "op": "COMMIT",
                    "res_id": res_id,
                    "status": "RESERVATION_NOT_FOUND"
                })
                
        elif op_type == "DISCARD":
            res_id = op.get("res_id")
            if res_id in reservations:
                res = reservations[res_id]
                res["state"] = "DISCARDED"
                stats["records_discarded"] += 1
                op_log.append({
                    "op": "DISCARD",
                    "res_id": res_id,
                    "status": "DISCARDED"
                })
            else:
                op_log.append({
                    "op": "DISCARD",
                    "res_id": res_id,
                    "status": "RESERVATION_NOT_FOUND"
                })
                
        elif op_type == "CONSUME":
            max_to_consume = op.get("max_records", 100)
            consumed_list = []
            discarded_skipped = 0
            blocked_by_busy = False
            
            while len(consumed_list) < max_to_consume and consumer_pos < producer_pos:
                if consumer_pos not in slots:
                    break
                    
                res_id = slots[consumer_pos]
                res = reservations[res_id]
                
                if res["state"] == "BUSY":
                    blocked_by_busy = True
                    break
                elif res["state"] == "DISCARDED":
                    consumer_pos += res["total_len"]
                    discarded_skipped += 1
                elif res["state"] == "COMMITTED":
                    consumed_list.append({
                        "res_id": res["res_id"],
                        "producer_id": res["producer_id"],
                        "data": res["data"],
                        "len": res["len"]
                    })
                    consumer_pos += res["total_len"]
                    stats["records_consumed"] += 1
                    stats["bytes_consumed"] += res["total_len"]
                    
            op_log.append({
                "op": "CONSUME",
                "consumed_count": len(consumed_list),
                "consumed_records": consumed_list,
                "discarded_skipped": discarded_skipped,
                "blocked_by_busy": blocked_by_busy,
                "consumer_pos": consumer_pos
            })

    unconsumed_bytes = producer_pos - consumer_pos
    utilization_ratio = round(unconsumed_bytes / max(1, ringbuf_size), 4)
    
    result = {
        "ringbuf_size": ringbuf_size,
        "producer_pos": producer_pos,
        "consumer_pos": consumer_pos,
        "unconsumed_bytes": unconsumed_bytes,
        "utilization_ratio": utilization_ratio,
        "stats": stats,
        "op_log": op_log
    }
    
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    solve()
