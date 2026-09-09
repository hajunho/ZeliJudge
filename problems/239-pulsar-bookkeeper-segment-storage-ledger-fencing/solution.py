import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    system = config.get("messaging_system", "PULSAR_BOOKKEEPER")
    fencing_enabled = bool(config.get("ledger_fencing_enabled", True))
    journal_separated = bool(config.get("journal_storage_separated", True))
    rebalance_req = bool(config.get("broker_rebalance_requested", True))
    partition_size_gb = float(config.get("partition_size_gb", 500.0))
    net_bw_gbps = float(config.get("network_bandwidth_gbps", 10.0))

    workload = data.get("workload", {})
    failed_bookie = int(workload.get("failed_bookie_id", -1))
    zombie_resurrection = bool(workload.get("zombie_broker_resurrection", False))

    if system == "KAFKA_MONOLITHIC":
        if rebalance_req:
            rebalance_sec = round((partition_size_gb * 8.0) / net_bw_gbps, 1)
            result = {
                "status": "FAILED",
                "verdict": "KAFKA_MONOLITHIC_PARTITION_REBALANCE_STALL",
                "metrics": {
                    "data_copied_gb": partition_size_gb,
                    "rebalance_duration_sec": rebalance_sec,
                    "p99_write_latency_ms": 285.0,
                    "ledger_fenced_success": False,
                    "split_brain_corrupted": False,
                    "ensemble_switches": 0
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return
        else:
            result = {
                "status": "SUCCESS",
                "verdict": "KAFKA_MONOLITHIC_PARTITION_STEADY_STATE",
                "metrics": {
                    "data_copied_gb": 0.0,
                    "rebalance_duration_sec": 0.0,
                    "p99_write_latency_ms": 3.8,
                    "ledger_fenced_success": False,
                    "split_brain_corrupted": False,
                    "ensemble_switches": 0
                }
            }
            print(json.dumps(result, ensure_ascii=False))
            return

    if not journal_separated:
        result = {
            "status": "FAILED",
            "verdict": "BOOKKEEPER_JOURNAL_SHARED_DISK_LATENCY_SPIKE",
            "metrics": {
                "data_copied_gb": 0.0,
                "rebalance_duration_sec": 0.012,
                "p99_write_latency_ms": 275.0,
                "ledger_fenced_success": fencing_enabled,
                "split_brain_corrupted": False,
                "ensemble_switches": 0
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    if zombie_resurrection and not fencing_enabled:
        result = {
            "status": "FAILED",
            "verdict": "ZOMBIE_BROKER_SPLIT_BRAIN_APPEND_CORRUPTION",
            "metrics": {
                "data_copied_gb": 0.0,
                "rebalance_duration_sec": 0.012,
                "p99_write_latency_ms": 12.5,
                "ledger_fenced_success": False,
                "split_brain_corrupted": True,
                "ensemble_switches": 0
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    ensemble_switches = 1 if failed_bookie >= 0 else 0
    rebalance_duration = 0.012 if rebalance_req else 0.0
    fenced_success = True if (zombie_resurrection and fencing_enabled) else False

    result = {
        "status": "SUCCESS",
        "verdict": "OPTIMAL_PULSAR_SEGMENT_BOOKKEEPER_STORAGE",
        "metrics": {
            "data_copied_gb": 0.0,
            "rebalance_duration_sec": rebalance_duration,
            "p99_write_latency_ms": 2.8,
            "ledger_fenced_success": fenced_success,
            "split_brain_corrupted": False,
            "ensemble_switches": ensemble_switches
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
