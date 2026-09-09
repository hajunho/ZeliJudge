import sys
import json
from typing import Dict, List, Any

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sub_config = input_data.get("subsystem_config", {})
    sub_nqn = sub_config.get("subsystem_nqn", "nqn.2014-08.org.nvmexpress:default")
    multipath_enabled = sub_config.get("multipath_enabled", True)
    iopolicy = sub_config.get("multipath_iopolicy", "round-robin")
    kato_sec = sub_config.get("kato_sec", 5)
    retry_timeout_sec = sub_config.get("retry_timeout_sec", 30)

    paths_data = input_data.get("paths", [])
    events = input_data.get("events", [])

    controllers = {}
    for p in paths_data:
        cid = p["controller_id"]
        controllers[cid] = {
            "controller_id": cid,
            "transport": p.get("transport", "rdma"),
            "ana_state": p.get("initial_ana_state", "OPTIMIZED"),
            "session_state": "CONNECTED",
            "base_lat_us": p.get("base_latency_us", 150),
            "io_handled": 0,
            "reconnect_until_ms": 0
        }

    total_io = 0
    completed_io = 0
    requeued_io = 0
    failed_io = 0
    ana_changes = 0
    kato_disconnects = 0
    latencies_us = []
    flapping_detected = False
    state_change_history = []
    non_opt_io_while_opt_avail = 0

    rr_idx = 0

    for ev in events:
        time_ms = ev.get("time_ms", 0)
        ev_type = ev.get("type")

        for cid, ctrl in controllers.items():
            if ctrl["session_state"] == "RECONNECTING" and time_ms >= ctrl["reconnect_until_ms"]:
                ctrl["session_state"] = "CONNECTED"

        if ev_type == "ANA_STATE_CHANGE":
            cid = ev.get("controller_id")
            new_state = ev.get("new_ana_state", "OPTIMIZED")
            if cid in controllers:
                controllers[cid]["ana_state"] = new_state
                ana_changes += 1
                state_change_history.append((time_ms, cid, new_state))
                recent = [t for t, c, s in state_change_history if time_ms - t <= 5000 and c == cid]
                if len(recent) >= 3:
                    flapping_detected = True

        elif ev_type == "FABRIC_CONGESTION_STALL":
            cid = ev.get("controller_id")
            duration_ms = ev.get("duration_ms", 1000)
            if duration_ms >= kato_sec * 1000:
                kato_disconnects += 1
                if cid in controllers:
                    controllers[cid]["session_state"] = "RECONNECTING"
                    controllers[cid]["reconnect_until_ms"] = time_ms + duration_ms

        elif ev_type == "IO_REQUEST":
            total_io += 1
            size_kb = ev.get("size_kb", 4)

            avail = [c for c in controllers.values() if c["session_state"] == "CONNECTED"]
            opt_paths = [c for c in avail if c["ana_state"] == "OPTIMIZED"]
            non_opt_paths = [c for c in avail if c["ana_state"] == "NON_OPTIMIZED"]

            if flapping_detected:
                requeued_io += 1
                lat = 5000000
                latencies_us.append(lat)
                completed_io += 1
                continue

            chosen_ctrl = None
            if not avail or (not opt_paths and not non_opt_paths):
                failed_io += 1
                continue

            if iopolicy == "round-robin":
                candidate_paths = opt_paths + non_opt_paths
                if candidate_paths:
                    candidate_paths.sort(key=lambda x: x["controller_id"])
                    chosen_ctrl = candidate_paths[rr_idx % len(candidate_paths)]
                    rr_idx += 1
                    if chosen_ctrl["ana_state"] == "NON_OPTIMIZED" and opt_paths:
                        non_opt_io_while_opt_avail += 1
            else:
                if opt_paths:
                    chosen_ctrl = opt_paths[rr_idx % len(opt_paths)]
                    rr_idx += 1
                elif non_opt_paths:
                    requeued_io += 1
                    chosen_ctrl = non_opt_paths[0]

            if chosen_ctrl:
                chosen_ctrl["io_handled"] += 1
                completed_io += 1
                lat = chosen_ctrl["base_lat_us"] + (size_kb * 2)
                latencies_us.append(lat)

    avg_lat = round(sum(latencies_us) / len(latencies_us), 2) if latencies_us else 0.0
    latencies_us.sort()
    p99_lat = latencies_us[int(len(latencies_us) * 0.99)] if latencies_us else 0.0

    anomalies = []
    if non_opt_io_while_opt_avail > (total_io * 0.3) and iopolicy == "round-robin":
        anomalies.append("NATIVE_NVME_MULTIPATH_ROUND_ROBIN_DEGRADATION")

    if flapping_detected or p99_lat >= 2000000.0:
        anomalies.append("ANA_PATH_FLAPPING_IO_FREEZE")

    if kato_disconnects > 0:
        anomalies.append("NVME_KATO_HEARTBEAT_DISCONNECT")

    if failed_io > 0:
        anomalies.append("ALL_PATHS_INACCESSIBLE_IO_ERROR")

    recommendations = []
    if "NATIVE_NVME_MULTIPATH_ROUND_ROBIN_DEGRADATION" in anomalies:
        recommendations.append("SET_NVME_IOPOLICY_TO_ANA_OPTIMIZED_ONLY")
    if "ANA_PATH_FLAPPING_IO_FREEZE" in anomalies:
        recommendations.append("STABILIZE_INTER_CONTROLLER_HEARTBEAT_FABRIC")
    if "NVME_KATO_HEARTBEAT_DISCONNECT" in anomalies:
        recommendations.append("TUNE_NVME_KATO_TIMEOUT_AND_PFC_PRIORITY")
    if "ALL_PATHS_INACCESSIBLE_IO_ERROR" in anomalies:
        recommendations.append("VERIFY_PHYSICAL_FABRIC_REDUNDANCY")

    diag_parts = []
    if "NATIVE_NVME_MULTIPATH_ROUND_ROBIN_DEGRADATION" in anomalies:
        diag_parts.append(f"round-robin I/O 정책으로 인해 최적 경로가 존재함에도 Non-Optimized 경로로 I/O({non_opt_io_while_opt_avail}건)가 분배되어 성능 저하 발생.")
    if "ANA_PATH_FLAPPING_IO_FREEZE" in anomalies:
        diag_parts.append(f"컨트롤러 간 ANA 상태 플래핑으로 인해 NVMe 헤드 재큐잉 프리즈 및 P99 지연시간({round(p99_lat / 1000.0, 1)}ms) 스파이크 발생.")
    if "NVME_KATO_HEARTBEAT_DISCONNECT" in anomalies:
        diag_parts.append(f"패브릭 지연이 KATO 임계치({kato_sec}초)를 초과하여 컨트롤러 세션 단절({kato_disconnects}건) 및 큐 재구축 발생.")
    if "ALL_PATHS_INACCESSIBLE_IO_ERROR" in anomalies:
        diag_parts.append(f"모든 NVMe-oF 경로 접근 불능으로 인해 I/O 실패({failed_io}건) 발생.")
    if not anomalies:
        diag_parts.append("ANA Optimized 경로를 통해 초저지연 I/O가 안정적으로 처리되었으며 패브릭 연결이 정상 유지되었습니다.")

    diagnosis = " ".join(diag_parts)

    paths_status = {}
    for cid, c in controllers.items():
        paths_status[cid] = {
            "ana_state": c["ana_state"],
            "session_state": c["session_state"],
            "io_handled": c["io_handled"]
        }

    return {
        "subsystem_nqn": sub_nqn,
        "multipath_iopolicy": iopolicy,
        "total_io_requests": total_io,
        "completed_io_requests": completed_io,
        "requeued_io_requests": requeued_io,
        "failed_io_requests": failed_io,
        "avg_latency_us": avg_lat,
        "p99_latency_us": p99_lat,
        "ana_state_change_count": ana_changes,
        "kato_disconnect_count": kato_disconnects,
        "paths_status": paths_status,
        "anomalies": anomalies,
        "recommendations": recommendations,
        "diagnosis": diagnosis
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
