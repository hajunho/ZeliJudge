import sys
import json
import heapq

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def solve(data):
    config = data.get("config", {})
    init_limit = float(config.get("initial_concurrency_limit", 10.0))
    min_limit = float(config.get("min_concurrency_limit", 2.0))
    max_limit = float(config.get("max_concurrency_limit", 100.0))
    headroom = float(config.get("headroom", 1.0))
    sample_window_size = int(config.get("sample_window_size", 5))
    min_grad = float(config.get("min_gradient", 0.5))
    max_grad = float(config.get("max_gradient", 1.5))
    initial_min_rtt = float(config.get("initial_min_rtt", 20.0))
    min_rtt_window_size = int(config.get("min_rtt_window_size", 3))

    requests = data.get("requests", [])
    
    current_limit = round(init_limit, 2)
    in_flight = 0

    events = []
    for idx, req in enumerate(requests):
        heapq.heappush(events, (req["arrival_time"], 1, idx, req))

    window_samples = []
    sample_rtt_history = [initial_min_rtt]
    limit_updates = []
    processed_requests = []
    
    admitted_count = 0
    rejected_count = 0

    def trigger_update(curr_time):
        nonlocal current_limit, window_samples, sample_rtt_history
        if not window_samples:
            return
        sample_rtt = sum(window_samples) / len(window_samples)
        
        sample_rtt_history.append(sample_rtt)
        if len(sample_rtt_history) > min_rtt_window_size:
            sample_rtt_history.pop(0)
            
        current_min_rtt = min(sample_rtt_history)
        
        raw_grad = current_min_rtt / sample_rtt if sample_rtt > 0 else 1.0
        grad = max(min_grad, min(max_grad, raw_grad))
        
        old_l = current_limit
        new_l = current_limit * grad + headroom
        new_l = max(min_limit, min(max_limit, new_l))
        new_l = round(new_l, 2)

        limit_updates.append({
            "timestamp": curr_time,
            "sample_rtt": round(sample_rtt, 2),
            "min_rtt": round(current_min_rtt, 2),
            "gradient": round(grad, 4),
            "old_limit": old_l,
            "new_limit": new_l
        })
        current_limit = new_l
        window_samples = []

    while events:
        curr_time, ev_type, p_id, payload = heapq.heappop(events)

        if ev_type == 0:
            in_flight -= 1
            rtt = payload["rtt"]
            window_samples.append(rtt)
            if len(window_samples) >= sample_window_size:
                trigger_update(curr_time)

        elif ev_type == 1:
            req = payload
            max_allowed = int(current_limit)
            if in_flight < max_allowed:
                in_flight += 1
                admitted_count += 1
                finish_time = curr_time + req["processing_time"]
                record = {
                    "id": req["id"],
                    "status": "ADMITTED",
                    "arrival_time": curr_time,
                    "finish_time": finish_time,
                    "rtt": req["processing_time"],
                    "limit_at_arrival": current_limit,
                    "in_flight_after_admission": in_flight
                }
                processed_requests.append(record)
                heapq.heappush(events, (finish_time, 0, p_id, {"id": req["id"], "rtt": req["processing_time"]}))
            else:
                rejected_count += 1
                record = {
                    "id": req["id"],
                    "status": "REJECTED",
                    "arrival_time": curr_time,
                    "reason": "CONCURRENCY_LIMIT_EXCEEDED",
                    "limit_at_arrival": current_limit,
                    "in_flight_at_arrival": in_flight
                }
                processed_requests.append(record)

    total_reqs = len(requests)
    rejection_rate = round(rejected_count / total_reqs, 4) if total_reqs > 0 else 0.0
    current_min_rtt = min(sample_rtt_history)

    return {
        "summary": {
            "total_requests": total_reqs,
            "admitted_requests": admitted_count,
            "rejected_requests": rejected_count,
            "rejection_rate": rejection_rate,
            "final_concurrency_limit": current_limit,
            "final_min_rtt": round(current_min_rtt, 2),
            "total_limit_updates": len(limit_updates)
        },
        "limit_updates": limit_updates,
        "processed_requests": processed_requests
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
