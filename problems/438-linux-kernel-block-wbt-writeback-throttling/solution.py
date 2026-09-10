# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #438 Solution:
Linux Kernel Block Layer: block/blk-wbt.c Writeback Throttling (WBT) & Dynamic Read Latency-Tracking Scaler
(block/blk-wbt.c, block/blk-wbt.h, include/linux/blk-mq.h)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class WbtEngine:
    def __init__(self, config):
        self.target_lat_us = config.get("target_lat_us", 2000)
        self.min_depth = config.get("min_depth", 2)
        self.max_depth = config.get("max_depth", 32)
        self.step_scale = config.get("step_scale", 2)
        
        self.cur_depth = self.max_depth
        self.inflight_reads = 0
        self.inflight_sync_writes = 0
        self.inflight_wb_writes = 0
        
        self.active_bios = {}
        self.pending_wb_queue = []
        self.window_samples = []
        
        self.total_reads_completed = 0
        self.total_wb_completed = 0
        self.total_throttled_events = 0
        self.scale_down_count = 0
        self.scale_up_count = 0
        self.window_count = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "SUBMIT_BIO":
            return self._submit_bio(cmd)
        elif op == "COMPLETE_BIO":
            return self._complete_bio(cmd)
        elif op == "STEP_WINDOW":
            return self._step_window(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _submit_bio(self, cmd):
        bio_id = cmd["bio_id"]
        bio_type = cmd["type"]
        timestamp = cmd.get("timestamp_us", 0)
        sectors = cmd.get("sectors", 8)
        
        bio_entry = {
            "bio_id": bio_id,
            "type": bio_type,
            "timestamp_us": timestamp,
            "sectors": sectors
        }
        self.active_bios[bio_id] = bio_entry
        
        if bio_type == "READ":
            self.inflight_reads += 1
            return {
                "op": "SUBMIT_BIO",
                "bio_id": bio_id,
                "type": bio_type,
                "status": "SUBMITTED_IMMEDIATE",
                "inflight_reads": self.inflight_reads
            }
        elif bio_type == "SYNC_WRITE":
            self.inflight_sync_writes += 1
            return {
                "op": "SUBMIT_BIO",
                "bio_id": bio_id,
                "type": bio_type,
                "status": "SUBMITTED_SYNC",
                "inflight_sync_writes": self.inflight_sync_writes
            }
        elif bio_type == "WB_WRITE":
            if self.inflight_wb_writes < self.cur_depth:
                self.inflight_wb_writes += 1
                return {
                    "op": "SUBMIT_BIO",
                    "bio_id": bio_id,
                    "type": bio_type,
                    "status": "SUBMITTED_WB",
                    "inflight_wb_writes": self.inflight_wb_writes,
                    "cur_depth": self.cur_depth
                }
            else:
                self.pending_wb_queue.append(bio_id)
                self.total_throttled_events += 1
                return {
                    "op": "SUBMIT_BIO",
                    "bio_id": bio_id,
                    "type": bio_type,
                    "status": "THROTTLED_WAITING",
                    "pending_position": len(self.pending_wb_queue),
                    "cur_depth": self.cur_depth
                }
        else:
            return {"op": "SUBMIT_BIO", "bio_id": bio_id, "status": "INVALID_TYPE"}

    def _complete_bio(self, cmd):
        bio_id = cmd["bio_id"]
        completion_us = cmd.get("completion_us", 0)
        
        if bio_id not in self.active_bios:
            return {"op": "COMPLETE_BIO", "bio_id": bio_id, "status": "NOT_FOUND"}
            
        entry = self.active_bios.pop(bio_id)
        bio_type = entry["type"]
        duration_us = max(0, completion_us - entry["timestamp_us"])
        
        dispatched_bio_id = None
        
        if bio_type == "READ":
            self.inflight_reads = max(0, self.inflight_reads - 1)
            self.window_samples.append(duration_us)
            self.total_reads_completed += 1
        elif bio_type == "SYNC_WRITE":
            self.inflight_sync_writes = max(0, self.inflight_sync_writes - 1)
        elif bio_type == "WB_WRITE":
            self.inflight_wb_writes = max(0, self.inflight_wb_writes - 1)
            self.total_wb_completed += 1
            
            if self.pending_wb_queue and self.inflight_wb_writes < self.cur_depth:
                dispatched_bio_id = self.pending_wb_queue.pop(0)
                self.inflight_wb_writes += 1
                
        return {
            "op": "COMPLETE_BIO",
            "bio_id": bio_id,
            "type": bio_type,
            "duration_us": duration_us,
            "dispatched_bio_id": dispatched_bio_id,
            "inflight_wb_writes": self.inflight_wb_writes,
            "pending_wb_count": len(self.pending_wb_queue)
        }

    def _step_window(self, cmd):
        self.window_count += 1
        sample_count = len(self.window_samples)
        old_depth = self.cur_depth
        dispatched_bios = []
        
        if sample_count == 0:
            action = "WINDOW_IDLE"
            measured_lat = 0
        else:
            self.window_samples.sort()
            p90_idx = int(sample_count * 0.9)
            if p90_idx >= sample_count:
                p90_idx = sample_count - 1
            measured_lat = self.window_samples[p90_idx]
            
            if measured_lat > self.target_lat_us:
                new_depth = max(self.min_depth, self.cur_depth // 2)
                if new_depth < self.cur_depth:
                    self.cur_depth = new_depth
                    action = "SCALED_DOWN"
                    self.scale_down_count += 1
                else:
                    action = "HELD_MIN_DEPTH"
            else:
                new_depth = min(self.max_depth, self.cur_depth + self.step_scale)
                if new_depth > self.cur_depth:
                    self.cur_depth = new_depth
                    action = "SCALED_UP"
                    self.scale_up_count += 1
                else:
                    action = "HELD_MAX_DEPTH"
                    
        while self.pending_wb_queue and self.inflight_wb_writes < self.cur_depth:
            nxt = self.pending_wb_queue.pop(0)
            self.inflight_wb_writes += 1
            dispatched_bios.append(nxt)
            
        self.window_samples.clear()
        
        return {
            "op": "STEP_WINDOW",
            "window_id": self.window_count,
            "samples_count": sample_count,
            "measured_lat_us": measured_lat,
            "target_lat_us": self.target_lat_us,
            "old_depth": old_depth,
            "new_depth": self.cur_depth,
            "action": action,
            "dispatched_bios": dispatched_bios
        }

    def _get_stats(self, cmd):
        return {
            "op": "GET_STATS",
            "cur_depth": self.cur_depth,
            "inflight_reads": self.inflight_reads,
            "inflight_sync_writes": self.inflight_sync_writes,
            "inflight_wb_writes": self.inflight_wb_writes,
            "pending_wb_count": len(self.pending_wb_queue),
            "total_reads_completed": self.total_reads_completed,
            "total_wb_completed": self.total_wb_completed,
            "total_throttled_events": self.total_throttled_events,
            "scale_down_count": self.scale_down_count,
            "scale_up_count": self.scale_up_count
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "final_cur_depth": self.cur_depth,
            "total_reads_completed": self.total_reads_completed,
            "total_wb_completed": self.total_wb_completed,
            "total_throttled_events": self.total_throttled_events,
            "scale_down_count": self.scale_down_count,
            "scale_up_count": self.scale_up_count,
            "remaining_pending_wb": len(self.pending_wb_queue)
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = WbtEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
