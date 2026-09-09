import json
import sys
from typing import Dict, List, Any, Optional

class KafkaBroker:
    def __init__(self, config: Dict[str, Any]):
        self.enable_idempotence = config.get("enable_idempotence", True)
        self.max_in_flight = config.get("max_in_flight_requests", 5)
        # partition_id -> list of log records
        self.partitions: Dict[int, List[Dict[str, Any]]] = {}
        # (partition_id, pid) -> {"last_seq": int, "epoch": int}
        self.producer_state: Dict[str, Dict[str, Any]] = {}
        # pid -> current epoch
        self.active_pids: Dict[int, int] = {}
        self.aborted_tx_pids: set = set()

    def _get_partition(self, partition_id: int) -> List[Dict[str, Any]]:
        if partition_id not in self.partitions:
            self.partitions[partition_id] = []
        return self.partitions[partition_id]

    def register_producer(self, pid: int, epoch: int):
        self.active_pids[pid] = epoch

    def handle_produce(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        pid = packet.get("pid", 100)
        epoch = packet.get("epoch", 0)
        partition_id = packet.get("partition", 0)
        seq = packet.get("seq", 0)
        payload = packet.get("payload", "")
        tx_id = packet.get("transactional_id")

        part_log = self._get_partition(partition_id)

        # Zombie Fencing check
        if pid in self.active_pids and epoch < self.active_pids[pid]:
            return {
                "status": "ERROR",
                "error": "ProducerFencedException",
                "reason": f"Producer epoch {epoch} is older than active epoch {self.active_pids[pid]}"
            }

        if not self.enable_idempotence:
            # Naive At-Least-Once append without deduplication
            offset = len(part_log)
            record = {
                "offset": offset,
                "pid": pid,
                "epoch": epoch,
                "seq": seq,
                "payload": payload,
                "is_control": False,
                "tx_id": tx_id
            }
            part_log.append(record)
            return {"status": "SUCCESS", "offset": offset, "action": "BLIND_APPEND"}

        # Idempotent Processing (KIP-98)
        state_key = f"{partition_id}:{pid}"
        if state_key not in self.producer_state:
            if seq != 0:
                return {
                    "status": "ERROR",
                    "error": "OutOfOrderSequenceException",
                    "reason": f"Expected sequence 0 for new producer {pid}, got {seq}"
                }
            self.producer_state[state_key] = {"last_seq": 0, "epoch": epoch}
            offset = len(part_log)
            record = {
                "offset": offset,
                "pid": pid,
                "epoch": epoch,
                "seq": seq,
                "payload": payload,
                "is_control": False,
                "tx_id": tx_id
            }
            part_log.append(record)
            return {"status": "SUCCESS", "offset": offset, "action": "FIRST_SEQ_APPEND"}

        state = self.producer_state[state_key]
        expected_seq = state["last_seq"] + 1

        if seq == expected_seq:
            state["last_seq"] = seq
            offset = len(part_log)
            record = {
                "offset": offset,
                "pid": pid,
                "epoch": epoch,
                "seq": seq,
                "payload": payload,
                "is_control": False,
                "tx_id": tx_id
            }
            part_log.append(record)
            return {"status": "SUCCESS", "offset": offset, "action": "SEQUENTIAL_APPEND"}

        elif seq <= state["last_seq"]:
            # Duplicate message due to retry after lost ACK!
            return {
                "status": "SUCCESS",
                "action": "DUPLICATE_DEDUPLICATED",
                "reason": f"Sequence {seq} <= last_seq {state['last_seq']}. Deduplicated without re-appending."
            }

        else:
            # seq > expected_seq -> gap in sequence
            return {
                "status": "ERROR",
                "error": "OutOfOrderSequenceException",
                "reason": f"Sequence gap: expected {expected_seq}, got {seq}"
            }

    def handle_end_txn(self, pid: int, epoch: int, partition_id: int, commit: bool):
        part_log = self._get_partition(partition_id)
        offset = len(part_log)
        marker = {
            "offset": offset,
            "pid": pid,
            "epoch": epoch,
            "seq": -1,
            "payload": "COMMIT" if commit else "ABORT",
            "is_control": True
        }
        part_log.append(marker)
        if not commit:
            self.aborted_tx_pids.add(pid)

    def consume(self, partition_id: int, isolation_level: str = "read_committed") -> List[Dict[str, Any]]:
        part_log = self._get_partition(partition_id)
        if isolation_level == "read_uncommitted":
            return [r for r in part_log if not r["is_control"]]

        # read_committed: filter out aborted transaction records
        committed_records = []
        for r in part_log:
            if r["is_control"]:
                continue
            if r.get("pid") not in self.aborted_tx_pids:
                committed_records.append(r)
        return committed_records

def solve(input_data: Dict[str, Any]) -> Dict[str, Any]:
    config = input_data.get("config", {})
    events = input_data.get("events", [])
    consumer_cfg = input_data.get("consumer", {})
    isolation_level = consumer_cfg.get("isolation_level", "read_committed")

    broker = KafkaBroker(config)
    event_logs = []
    total_messages_sent = 0
    total_retries = 0
    dedup_count = 0
    fenced_count = 0
    out_of_order_count = 0

    for ev in events:
        ev_type = ev.get("type")
        if ev_type == "REGISTER_PRODUCER":
            broker.register_producer(ev["pid"], ev["epoch"])
            event_logs.append({"event": "REGISTER_PRODUCER", "pid": ev["pid"], "epoch": ev["epoch"]})

        elif ev_type == "PRODUCE":
            total_messages_sent += 1
            is_retry = ev.get("is_retry", False)
            if is_retry:
                total_retries += 1

            res = broker.handle_produce(ev)
            if res.get("action") == "DUPLICATE_DEDUPLICATED":
                dedup_count += 1
            elif res.get("error") == "ProducerFencedException":
                fenced_count += 1
            elif res.get("error") == "OutOfOrderSequenceException":
                out_of_order_count += 1

            event_logs.append({
                "event": "PRODUCE",
                "pid": ev.get("pid"),
                "seq": ev.get("seq"),
                "is_retry": is_retry,
                "result": res
            })

        elif ev_type == "END_TXN":
            broker.handle_end_txn(ev["pid"], ev.get("epoch", 0), ev.get("partition", 0), ev.get("commit", True))
            event_logs.append({
                "event": "END_TXN",
                "pid": ev["pid"],
                "commit": ev.get("commit", True)
            })

    # Read consumer output for partition 0 (or all)
    consumed_records = broker.consume(0, isolation_level=isolation_level)

    # Check for duplicate payloads in log
    payloads = [r["payload"] for r in broker._get_partition(0) if not r["is_control"]]
    has_duplicates = len(payloads) != len(set(payloads))

    # Determine verdict
    if not config.get("enable_idempotence", True) and has_duplicates:
        verdict = "CATASTROPHIC_DUPLICATE_MESSAGE_INJECTION"
    elif fenced_count > 0:
        verdict = "ZOMBIE_PRODUCER_FENCED"
    elif out_of_order_count > 0:
        verdict = "OUT_OF_ORDER_SEQUENCE_BLOCKED"
    elif dedup_count > 0 or config.get("enable_idempotence", True):
        verdict = "EXACTLY_ONCE_SEMANTICS_GUARANTEED"
    else:
        verdict = "AT_LEAST_ONCE_CONFORMANT"

    return {
        "status": "SUCCESS",
        "config": {
            "enable_idempotence": config.get("enable_idempotence", True),
            "isolation_level": isolation_level
        },
        "metrics": {
            "total_messages_sent": total_messages_sent,
            "total_retries": total_retries,
            "deduplicated_messages": dedup_count,
            "fenced_producers": fenced_count,
            "out_of_order_errors": out_of_order_count,
            "partition_log_length": len(broker._get_partition(0)),
            "consumed_records_count": len(consumed_records),
            "verdict": verdict
        },
        "consumed_records": consumed_records,
        "sample_event_logs": event_logs[:20]
    }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = solve(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
