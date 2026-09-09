import sys
import json

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return

    data = json.loads(input_data)
    config = data.get("config", {})
    engine = config.get("engine", "INNODB")
    doublewrite_enabled = bool(config.get("doublewrite_enabled", True))
    fpw_enabled = bool(config.get("full_page_writes_enabled", True))
    nvme_atomic_kb = int(config.get("nvme_atomic_write_unit_kb", 4))
    page_size_kb = int(config.get("page_size_kb", 16 if engine == "INNODB" else 8))

    workload = data.get("workload", {})
    dirty_pages = int(workload.get("dirty_pages_count", 5000))
    power_cut = bool(workload.get("power_cut_during_flush", True))

    hardware_atomic = (nvme_atomic_kb >= page_size_kb)

    if not power_cut:
        if (engine == "INNODB" and not doublewrite_enabled) or (engine == "POSTGRESQL" and not fpw_enabled) or engine == "RAW_WAL_ONLY":
            result = {
                "status": "WARNING",
                "verdict": "NO_CRASH_BUT_TORN_WRITE_VULNERABLE",
                "metrics": {
                    "torn_pages_detected": 0,
                    "pages_restored": 0,
                    "crash_recovery_success": True,
                    "data_corruption": False,
                    "write_amplification_factor": 1.0,
                    "hardware_atomic_guaranteed": hardware_atomic
                }
            }
        else:
            write_amp = 2.0 if engine == "INNODB" and doublewrite_enabled else 1.35
            result = {
                "status": "SUCCESS",
                "verdict": "CLEAN_FLUSH_PROTECTED_STATE",
                "metrics": {
                    "torn_pages_detected": 0,
                    "pages_restored": 0,
                    "crash_recovery_success": True,
                    "data_corruption": False,
                    "write_amplification_factor": round(write_amp, 2),
                    "hardware_atomic_guaranteed": hardware_atomic
                }
            }
        print(json.dumps(result, ensure_ascii=False))
        return

    if hardware_atomic:
        result = {
            "status": "SUCCESS",
            "verdict": "OPTIMAL_NVME_HARDWARE_ATOMIC_WRITE_RECOVERY",
            "metrics": {
                "torn_pages_detected": 0,
                "pages_restored": 0,
                "crash_recovery_success": True,
                "data_corruption": False,
                "write_amplification_factor": 1.0,
                "hardware_atomic_guaranteed": True
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    torn_pages = 1
    if engine == "RAW_WAL_ONLY" or (engine == "INNODB" and not doublewrite_enabled) or (engine == "POSTGRESQL" and not fpw_enabled):
        result = {
            "status": "FAILED",
            "verdict": "TORN_PAGE_WRITE_PERMANENT_CORRUPTION",
            "metrics": {
                "torn_pages_detected": torn_pages,
                "pages_restored": 0,
                "crash_recovery_success": False,
                "data_corruption": True,
                "write_amplification_factor": 1.0,
                "hardware_atomic_guaranteed": False
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    if engine == "INNODB" and doublewrite_enabled:
        result = {
            "status": "SUCCESS",
            "verdict": "OPTIMAL_DOUBLEWRITE_BUFFER_CRASH_RECOVERY",
            "metrics": {
                "torn_pages_detected": torn_pages,
                "pages_restored": torn_pages,
                "crash_recovery_success": True,
                "data_corruption": False,
                "write_amplification_factor": 2.0,
                "hardware_atomic_guaranteed": False
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    if engine == "POSTGRESQL" and fpw_enabled:
        result = {
            "status": "SUCCESS",
            "verdict": "OPTIMAL_POSTGRESQL_FULL_PAGE_WRITE_RECOVERY",
            "metrics": {
                "torn_pages_detected": torn_pages,
                "pages_restored": torn_pages,
                "crash_recovery_success": True,
                "data_corruption": False,
                "write_amplification_factor": 1.35,
                "hardware_atomic_guaranteed": False
            }
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    result = {
        "status": "FAILED",
        "verdict": "UNKNOWN_CONFIG",
        "metrics": {
            "torn_pages_detected": 0,
            "pages_restored": 0,
            "crash_recovery_success": False,
            "data_corruption": True,
            "write_amplification_factor": 1.0,
            "hardware_atomic_guaranteed": False
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
