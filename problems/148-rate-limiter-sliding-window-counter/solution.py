import json
import sys

def solve(data):
    cfg = data.get("rate_limit_config", {})
    window_size = float(cfg.get("window_size_seconds", 60.0))
    limit = int(cfg.get("limit", 60))
    algorithm = cfg.get("algorithm", "FIXED_WINDOW").upper()
    
    requests = data.get("requests", [])
    
    results = []
    window_counts = {}
    
    allowed_timestamps = []
    
    for req in requests:
        req_id = req.get("req_id", "")
        ts = float(req.get("timestamp_seconds", 0.0))
        
        is_allowed = False
        reason = ""
        current_load = 0.0
        
        if algorithm == "FIXED_WINDOW":
            w_idx = int(ts // window_size)
            cnt = window_counts.get(w_idx, 0)
            if cnt < limit:
                is_allowed = True
                window_counts[w_idx] = cnt + 1
                current_load = float(cnt + 1)
                reason = "WITHIN_FIXED_WINDOW_LIMIT"
            else:
                is_allowed = False
                current_load = float(cnt)
                reason = "FIXED_WINDOW_LIMIT_EXCEEDED"
                
        elif algorithm == "SLIDING_WINDOW_COUNTER":
            curr_w_idx = int(ts // window_size)
            offset = ts - (curr_w_idx * window_size)
            weight_prev = max(0.0, 1.0 - (offset / window_size))
            
            cnt_prev = window_counts.get(curr_w_idx - 1, 0)
            cnt_curr = window_counts.get(curr_w_idx, 0)
            
            estimated = (cnt_prev * weight_prev) + cnt_curr
            current_load = round(estimated, 2)
            
            if estimated < limit:
                is_allowed = True
                window_counts[curr_w_idx] = cnt_curr + 1
                reason = "WITHIN_SLIDING_COUNTER_LIMIT"
            else:
                is_allowed = False
                reason = "SLIDING_COUNTER_LIMIT_EXCEEDED"
                
        else: # Default fallback
            is_allowed = True
            reason = "UNKNOWN_ALGORITHM"
            
        if is_allowed:
            allowed_timestamps.append(ts)
            
        results.append({
            "req_id": req_id,
            "timestamp_seconds": ts,
            "allowed": is_allowed,
            "estimated_load": current_load,
            "reason": reason
        })
        
    # Analyze rolling window max requests
    max_rolling = 0
    if allowed_timestamps:
        allowed_timestamps.sort()
        left = 0
        for right in range(len(allowed_timestamps)):
            while left <= right and (allowed_timestamps[right] - allowed_timestamps[left]) >= window_size:
                left += 1
            cur_count = right - left + 1
            if cur_count > max_rolling:
                max_rolling = cur_count
                
    burst_detected = (max_rolling > limit)
    burst_ratio = round(max_rolling / limit, 2) if limit > 0 else 0.0
    
    total_reqs = len(requests)
    allowed_count = sum(1 for r in results if r["allowed"])
    blocked_count = total_reqs - allowed_count
    
    if algorithm == "FIXED_WINDOW" and burst_detected:
        verdict = "FIXED_WINDOW_BOUNDARY_BURST_DISASTER"
    elif algorithm == "SLIDING_WINDOW_COUNTER" and burst_ratio <= 1.05:
        verdict = "SLIDING_WINDOW_COUNTER_OPTIMAL"
    elif not burst_detected:
        verdict = "BALANCED_EXECUTION"
    else:
        verdict = "BURST_LIMIT_EXCEEDED"
        
    summary = {
        "algorithm": algorithm,
        "window_size_seconds": window_size,
        "limit": limit,
        "total_requests": total_reqs,
        "allowed_requests": allowed_count,
        "blocked_requests": blocked_count,
        "max_requests_in_any_rolling_window": max_rolling,
        "burst_detected": burst_detected,
        "burst_ratio": burst_ratio,
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary,
        "results": results
    }

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve(inp)
        print(json.dumps(res, indent=2))
