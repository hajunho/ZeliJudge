import sys
import json
from typing import Dict, List, Any

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    db_config = input_data.get("db_config", {})
    disk_cap_mb = db_config.get("disk_capacity_mb", 100000)
    base_data_mb = db_config.get("base_data_size_mb", 30000)
    wal_seg_mb = db_config.get("wal_segment_size_mb", 16)
    max_slot_wal_keep_mb = db_config.get("max_slot_wal_keep_size_mb", -1)
    min_wal_mb = db_config.get("min_wal_size_mb", 1024)

    slots = {}
    for s in input_data.get("replication_slots", []):
        name = s["slot_name"]
        slots[name] = {
            "slot_name": name,
            "slot_type": s.get("slot_type", "logical"),
            "status": s.get("status", "active"),
            "restart_lsn_mb": s.get("restart_lsn_mb", 0),
            "invalidation_reason": None
        }

    events = input_data.get("events", [])

    current_lsn_mb = 0
    earliest_wal_lsn_mb = 0
    db_crashed = False
    slot_invalidated = False

    for ev in events:
        if db_crashed:
            break

        ev_type = ev.get("type")

        if ev_type == "WRITE_BURST":
            wal_mb = ev.get("wal_generated_mb", 16)
            current_lsn_mb += wal_mb

            active_wal_mb = current_lsn_mb - earliest_wal_lsn_mb
            total_used_mb = base_data_mb + active_wal_mb
            if total_used_mb >= disk_cap_mb:
                db_crashed = True
                break

        elif ev_type == "SLOT_ADVANCE":
            s_name = ev.get("slot_name")
            consumed_mb = ev.get("consumed_mb", 0)
            if s_name in slots and slots[s_name]["status"] != "lost":
                s = slots[s_name]
                s["restart_lsn_mb"] = min(current_lsn_mb, s["restart_lsn_mb"] + consumed_mb)
                s["status"] = "active"

        elif ev_type == "SLOT_FAILURE":
            s_name = ev.get("slot_name")
            if s_name in slots and slots[s_name]["status"] != "lost":
                slots[s_name]["status"] = "inactive"

        elif ev_type == "CHECKPOINT":
            valid_slots_lsn = []
            for s_name, s in slots.items():
                if s["status"] in ("active", "inactive"):
                    lag_mb = current_lsn_mb - s["restart_lsn_mb"]
                    if max_slot_wal_keep_mb > 0 and lag_mb > max_slot_wal_keep_mb:
                        s["status"] = "lost"
                        s["invalidation_reason"] = "max_slot_wal_keep_size_exceeded"
                        slot_invalidated = True
                    else:
                        valid_slots_lsn.append(s["restart_lsn_mb"])

            if valid_slots_lsn:
                retained_horizon = min(min(valid_slots_lsn), current_lsn_mb)
            else:
                retained_horizon = max(0, current_lsn_mb - min_wal_mb)

            earliest_wal_lsn_mb = max(earliest_wal_lsn_mb, retained_horizon)

            active_wal_mb = current_lsn_mb - earliest_wal_lsn_mb
            total_used_mb = base_data_mb + active_wal_mb
            if total_used_mb >= disk_cap_mb:
                db_crashed = True
                break

    active_wal_mb = current_lsn_mb - earliest_wal_lsn_mb
    total_used_mb = min(disk_cap_mb, base_data_mb + active_wal_mb) if db_crashed else (base_data_mb + active_wal_mb)
    disk_util_pct = round((total_used_mb / disk_cap_mb) * 100.0, 2)
    retained_wal_count = max(1, active_wal_mb // wal_seg_mb)

    slots_status = {}
    abandoned_lag_detected = False
    for s_name, s in slots.items():
        lag_mb = current_lsn_mb - s["restart_lsn_mb"]
        if s["status"] == "inactive" and lag_mb >= 5000:
            abandoned_lag_detected = True
        slots_status[s_name] = {
            "status": s["status"],
            "wal_lag_mb": lag_mb,
            "restart_lsn_mb": s["restart_lsn_mb"],
            "invalidation_reason": s["invalidation_reason"]
        }

    anomalies = []
    if db_crashed:
        anomalies.append("REPLICATION_SLOT_WAL_DISK_FULL_PANIC")
    if slot_invalidated:
        anomalies.append("REPLICATION_SLOT_INVALIDATED_LOST")
    if abandoned_lag_detected and not db_crashed and not slot_invalidated:
        anomalies.append("ABANDONED_REPLICATION_SLOT_LAG_WARNING")

    recommendations = []
    if "REPLICATION_SLOT_WAL_DISK_FULL_PANIC" in anomalies or "ABANDONED_REPLICATION_SLOT_LAG_WARNING" in anomalies:
        recommendations.append("CONFIGURE_MAX_SLOT_WAL_KEEP_SIZE")
        recommendations.append("DROP_OR_REPAIR_ABANDONED_REPLICATION_SLOTS")
    if "REPLICATION_SLOT_INVALIDATED_LOST" in anomalies:
        recommendations.append("REBUILD_SUBSCRIBER_FROM_FRESH_SNAPSHOT")
    recommendations.append("PROACTIVE_WAL_DISK_USAGE_ALERTING")

    diag_parts = []
    if "REPLICATION_SLOT_WAL_DISK_FULL_PANIC" in anomalies:
        diag_parts.append(f"복제 슬롯의 WAL 소비 중단으로 인해 WAL 세그먼트가 무제한 누적({active_wal_mb}MB)되어 디스크 용량 100% 소진 및 데이터베이스 PANIC 크래시 발생.")
    if "REPLICATION_SLOT_INVALIDATED_LOST" in anomalies:
        diag_parts.append(f"max_slot_wal_keep_size({max_slot_wal_keep_mb}MB) 초과로 지연된 복제 슬롯이 안전하게 비활성화(lost)되어 주 데이터베이스 디스크 풀 크래시를 방어함.")
    if "ABANDONED_REPLICATION_SLOT_LAG_WARNING" in anomalies:
        diag_parts.append("비활성 복제 슬롯이 WAL을 보류 중이며 디스크 사용량이 계속 증가하고 있음.")
    if not anomalies:
        diag_parts.append("모든 복제 슬롯이 정상적으로 WAL을 소비하고 체크포인트에 의해 오래된 세그먼트가 안정적으로 회수되었습니다.")

    diagnosis = " ".join(diag_parts)

    return {
        "current_wal_lsn_mb": current_lsn_mb,
        "current_disk_used_mb": total_used_mb,
        "disk_utilization_pct": disk_util_pct,
        "active_wal_size_mb": active_wal_mb,
        "retained_wal_count": retained_wal_count,
        "slots_status": slots_status,
        "db_crashed_disk_full": db_crashed,
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
