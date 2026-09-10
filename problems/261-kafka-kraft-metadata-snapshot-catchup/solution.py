import sys
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

class MetadataImage:
    def __init__(self):
        self.brokers = {}
        self.topics = {}
        self.topic_name_to_id = {}

    def apply_record(self, record: dict):
        rec_type = record["type"]
        data = record["data"]

        if rec_type == "REGISTER_BROKER":
            b_id = data["broker_id"]
            self.brokers[str(b_id)] = {
                "broker_id": b_id,
                "rack": data.get("rack", "default"),
                "status": "ACTIVE"
            }
        elif rec_type == "FENCE_BROKER":
            b_id = str(data["broker_id"])
            if b_id in self.brokers:
                self.brokers[b_id]["status"] = "FENCED"
        elif rec_type == "UNFENCE_BROKER":
            b_id = str(data["broker_id"])
            if b_id in self.brokers:
                self.brokers[b_id]["status"] = "ACTIVE"
        elif rec_type == "TOPIC_RECORD":
            t_id = data["topic_id"]
            t_name = data["name"]
            self.topics[t_id] = {
                "topic_id": t_id,
                "name": t_name,
                "partitions": {}
            }
            self.topic_name_to_id[t_name] = t_id
        elif rec_type == "PARTITION_RECORD":
            t_id = data["topic_id"]
            p_id = str(data["partition_id"])
            if t_id in self.topics:
                self.topics[t_id]["partitions"][p_id] = {
                    "partition_id": data["partition_id"],
                    "replicas": data["replicas"],
                    "isr": data["isr"],
                    "leader": data["leader"],
                    "leader_epoch": data.get("leader_epoch", 1)
                }

    def to_dict(self) -> dict:
        return {
            "brokers": copy.deepcopy(self.brokers),
            "topics": copy.deepcopy(self.topics)
        }

    @classmethod
    def from_dict(cls, data: dict):
        img = cls()
        img.brokers = copy.deepcopy(data.get("brokers", {}))
        img.topics = copy.deepcopy(data.get("topics", {}))
        for t_id, t_info in img.topics.items():
            img.topic_name_to_id[t_info["name"]] = t_id
        return img

class KRaftController:
    def __init__(self, config: dict):
        self.cluster_id = config.get("cluster_id", "KRAFT_CLUSTER_01")
        self.leader_epoch = config.get("leader_epoch", 1)
        self.snapshot_interval = config.get("snapshot_interval_records", 20)

        self.log = []
        self.log_start_offset = 0
        self.next_offset = 0

        self.current_image = MetadataImage()
        self.latest_snapshot = None
        self.snapshots = {}

        self.broker_fetch_offsets = {}
        self.metrics = {
            "total_records_appended": 0,
            "snapshots_created": 0,
            "log_truncations_performed": 0,
            "fetch_snapshot_fallbacks": 0,
            "incremental_fetches": 0
        }
        self.diagnostics = []

    def append_record(self, record: dict):
        offset = self.next_offset
        entry = {
            "offset": offset,
            "epoch": self.leader_epoch,
            "record": record
        }
        self.log.append(entry)
        self.next_offset += 1
        self.current_image.apply_record(record)
        self.metrics["total_records_appended"] += 1

        uncompacted_count = self.next_offset - self.log_start_offset
        if uncompacted_count >= self.snapshot_interval:
            self.create_snapshot(self.next_offset)

    def create_snapshot(self, end_offset: int):
        snap_dict = {
            "snapshot_offset": end_offset,
            "snapshot_epoch": self.leader_epoch,
            "image": self.current_image.to_dict()
        }
        self.snapshots[end_offset] = snap_dict
        self.latest_snapshot = snap_dict
        self.metrics["snapshots_created"] += 1
        self.diagnostics.append(f"METADATA_SNAPSHOT_CREATED: offset={end_offset}, epoch={self.leader_epoch}")

        old_start = self.log_start_offset
        self.log = [e for e in self.log if e["offset"] >= end_offset]
        self.log_start_offset = end_offset
        self.metrics["log_truncations_performed"] += 1
        self.diagnostics.append(f"LOG_TRUNCATED: old_start={old_start}, new_start={end_offset}")

    def handle_fetch(self, broker_id: int, fetch_offset: int) -> dict:
        self.broker_fetch_offsets[str(broker_id)] = fetch_offset

        if fetch_offset < self.log_start_offset:
            self.metrics["fetch_snapshot_fallbacks"] += 1
            self.diagnostics.append(f"FETCH_SNAPSHOT_FALLBACK_TRIGGERED: broker={broker_id}, fetch_offset={fetch_offset}, log_start={self.log_start_offset}")
            return {
                "type": "FETCH_SNAPSHOT_RESPONSE",
                "snapshot": self.latest_snapshot,
                "high_watermark": self.next_offset
            }
        else:
            self.metrics["incremental_fetches"] += 1
            matching_records = [e for e in self.log if e["offset"] >= fetch_offset]
            return {
                "type": "FETCH_RECORDS_RESPONSE",
                "records": matching_records,
                "high_watermark": self.next_offset
            }

