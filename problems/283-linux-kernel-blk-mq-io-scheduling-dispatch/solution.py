import sys
import json

class BlkMqEngine:
    def __init__(self, num_cpus, num_hw_queues, cpu_to_hw_map, queue_depth=16, max_sectors=128, scheduler="NONE", read_expire_us=500, write_expire_us=5000):
        self.num_cpus = num_cpus
        self.num_hw_queues = num_hw_queues
        self.cpu_to_hw_map = cpu_to_hw_map
        self.queue_depth = queue_depth
        self.max_sectors = max_sectors
        self.scheduler = scheduler
        self.read_expire_us = read_expire_us
        self.write_expire_us = write_expire_us
        
        self.plugs = {c: None for c in range(num_cpus)}
        self.sw_queues = {c: [] for c in range(num_cpus)}
        
        self.hw_queues = {}
        for h in range(num_hw_queues):
            self.hw_queues[h] = {
                "in_flight": {},
                "free_tags": set(range(queue_depth)),
                "dispatch_list": []
            }
            
        self.stats = {
            "total_bios_submitted": 0,
            "front_merges": 0,
            "back_merges": 0,
            "requests_dispatched": 0,
            "requests_completed": 0,
            "read_requests_completed": 0,
            "write_requests_completed": 0,
            "tag_starvation_events": 0,
            "completed_latencies": []
        }
        self.req_counter = 1

    def start_plug(self, cpu_id):
        if self.plugs[cpu_id] is None:
            self.plugs[cpu_id] = []
            return True
        return False

    def _try_merge_bio(self, req_list, bio):
        for req in req_list:
            if req["op"] != bio["op"]:
                continue
            if req["nr_sectors"] + bio["nr_sectors"] > self.max_sectors:
                continue
                
            if req["end_sector"] == bio["sector"]:
                req["end_sector"] += bio["nr_sectors"]
                req["nr_sectors"] += bio["nr_sectors"]
                req["bios"].append(bio["bio_id"])
                self.stats["back_merges"] += 1
                return ("BACK_MERGE", req["req_id"])
                
            if bio["sector"] + bio["nr_sectors"] == req["start_sector"]:
                req["start_sector"] = bio["sector"]
                req["nr_sectors"] += bio["nr_sectors"]
                req["bios"].insert(0, bio["bio_id"])
                self.stats["front_merges"] += 1
                return ("FRONT_MERGE", req["req_id"])
                
        return None

    def submit_bio(self, cpu_id, bio_id, op, sector, nr_sectors, timestamp):
        self.stats["total_bios_submitted"] += 1
        bio = {
            "bio_id": bio_id,
            "cpu_id": cpu_id,
            "op": op,
            "sector": sector,
            "nr_sectors": nr_sectors,
            "timestamp": timestamp
        }
        
        expire_delta = self.read_expire_us if op == "READ" else self.write_expire_us
        deadline = timestamp + expire_delta
        
        if self.plugs[cpu_id] is not None:
            merge_res = self._try_merge_bio(self.plugs[cpu_id], bio)
            if merge_res:
                return {
                    "action": merge_res[0],
                    "req_id": merge_res[1],
                    "bio_id": bio_id,
                    "target": "PLUG"
                }
            new_req = {
                "req_id": f"REQ-{self.req_counter:04d}",
                "op": op,
                "start_sector": sector,
                "end_sector": sector + nr_sectors,
                "nr_sectors": nr_sectors,
                "cpu_id": cpu_id,
                "submit_ts": timestamp,
                "deadline": deadline,
                "bios": [bio_id]
            }
            self.req_counter += 1
            self.plugs[cpu_id].append(new_req)
            return {
                "action": "PLUGGED_NEW_REQ",
                "req_id": new_req["req_id"],
                "bio_id": bio_id,
                "target": "PLUG"
            }
        else:
            merge_res = self._try_merge_bio(self.sw_queues[cpu_id], bio)
            if merge_res:
                return {
                    "action": merge_res[0],
                    "req_id": merge_res[1],
                    "bio_id": bio_id,
                    "target": "SW_QUEUE"
                }
            new_req = {
                "req_id": f"REQ-{self.req_counter:04d}",
                "op": op,
                "start_sector": sector,
                "end_sector": sector + nr_sectors,
                "nr_sectors": nr_sectors,
                "cpu_id": cpu_id,
                "submit_ts": timestamp,
                "deadline": deadline,
                "bios": [bio_id]
            }
            self.req_counter += 1
            self.sw_queues[cpu_id].append(new_req)
            return {
                "action": "QUEUED_SW",
                "req_id": new_req["req_id"],
                "bio_id": bio_id,
                "target": "SW_QUEUE"
            }

    def finish_plug(self, cpu_id):
        if self.plugs[cpu_id] is None:
            return 0
        reqs = self.plugs[cpu_id]
        count = len(reqs)
        self.sw_queues[cpu_id].extend(reqs)
        self.plugs[cpu_id] = None
        return count

    def flush_sw_to_hw(self):
        moved = 0
        for c in range(self.num_cpus):
            hctx_id = self.cpu_to_hw_map[c]
            reqs = self.sw_queues[c]
            if reqs:
                self.hw_queues[hctx_id]["dispatch_list"].extend(reqs)
                moved += len(reqs)
                self.sw_queues[c] = []
        return moved

    def dispatch_hw(self, current_ts):
        self.flush_sw_to_hw()
        dispatched_events = []
        
        for h in range(self.num_hw_queues):
            hq = self.hw_queues[h]
            d_list = hq["dispatch_list"]
            if not d_list:
                continue
                
            if self.scheduler == "MQ-DEADLINE":
                expired = [r for r in d_list if r["deadline"] <= current_ts]
                if expired:
                    expired.sort(key=lambda r: (r["deadline"], r["start_sector"]))
                    non_expired = [r for r in d_list if r not in expired]
                    d_list = expired + non_expired
                else:
                    reads = sorted([r for r in d_list if r["op"] == "READ"], key=lambda r: r["start_sector"])
                    writes = sorted([r for r in d_list if r["op"] == "WRITE"], key=lambda r: r["start_sector"])
                    d_list = reads + writes

            new_d_list = []
            for req in d_list:
                if len(hq["free_tags"]) > 0:
                    tag = min(hq["free_tags"])
                    hq["free_tags"].remove(tag)
                    req["hw_tag"] = tag
                    req["hctx_id"] = h
                    hq["in_flight"][tag] = req
                    self.stats["requests_dispatched"] += 1
                    dispatched_events.append({
                        "req_id": req["req_id"],
                        "hctx_id": h,
                        "hw_tag": tag,
                        "op": req["op"],
                        "start_sector": req["start_sector"],
                        "sectors": req["nr_sectors"]
                    })
                else:
                    self.stats["tag_starvation_events"] += 1
                    new_d_list.append(req)
            hq["dispatch_list"] = new_d_list
            
        return dispatched_events

    def complete_request(self, hctx_id, hw_tag, complete_ts):
        hq = self.hw_queues[hctx_id]
        if hw_tag not in hq["in_flight"]:
            return None
            
        req = hq["in_flight"].pop(hw_tag)
        hq["free_tags"].add(hw_tag)
        
        latency = complete_ts - req["submit_ts"]
        self.stats["requests_completed"] += 1
        if req["op"] == "READ":
            self.stats["read_requests_completed"] += 1
        else:
            self.stats["write_requests_completed"] += 1
        self.stats["completed_latencies"].append(latency)
        
        return {
            "req_id": req["req_id"],
            "hctx_id": hctx_id,
            "hw_tag": hw_tag,
            "latency_us": latency,
            "bios_completed": req["bios"]
        }

    def get_snapshot(self):
        hw_status = {}
        for h in range(self.num_hw_queues):
            hq = self.hw_queues[h]
            hw_status[f"hctx_{h}"] = {
                "in_flight_count": len(hq["in_flight"]),
                "free_tags_count": len(hq["free_tags"]),
                "pending_dispatch_count": len(hq["dispatch_list"]),
                "active_tags": sorted(list(hq["in_flight"].keys()))
            }
            
        sw_status = {}
        for c in range(self.num_cpus):
            sw_status[f"cpu_{c}"] = {
                "plugged_count": len(self.plugs[c]) if self.plugs[c] is not None else 0,
                "is_plugged": self.plugs[c] is not None,
                "sw_queue_count": len(self.sw_queues[c])
            }
            
        avg_lat = round(sum(self.stats["completed_latencies"]) / len(self.stats["completed_latencies"]), 2) if self.stats["completed_latencies"] else 0.0
        
        return {
            "sw_queues": sw_status,
            "hw_queues": hw_status,
            "metrics": {
                "total_bios_submitted": self.stats["total_bios_submitted"],
                "front_merges": self.stats["front_merges"],
                "back_merges": self.stats["back_merges"],
                "total_merges": self.stats["front_merges"] + self.stats["back_merges"],
                "requests_dispatched": self.stats["requests_dispatched"],
                "requests_completed": self.stats["requests_completed"],
                "read_requests_completed": self.stats["read_requests_completed"],
                "write_requests_completed": self.stats["write_requests_completed"],
                "tag_starvation_events": self.stats["tag_starvation_events"],
                "avg_latency_us": avg_lat
            }
        }

