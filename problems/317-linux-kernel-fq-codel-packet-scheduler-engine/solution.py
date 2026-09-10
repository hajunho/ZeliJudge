import sys
import os
import math
import json
from collections import deque

class FQCoDelQueue:
    def __init__(self, config: dict):
        self.flows_cnt = config.get("flows_cnt", 8)
        self.limit = config.get("limit", 100)
        self.quantum = config.get("quantum", 1514)
        self.target_us = config.get("target_us", 5000)        # 5ms
        self.interval_us = config.get("interval_us", 100000)  # 100ms
        self.ecn = config.get("ecn", True)

        self.flows = []
        for fid in range(self.flows_cnt):
            self.flows.append({
                "flow_id": fid,
                "deficit": self.quantum,
                "queue": deque(),
                "bytes": 0,
                "dropping": False,
                "first_above_time_us": 0,
                "drop_next_us": 0,
                "count": 0
            })

        self.new_flows = deque()
        self.old_flows = deque()
        self.total_packets = 0
        self.event_log = []
        self.history = []
        self.stats = {
            "enqueued": 0,
            "dequeued": 0,
            "codel_drops": 0,
            "ecn_marks": 0,
            "overlimit_drops": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def enqueue(self, pkt: dict, current_time_us: int) -> dict:
        flow_id = pkt["flow_id"] % self.flows_cnt
        flow = self.flows[flow_id]
        size = pkt.get("size", 1000)

        if self.total_packets >= self.limit:
            largest_flow = max(self.flows, key=lambda f: len(f["queue"]))
            if len(largest_flow["queue"]) > 0:
                dropped_pkt = largest_flow["queue"].popleft()
                largest_flow["bytes"] -= dropped_pkt["size"]
                self.total_packets -= 1
                self.stats["overlimit_drops"] += 1
                self.log(f"OVERLIMIT_DROP pkt_id={dropped_pkt['pkt_id']} flow={largest_flow['flow_id']}")
                if len(largest_flow["queue"]) == 0:
                    if self.new_flows and self.new_flows[0] == largest_flow["flow_id"]:
                        self.new_flows.popleft()
                    elif self.old_flows and self.old_flows[0] == largest_flow["flow_id"]:
                        self.old_flows.popleft()

        packet_entry = {
            "pkt_id": pkt["pkt_id"],
            "flow_id": flow_id,
            "size": size,
            "enqueue_time_us": current_time_us,
            "ecn_capable": pkt.get("ecn_capable", False),
            "ecn_marked": False
        }

        if len(flow["queue"]) == 0 and flow_id not in self.new_flows and flow_id not in self.old_flows:
            flow["deficit"] = self.quantum
            self.new_flows.append(flow_id)

        flow["queue"].append(packet_entry)
        flow["bytes"] += size
        self.total_packets += 1
        self.stats["enqueued"] += 1

        res = {"op": "ENQUEUE", "pkt_id": pkt["pkt_id"], "flow_id": flow_id, "status": "ENQUEUED"}
        self.history.append(res)
        return res

    def dequeue(self, current_time_us: int) -> dict:
        if self.total_packets == 0:
            res = {"op": "DEQUEUE", "status": "QUEUE_EMPTY"}
            self.history.append(res)
            return res

        while True:
            flow = None

            while self.new_flows:
                fid = self.new_flows[0]
                candidate = self.flows[fid]
                if len(candidate["queue"]) == 0:
                    self.new_flows.popleft()
                    continue
                if candidate["deficit"] <= 0:
                    candidate["deficit"] += self.quantum
                    self.new_flows.popleft()
                    self.old_flows.append(fid)
                    continue
                flow = candidate
                break

            if flow is None:
                while self.old_flows:
                    fid = self.old_flows[0]
                    candidate = self.flows[fid]
                    if len(candidate["queue"]) == 0:
                        self.old_flows.popleft()
                        continue
                    if candidate["deficit"] <= 0:
                        candidate["deficit"] += self.quantum
                        self.old_flows.popleft()
                        self.old_flows.append(fid)
                        continue
                    flow = candidate
                    break

            if flow is None:
                res = {"op": "DEQUEUE", "status": "QUEUE_EMPTY"}
                self.history.append(res)
                return res

            pkt = flow["queue"].popleft()
            flow["bytes"] -= pkt["size"]
            self.total_packets -= 1
            flow["deficit"] -= pkt["size"]

            if len(flow["queue"]) == 0:
                if self.new_flows and self.new_flows[0] == flow["flow_id"]:
                    self.new_flows.popleft()
                elif self.old_flows and self.old_flows[0] == flow["flow_id"]:
                    self.old_flows.popleft()

            sojourn_time = current_time_us - pkt["enqueue_time_us"]
            drop_or_mark = False

            if sojourn_time < self.target_us:
                flow["first_above_time_us"] = 0
                flow["dropping"] = False
            else:
                if not flow["dropping"]:
                    if flow["first_above_time_us"] == 0:
                        flow["first_above_time_us"] = current_time_us + self.interval_us
                    elif current_time_us >= flow["first_above_time_us"]:
                        flow["dropping"] = True
                        flow["count"] = 1
                        flow["drop_next_us"] = current_time_us + int(self.interval_us / math.sqrt(flow["count"]))
                        drop_or_mark = True
                else:
                    if current_time_us >= flow["drop_next_us"]:
                        drop_or_mark = True
                        flow["count"] += 1
                        flow["drop_next_us"] = current_time_us + int(self.interval_us / math.sqrt(flow["count"]))

            if drop_or_mark:
                if self.ecn and pkt["ecn_capable"]:
                    pkt["ecn_marked"] = True
                    self.stats["ecn_marks"] += 1
                    self.stats["dequeued"] += 1
                    self.log(f"CODEL_ECN_MARK pkt_id={pkt['pkt_id']} flow={flow['flow_id']} sojourn={sojourn_time}")
                    res = {
                        "op": "DEQUEUE",
                        "status": "SUCCESS",
                        "pkt_id": pkt["pkt_id"],
                        "flow_id": flow["flow_id"],
                        "sojourn_time_us": sojourn_time,
                        "ecn_marked": True
                    }
                    self.history.append(res)
                    return res
                else:
                    self.stats["codel_drops"] += 1
                    self.log(f"CODEL_DROP pkt_id={pkt['pkt_id']} flow={flow['flow_id']} sojourn={sojourn_time}")
                    if self.total_packets == 0:
                        res = {"op": "DEQUEUE", "status": "QUEUE_EMPTY"}
                        self.history.append(res)
                        return res
                    continue
            else:
                self.stats["dequeued"] += 1
                res = {
                    "op": "DEQUEUE",
                    "status": "SUCCESS",
                    "pkt_id": pkt["pkt_id"],
                    "flow_id": flow["flow_id"],
                    "sojourn_time_us": sojourn_time,
                    "ecn_marked": False
                }
                self.history.append(res)
                return res

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    qdisc = FQCoDelQueue(config)

    for op_info in operations:
        op = op_info.get("op")
        ts = op_info.get("timestamp_us", 0)
        if op == "ENQUEUE":
            pkt = op_info.get("packet", {})
            qdisc.enqueue(pkt, ts)
        elif op == "DEQUEUE":
            qdisc.dequeue(ts)

    flows_dump = {}
    for f in qdisc.flows:
        flows_dump[str(f["flow_id"])] = {
            "queue_len": len(f["queue"]),
            "bytes": f["bytes"],
            "deficit": f["deficit"],
            "dropping": f["dropping"],
            "count": f["count"]
        }

    return {
        "stats": qdisc.stats,
        "total_packets": qdisc.total_packets,
        "new_flows_count": len(qdisc.new_flows),
        "old_flows_count": len(qdisc.old_flows),
        "flows": flows_dump,
        "history": qdisc.history,
        "event_log": qdisc.event_log
    }

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    input_text = sys.stdin.read().strip()
    if not input_text:
        sys.exit(0)

    data = json.loads(input_text)
    result = run_simulation(data)
    print(json.dumps(result, ensure_ascii=False))
