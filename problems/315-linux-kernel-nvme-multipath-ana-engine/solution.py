import sys
import os
import json

# ANA States
ANA_OPTIMIZED       = "OPTIMIZED"
ANA_NON_OPTIMIZED   = "NON_OPTIMIZED"
ANA_INACCESSIBLE    = "INACCESSIBLE"
ANA_PERSISTENT_LOSS = "PERSISTENT_LOSS"
ANA_CHANGE          = "CHANGE"

class NVMeMultipathEngine:
    def __init__(self, config):
        self.iopolicy = config.get("iopolicy", "round-robin")
        self.max_retries = config.get("max_retries", 3)
        self.controllers = {}
        for c in config.get("controllers", []):
            cid = c["ctrl_id"]
            self.controllers[cid] = {
                "ctrl_id": cid,
                "ana_state": c.get("ana_state", ANA_OPTIMIZED),
                "inflight": 0,
                "total_ios": 0,
                "failed_ios": 0
            }

        self.rr_index = 0
        self.requeue_queue = []
        self.active_ios = {}
        self.completed_ios = []
        self.history = []
        self.event_log = []
        self.stats = {
            "ios_submitted": 0,
            "ios_completed": 0,
            "ios_requeued": 0,
            "failovers": 0,
            "ios_failed_permanently": 0
        }

    def log(self, msg: str):
        self.event_log.append(msg)

    def select_path(self, req: dict):
        opt_paths = [c for c in self.controllers.values() if c["ana_state"] == ANA_OPTIMIZED]
        non_opt_paths = [c for c in self.controllers.values() if c["ana_state"] == ANA_NON_OPTIMIZED]

        candidates = opt_paths if opt_paths else non_opt_paths
        if not candidates:
            return None

        failed_paths = req.get("failed_paths", set())
        available = [c for c in candidates if c["ctrl_id"] not in failed_paths]
        if not available:
            if candidates == opt_paths and non_opt_paths:
                available = [c for c in non_opt_paths if c["ctrl_id"] not in failed_paths]
            if not available:
                available = candidates

        if self.iopolicy == "queue-depth":
            selected = min(available, key=lambda c: (c["inflight"], c["ctrl_id"]))
        else:
            selected = available[self.rr_index % len(available)]
            self.rr_index = (self.rr_index + 1) % len(available)

        return selected

    def submit_io(self, io_id: int, nsid: int = 1, slba: int = 0, nlb: int = 1) -> dict:
        self.stats["ios_submitted"] += 1
        req = {
            "io_id": io_id,
            "nsid": nsid,
            "slba": slba,
            "nlb": nlb,
            "retries": 0,
            "failed_paths": set(),
            "assigned_ctrl": None,
            "status": "IN_FLIGHT"
        }

        path = self.select_path(req)
        if path is None:
            self.stats["ios_requeued"] += 1
            req["status"] = "REQUEUED"
            self.requeue_queue.append(req)
            self.log(f"SUBMIT_IO io_id={io_id} NO_PATH -> REQUEUED")
            res = {"op": "SUBMIT_IO", "io_id": io_id, "status": "REQUEUED", "ctrl_id": None}
            self.history.append(res)
            return res

        req["assigned_ctrl"] = path["ctrl_id"]
        path["inflight"] += 1
        path["total_ios"] += 1
        self.active_ios[io_id] = req
        self.log(f"SUBMIT_IO io_id={io_id} assigned to ctrl={path['ctrl_id']} state={path['ana_state']} inflight={path['inflight']}")
        res = {"op": "SUBMIT_IO", "io_id": io_id, "status": "IN_FLIGHT", "ctrl_id": path["ctrl_id"]}
        self.history.append(res)
        return res

    def complete_io(self, io_id: int) -> dict:
        if io_id not in self.active_ios:
            res = {"op": "COMPLETE_IO", "io_id": io_id, "status": "NOT_FOUND"}
            self.history.append(res)
            return res

        req = self.active_ios.pop(io_id)
        cid = req["assigned_ctrl"]
        ctrl = self.controllers[cid]
        ctrl["inflight"] = max(0, ctrl["inflight"] - 1)
        req["status"] = "COMPLETED"
        self.stats["ios_completed"] += 1
        self.completed_ios.append({
            "io_id": io_id,
            "ctrl_id": cid,
            "retries": req["retries"],
            "status": "SUCCESS"
        })
        self.log(f"COMPLETE_IO io_id={io_id} ctrl={cid} inflight={ctrl['inflight']}")
        res = {"op": "COMPLETE_IO", "io_id": io_id, "status": "SUCCESS", "ctrl_id": cid}
        self.history.append(res)
        return res

    def fail_io_path(self, io_id: int, error_status: str = "NVME_SC_ANA_INACCESSIBLE") -> dict:
        if io_id not in self.active_ios:
            res = {"op": "FAIL_PATH", "io_id": io_id, "status": "NOT_FOUND"}
            self.history.append(res)
            return res

        req = self.active_ios.pop(io_id)
        cid = req["assigned_ctrl"]
        ctrl = self.controllers[cid]
        ctrl["inflight"] = max(0, ctrl["inflight"] - 1)
        ctrl["failed_ios"] += 1

        self.stats["failovers"] += 1
        req["failed_paths"].add(cid)
        req["retries"] += 1

        self.log(f"FAIL_PATH io_id={io_id} ctrl={cid} error={error_status} retries={req['retries']}/{self.max_retries}")

        if req["retries"] > self.max_retries:
            self.stats["ios_failed_permanently"] += 1
            req["status"] = "FAILED_EIO"
            self.completed_ios.append({
                "io_id": io_id,
                "ctrl_id": cid,
                "retries": req["retries"],
                "status": "FAILED_EIO"
            })
            self.log(f"IO_FAILED_PERMANENTLY io_id={io_id} max_retries_exceeded")
            res = {"op": "FAIL_PATH", "io_id": io_id, "status": "FAILED_EIO", "retries": req["retries"]}
            self.history.append(res)
            return res

        new_path = self.select_path(req)
        if new_path is not None:
            req["assigned_ctrl"] = new_path["ctrl_id"]
            new_path["inflight"] += 1
            new_path["total_ios"] += 1
            self.active_ios[io_id] = req
            self.log(f"FAILOVER_SUCCESS io_id={io_id} new_ctrl={new_path['ctrl_id']} state={new_path['ana_state']}")
            res = {"op": "FAIL_PATH", "io_id": io_id, "status": "FAILOVER_RETRY", "new_ctrl_id": new_path["ctrl_id"]}
            self.history.append(res)
            return res
        else:
            req["status"] = "REQUEUED"
            self.stats["ios_requeued"] += 1
            self.requeue_queue.append(req)
            self.log(f"FAILOVER_REQUEUED io_id={io_id} no alternative path currently available")
            res = {"op": "FAIL_PATH", "io_id": io_id, "status": "REQUEUED"}
            self.history.append(res)
            return res

    def set_ana_state(self, ctrl_id: int, new_state: str):
        if ctrl_id not in self.controllers:
            return
        ctrl = self.controllers[ctrl_id]
        old_state = ctrl["ana_state"]
        ctrl["ana_state"] = new_state
        self.log(f"ANA_UPDATE ctrl={ctrl_id} old={old_state} new={new_state}")
        self.history.append({"op": "ANA_UPDATE", "ctrl_id": ctrl_id, "old_state": old_state, "new_state": new_state})

    def drain_requeue(self) -> int:
        if not self.requeue_queue:
            self.history.append({"op": "DRAIN_REQUEUE", "drained": 0, "remaining": 0})
            return 0
        pending = list(self.requeue_queue)
        self.requeue_queue = []
        drained = 0
        for req in pending:
            path = self.select_path(req)
            if path is not None:
                req["assigned_ctrl"] = path["ctrl_id"]
                req["status"] = "IN_FLIGHT"
                path["inflight"] += 1
                path["total_ios"] += 1
                self.active_ios[req["io_id"]] = req
                drained += 1
                self.log(f"DRAIN_REQUEUE io_id={req['io_id']} assigned to ctrl={path['ctrl_id']}")
            else:
                self.requeue_queue.append(req)
        self.history.append({"op": "DRAIN_REQUEUE", "drained": drained, "remaining": len(self.requeue_queue)})
        return drained

