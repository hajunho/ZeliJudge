import sys
import json
from typing import Dict, List, Any

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    config = input_data.get("config", {})
    topic = config.get("topic", "events.tx")
    partition_id = config.get("partition_id", 0)
    isolation_level = config.get("consumer_isolation_level", "read_committed")
    txn_timeout_ms = config.get("transaction_timeout_ms", 60000)
    fencing_enabled = config.get("producer_epoch_fencing_enabled", True)

    producers_meta = {p["producer_id"]: p for p in input_data.get("producers", [])}
    events = input_data.get("events", [])

    log = []
    open_transactions = {}
    producer_epochs = {pid: p.get("initial_epoch", 0) for pid, p in producers_meta.items()}
    fenced_producers = set()

    leo = 0
    hw = 0
    consumer_offset = 0
    total_consumed = 0
    aborted_skipped = 0
    max_lag = 0
    zombie_fenced_attempts = 0
    dirty_reads_detected = False

    lso_stall_start_time = None
    total_lso_stall_duration = 0

    def get_lso():
        if not open_transactions:
            return hw
        return min(tx["start_offset"] for tx in open_transactions.values())

    for ev in events:
        time_ms = ev.get("time_ms", 0)
        ev_type = ev.get("type")
        pid = ev.get("producer_id")

        if ev_type == "TXN_BEGIN":
            if pid in fenced_producers and fencing_enabled:
                zombie_fenced_attempts += 1
                continue
            open_transactions[pid] = {
                "start_offset": leo,
                "start_time_ms": time_ms,
                "epoch": producer_epochs.get(pid, 0),
                "messages": [],
                "status": "ACTIVE"
            }

        elif ev_type == "PRODUCE":
            if pid in fenced_producers and fencing_enabled:
                zombie_fenced_attempts += 1
                continue
            msg_id = ev.get("message_id", f"msg-{leo}")
            payload = ev.get("payload", "")

            is_tx = pid in open_transactions and open_transactions[pid]["status"] in ("ACTIVE", "HANGING")
            if is_tx:
                tx = open_transactions[pid]
                if not tx["messages"]:
                    tx["start_offset"] = leo
                tx["messages"].append(leo)
                entry = {
                    "offset": leo,
                    "type": "DATA",
                    "producer_id": pid,
                    "is_tx": True,
                    "status": "PENDING",
                    "msg_id": msg_id,
                    "payload": payload
                }
            else:
                entry = {
                    "offset": leo,
                    "type": "DATA",
                    "producer_id": pid,
                    "is_tx": False,
                    "status": "COMMITTED",
                    "msg_id": msg_id,
                    "payload": payload
                }
            log.append(entry)
            leo += 1
            hw = leo

        elif ev_type == "PRODUCE_BURST":
            if pid in fenced_producers and fencing_enabled:
                zombie_fenced_attempts += 1
                continue
            count = ev.get("count", 1)
            is_tx = pid in open_transactions and open_transactions[pid]["status"] in ("ACTIVE", "HANGING")
            for i in range(count):
                if is_tx:
                    tx = open_transactions[pid]
                    if not tx["messages"]:
                        tx["start_offset"] = leo
                    tx["messages"].append(leo)
                    entry = {
                        "offset": leo,
                        "type": "DATA",
                        "producer_id": pid,
                        "is_tx": True,
                        "status": "PENDING",
                        "msg_id": f"burst-{leo}",
                        "payload": "burst"
                    }
                else:
                    entry = {
                        "offset": leo,
                        "type": "DATA",
                        "producer_id": pid,
                        "is_tx": False,
                        "status": "COMMITTED",
                        "msg_id": f"burst-{leo}",
                        "payload": "burst"
                    }
                log.append(entry)
                leo += 1
            hw = leo

        elif ev_type == "PRODUCER_HANG":
            if pid in open_transactions:
                open_transactions[pid]["status"] = "HANGING"

        elif ev_type == "TXN_COMMIT":
            if pid in fenced_producers and fencing_enabled:
                zombie_fenced_attempts += 1
                continue
            if pid in open_transactions:
                tx = open_transactions[pid]
                for off in tx["messages"]:
                    log[off]["status"] = "COMMITTED"
                log.append({
                    "offset": leo,
                    "type": "TXN_MARKER",
                    "producer_id": pid,
                    "marker": "COMMIT",
                    "status": "COMMITTED"
                })
                leo += 1
                hw = leo
                del open_transactions[pid]

        elif ev_type == "TXN_ABORT":
            if pid in fenced_producers and fencing_enabled:
                zombie_fenced_attempts += 1
                continue
            if pid in open_transactions:
                tx = open_transactions[pid]
                for off in tx["messages"]:
                    log[off]["status"] = "ABORTED"
                log.append({
                    "offset": leo,
                    "type": "TXN_MARKER",
                    "producer_id": pid,
                    "marker": "ABORT",
                    "status": "COMMITTED"
                })
                leo += 1
                hw = leo
                del open_transactions[pid]

        elif ev_type == "COORDINATOR_TICK":
            timed_out_pids = []
            for t_pid, tx in list(open_transactions.items()):
                if time_ms - tx["start_time_ms"] >= txn_timeout_ms:
                    timed_out_pids.append(t_pid)

            for t_pid in timed_out_pids:
                tx = open_transactions[t_pid]
                for off in tx["messages"]:
                    log[off]["status"] = "ABORTED"
                log.append({
                    "offset": leo,
                    "type": "TXN_MARKER",
                    "producer_id": t_pid,
                    "marker": "ABORT",
                    "status": "COMMITTED"
                })
                leo += 1
                hw = leo
                del open_transactions[t_pid]
                fenced_producers.add(t_pid)
                producer_epochs[t_pid] = producer_epochs.get(t_pid, 0) + 1

        elif ev_type == "CONSUME_POLL":
            current_lso = get_lso()
            if isolation_level == "read_uncommitted":
                while consumer_offset < hw:
                    entry = log[consumer_offset]
                    if entry["type"] == "DATA":
                        total_consumed += 1
                        if entry["status"] == "ABORTED":
                            dirty_reads_detected = True
                    consumer_offset += 1
            else:
                while consumer_offset < current_lso:
                    entry = log[consumer_offset]
                    if entry["type"] == "DATA":
                        if entry["status"] == "COMMITTED":
                            total_consumed += 1
                        elif entry["status"] == "ABORTED":
                            aborted_skipped += 1
                    consumer_offset += 1

            current_lag = hw - consumer_offset
            if current_lag > max_lag:
                max_lag = current_lag

            if current_lag >= 100 and current_lso < hw:
                if lso_stall_start_time is None:
                    lso_stall_start_time = time_ms
            else:
                if lso_stall_start_time is not None:
                    total_lso_stall_duration += (time_ms - lso_stall_start_time)
                    lso_stall_start_time = None

    if lso_stall_start_time is not None:
        last_time = events[-1].get("time_ms", 0) if events else 0
        total_lso_stall_duration += max(0, last_time - lso_stall_start_time)

    final_lso = get_lso()
    anomalies = []
    if max_lag >= 100 and isolation_level == "read_committed" and total_lso_stall_duration > 0:
        anomalies.append("LSO_STALL_CONSUMER_LAG_EXPLOSION")

    if txn_timeout_ms >= 60000 and total_lso_stall_duration >= 30000:
        anomalies.append("EXCESSIVE_TRANSACTION_TIMEOUT_DELAY")

    if zombie_fenced_attempts > 0:
        anomalies.append("ZOMBIE_PRODUCER_SPLIT_BRAIN_ATTEMPT")

    if dirty_reads_detected:
        anomalies.append("READ_UNCOMMITTED_DIRTY_READ")

    recommendations = []
    if "LSO_STALL_CONSUMER_LAG_EXPLOSION" in anomalies:
        recommendations.append("TUNE_TRANSACTION_TIMEOUT_MS_AND_MONITOR_LSO")
    if "EXCESSIVE_TRANSACTION_TIMEOUT_DELAY" in anomalies:
        recommendations.append("LOWER_TRANSACTION_TIMEOUT_MS_TO_REDUCE_BLOCKED_WINDOW")
    if "ZOMBIE_PRODUCER_SPLIT_BRAIN_ATTEMPT" in anomalies:
        recommendations.append("ENFORCE_TRANSACTIONAL_ID_AND_EPOCH_FENCING")
    if "READ_UNCOMMITTED_DIRTY_READ" in anomalies:
        recommendations.append("SET_CONSUMER_ISOLATION_LEVEL_TO_READ_COMMITTED")

    diag_parts = []
    if "LSO_STALL_CONSUMER_LAG_EXPLOSION" in anomalies:
        diag_parts.append(f"미완결 트랜잭션으로 인해 LSO가 고정(LSO={final_lso}, HW={hw})되어 read_committed 컨슈머 랙이 최대 {max_lag}개까지 폭증함.")
    if "EXCESSIVE_TRANSACTION_TIMEOUT_DELAY" in anomalies:
        diag_parts.append(f"기본 트랜잭션 타임아웃({txn_timeout_ms}ms)이 과도하게 길어 장애 발생 시 LSO 회복 지연({total_lso_stall_duration}ms) 유발.")
    if "ZOMBIE_PRODUCER_SPLIT_BRAIN_ATTEMPT" in anomalies:
        diag_parts.append(f"코디네이터 타임아웃으로 에포크가 펜싱된 좀비 프로듀서의 쓰기 시도({zombie_fenced_attempts}건)가 안전하게 차단됨.")
    if "READ_UNCOMMITTED_DIRTY_READ" in anomalies:
        diag_parts.append("read_uncommitted 격리 수준으로 인해 롤백/폐기된 트랜잭션 메시지가 컨슈머에 더티 리드(Dirty Read)됨.")
    if not anomalies:
        diag_parts.append("모든 트랜잭션이 신속하게 커밋/어보트되어 LSO와 HW가 일치하며 컨슈머 지연 없이 안정적으로 처리되었습니다.")

    diagnosis = " ".join(diag_parts)

    return {
        "topic": topic,
        "partition_id": partition_id,
        "isolation_level": isolation_level,
        "total_messages_produced": len([e for e in log if e["type"] == "DATA"]),
        "total_messages_consumed": total_consumed,
        "aborted_messages_skipped": aborted_skipped,
        "max_consumer_lag": max_lag,
        "lso_stalled_duration_ms": total_lso_stall_duration,
        "current_lso": final_lso,
        "current_hw": hw,
        "zombie_fenced_attempts": zombie_fenced_attempts,
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
