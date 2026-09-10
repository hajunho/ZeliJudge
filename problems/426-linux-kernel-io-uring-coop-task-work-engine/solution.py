import sys
import json

class IoUringCoopTaskWorkEngine:
    def __init__(self, config=None):
        config = config or {}
        self.mode = config.get("mode", "COOP")
        self.flags = set(config.get("flags", ["IORING_SETUP_COOP_TASKRUN", "IORING_SETUP_TASKRUN_FLAG"]))
        self.cq_entries = config.get("cq_entries", 16)
        
        self.sq_taskrun_flag = False
        self.pending_task_work = []
        self.cqes = []
        
        self.total_requests = 0
        self.ipis_sent = 0
        self.task_work_runs = 0
        self.cqes_generated = 0
        self.batch_flushes = 0
        
        self.task_work_logs = []
        self.event_logs = []

    def submit_async_req(self, current_time, req_id, op, data_len):
        self.total_requests += 1
        self.event_logs.append({
            "time": current_time,
            "event": "REQ_SUBMITTED",
            "req_id": req_id,
            "op": op,
            "len": data_len
        })

    def complete_async_req(self, current_time, req_id, result):
        item = {
            "req_id": req_id,
            "result": result,
            "time": current_time
        }
        
        if self.mode == "LEGACY":
            self.ipis_sent += 1
            self.task_work_runs += 1
            self.cqes.append({"req_id": req_id, "res": result})
            self.cqes_generated += 1
            self.task_work_logs.append({
                "time": current_time,
                "action": "LEGACY_IPI_TASK_WORK",
                "req_id": req_id,
                "ipi_sent": True
            })
            self.event_logs.append({
                "time": current_time,
                "event": "IPI_INTERRUPT_TRIGGERED",
                "req_id": req_id
            })
        else:
            self.pending_task_work.append(item)
            if "IORING_SETUP_TASKRUN_FLAG" in self.flags:
                self.sq_taskrun_flag = True
            self.task_work_logs.append({
                "time": current_time,
                "action": "COOP_WORK_QUEUED",
                "req_id": req_id,
                "ipi_sent": False,
                "sq_taskrun_flag": self.sq_taskrun_flag
            })
            self.event_logs.append({
                "time": current_time,
                "event": "COOP_WORK_QUEUED_NO_IPI",
                "req_id": req_id
            })

    def enter_wait(self, current_time, min_complete=1):
        if self.mode == "COOP":
            if self.pending_task_work:
                batch_count = len(self.pending_task_work)
                self.batch_flushes += 1
                self.task_work_runs += 1
                
                while self.pending_task_work:
                    item = self.pending_task_work.pop(0)
                    self.cqes.append({"req_id": item["req_id"], "res": item["result"]})
                    self.cqes_generated += 1
                    
                self.sq_taskrun_flag = False
                self.task_work_logs.append({
                    "time": current_time,
                    "action": "COOP_BATCH_DRAINED",
                    "items_drained": batch_count
                })
                self.event_logs.append({
                    "time": current_time,
                    "event": "COOP_TASK_WORK_DRAINED",
                    "count": batch_count
                })

    def user_peek_cqe(self, current_time):
        avail = len(self.cqes)
        self.event_logs.append({
            "time": current_time,
            "event": "USER_PEEK_CQE",
            "cqes_available": avail,
            "sq_taskrun_flag": self.sq_taskrun_flag
        })
        return avail

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "SUBMIT_ASYNC_REQ":
                self.submit_async_req(t, ev["req_id"], ev["op"], ev["data_len"])
            elif ev_type == "COMPLETE_ASYNC_REQ":
                self.complete_async_req(t, ev["req_id"], ev["result"])
            elif ev_type == "ENTER_WAIT":
                self.enter_wait(t, ev.get("min_complete", 1))
            elif ev_type == "USER_PEEK_CQE":
                self.user_peek_cqe(t)

    def get_result(self):
        return {
            "summary": {
                "mode": self.mode,
                "total_requests": self.total_requests,
                "ipis_sent": self.ipis_sent,
                "task_work_runs": self.task_work_runs,
                "cqes_generated": self.cqes_generated,
                "batch_flushes": self.batch_flushes,
                "pending_task_work": len(self.pending_task_work),
                "sq_taskrun_flag": self.sq_taskrun_flag
            },
            "cqes": list(self.cqes),
            "task_work_logs": self.task_work_logs,
            "event_logs": self.event_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    engine = IoUringCoopTaskWorkEngine(data.get("config", {}))
    engine.run_trace(data.get("trace", []))
    res = engine.get_result()
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
