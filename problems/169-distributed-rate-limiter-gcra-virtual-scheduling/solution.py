import sys
import json

def simulate_gcra(config):
    rate = config.get("rate", 10)
    period_ms = config.get("period_ms", 1000)
    burst = config.get("burst", 5)
    algorithm = config.get("algorithm", "GCRA")
    requests = config.get("requests", [])

    T = period_ms / rate
    tau = burst * T

    metrics = {
        "algorithm": algorithm,
        "total_requests": len(requests),
        "allowed_requests": 0,
        "rejected_requests": 0,
        "total_cost_consumed": 0,
        "max_consecutive_burst": 0,
        "average_retry_after_ms": 0.0,
        "final_tats": {},
        "verdict": ""
    }

    tat_map = {}
    response_log = []
    retry_after_list = []
    
    current_streak = 0
    max_streak = 0
    last_req_t = None
    multi_cost_rejected = False

    for req in requests:
        req_id = req.get("id", "req")
        key = req.get("key", "default_key")
        t = req["timestamp_ms"]
        cost = req.get("cost", 1)

        tat = tat_map.get(key, 0)
        tat_prime = max(t, tat)
        
        # Check tolerance for cost C
        is_allowed = (tat_prime + (cost - 1) * T - t) <= tau

        if is_allowed:
            new_tat = tat_prime + cost * T
            tat_map[key] = new_tat
            metrics["allowed_requests"] += 1
            metrics["total_cost_consumed"] += cost

            remaining = max(0, int((tau - (new_tat - t - T)) // T))
            reset_ms = max(0, int(new_tat - t))
            retry_after_ms = 0

            if last_req_t == t:
                current_streak += 1
            else:
                current_streak = 1
                last_req_t = t
            max_streak = max(max_streak, current_streak)
        else:
            metrics["rejected_requests"] += 1
            current_streak = 0
            if cost > 1:
                multi_cost_rejected = True

            remaining = max(0, int((tau - (tat - t)) // T)) if (tat - t) <= tau else 0
            reset_ms = max(0, int(tat - t))
            retry_after_ms = max(0, int(tat_prime + (cost - 1) * T - t - tau))
            retry_after_list.append(retry_after_ms)

        response_log.append({
            "id": req_id,
            "key": key,
            "t": t,
            "cost": cost,
            "allowed": is_allowed,
            "remaining": remaining,
            "reset_ms": reset_ms,
            "retry_after_ms": retry_after_ms
        })

    metrics["max_consecutive_burst"] = max_streak
    metrics["average_retry_after_ms"] = round(sum(retry_after_list) / len(retry_after_list), 2) if retry_after_list else 0.0
    metrics["final_tats"] = {k: int(v) for k, v in tat_map.items()}

    # Verdict
    unique_keys = set(r.get("key", "default_key") for r in requests)
    if len(unique_keys) > 1:
        metrics["verdict"] = "MULTI_TENANT_ISOLATED_COMPLIANCE"
    elif multi_cost_rejected:
        metrics["verdict"] = "MULTI_COST_QUOTA_EXCEEDED"
    elif metrics["rejected_requests"] > 0:
        metrics["verdict"] = "BURST_TOLERANCE_EXHAUSTED"
    else:
        metrics["verdict"] = "CONFORMANT_STEADY_STREAM"

    return {
        "metrics": metrics,
        "sample_responses": response_log[:20]
    }


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    config = json.loads(raw)
    result = simulate_gcra(config)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
