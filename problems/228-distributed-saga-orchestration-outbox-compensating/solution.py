import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    saga_pattern = config.get("saga_pattern", "ORCHESTRATION")
    outbox_pattern_enabled = bool(config.get("outbox_pattern_enabled", True))
    max_compensation_retries = int(config.get("max_compensation_retries", 3))

    transaction = data.get("transaction", {})
    steps = transaction.get("steps", [])
    injected_failures = transaction.get("injected_failures", {})
    network_failure_step = transaction.get("network_failure_step", None)

    executed_steps = []
    compensated_steps = []
    dual_write_loss = False
    uncompensated_services = []

    if saga_pattern == "CHOREOGRAPHY":
        visited_services = set()
        has_circular = False
        for step in steps:
            svc = step["service"]
            if svc in visited_services:
                has_circular = True
                break
            visited_services.add(svc)

        if has_circular or len(steps) >= 5:
            result = {
                "status": "FAILED",
                "verdict": "CHOREOGRAPHY_CIRCULAR_EVENT_STORM",
                "metrics": {
                    "saga_pattern": saga_pattern,
                    "completed_steps": executed_steps,
                    "compensated_steps": compensated_steps,
                    "uncompensated_services": [],
                    "dual_write_loss": False,
                    "final_state": "CIRCULAR_STORM"
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return

    failure_occurred_at = None
    for step in steps:
        svc = step["service"]

        if not outbox_pattern_enabled and network_failure_step == svc:
            dual_write_loss = True
            executed_steps.append(svc)
            result = {
                "status": "FAILED",
                "verdict": "DUAL_WRITE_MESSAGE_LOSS_INCONSISTENCY",
                "metrics": {
                    "saga_pattern": saga_pattern,
                    "completed_steps": executed_steps,
                    "compensated_steps": [],
                    "uncompensated_services": [svc],
                    "dual_write_loss": True,
                    "final_state": "GHOST_COMMITTED_STATE"
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return

        if svc in injected_failures:
            failure_occurred_at = svc
            break
        else:
            executed_steps.append(svc)

    if failure_occurred_at:
        compensation_failed = False
        for svc in reversed(executed_steps):
            retries = injected_failures.get(f"{svc}_COMPENSATION_RETRIES", 0)
            if retries > max_compensation_retries:
                compensation_failed = True
                uncompensated_services.append(svc)
            else:
                compensated_steps.append(svc)

        if compensation_failed:
            status = "FAILED"
            verdict = "COMPENSATING_RETRY_EXHAUSTION_INCONSISTENCY"
            final_state = "PARTIALLY_COMPENSATED_DRIFT"
        else:
            status = "SUCCESS"
            verdict = "SAGA_COMPENSATED_ROLLBACK_SUCCESS"
            final_state = "SAFELY_COMPENSATED"
    else:
        status = "SUCCESS"
        if saga_pattern == "CHOREOGRAPHY":
            verdict = "CHOREOGRAPHY_SIMPLE_SAGA_SUCCESS"
        else:
            verdict = "OPTIMAL_ORCHESTRATED_SAGA_EVENTUAL_CONSISTENCY"
        final_state = "COMMITTED"

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "saga_pattern": saga_pattern,
            "completed_steps": executed_steps,
            "compensated_steps": compensated_steps,
            "uncompensated_services": uncompensated_services,
            "dual_write_loss": dual_write_loss,
            "final_state": final_state
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
