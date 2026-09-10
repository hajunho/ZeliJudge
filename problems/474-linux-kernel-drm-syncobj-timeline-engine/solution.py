import sys
import json

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

class DrmSyncobjTimelineEngine:
    def __init__(self, config=None):
        self.config = config or {}
        self.syncobjs = {}
        self.engines = {
            "RENDER": [],
            "COMPUTE": [],
            "COPY": []
        }
        self.active_jobs = {
            "RENDER": None,
            "COMPUTE": None,
            "COPY": None
        }
        self.current_cycles = 0
        self.completed_jobs = []
        self.stats = {
            "total_jobs_submitted": 0,
            "total_jobs_completed": 0,
            "total_fence_signals": 0,
            "total_cycles": 0,
            "pipeline_stalls": 0
        }

    def create_syncobj(self, handle, initial_point=0):
        self.syncobjs[handle] = {
            "handle": handle,
            "point": initial_point
        }

    def reset_syncobj(self, handle):
        if handle in self.syncobjs:
            self.syncobjs[handle]["point"] = 0

    def cpu_signal(self, handle, point):
        if handle in self.syncobjs:
            obj = self.syncobjs[handle]
            if point > obj["point"]:
                obj["point"] = point
                self.stats["total_fence_signals"] += 1

    def transfer_point(self, src_handle, dst_handle, point=None):
        if src_handle in self.syncobjs and dst_handle in self.syncobjs:
            p = point if point is not None else self.syncobjs[src_handle]["point"]
            if p > self.syncobjs[dst_handle]["point"]:
                self.syncobjs[dst_handle]["point"] = p
                self.stats["total_fence_signals"] += 1

    def submit_job(self, job_id, engine, execution_cycles, wait_dependencies=None, signal_fences=None):
        job = {
            "job_id": job_id,
            "engine": engine,
            "execution_cycles": execution_cycles,
            "remaining_cycles": execution_cycles,
            "wait_dependencies": wait_dependencies or [],
            "signal_fences": signal_fences or [],
            "status": "QUEUED",
            "submitted_at": self.current_cycles,
            "started_at": None,
            "completed_at": None
        }
        self.engines[engine].append(job)
        self.stats["total_jobs_submitted"] += 1

    def _can_execute(self, job):
        for dep in job["wait_dependencies"]:
            h = dep["handle"]
            p = dep["point"]
            if self.syncobjs.get(h, {}).get("point", 0) < p:
                return False
        return True

    def advance_cycles(self, delta_cycles):
        for _ in range(delta_cycles):
            self.current_cycles += 1
            self.stats["total_cycles"] += 1

            for eng_name in ("RENDER", "COMPUTE", "COPY"):
                active = self.active_jobs[eng_name]
                if active is None:
                    if self.engines[eng_name]:
                        cand = self.engines[eng_name][0]
                        if self._can_execute(cand):
                            self.engines[eng_name].pop(0)
                            cand["status"] = "EXECUTING"
                            cand["started_at"] = self.current_cycles
                            self.active_jobs[eng_name] = cand
                            active = cand
                        else:
                            cand["status"] = "WAITING_ON_FENCE"
                            self.stats["pipeline_stalls"] += 1

                if active is not None:
                    active["remaining_cycles"] -= 1
                    if active["remaining_cycles"] == 0:
                        active["status"] = "COMPLETED"
                        active["completed_at"] = self.current_cycles
                        self.completed_jobs.append(active["job_id"])
                        self.stats["total_jobs_completed"] += 1

                        for sig in active["signal_fences"]:
                            h = sig["handle"]
                            p = sig["point"]
                            if h in self.syncobjs:
                                if p > self.syncobjs[h]["point"]:
                                    self.syncobjs[h]["point"] = p
                                    self.stats["total_fence_signals"] += 1

                        self.active_jobs[eng_name] = None

    def timeline_wait(self, points, wait_all=True, timeout_cycles=1000):
        start = self.current_cycles
        while self.current_cycles - start < timeout_cycles:
            satisfied = []
            for item in points:
                curr = self.syncobjs.get(item["handle"], {}).get("point", 0)
                satisfied.append(curr >= item["point"])
            
            if wait_all and all(satisfied):
                return {"status": "SIGNALED", "waited_cycles": self.current_cycles - start}
            elif (not wait_all) and any(satisfied):
                return {"status": "SIGNALED", "waited_cycles": self.current_cycles - start}
            
            self.advance_cycles(1)

        return {"status": "TIMEOUT", "waited_cycles": timeout_cycles}

    def query_timeline(self, handles):
        res = {}
        for h in handles:
            res[str(h)] = self.syncobjs.get(h, {}).get("point", 0)
        return res

    def run(self, ops):
        results = []
        for idx, op in enumerate(ops):
            t = op["type"]
            if t == "CREATE_SYNCOBJ":
                self.create_syncobj(op["handle"], op.get("initial_point", 0))
                results.append({
                    "op_index": idx,
                    "type": t,
                    "handle": op["handle"],
                    "initial_point": op.get("initial_point", 0),
                    "status": "CREATED"
                })
            elif t == "RESET_SYNCOBJ":
                self.reset_syncobj(op["handle"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "handle": op["handle"],
                    "status": "RESET"
                })
            elif t == "TRANSFER_POINT":
                self.transfer_point(op["src_handle"], op["dst_handle"], op.get("point"))
                results.append({
                    "op_index": idx,
                    "type": t,
                    "src_handle": op["src_handle"],
                    "dst_handle": op["dst_handle"],
                    "dst_point": self.syncobjs[op["dst_handle"]]["point"]
                })
            elif t == "CPU_SIGNAL":
                self.cpu_signal(op["handle"], op["point"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "handle": op["handle"],
                    "point": op["point"],
                    "current_point": self.syncobjs[op["handle"]]["point"]
                })
            elif t == "SUBMIT_JOB":
                self.submit_job(
                    op["job_id"],
                    op["engine"],
                    op["execution_cycles"],
                    op.get("wait_dependencies"),
                    op.get("signal_fences")
                )
                results.append({
                    "op_index": idx,
                    "type": t,
                    "job_id": op["job_id"],
                    "engine": op["engine"],
                    "status": "QUEUED"
                })
            elif t == "ADVANCE_CYCLES":
                self.advance_cycles(op["cycles"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "advanced_cycles": op["cycles"],
                    "current_cycles": self.current_cycles,
                    "completed_jobs": list(self.completed_jobs)
                })
            elif t == "TIMELINE_WAIT":
                wait_res = self.timeline_wait(
                    op["points"],
                    op.get("wait_all", True),
                    op.get("timeout_cycles", 100)
                )
                results.append({
                    "op_index": idx,
                    "type": t,
                    **wait_res,
                    "current_cycles": self.current_cycles
                })
            elif t == "QUERY_TIMELINE":
                q_res = self.query_timeline(op["handles"])
                results.append({
                    "op_index": idx,
                    "type": t,
                    "points": q_res
                })

        return {
            "operation_results": results,
            "final_timeline": {str(k): v["point"] for k, v in self.syncobjs.items()},
            "summary": {
                "total_operations": len(ops),
                "total_cycles": self.current_cycles,
                "completed_jobs_count": len(self.completed_jobs),
                "stats": self.stats
            }
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    engine = DrmSyncobjTimelineEngine(data.get("config", {}))
    output = engine.run(data.get("operations", []))
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
