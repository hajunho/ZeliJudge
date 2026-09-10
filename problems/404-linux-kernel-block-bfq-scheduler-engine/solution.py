import sys
import json
import math
import heapq
from collections import deque

class BFQQueue:
    def __init__(self, qid, base_weight, default_budget):
        self.qid = qid
        self.base_weight = base_weight
        self.budget = default_budget
        self.allocated_budget = default_budget
        self.consumed_budget = 0
        self.vstart = 0.0
        self.vfinish = 0.0
        self.prev_vfinish = 0.0
        self.pending_requests = deque()
        self.is_active = False
        self.is_in_service = False
        
        # Low latency / weight raising
        self.is_weight_raised = False
        self.wr_until = 0
        self.wr_coeff = 1
        self.last_completion_time = None
        self.cumulative_sectors_in_burst = 0
        self.weight_raising_count = 0
        
        # Metrics
        self.total_dispatched_requests = 0
        self.total_sectors_served = 0
        self.total_wait_time = 0
        self.total_service_time = 0

    def effective_weight(self):
        if self.is_weight_raised:
            return min(1000, self.base_weight * self.wr_coeff)
        return self.base_weight

class BFQSimulation:
    def __init__(self, config):
        self.default_budget = config.get("default_budget", 256)
        self.max_budget = config.get("max_budget", 1024)
        self.min_budget = config.get("min_budget", 64)
        self.slice_idle = config.get("slice_idle", 8)
        self.enable_idling = config.get("enable_idling", True)
        self.device_speed = config.get("device_speed_sectors_per_ms", 10)
        self.switch_overhead = config.get("switch_overhead_ms", 1)
        self.enable_low_latency = config.get("enable_low_latency", True)
        self.think_time_threshold = config.get("think_time_threshold", 16)
        self.burst_sectors_threshold = config.get("burst_sectors_threshold", 128)
        self.wr_boost_factor = config.get("wr_boost_factor", 10)
        self.wr_duration = config.get("wr_duration_ms", 200)

        self.queues = {}
        self.system_vtime = 0.0
        self.current_time = 0
        self.in_service_queue = None
        self.last_served_qid = None
        
        self.is_anticipatory_idle = False
        self.idle_start_time = 0
        self.idle_timeout_gen = 0
        
        self.in_flight_req = None
        
        self.events = []
        self.event_counter = 0
        
        self.total_idle_time = 0
        self.total_switch_overhead_time = 0
        self.dispatched_order = []
        self.expiration_log = []

    def schedule_event(self, time, priority, event_type, payload=None):
        heapq.heappush(self.events, (time, priority, self.event_counter, event_type, payload))
        self.event_counter += 1

    def get_or_create_queue(self, qid, base_weight=100):
        if qid not in self.queues:
            q = BFQQueue(qid, base_weight, self.default_budget)
            self.queues[qid] = q
        return self.queues[qid]

    def trigger_weight_raising_check(self, queue, arrival_time):
        if not self.enable_low_latency:
            return
        
        is_new = False
        if queue.last_completion_time is None:
            is_new = True
        else:
            think_time = arrival_time - queue.last_completion_time
            if think_time >= self.think_time_threshold:
                is_new = True
        
        if is_new:
            if not queue.is_weight_raised:
                queue.weight_raising_count += 1
            queue.is_weight_raised = True
            queue.wr_coeff = self.wr_boost_factor
            queue.wr_until = arrival_time + self.wr_duration
            queue.cumulative_sectors_in_burst = 0

    def check_low_latency_decay(self, queue, current_time):
        if queue.is_weight_raised:
            if current_time >= queue.wr_until or queue.cumulative_sectors_in_burst >= self.burst_sectors_threshold:
                queue.is_weight_raised = False

    def activate_queue_if_needed(self, queue):
        if not queue.is_active and not queue.is_in_service:
            queue.is_active = True
            queue.vstart = max(self.system_vtime, queue.prev_vfinish)
            queue.vfinish = queue.vstart + (queue.allocated_budget / queue.effective_weight())

    def run(self, queue_configs, workload):
        for q_cfg in queue_configs:
            self.get_or_create_queue(q_cfg["qid"], q_cfg.get("weight", 100))
        
        sorted_workload = sorted(workload, key=lambda r: (r["arrival_time"], r["req_id"]))
        for req in sorted_workload:
            self.schedule_event(req["arrival_time"], 1, "ARRIVAL", req)
        
        while self.events:
            event_time, priority, _, event_type, payload = heapq.heappop(self.events)
            self.current_time = event_time
            
            if event_type == "COMPLETION":
                self.handle_completion(payload)
            elif event_type == "ARRIVAL":
                self.handle_arrival(payload)
            elif event_type == "IDLE_TIMEOUT":
                self.handle_idle_timeout(payload)
            
            self.try_dispatch()
            
        return self.generate_result()

    def handle_arrival(self, req):
        qid = req["qid"]
        queue = self.get_or_create_queue(qid)
        self.trigger_weight_raising_check(queue, self.current_time)
        queue.pending_requests.append(req)
        
        if self.is_anticipatory_idle and self.in_service_queue == queue:
            self.total_idle_time += (self.current_time - self.idle_start_time)
            self.is_anticipatory_idle = False
            self.idle_timeout_gen += 1
            return
        
        self.activate_queue_if_needed(queue)

    def handle_completion(self, payload):
        req, queue, sectors, dispatch_time = payload
        completion_time = self.current_time
        
        self.in_flight_req = None
        queue.last_completion_time = completion_time
        queue.consumed_budget += sectors
        queue.cumulative_sectors_in_burst += sectors
        queue.total_sectors_served += sectors
        queue.total_service_time += (completion_time - dispatch_time)
        
        active_weights = sum(q.effective_weight() for q in self.queues.values() if q.is_active or q.is_in_service)
        if active_weights > 0:
            self.system_vtime += (sectors / active_weights)
        
        self.check_low_latency_decay(queue, self.current_time)
        
        if queue.consumed_budget >= queue.allocated_budget:
            self.expire_queue(queue, "BUDGET_EXHAUSTED")
        elif len(queue.pending_requests) == 0:
            if self.enable_idling and self.slice_idle > 0 and (queue.is_weight_raised or not self.enable_low_latency):
                self.is_anticipatory_idle = True
                self.idle_start_time = self.current_time
                gen = self.idle_timeout_gen
                self.schedule_event(self.current_time + self.slice_idle, 2, "IDLE_TIMEOUT", (queue, gen))
            else:
                self.expire_queue(queue, "EMPTY_NO_IDLE")
        else:
            pass

    def handle_idle_timeout(self, payload):
        queue, gen = payload
        if not self.is_anticipatory_idle or gen != self.idle_timeout_gen:
            return
        
        self.total_idle_time += (self.current_time - self.idle_start_time)
        self.is_anticipatory_idle = False
        self.expire_queue(queue, "EMPTY_TIMEOUT")

    def expire_queue(self, queue, reason):
        consumed = queue.consumed_budget
        allocated = queue.allocated_budget
        
        if reason == "BUDGET_EXHAUSTED":
            new_budget = min(self.max_budget, queue.budget * 2)
        elif reason in ("EMPTY_NO_IDLE", "EMPTY_TIMEOUT"):
            if consumed < queue.budget // 2:
                new_budget = max(self.min_budget, max(consumed, queue.budget // 2))
            else:
                new_budget = queue.budget
        else:
            new_budget = queue.budget
        
        queue.budget = new_budget
        queue.allocated_budget = new_budget
        
        service_delivered = consumed
        eff_weight = queue.effective_weight()
        queue.prev_vfinish = queue.vstart + (service_delivered / eff_weight)
        
        queue.consumed_budget = 0
        queue.is_in_service = False
        self.in_service_queue = None
        
        if len(queue.pending_requests) > 0:
            queue.is_active = True
            queue.vstart = max(self.system_vtime, queue.prev_vfinish)
            queue.vfinish = queue.vstart + (queue.allocated_budget / queue.effective_weight())
        else:
            queue.is_active = False
            queue.vfinish = queue.prev_vfinish
        
        self.expiration_log.append({
            "time": self.current_time,
            "qid": queue.qid,
            "reason": reason,
            "consumed": consumed,
            "new_budget": new_budget,
            "vstart": round(queue.vstart, 4),
            "vfinish": round(queue.vfinish, 4)
        })

    def select_next_queue(self):
        active_queues = [q for q in self.queues.values() if q.is_active and len(q.pending_requests) > 0]
        if not active_queues:
            return None
        
        eligible = [q for q in active_queues if q.vstart <= self.system_vtime + 1e-9]
        if not eligible:
            min_vstart = min(q.vstart for q in active_queues)
            self.system_vtime = max(self.system_vtime, min_vstart)
            eligible = [q for q in active_queues if q.vstart <= self.system_vtime + 1e-9]
        
        eligible.sort(key=lambda q: (q.vfinish, q.qid))
        return eligible[0]

    def try_dispatch(self):
        if self.in_flight_req is not None or self.is_anticipatory_idle:
            return
        
        if self.in_service_queue is None:
            chosen = self.select_next_queue()
            if chosen is None:
                return
            
            chosen.is_in_service = True
            chosen.is_active = False
            chosen.consumed_budget = 0
            self.in_service_queue = chosen
        
        q = self.in_service_queue
        if not q.pending_requests:
            return
        
        req = q.pending_requests.popleft()
        sectors = req["sectors"]
        dispatch_time = self.current_time
        
        overhead = 0
        if self.last_served_qid is not None and self.last_served_qid != q.qid:
            overhead = self.switch_overhead
            self.total_switch_overhead_time += overhead
            
        transfer_time = math.ceil(sectors / self.device_speed)
        duration = overhead + transfer_time
        completion_time = dispatch_time + duration
        
        self.last_served_qid = q.qid
        self.in_flight_req = req
        q.total_dispatched_requests += 1
        q.total_wait_time += (dispatch_time - req["arrival_time"])
        self.dispatched_order.append(req["req_id"])
        
        payload = (req, q, sectors, dispatch_time)
        self.schedule_event(completion_time, 0, "COMPLETION", payload)

    def generate_result(self):
        total_dispatched = sum(q.total_dispatched_requests for q in self.queues.values())
        total_sectors = sum(q.total_sectors_served for q in self.queues.values())
        
        queue_metrics = {}
        for qid in sorted(self.queues.keys()):
            q = self.queues[qid]
            avg_wait = round(q.total_wait_time / q.total_dispatched_requests, 2) if q.total_dispatched_requests > 0 else 0.0
            avg_service = round(q.total_service_time / q.total_dispatched_requests, 2) if q.total_dispatched_requests > 0 else 0.0
            queue_metrics[qid] = {
                "base_weight": q.base_weight,
                "final_budget": q.budget,
                "dispatched_count": q.total_dispatched_requests,
                "total_sectors": q.total_sectors_served,
                "avg_wait_time_ms": avg_wait,
                "avg_service_time_ms": avg_service,
                "weight_raising_count": q.weight_raising_count
            }
            
        return {
            "summary": {
                "total_simulation_time": self.current_time,
                "total_dispatched_requests": total_dispatched,
                "total_sectors_served": total_sectors,
                "total_idle_time": self.total_idle_time,
                "total_switch_overhead_time": self.total_switch_overhead_time
            },
            "queue_metrics": queue_metrics,
            "expirations": self.expiration_log,
            "dispatch_order": self.dispatched_order
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    queue_configs = input_data.get("queues", [])
    workload = input_data.get("requests", [])
    
    sim = BFQSimulation(config)
    result = sim.run(queue_configs, workload)
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
