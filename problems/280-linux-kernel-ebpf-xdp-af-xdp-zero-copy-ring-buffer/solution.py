import sys
import json

def solve():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    line = sys.stdin.read().strip()
    if not line:
        return
    req = json.loads(line)
    
    umem_cfg = req.get("umem", {})
    chunk_size = umem_cfg.get("chunk_size", 2048)
    ring_size = umem_cfg.get("ring_size", 4)
    
    prog_cfg = req.get("xdp_program", {})
    default_act = prog_cfg.get("default_action", "XDP_PASS")
    bpf_rules = prog_cfg.get("bpf_rules", [])
    
    fill_ring = []
    rx_ring = []
    tx_ring = []
    completion_ring = []
    
    stats = {
        "rx_total_packets": 0,
        "xdp_drop": 0,
        "xdp_pass": 0,
        "xdp_tx": 0,
        "xdp_redirect": 0,
        "fill_ring_empty_drops": 0,
        "rx_ring_full_drops": 0,
        "tx_submitted": 0,
        "tx_completed": 0
    }
    
    logs = []
    
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "USER_FILL_RING_ENQUEUE":
            addrs = op_item["chunk_addrs"]
            accepted = []
            rejected = []
            for a in addrs:
                if len(fill_ring) < ring_size:
                    fill_ring.append(a)
                    accepted.append(a)
                else:
                    rejected.append(a)
            logs.append({
                "step": step,
                "op": op,
                "enqueued_count": len(accepted),
                "enqueued_addrs": accepted,
                "rejected_full_addrs": rejected
            })
            
        elif op == "NIC_RECEIVE_PACKET":
            pkt = op_item["packet"]
            stats["rx_total_packets"] += 1
            
            action = default_act
            for r in bpf_rules:
                m = r.get("match", {})
                matched = True
                for k, v in m.items():
                    if pkt.get(k) != v:
                        matched = False
                        break
                if matched:
                    action = r["action"]
                    break
                    
            if action == "XDP_DROP":
                stats["xdp_drop"] += 1
                logs.append({
                    "step": step,
                    "op": op,
                    "packet_id": pkt.get("id"),
                    "action": "XDP_DROP",
                    "status": "DROPPED"
                })
            elif action == "XDP_PASS":
                stats["xdp_pass"] += 1
                logs.append({
                    "step": step,
                    "op": op,
                    "packet_id": pkt.get("id"),
                    "action": "XDP_PASS",
                    "status": "PASSED_TO_KERNEL_SKB"
                })
            elif action == "XDP_TX":
                stats["xdp_tx"] += 1
                logs.append({
                    "step": step,
                    "op": op,
                    "packet_id": pkt.get("id"),
                    "action": "XDP_TX",
                    "status": "HAIRPIN_BOUNCE_TX"
                })
            elif action == "XDP_REDIRECT":
                if not fill_ring:
                    stats["fill_ring_empty_drops"] += 1
                    logs.append({
                        "step": step,
                        "op": op,
                        "packet_id": pkt.get("id"),
                        "action": "XDP_REDIRECT",
                        "status": "DROPPED_FILL_RING_EMPTY"
                    })
                elif len(rx_ring) >= ring_size:
                    stats["rx_ring_full_drops"] += 1
                    logs.append({
                        "step": step,
                        "op": op,
                        "packet_id": pkt.get("id"),
                        "action": "XDP_REDIRECT",
                        "status": "DROPPED_RX_RING_FULL"
                    })
                else:
                    addr = fill_ring.pop(0)
                    desc = {
                        "chunk_addr": addr,
                        "packet_id": pkt.get("id"),
                        "len": pkt.get("len", 64)
                    }
                    rx_ring.append(desc)
                    stats["xdp_redirect"] += 1
                    logs.append({
                        "step": step,
                        "op": op,
                        "packet_id": pkt.get("id"),
                        "action": "XDP_REDIRECT",
                        "status": "ZERO_COPY_RX_DELIVERED",
                        "assigned_chunk_addr": addr
                    })
                    
        elif op == "USER_RX_RING_DEQUEUE":
            batch = op_item.get("batch_size", 4)
            dequeued = []
            while rx_ring and len(dequeued) < batch:
                dequeued.append(rx_ring.pop(0))
            logs.append({
                "step": step,
                "op": op,
                "dequeued_count": len(dequeued),
                "packets": dequeued
            })
            
        elif op == "USER_TX_RING_ENQUEUE":
            tx_pkts = op_item["tx_packets"]
            accepted = []
            rejected = []
            for p in tx_pkts:
                if len(tx_ring) < ring_size:
                    tx_ring.append(p)
                    accepted.append(p)
                    stats["tx_submitted"] += 1
                else:
                    rejected.append(p)
            logs.append({
                "step": step,
                "op": op,
                "submitted_count": len(accepted),
                "submitted": accepted,
                "rejected_full": rejected
            })
            
        elif op == "KERNEL_TX_COMPLETION":
            completed = []
            while tx_ring and len(completion_ring) < ring_size:
                p = tx_ring.pop(0)
                completion_ring.append(p["chunk_addr"])
                stats["tx_completed"] += 1
                completed.append(p["chunk_addr"])
            logs.append({
                "step": step,
                "op": op,
                "completed_count": len(completed),
                "completed_chunks": completed
            })
            
        elif op == "USER_COMPLETION_RING_DEQUEUE":
            batch = op_item.get("batch_size", 4)
            reclaimed = []
            while completion_ring and len(reclaimed) < batch:
                reclaimed.append(completion_ring.pop(0))
            logs.append({
                "step": step,
                "op": op,
                "reclaimed_count": len(reclaimed),
                "reclaimed_chunks": reclaimed
            })

    res = {
        "operations_log": logs,
        "final_ring_states": {
            "fill_ring": list(fill_ring),
            "rx_ring": list(rx_ring),
            "tx_ring": list(tx_ring),
            "completion_ring": list(completion_ring)
        },
        "statistics": stats
    }
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