def simulate_kraft(input_data: dict) -> dict:
    config = input_data.get("config", {})
    controller = KRaftController(config)
    workload = input_data.get("workload_events", [])

    broker_images = {}
    broker_offsets = {}

    for ev in workload:
        ev_type = ev["type"]
        if ev_type == "APPEND_RECORD":
            controller.append_record(ev["record"])
        elif ev_type == "FORCE_SNAPSHOT":
            controller.create_snapshot(controller.next_offset)
        elif ev_type == "BROKER_FETCH":
            b_id = ev["broker_id"]
            f_offset = broker_offsets.get(b_id, 0)
            resp = controller.handle_fetch(b_id, f_offset)
            if resp["type"] == "FETCH_SNAPSHOT_RESPONSE":
                snap = resp["snapshot"]
                broker_images[b_id] = MetadataImage.from_dict(snap["image"])
                broker_offsets[b_id] = snap["snapshot_offset"]
                if broker_offsets[b_id] < resp["high_watermark"]:
                    sub_resp = controller.handle_fetch(b_id, broker_offsets[b_id])
                    if sub_resp["type"] == "FETCH_RECORDS_RESPONSE":
                        for e in sub_resp["records"]:
                            broker_images[b_id].apply_record(e["record"])
                        broker_offsets[b_id] = resp["high_watermark"]
            elif resp["type"] == "FETCH_RECORDS_RESPONSE":
                if b_id not in broker_images:
                    broker_images[b_id] = MetadataImage()
                for e in resp["records"]:
                    broker_images[b_id].apply_record(e["record"])
                broker_offsets[b_id] = resp["high_watermark"]

    broker_status = {}
    for b_id, img in broker_images.items():
        broker_status[str(b_id)] = {
            "synchronized_offset": broker_offsets.get(b_id, 0),
            "brokers_count": len(img.brokers),
            "topics_count": len(img.topics),
            "in_sync_with_controller": (broker_offsets.get(b_id, 0) == controller.next_offset)
        }

    return {
        "cluster_id": controller.cluster_id,
        "active_controller_epoch": controller.leader_epoch,
        "high_watermark": controller.next_offset,
        "log_start_offset": controller.log_start_offset,
        "active_log_records_retained": len(controller.log),
        "latest_snapshot_offset": controller.latest_snapshot["snapshot_offset"] if controller.latest_snapshot else None,
        "metrics": controller.metrics,
        "controller_metadata_summary": {
            "total_brokers": len(controller.current_image.brokers),
            "total_topics": len(controller.current_image.topics)
        },
        "controller_image": controller.current_image.to_dict(),
        "broker_sync_status": broker_status,
        "diagnostics": controller.diagnostics
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    result = simulate_kraft(input_data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