def run_simulation(input_data: dict) -> dict:
    config = input_data.get("config", {})
    operations = input_data.get("operations", [])

    engine = NVMeMultipathEngine(config)

    for op_info in operations:
        op = op_info.get("op")
        if op == "SUBMIT_IO":
            io_id = op_info.get("io_id")
            nsid = op_info.get("nsid", 1)
            slba = op_info.get("slba", 0)
            nlb = op_info.get("nlb", 1)
            engine.submit_io(io_id, nsid, slba, nlb)
        elif op == "COMPLETE_IO":
            io_id = op_info.get("io_id")
            engine.complete_io(io_id)
        elif op == "FAIL_PATH":
            io_id = op_info.get("io_id")
            err = op_info.get("error_status", "NVME_SC_ANA_INACCESSIBLE")
            engine.fail_io_path(io_id, err)
        elif op == "ANA_UPDATE":
            ctrl_id = op_info.get("ctrl_id")
            new_state = op_info.get("new_state")
            engine.set_ana_state(ctrl_id, new_state)
        elif op == "DRAIN_REQUEUE":
            engine.drain_requeue()

    controllers_dump = {}
    for cid in sorted(engine.controllers.keys()):
        c = engine.controllers[cid]
        controllers_dump[str(cid)] = {
            "ana_state": c["ana_state"],
            "inflight": c["inflight"],
            "total_ios": c["total_ios"],
            "failed_ios": c["failed_ios"]
        }

    requeue_ids = [r["io_id"] for r in engine.requeue_queue]

    return {
        "stats": engine.stats,
        "controllers": controllers_dump,
        "active_ios_count": len(engine.active_ios),
        "requeue_queue": requeue_ids,
        "completed_ios": engine.completed_ios,
        "history": engine.history,
        "event_log": engine.event_log
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
