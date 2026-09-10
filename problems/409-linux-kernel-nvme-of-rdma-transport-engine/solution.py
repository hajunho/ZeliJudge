import sys
import json
from collections import deque

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class MR:
    def __init__(self, mr_id):
        self.mr_id = mr_id
        self.rkey = 0x1000 + mr_id * 0x100
        self.is_busy = False
        self.assigned_req = None

    def to_dict(self):
        return {
            "mr_id": self.mr_id,
            "rkey": hex(self.rkey),
            "is_busy": self.is_busy,
            "assigned_req": self.assigned_req
        }

class NVMeRDMAEngine:
    def __init__(self, config):
        self.queue_depth = config.get("queue_depth", 16)
        self.in_capsule_data_size = config.get("in_capsule_data_size", 4096)
        self.mr_pool_size = config.get("mr_pool_size", 8)
        self.cq_poll_budget = config.get("cq_poll_budget", 4)
        self.fabric_rtt_ms = config.get("fabric_rtt_ms", 2)
        self.target_proc_time_ms = config.get("target_proc_time_ms", 5)
        self.transfer_rate_kb_per_ms = config.get("transfer_rate_kb_per_ms", 64)
        
        # State
        self.qp_state = "IB_QPS_RTS"
        self.sq_head = 0
        self.sq_tail = 0
        self.sqhd = 0
        
        self.mrs = [MR(i) for i in range(self.mr_pool_size)]
        self.free_mrs = deque(self.mrs)
        
        # Queues
        self.pending_queue = deque()
        self.mr_wait_queue = deque()
        self.in_flight_reqs = {}
        self.cq_completions = []
        
        # Metrics
        self.total_submitted = 0
        self.in_capsule_count = 0
        self.rdma_sgl_count = 0
        self.credit_starvations = 0
        self.mr_starvations = 0
        self.completed_reqs = []
        self.event_logs = []

    def _try_submit_request(self, req, current_time):
        active_credits = self.sq_tail - self.sq_head
        if active_credits >= self.queue_depth:
            self.pending_queue.append(req)
            self.credit_starvations += 1
            self.event_logs.append({
                "time": current_time,
                "event": "CREDIT_EXHAUSTED",
                "req_id": req["req_id"],
                "active_credits": active_credits,
                "queue_depth": self.queue_depth
            })
            return False
            
        size = req["size_bytes"]
        if size <= self.in_capsule_data_size:
            self.sq_tail += 1
            self.in_capsule_count += 1
            req["mode"] = "IN_CAPSULE"
            req["mr_id"] = None
            req["rkey"] = None
            
            done_time = current_time + self.fabric_rtt_ms + self.target_proc_time_ms
            self.in_flight_reqs[req["req_id"]] = req
            self.cq_completions.append((done_time, req["req_id"], "SUCCESS"))
            self.cq_completions.sort(key=lambda x: (x[0], x[1]))
            
            self.event_logs.append({
                "time": current_time,
                "event": "POST_SEND_IN_CAPSULE",
                "req_id": req["req_id"],
                "sq_tail": self.sq_tail,
                "size_bytes": size
            })
            return True
        else:
            if not self.free_mrs:
                self.mr_wait_queue.append(req)
                self.mr_starvations += 1
                self.event_logs.append({
                    "time": current_time,
                    "event": "MR_EXHAUSTED",
                    "req_id": req["req_id"],
                    "free_mrs": 0
                })
                return False
                
            mr = self.free_mrs.popleft()
            mr.is_busy = True
            mr.assigned_req = req["req_id"]
            
            self.sq_tail += 1
            self.rdma_sgl_count += 1
            req["mode"] = "RDMA_SGL"
            req["mr_id"] = mr.mr_id
            req["rkey"] = mr.rkey
            
            transfer_delay = (size + (self.transfer_rate_kb_per_ms * 1024 - 1)) // (self.transfer_rate_kb_per_ms * 1024)
            done_time = current_time + self.fabric_rtt_ms + self.target_proc_time_ms + transfer_delay
            self.in_flight_reqs[req["req_id"]] = req
            self.cq_completions.append((done_time, req["req_id"], "SUCCESS"))
            self.cq_completions.sort(key=lambda x: (x[0], x[1]))
            
            self.event_logs.append({
                "time": current_time,
                "event": "POST_SEND_RDMA_SGL",
                "req_id": req["req_id"],
                "sq_tail": self.sq_tail,
                "mr_id": mr.mr_id,
                "rkey": hex(mr.rkey),
                "size_bytes": size
            })
            return True

    def submit_cmd(self, current_time, req_id, opcode, lba, size_bytes):
        if self.qp_state != "IB_QPS_RTS":
            self.event_logs.append({
                "time": current_time,
                "event": "SUBMIT_REJECTED_QP_ERR",
                "req_id": req_id
            })
            return
            
        req = {
            "req_id": req_id,
            "opcode": opcode,
            "lba": lba,
            "size_bytes": size_bytes,
            "submit_time": current_time
        }
        self.total_submitted += 1
        self._try_submit_request(req, current_time)

    def poll_cq(self, current_time, budget=None):
        if budget is None:
            budget = self.cq_poll_budget
            
        polled_count = 0
        remaining_completions = []
        
        for item in self.cq_completions:
            done_time, req_id, status = item
            if done_time <= current_time and polled_count < budget:
                polled_count += 1
                req = self.in_flight_reqs.pop(req_id, None)
                if req:
                    self.sq_head += 1
                    self.sqhd = self.sq_head
                    
                    if req.get("mr_id") is not None:
                        mr = self.mrs[req["mr_id"]]
                        mr.is_busy = False
                        mr.assigned_req = None
                        self.free_mrs.append(mr)
                        
                    latency = current_time - req["submit_time"]
                    self.completed_reqs.append({
                        "req_id": req_id,
                        "opcode": req["opcode"],
                        "size_bytes": req["size_bytes"],
                        "mode": req["mode"],
                        "completion_time": current_time,
                        "latency_ms": latency,
                        "status": status
                    })
                    self.event_logs.append({
                        "time": current_time,
                        "event": "CQ_COMPLETION",
                        "req_id": req_id,
                        "status": status,
                        "sq_head": self.sq_head,
                        "sqhd": self.sqhd
                    })
            else:
                remaining_completions.append(item)
                
        self.cq_completions = remaining_completions
        
        # Wakeup MR waiters first
        while self.mr_wait_queue and self.free_mrs and (self.sq_tail - self.sq_head < self.queue_depth):
            waiter_req = self.mr_wait_queue.popleft()
            self._try_submit_request(waiter_req, current_time)
            
        # Wakeup Pending queue (credits available)
        while self.pending_queue and (self.sq_tail - self.sq_head < self.queue_depth):
            waiter_req = self.pending_queue.popleft()
            if not self._try_submit_request(waiter_req, current_time):
                break

    def trigger_qp_error(self, current_time, reason="FABRIC_DISCONNECT"):
        self.qp_state = "IB_QPS_ERR"
        flushed_count = 0
        
        # Flush in-flight
        sorted_in_flight = sorted(self.in_flight_reqs.items(), key=lambda x: x[1]["submit_time"])
        for req_id, req in sorted_in_flight:
            if req.get("mr_id") is not None:
                mr = self.mrs[req["mr_id"]]
                mr.is_busy = False
                mr.assigned_req = None
                self.free_mrs.append(mr)
            self.completed_reqs.append({
                "req_id": req_id,
                "opcode": req["opcode"],
                "size_bytes": req["size_bytes"],
                "mode": req["mode"],
                "completion_time": current_time,
                "latency_ms": current_time - req["submit_time"],
                "status": "NVME_SC_TRANSPORT_ERROR"
            })
            flushed_count += 1
        self.in_flight_reqs.clear()
        self.cq_completions.clear()
        
        # Flush pending
        while self.pending_queue:
            req = self.pending_queue.popleft()
            self.completed_reqs.append({
                "req_id": req["req_id"],
                "opcode": req["opcode"],
                "size_bytes": req["size_bytes"],
                "mode": "FLUSHED",
                "completion_time": current_time,
                "latency_ms": current_time - req["submit_time"],
                "status": "NVME_SC_TRANSPORT_ERROR"
            })
            flushed_count += 1
            
        # Flush mr_wait
        while self.mr_wait_queue:
            req = self.mr_wait_queue.popleft()
            self.completed_reqs.append({
                "req_id": req["req_id"],
                "opcode": req["opcode"],
                "size_bytes": req["size_bytes"],
                "mode": "FLUSHED",
                "completion_time": current_time,
                "latency_ms": current_time - req["submit_time"],
                "status": "NVME_SC_TRANSPORT_ERROR"
            })
            flushed_count += 1
            
        self.sq_head = self.sq_tail
        self.event_logs.append({
            "time": current_time,
            "event": "QP_ERROR_FLUSH",
            "reason": reason,
            "flushed_count": flushed_count
        })

    def reconnect(self, current_time):
        self.qp_state = "IB_QPS_RTS"
        self.sq_head = 0
        self.sq_tail = 0
        self.sqhd = 0
        self.mrs = [MR(i) for i in range(self.mr_pool_size)]
        self.free_mrs = deque(self.mrs)
        self.event_logs.append({
            "time": current_time,
            "event": "QP_RECONNECTED"
        })

    def run_trace(self, trace):
        for ev in trace:
            ev_type = ev.get("type")
            t = ev.get("time", 0)
            if ev_type == "SUBMIT_CMD":
                self.submit_cmd(t, ev["req_id"], ev["opcode"], ev.get("lba", 0), ev["size_bytes"])
            elif ev_type == "POLL_CQ":
                self.poll_cq(t, ev.get("budget"))
            elif ev_type == "TRIGGER_QP_ERROR":
                self.trigger_qp_error(t, ev.get("reason", "FABRIC_DISCONNECT"))
            elif ev_type == "RECONNECT_QP":
                self.reconnect(t)
                
    def get_result(self):
        return {
            "summary": {
                "total_submitted": self.total_submitted,
                "completed_count": len(self.completed_reqs),
                "in_capsule_count": self.in_capsule_count,
                "rdma_sgl_count": self.rdma_sgl_count,
                "credit_starvations": self.credit_starvations,
                "mr_starvations": self.mr_starvations,
                "active_credits": self.sq_tail - self.sq_head,
                "free_mr_count": len(self.free_mrs),
                "qp_state": self.qp_state
            },
            "completed_requests": self.completed_reqs,
            "mr_pool_status": [mr.to_dict() for mr in self.mrs],
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = NVMeRDMAEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
