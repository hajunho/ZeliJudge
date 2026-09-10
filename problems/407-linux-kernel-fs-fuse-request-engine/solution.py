import sys
import json
import math
import heapq
from collections import deque

class FUSERequest:
    def __init__(self, req_id, opcode, target, size_bytes=0, is_background=False, submit_time=0):
        self.req_id = req_id
        self.opcode = opcode
        self.target = target
        self.size_bytes = size_bytes
        self.is_background = is_background
        self.submit_time = submit_time
        self.dispatch_time = None
        self.completion_time = None
        self.state = "SUBMITTED"
        self.interrupted = False

class FUSESimulation:
    def __init__(self, config):
        self.max_background = config.get("max_background", 12)
        self.congestion_threshold = config.get("congestion_threshold", 9)
        self.attr_timeout = config.get("attr_timeout_ms", 100)
        self.entry_timeout = config.get("entry_timeout_ms", 100)
        self.enable_writeback_cache = config.get("enable_writeback_cache", False)
        self.enable_splice = config.get("enable_splice", False)
        self.daemon_workers = config.get("daemon_workers", 4)
        self.daemon_proc_time = config.get("daemon_proc_time_ms", 5)
        self.copy_overhead_per_kb = config.get("copy_overhead_per_kb_ms", 1)
        
        self.pending_queue = deque()
        self.interrupt_queue = deque()
        self.bg_queue = deque()
        self.processing = {}
        
        self.active_workers = 0
        self.num_background = 0
        
        self.attr_cache = {}
        self.dentry_cache = {}
        
        self.is_congested = False
        self.congestion_events = []
        
        self.events = []
        self.event_counter = 0
        self.current_time = 0
        
        self.completed_requests = []
        self.interrupted_requests = []
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_submitted = 0
        self.max_observed_bg_depth = 0
        self.max_observed_pending_depth = 0

    def schedule_event(self, time, priority, event_type, payload=None):
        heapq.heappush(self.events, (time, priority, self.event_counter, event_type, payload))
        self.event_counter += 1

    def check_congestion(self):
        total_bg = self.num_background + len(self.bg_queue)
        if total_bg >= self.congestion_threshold:
            if not self.is_congested:
                self.is_congested = True
                self.congestion_events.append({"time": self.current_time, "state": "CONGESTED", "depth": total_bg})
        else:
            if self.is_congested:
                self.is_congested = False
                self.congestion_events.append({"time": self.current_time, "state": "CLEARED", "depth": total_bg})

    def handle_submit(self, req):
        self.total_submitted += 1
        
        if req.opcode in ("FUSE_LOOKUP", "FUSE_GETATTR"):
            cache = self.dentry_cache if req.opcode == "FUSE_LOOKUP" else self.attr_cache
            if req.target in cache and self.current_time <= cache[req.target]:
                self.cache_hits += 1
                req.state = "COMPLETED"
                req.dispatch_time = self.current_time
                req.completion_time = self.current_time
                self.completed_requests.append(req)
                return
            else:
                self.cache_misses += 1
        
        if req.opcode == "FUSE_WRITE" and self.enable_writeback_cache:
            req.is_background = True
        
        if req.is_background:
            if self.num_background < self.max_background:
                self.num_background += 1
                req.state = "PENDING"
                self.pending_queue.append(req)
            else:
                req.state = "BG_WAITING"
                self.bg_queue.append(req)
        else:
            req.state = "PENDING"
            self.pending_queue.append(req)
            
        self.max_observed_bg_depth = max(self.max_observed_bg_depth, len(self.bg_queue))
        self.max_observed_pending_depth = max(self.max_observed_pending_depth, len(self.pending_queue))
        self.check_congestion()
        self.try_dispatch()

    def handle_signal_interrupt(self, target_req_id):
        for req in list(self.pending_queue):
            if req.req_id == target_req_id:
                self.pending_queue.remove(req)
                req.state = "INTERRUPTED"
                req.completion_time = self.current_time
                self.interrupted_requests.append(req)
                if req.is_background:
                    self.num_background -= 1
                    self.refill_background()
                self.check_congestion()
                return
        
        for req in list(self.bg_queue):
            if req.req_id == target_req_id:
                self.bg_queue.remove(req)
                req.state = "INTERRUPTED"
                req.completion_time = self.current_time
                self.interrupted_requests.append(req)
                self.check_congestion()
                return
        
        if target_req_id in self.processing:
            int_req = FUSERequest(
                req_id=f"int_{target_req_id}",
                opcode="FUSE_INTERRUPT",
                target=target_req_id,
                submit_time=self.current_time
            )
            self.interrupt_queue.append(int_req)
            self.try_dispatch()

    def try_dispatch(self):
        while self.active_workers < self.daemon_workers:
            if self.interrupt_queue:
                int_req = self.interrupt_queue.popleft()
                self.active_workers += 1
                int_req.dispatch_time = self.current_time
                target_id = int_req.target
                if target_id in self.processing:
                    target_req = self.processing[target_id]
                    target_req.interrupted = True
                self.schedule_event(self.current_time + 1, 0, "DAEMON_REPLY", (int_req, True))
            elif self.pending_queue:
                req = self.pending_queue.popleft()
                self.active_workers += 1
                req.state = "PROCESSING"
                req.dispatch_time = self.current_time
                self.processing[req.req_id] = req
                
                overhead = 0 if self.enable_splice else math.ceil((req.size_bytes / 1024.0) * self.copy_overhead_per_kb)
                duration = self.daemon_proc_time + overhead
                self.schedule_event(self.current_time + duration, 0, "DAEMON_REPLY", (req, False))
            else:
                break

    def handle_daemon_reply(self, payload):
        req, is_interrupt_op = payload
        self.active_workers -= 1
        
        if is_interrupt_op:
            req.state = "COMPLETED"
            req.completion_time = self.current_time
            self.try_dispatch()
            return
        
        del self.processing[req.req_id]
        
        if req.interrupted:
            req.state = "INTERRUPTED"
            req.completion_time = self.current_time
            self.interrupted_requests.append(req)
        else:
            req.state = "COMPLETED"
            req.completion_time = self.current_time
            self.completed_requests.append(req)
            
            if req.opcode == "FUSE_LOOKUP":
                self.dentry_cache[req.target] = self.current_time + self.entry_timeout
            elif req.opcode == "FUSE_GETATTR":
                self.attr_cache[req.target] = self.current_time + self.attr_timeout
                
        if req.is_background:
            self.num_background -= 1
            self.refill_background()
            
        self.check_congestion()
        self.try_dispatch()

    def refill_background(self):
        while self.num_background < self.max_background and self.bg_queue:
            bg_req = self.bg_queue.popleft()
            bg_req.state = "PENDING"
            self.num_background += 1
            self.pending_queue.append(bg_req)

    def run(self, trace):
        for item in trace:
            self.schedule_event(item["time"], 1, "TRACE_EVENT", item)
            
        while self.events:
            time, priority, _, event_type, payload = heapq.heappop(self.events)
            self.current_time = time
            
            if event_type == "TRACE_EVENT":
                kind = payload["type"]
                if kind == "SUBMIT":
                    req = FUSERequest(
                        req_id=payload["req_id"],
                        opcode=payload["opcode"],
                        target=payload["target"],
                        size_bytes=payload.get("size_bytes", 0),
                        is_background=payload.get("is_background", False),
                        submit_time=self.current_time
                    )
                    self.handle_submit(req)
                elif kind == "SIGNAL_INTERRUPT":
                    self.handle_signal_interrupt(payload["target_req_id"])
            elif event_type == "DAEMON_REPLY":
                self.handle_daemon_reply(payload)
                
        return self.generate_result()

    def generate_result(self):
        total_lat = sum(r.completion_time - r.submit_time for r in self.completed_requests)
        avg_lat = round(total_lat / len(self.completed_requests), 2) if self.completed_requests else 0.0
        
        req_results = []
        for r in sorted(self.completed_requests + self.interrupted_requests, key=lambda x: str(x.req_id)):
            req_results.append({
                "req_id": r.req_id,
                "opcode": r.opcode,
                "state": r.state,
                "latency_ms": r.completion_time - r.submit_time
            })
            
        return {
            "summary": {
                "total_simulation_time": self.current_time,
                "total_submitted": self.total_submitted,
                "completed_count": len(self.completed_requests),
                "interrupted_count": len(self.interrupted_requests),
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "avg_latency_ms": avg_lat,
                "max_bg_depth": self.max_observed_bg_depth,
                "max_pending_depth": self.max_observed_pending_depth
            },
            "congestion_events": self.congestion_events,
            "requests": req_results
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    trace = input_data.get("trace", [])
    
    sim = FUSESimulation(config)
    result = sim.run(trace)
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