def run_simulation(req):
    cfg = req.get("config", {})
    engine = BlkMqEngine(
        num_cpus=cfg.get("num_cpus", 4),
        num_hw_queues=cfg.get("num_hw_queues", 2),
        cpu_to_hw_map=cfg.get("cpu_to_hw_map", [0, 0, 1, 1]),
        queue_depth=cfg.get("queue_depth", 16),
        max_sectors=cfg.get("max_sectors", 128),
        scheduler=cfg.get("scheduler", "NONE"),
        read_expire_us=cfg.get("read_expire_us", 500),
        write_expire_us=cfg.get("write_expire_us", 5000)
    )
    
    logs = []
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "START_PLUG":
            c_id = op_item["cpu_id"]
            success = engine.start_plug(c_id)
            logs.append({"step": step, "op": op, "cpu_id": c_id, "success": success})
            
        elif op == "SUBMIT_BIO":
            res = engine.submit_bio(
                cpu_id=op_item["cpu_id"],
                bio_id=op_item["bio_id"],
                op=op_item["type"],
                sector=op_item["sector"],
                nr_sectors=op_item["nr_sectors"],
                timestamp=op_item["timestamp"]
            )
            logs.append({"step": step, "op": op, **res})
            
        elif op == "FINISH_PLUG":
            c_id = op_item["cpu_id"]
            flushed = engine.finish_plug(c_id)
            logs.append({"step": step, "op": op, "cpu_id": c_id, "flushed_requests": flushed})
            
        elif op == "DISPATCH_HW":
            ts = op_item.get("timestamp", 0)
            dispatched = engine.dispatch_hw(ts)
            logs.append({"step": step, "op": op, "timestamp": ts, "dispatched": dispatched})
            
        elif op == "COMPLETE_REQUEST":
            h_id = op_item["hctx_id"]
            tag = op_item["hw_tag"]
            ts = op_item["timestamp"]
            res = engine.complete_request(h_id, tag, ts)
            logs.append({"step": step, "op": op, "completed": res})
            
        elif op == "GET_SNAPSHOT":
            snap = engine.get_snapshot()
            logs.append({"step": step, "op": op, "snapshot": snap})
            
    final_snap = engine.get_snapshot()
    return {
        "operations_log": logs,
        "final_state": final_snap
    }

def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    raw_in = sys.stdin.read().strip()
    if not raw_in:
        return
        
    req = json.loads(raw_in)
    res = run_simulation(req)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
