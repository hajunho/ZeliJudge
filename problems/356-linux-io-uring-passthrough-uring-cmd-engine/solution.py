import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    config = input_data.get("config", {})
    sqpoll_enabled = config.get("sqpoll_enabled", False)
    iopoll_enabled = config.get("iopoll_enabled", False)
    cqe32_enabled = config.get("cqe32_enabled", False)
    queue_depth = config.get("queue_depth", 64)
    
    namespaces = {ns["nsid"]: ns for ns in input_data.get("namespaces", [])}
    sqes = input_data.get("sqes", [])
    
    cqes = []
    active_tags = 0
    max_active_tags = 0
    total_bytes = 0
    total_latency_us = 0.0
    bypassed_count = 0
    error_count = 0
    
    for sqe in sqes:
        sqe_id = sqe.get("sqe_id")
        user_data = sqe.get("user_data", sqe_id)
        opcode = sqe.get("opcode")
        cmd_op = sqe.get("cmd_op")
        nsid = sqe.get("nsid")
        nvme_opcode = sqe.get("nvme_opcode", "READ")
        slba = sqe.get("slba", 0)
        nlb = sqe.get("nlb", 1)
        buffer_len = sqe.get("buffer_len", 4096)
        
        # 1. Opcode validation
        if opcode != "IORING_OP_URING_CMD":
            cqe = {
                "user_data": user_data,
                "res": -22, # -EINVAL
                "status": "ERR_INVALID_OPCODE"
            }
            if cqe32_enabled:
                cqe["extra1"] = 0
                cqe["extra2"] = 0
            cqes.append(cqe)
            error_count += 1
            continue
            
        # 2. Namespace validation
        if nsid not in namespaces:
            cqe = {
                "user_data": user_data,
                "res": -19, # -ENODEV
                "status": "ERR_INVALID_NSID"
            }
            if cqe32_enabled:
                cqe["extra1"] = 0
                cqe["extra2"] = 0
            cqes.append(cqe)
            error_count += 1
            continue
            
        ns = namespaces[nsid]
        lba_bytes = ns.get("lba_bytes", 4096)
        size_lba = ns.get("size_lba", 1048576)
        is_readonly = ns.get("readonly", False)
        
        # 3. Readonly check
        if is_readonly and nvme_opcode in ("WRITE", "DSM_TRIM"):
            cqe = {
                "user_data": user_data,
                "res": -30, # -EROFS
                "status": "ERR_READONLY_NAMESPACE"
            }
            if cqe32_enabled:
                cqe["extra1"] = 640 # 0x280 NVMe status: Write to read only range
                cqe["extra2"] = 0
            cqes.append(cqe)
            error_count += 1
            continue
            
        # 4. LBA Range check
        if slba < 0 or (slba + nlb) > size_lba:
            cqe = {
                "user_data": user_data,
                "res": -28, # -ENOSPC / LBA Out of Range
                "status": "ERR_LBA_OUT_OF_BOUNDS"
            }
            if cqe32_enabled:
                cqe["extra1"] = 128 # 0x80 NVMe LBA Out of range
                cqe["extra2"] = 0
            cqes.append(cqe)
            error_count += 1
            continue
            
        # 5. Buffer length check (for read/write)
        expected_bytes = nlb * lba_bytes
        if nvme_opcode in ("READ", "WRITE") and buffer_len < expected_bytes:
            cqe = {
                "user_data": user_data,
                "res": -14, # -EFAULT / Buffer too small
                "status": "ERR_BUFFER_OVERFLOW"
            }
            if cqe32_enabled:
                cqe["extra1"] = 0
                cqe["extra2"] = 0
            cqes.append(cqe)
            error_count += 1
            continue
            
        # 6. Queue depth / tag check
        if active_tags >= queue_depth:
            cqe = {
                "user_data": user_data,
                "res": -11, # -EAGAIN
                "status": "ERR_QUEUE_FULL"
            }
            if cqe32_enabled:
                cqe["extra1"] = 0
                cqe["extra2"] = 0
            cqes.append(cqe)
            error_count += 1
            continue
            
        # Success path
        active_tags += 1
        if active_tags > max_active_tags:
            max_active_tags = active_tags
            
        base_lat = 1.5 + (expected_bytes / 4096.0) * 0.1 if nvme_opcode in ("READ", "WRITE") else 1.2
        if sqpoll_enabled:
            base_lat -= 0.5
        if iopoll_enabled:
            base_lat -= 0.4
            
        base_lat = max(0.2, round(base_lat, 2))
        total_latency_us += base_lat
        bypassed_count += 1
        
        if nvme_opcode in ("READ", "WRITE"):
            total_bytes += expected_bytes
            res_val = expected_bytes
        else:
            res_val = 0
            
        cqe = {
            "user_data": user_data,
            "res": res_val,
            "status": "SUCCESS_PASSTHROUGH",
            "latency_us": base_lat
        }
        if cqe32_enabled:
            cqe["extra1"] = (slba & 0xFFFFFFFF)
            cqe["extra2"] = 0
            
        cqes.append(cqe)
        active_tags -= 1
        
    avg_latency = round(total_latency_us / bypassed_count, 2) if bypassed_count > 0 else 0.0
    queue_util = round((max_active_tags / queue_depth) * 100.0, 1) if queue_depth > 0 else 0.0
    
    if error_count == 0 and bypassed_count > 0:
        verdict = "ZERO_COPY_PASSTHROUGH_OPTIMAL"
    elif bypassed_count > 0 and error_count > 0:
        verdict = "PARTIAL_PASSTHROUGH_WITH_EXCEPTIONS"
    else:
        verdict = "PASSTHROUGH_PIPELINE_FAILED"
        
    output = {
        "engine": "io_uring_passthrough_nvme",
        "metrics": {
            "total_sqes": len(sqes),
            "completed_cqes": len(cqes),
            "successful_bypasses": bypassed_count,
            "error_count": error_count,
            "total_bytes_transferred": total_bytes,
            "avg_latency_us": avg_latency,
            "peak_queue_utilization_pct": queue_util,
            "sqpoll_active": sqpoll_enabled,
            "iopoll_active": iopoll_enabled,
            "cqe32_mode": cqe32_enabled
        },
        "verdict": verdict,
        "cqes": cqes
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
