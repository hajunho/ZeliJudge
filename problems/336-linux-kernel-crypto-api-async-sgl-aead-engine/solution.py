import sys
import json
import hashlib
import hmac

def run_crypto_api_engine(data):
    config = data.get("config", {})
    registered_algs = data.get("registered_algorithms", [])
    hardware_accelerator = data.get("hardware_accelerator", {})
    requests = data.get("crypto_requests", [])

    hw_enabled = bool(hardware_accelerator.get("enabled", False))
    queue_capacity = int(hardware_accelerator.get("queue_capacity", 4))
    backlog_capacity = int(hardware_accelerator.get("backlog_capacity", 4))

    drivers_by_alg = {}
    for drv in registered_algs:
        name = drv["alg_name"]
        if name not in drivers_by_alg:
            drivers_by_alg[name] = []
        drivers_by_alg[name].append(drv)
    for name in drivers_by_alg:
        drivers_by_alg[name].sort(key=lambda x: -x.get("cra_priority", 0))

    active_queue = []
    backlog_queue = []

    stats = {
        "sync_completed": 0,
        "async_queued": 0,
        "backlog_queued": 0,
        "queue_overflows": 0,
        "auth_failures": 0,
        "total_bytes_processed": 0
    }

    def gather_sgl(sgl_entries):
        chunks = []
        for sg in sgl_entries:
            data_str = sg.get("data", "")
            offset = int(sg.get("offset", 0))
            length = int(sg.get("length", len(data_str) - offset))
            chunks.append(data_str[offset:offset+length])
        return "".join(chunks)

    def scatter_sgl(payload_str, dst_template):
        res = []
        curr_idx = 0
        p_len = len(payload_str)
        for sg in dst_template:
            sg_cap = int(sg.get("capacity", 0))
            take = min(sg_cap, p_len - curr_idx)
            chunk = payload_str[curr_idx:curr_idx + take] if take > 0 else ""
            curr_idx += take
            res.append({
                "sg_id": sg.get("sg_id", ""),
                "capacity": sg_cap,
                "length": len(chunk),
                "data": chunk
            })
        return res

    request_results = []

    for req in requests:
        req_id = req["req_id"]
        op_type = req["op_type"]
        
        if op_type == "poll_completions":
            count_to_drain = int(req.get("max_drain", len(active_queue)))
            drained = []
            while active_queue and len(drained) < count_to_drain:
                completed_id = active_queue.pop(0)
                drained.append(completed_id)
                if backlog_queue:
                    promoted_id = backlog_queue.pop(0)
                    active_queue.append(promoted_id)
            request_results.append({
                "req_id": req_id,
                "op": "poll_completions",
                "status": "SUCCESS",
                "drained_count": len(drained),
                "completed_requests": drained,
                "remaining_active": len(active_queue),
                "remaining_backlog": len(backlog_queue)
            })
            continue

        alg_name = req["alg_name"]
        assoc_len = int(req.get("assoclen", 0))
        may_backlog = bool(req.get("may_backlog", False))

        if alg_name not in drivers_by_alg or not drivers_by_alg[alg_name]:
            request_results.append({
                "req_id": req_id,
                "op": op_type,
                "status": "ENOENT",
                "error": f"Algorithm '{alg_name}' not registered"
            })
            continue

        selected_driver = drivers_by_alg[alg_name][0]
        driver_type = selected_driver.get("driver_type", "simd")
        auth_tag_size = int(selected_driver.get("authsize", 16))

        src_raw = gather_sgl(req.get("src_sgl", []))
        iv_hex = req.get("iv_hex", "00" * 12)
        key_hex = req.get("key_hex", "00" * 32)

        aad = src_raw[:assoc_len]
        payload = src_raw[assoc_len:]

        is_async = (driver_type == "hardware" and hw_enabled)
        
        if is_async:
            if len(active_queue) < queue_capacity:
                active_queue.append(req_id)
                stats["async_queued"] += 1
                queue_status = "EINPROGRESS"
            elif may_backlog and len(backlog_queue) < backlog_capacity:
                backlog_queue.append(req_id)
                stats["backlog_queued"] += 1
                queue_status = "EBUSY"
            else:
                stats["queue_overflows"] += 1
                request_results.append({
                    "req_id": req_id,
                    "op": op_type,
                    "status": "ENOSPC",
                    "driver_name": selected_driver["driver_name"],
                    "error": "Hardware accelerator queue and backlog exhausted"
                })
                continue

        hash_seed = hashlib.sha256((key_hex + iv_hex).encode('utf-8')).hexdigest()
        
        if op_type == "encrypt":
            plain_bytes = payload.encode('utf-8')
            stream = (hash_seed * ((len(plain_bytes) // len(hash_seed)) + 2))[:len(plain_bytes)]
            cipher_bytes = bytes([b ^ ord(stream[i]) for i, b in enumerate(plain_bytes)])
            cipher_hex = cipher_bytes.hex()
            
            mac = hmac.new(key_hex.encode('utf-8'), (aad + cipher_hex).encode('utf-8'), hashlib.sha256).hexdigest()[:auth_tag_size * 2]
            
            combined_out = aad + cipher_hex + mac
            dst_scattered = scatter_sgl(combined_out, req.get("dst_template", []))
            
            stats["total_bytes_processed"] += len(plain_bytes)
            if not is_async:
                stats["sync_completed"] += 1

            request_results.append({
                "req_id": req_id,
                "op": "encrypt",
                "status": queue_status if is_async else "SUCCESS",
                "driver_name": selected_driver["driver_name"],
                "driver_type": driver_type,
                "cra_priority": selected_driver.get("cra_priority", 100),
                "is_async_queued": is_async,
                "aad_length": len(aad),
                "ciphertext_length": len(cipher_hex),
                "auth_tag": mac,
                "dst_sgl": dst_scattered
            })

        elif op_type == "decrypt":
            tag_len_hex = auth_tag_size * 2
            if len(payload) < tag_len_hex:
                stats["auth_failures"] += 1
                request_results.append({
                    "req_id": req_id,
                    "op": "decrypt",
                    "status": "EINVAL",
                    "driver_name": selected_driver["driver_name"],
                    "error": "Payload shorter than auth tag"
                })
                continue

            cipher_hex = payload[:-tag_len_hex]
            provided_tag = payload[-tag_len_hex:]

            expected_mac = hmac.new(key_hex.encode('utf-8'), (aad + cipher_hex).encode('utf-8'), hashlib.sha256).hexdigest()[:tag_len_hex]
            
            if not hmac.compare_digest(provided_tag.lower(), expected_mac.lower()):
                stats["auth_failures"] += 1
                request_results.append({
                    "req_id": req_id,
                    "op": "decrypt",
                    "status": "EBADMSG",
                    "driver_name": selected_driver["driver_name"],
                    "error": "Authentication tag verification failed (ICV mismatch)"
                })
                continue

            try:
                cipher_bytes = bytes.fromhex(cipher_hex)
                stream = (hash_seed * ((len(cipher_bytes) // len(hash_seed)) + 2))[:len(cipher_bytes)]
                plain_bytes = bytes([b ^ ord(stream[i]) for i, b in enumerate(cipher_bytes)])
                plain_text = plain_bytes.decode('utf-8', errors='replace')
            except Exception as ex:
                request_results.append({
                    "req_id": req_id,
                    "op": "decrypt",
                    "status": "EILSEQ",
                    "error": str(ex)
                })
                continue

            combined_out = aad + plain_text
            dst_scattered = scatter_sgl(combined_out, req.get("dst_template", []))
            
            stats["total_bytes_processed"] += len(cipher_bytes)
            if not is_async:
                stats["sync_completed"] += 1

            request_results.append({
                "req_id": req_id,
                "op": "decrypt",
                "status": queue_status if is_async else "SUCCESS",
                "driver_name": selected_driver["driver_name"],
                "driver_type": driver_type,
                "cra_priority": selected_driver.get("cra_priority", 100),
                "is_async_queued": is_async,
                "aad_length": len(aad),
                "plaintext_length": len(plain_text),
                "dst_sgl": dst_scattered
            })

    return {
        "request_results": request_results,
        "crypto_subsystem_metrics": stats,
        "hardware_engine_status": {
            "active_queue_depth": len(active_queue),
            "backlog_queue_depth": len(backlog_queue),
            "is_throttled": (len(active_queue) >= queue_capacity)
        }
    }

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    result = run_crypto_api_engine(data)
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
