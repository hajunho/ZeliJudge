# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #391: Linux Kernel Block Layer blk-throttle Cgroup I/O Rate Limiting Engine
Implementation in Python 3.
"""
import sys
import json
import math

class BlkThrottleEngine:
    def __init__(self, config):
        self.slice_window_ms = config.get("slice_window_ms", 100)
        self.cgroups = {}
        for cg_id, cg_cfg in config.get("cgroups", {}).items():
            self.cgroups[cg_id] = {
                "id": cg_id,
                "rbps": cg_cfg.get("rbps", 0),
                "wbps": cg_cfg.get("wbps", 0),
                "riops": cg_cfg.get("riops", 0),
                "wiops": cg_cfg.get("wiops", 0),
                "slice_start": 0,
                "slice_end": self.slice_window_ms,
                "bytes_disp": {"READ": 0, "WRITE": 0},
                "io_disp": {"READ": 0, "WRITE": 0},
                "wait_queue": []
            }

        self.current_time_ms = 0
        self.events = []
        self.dispatched_count = 0
        self.throttled_count = 0

    def _refresh_slice(self, cg, now_ms):
        if now_ms >= cg["slice_end"]:
            slices_passed = (now_ms - cg["slice_start"]) // self.slice_window_ms
            cg["slice_start"] += slices_passed * self.slice_window_ms
            cg["slice_end"] = cg["slice_start"] + self.slice_window_ms
            cg["bytes_disp"]["READ"] = 0
            cg["bytes_disp"]["WRITE"] = 0
            cg["io_disp"]["READ"] = 0
            cg["io_disp"]["WRITE"] = 0

    def submit_bio(self, bio_id, cg_id, op, size_bytes, now_ms):
        self.current_time_ms = max(self.current_time_ms, now_ms)
        cg = self.cgroups.get(cg_id)
        if not cg:
            self.events.append({"op": "SUBMIT_BIO", "bio_id": bio_id, "status": "FAIL_NO_CGROUP"})
            return

        self._refresh_slice(cg, now_ms)

        bps_limit = cg["rbps"] if op == "READ" else cg["wbps"]
        iops_limit = cg["riops"] if op == "READ" else cg["wiops"]

        bps_unlimited = (bps_limit == 0)
        iops_unlimited = (iops_limit == 0)

        slice_duration_sec = self.slice_window_ms / 1000.0
        bps_slice_budget = math.ceil(bps_limit * slice_duration_sec) if not bps_unlimited else float('inf')
        iops_slice_budget = math.ceil(iops_limit * slice_duration_sec) if not iops_unlimited else float('inf')

        rem_bytes = bps_slice_budget - cg["bytes_disp"][op]
        rem_iops = iops_slice_budget - cg["io_disp"][op]

        if len(cg["wait_queue"]) > 0 or (not bps_unlimited and size_bytes > rem_bytes) or (not iops_unlimited and 1 > rem_iops):
            self.throttled_count += 1
            wait_until = cg["slice_end"]
            bio_entry = {
                "bio_id": bio_id,
                "op": op,
                "size_bytes": size_bytes,
                "submitted_at": now_ms,
                "wake_time": wait_until
            }
            cg["wait_queue"].append(bio_entry)
            self.events.append({
                "op": "SUBMIT_BIO",
                "bio_id": bio_id,
                "cgroup_id": cg_id,
                "status": "THROTTLED_QUEUED",
                "queue_len": len(cg["wait_queue"]),
                "wake_time": wait_until
            })
        else:
            cg["bytes_disp"][op] += size_bytes
            cg["io_disp"][op] += 1
            self.dispatched_count += 1
            self.events.append({
                "op": "SUBMIT_BIO",
                "bio_id": bio_id,
                "cgroup_id": cg_id,
                "status": "DISPATCHED_IMMEDIATELY",
                "dispatched_at": now_ms
            })

    def advance_time(self, new_time_ms):
        self.current_time_ms = new_time_ms
        for cg_id, cg in self.cgroups.items():
            self._process_wait_queue(cg, new_time_ms)

    def _process_wait_queue(self, cg, now_ms):
        self._refresh_slice(cg, now_ms)
        while cg["wait_queue"]:
            head = cg["wait_queue"][0]
            op = head["op"]
            size_bytes = head["size_bytes"]

            bps_limit = cg["rbps"] if op == "READ" else cg["wbps"]
            iops_limit = cg["riops"] if op == "READ" else cg["wiops"]

            bps_unlimited = (bps_limit == 0)
            iops_unlimited = (iops_limit == 0)

            slice_duration_sec = self.slice_window_ms / 1000.0
            bps_slice_budget = math.ceil(bps_limit * slice_duration_sec) if not bps_unlimited else float('inf')
            iops_slice_budget = math.ceil(iops_limit * slice_duration_sec) if not iops_unlimited else float('inf')

            rem_bytes = bps_slice_budget - cg["bytes_disp"][op]
            rem_iops = iops_slice_budget - cg["io_disp"][op]

            if (bps_unlimited or size_bytes <= rem_bytes) and (iops_unlimited or 1 <= rem_iops):
                cg["wait_queue"].pop(0)
                cg["bytes_disp"][op] += size_bytes
                cg["io_disp"][op] += 1
                self.dispatched_count += 1
                self.events.append({
                    "op": "WAKE_DISPATCH",
                    "bio_id": head["bio_id"],
                    "cgroup_id": cg["id"],
                    "status": "DISPATCHED_FROM_QUEUE",
                    "dispatched_at": now_ms,
                    "delay_ms": now_ms - head["submitted_at"]
                })
            else:
                break

    def run_commands(self, commands):
        for cmd in commands:
            op = cmd.get("op")
            if op == "SUBMIT_BIO":
                self.submit_bio(
                    cmd["bio_id"],
                    cmd["cgroup_id"],
                    cmd["direction"],
                    cmd["size_bytes"],
                    cmd.get("timestamp_ms", self.current_time_ms)
                )
            elif op == "ADVANCE_TIME":
                self.advance_time(cmd["new_time_ms"])

    def get_result(self):
        cg_states = {}
        for cid, cg in self.cgroups.items():
            cg_states[cid] = {
                "remaining_wait_queue": len(cg["wait_queue"]),
                "current_slice": [cg["slice_start"], cg["slice_end"]],
                "bytes_disp": dict(cg["bytes_disp"]),
                "io_disp": dict(cg["io_disp"])
            }

        return {
            "current_time_ms": self.current_time_ms,
            "dispatched_count": self.dispatched_count,
            "throttled_count": self.throttled_count,
            "cgroups": cg_states,
            "events": self.events
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    commands = data.get("commands", [])

    engine = BlkThrottleEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
