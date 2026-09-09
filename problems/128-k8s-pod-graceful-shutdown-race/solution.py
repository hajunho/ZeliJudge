import sys
import json
import copy

def simulate_k8s_graceful_shutdown(data):
    data = copy.deepcopy(data)
    scenarios_input = data.get("scenarios", [])
    scenario_results = []
    
    total_502 = 0
    total_504 = 0
    zero_downtime_count = 0
    failed_scenarios_count = 0
    
    for sc in scenarios_input:
        sc_id = sc.get("scenario_id", "")
        pod_cfg = sc.get("pod_config", {})
        net_cfg = sc.get("network_config", {})
        events = sc.get("events", [])
        
        pod_name = pod_cfg.get("pod_name", "pod")
        pre_stop_delay = float(pod_cfg.get("pre_stop_delay_sec", 0.0))
        grace_period = float(pod_cfg.get("termination_grace_period_sec", 30.0))
        drain_timeout = float(pod_cfg.get("app_drain_timeout_sec", 15.0))
        shutdown_behavior = pod_cfg.get("app_shutdown_behavior", "graceful")
        
        dereg_delay = float(net_cfg.get("endpoint_deregistration_delay_sec", 3.0))
        
        term_event = next((e for e in events if e.get("type") == "POD_TERMINATION_REQUESTED"), None)
        t_term = float(term_event.get("time", 0.0)) if term_event else 0.0
        
        t_deregister = t_term + dereg_delay
        t_prestop_end = t_term + pre_stop_delay
        t_sigterm = t_prestop_end
        t_sigkill_limit = t_term + grace_period
        
        incoming_reqs = [e for e in events if e.get("type") == "INCOMING_REQUEST"]
        incoming_reqs.sort(key=lambda r: float(r.get("time", 0.0)))
        
        req_results = []
        in_flight_accepted = []
        
        for req in incoming_reqs:
            req_id = req.get("request_id")
            t_req = float(req.get("time", 0.0))
            duration = float(req.get("duration_sec", 1.0))
            t_finish = t_req + duration
            
            if t_req >= t_deregister:
                req_results.append({
                    "request_id": req_id,
                    "arrival_time": round(t_req, 2),
                    "status": "ROUTED_TO_OTHER_REPLICA",
                    "http_status": 200,
                    "error": None
                })
            else:
                if t_req >= t_sigterm:
                    req_results.append({
                        "request_id": req_id,
                        "arrival_time": round(t_req, 2),
                        "status": "CONNECTION_REFUSED",
                        "http_status": 502,
                        "error": "ERR_CONNECTION_REFUSED_PORT_CLOSED"
                    })
                else:
                    res = {
                        "request_id": req_id,
                        "arrival_time": round(t_req, 2),
                        "status": None,
                        "http_status": None,
                        "error": None
                    }
                    req_results.append(res)
                    in_flight_accepted.append({
                        "result_ref": res,
                        "start": t_req,
                        "finish": t_finish,
                        "duration": duration
                    })
                    
        sigkill_time = None
        
        if shutdown_behavior == "immediate":
            container_exit_time = t_sigterm
            for item in in_flight_accepted:
                if item["finish"] <= t_sigterm:
                    item["result_ref"]["status"] = "COMPLETED"
                    item["result_ref"]["http_status"] = 200
                else:
                    item["result_ref"]["status"] = "IN_FLIGHT_ABORTED_SIGTERM"
                    item["result_ref"]["http_status"] = 502
                    item["result_ref"]["error"] = "ERR_IN_FLIGHT_ABORTED_ON_SIGTERM"
        else:
            t_drain_limit = t_sigterm + drain_timeout
            effective_drain_cutoff = min(t_drain_limit, t_sigkill_limit)
            
            max_completed_finish = t_sigterm
            any_timeout_drain = False
            any_sigkill_drop = False
            
            for item in in_flight_accepted:
                t_fin = item["finish"]
                if t_fin <= effective_drain_cutoff:
                    item["result_ref"]["status"] = "COMPLETED"
                    item["result_ref"]["http_status"] = 200
                    if t_fin > max_completed_finish:
                        max_completed_finish = t_fin
                else:
                    if effective_drain_cutoff == t_sigkill_limit:
                        item["result_ref"]["status"] = "DROPPED_BY_SIGKILL"
                        item["result_ref"]["http_status"] = 504
                        item["result_ref"]["error"] = "ERR_GATEWAY_TIMEOUT_SIGKILL"
                        any_sigkill_drop = True
                    else:
                        item["result_ref"]["status"] = "DRAIN_TIMEOUT_ABORTED"
                        item["result_ref"]["http_status"] = 504
                        item["result_ref"]["error"] = "ERR_APP_DRAIN_TIMEOUT_EXCEEDED"
                        any_timeout_drain = True
                        
            if any_sigkill_drop:
                sigkill_time = round(t_sigkill_limit, 2)
                container_exit_time = t_sigkill_limit
            elif any_timeout_drain:
                container_exit_time = t_drain_limit
            else:
                container_exit_time = max(t_sigterm, max_completed_finish)
                
        c_502 = sum(1 for r in req_results if r["http_status"] == 502)
        c_504 = sum(1 for r in req_results if r["http_status"] == 504)
        c_success = sum(1 for r in req_results if r["http_status"] == 200)
        c_failed = c_502 + c_504
        has_errors = (c_failed > 0)
        
        if has_errors:
            failed_scenarios_count += 1
        else:
            zero_downtime_count += 1
            
        total_502 += c_502
        total_504 += c_504
        
        scenario_results.append({
            "scenario_id": sc_id,
            "pod_name": pod_name,
            "has_downtime_or_errors": has_errors,
            "container_exit_time": round(container_exit_time, 2),
            "sigterm_sent_time": round(t_sigterm, 2),
            "sigkill_sent_time": sigkill_time,
            "endpoint_deregistered_time": round(t_deregister, 2),
            "stats": {
                "total_requests": len(req_results),
                "successful_requests": c_success,
                "failed_requests": c_failed,
                "bad_gateway_502_count": c_502,
                "gateway_timeout_504_count": c_504
            },
            "request_results": req_results
        })
        
    summary = {
        "total_scenarios": len(scenario_results),
        "zero_downtime_scenarios": zero_downtime_count,
        "failed_scenarios": failed_scenarios_count,
        "total_502_errors": total_502,
        "total_504_errors": total_504
    }
    
    return {
        "summary": summary,
        "scenarios": scenario_results
    }

def main():
    input_text = sys.stdin.read().strip()
    if not input_text:
        return
    data = json.loads(input_text)
    out = simulate_k8s_graceful_shutdown(data)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
