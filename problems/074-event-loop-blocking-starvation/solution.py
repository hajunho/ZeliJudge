import sys

class NaiveEventLoop:
    def __init__(self, max_wait_ticks):
        self.max_wait_ticks = max_wait_ticks
        self.current_tick = 0
        self.queue = []  # [{id, type, cost, arrival_tick}]
        self.current_task = None  # {id, type, cost, remaining_ticks}
        self.completed_count = 0
        self.timed_out_count = 0
        self.total_requests = 0

    def enqueue(self, req_id, req_type, cost):
        self.total_requests += 1
        self.queue.append({
            "id": req_id,
            "type": req_type,
            "cost": cost,
            "arrival_tick": self.current_tick
        })

    def run_ticks(self, num_ticks):
        for _ in range(num_ticks):
            # 1. If currently executing task, progress it
            if self.current_task is not None:
                self.current_task["remaining_ticks"] -= 1
                if self.current_task["remaining_ticks"] <= 0:
                    self.completed_count += 1
                    self.current_task = None

            # 2. If idle, pick next task from queue
            if self.current_task is None:
                while self.queue:
                    candidate = self.queue.pop(0)
                    wait_time = self.current_tick - candidate["arrival_tick"]
                    if wait_time > self.max_wait_ticks:
                        self.timed_out_count += 1
                        continue
                    # Start candidate
                    self.current_task = {
                        "id": candidate["id"],
                        "type": candidate["type"],
                        "cost": candidate["cost"],
                        "remaining_ticks": candidate["cost"]
                    }
                    self.current_task["remaining_ticks"] -= 1
                    if self.current_task["remaining_ticks"] <= 0:
                        self.completed_count += 1
                        self.current_task = None
                    break

            self.current_tick += 1

    def get_busy_str(self):
        if self.current_task is not None:
            return f"{self.current_task['id']}({self.current_task['type']},REM:{self.current_task['remaining_ticks']})"
        return "IDLE"

    def check_health(self):
        if self.current_task is not None and self.current_task["type"] in ("HEAVY_CPU", "SYNC_IO"):
            return f"PROBE_FAILED (BLOCKED_BY_{self.current_task['type']})"
        return "PROBE_OK"


class TunedEventLoop:
    def __init__(self, max_wait_ticks, worker_pool_size):
        self.max_wait_ticks = max_wait_ticks
        self.worker_pool_size = worker_pool_size
        self.current_tick = 0
        self.main_queue = []  # [{id, type, cost, arrival_tick}]
        self.main_task = None  # {id, type, cost, remaining_ticks}
        self.active_workers = []  # [{id, type, remaining_ticks}]
        self.worker_queue = []  # [{id, type, cost}]
        self.kernel_async_io = []  # [{id, remaining_ticks}]
        self.completed_count = 0
        self.timed_out_count = 0
        self.total_requests = 0

    def enqueue(self, req_id, req_type, cost):
        self.total_requests += 1
        self.main_queue.append({
            "id": req_id,
            "type": req_type,
            "cost": cost,
            "arrival_tick": self.current_tick
        })

    def run_ticks(self, num_ticks):
        for _ in range(num_ticks):
            # 1. Background Worker Pool progress
            finished_workers = []
            for w in self.active_workers:
                w["remaining_ticks"] -= 1
                if w["remaining_ticks"] <= 0:
                    finished_workers.append(w)
            for w in finished_workers:
                self.active_workers.remove(w)
                self.completed_count += 1

            # Dispatch queued worker tasks if slots available
            while self.worker_queue and len(self.active_workers) < self.worker_pool_size:
                task = self.worker_queue.pop(0)
                self.active_workers.append({
                    "id": task["id"],
                    "type": task["type"],
                    "remaining_ticks": task["cost"]
                })

            # 2. Kernel Async I/O progress
            finished_io = []
            for io in self.kernel_async_io:
                io["remaining_ticks"] -= 1
                if io["remaining_ticks"] <= 0:
                    finished_io.append(io)
            for io in finished_io:
                self.kernel_async_io.remove(io)
                self.completed_count += 1

            # 3. Main Event Loop Thread progress
            if self.main_task is not None:
                self.main_task["remaining_ticks"] -= 1
                if self.main_task["remaining_ticks"] <= 0:
                    # Dispatch or finish
                    m_type = self.main_task["type"]
                    if m_type == "LIGHT":
                        self.completed_count += 1
                    elif m_type == "HEAVY_CPU":
                        # Offload to worker pool
                        if len(self.active_workers) < self.worker_pool_size:
                            self.active_workers.append({
                                "id": self.main_task["id"],
                                "type": m_type,
                                "remaining_ticks": self.main_task["cost"]
                            })
                        else:
                            self.worker_queue.append({
                                "id": self.main_task["id"],
                                "type": m_type,
                                "cost": self.main_task["cost"]
                            })
                    elif m_type == "SYNC_IO":
                        # Offload to Kernel Non-blocking Async I/O
                        self.kernel_async_io.append({
                            "id": self.main_task["id"],
                            "remaining_ticks": self.main_task["cost"]
                        })
                    self.main_task = None

            # 4. If Main Thread idle, pick next task from main_queue
            if self.main_task is None:
                while self.main_queue:
                    candidate = self.main_queue.pop(0)
                    wait_time = self.current_tick - candidate["arrival_tick"]
                    if wait_time > self.max_wait_ticks:
                        self.timed_out_count += 1
                        continue
                    # Main thread takes 1 tick to execute or dispatch
                    self.main_task = {
                        "id": candidate["id"],
                        "type": candidate["type"],
                        "cost": candidate["cost"],
                        "remaining_ticks": 1
                    }
                    self.main_task["remaining_ticks"] -= 1
                    if self.main_task["remaining_ticks"] <= 0:
                        m_type = self.main_task["type"]
                        if m_type == "LIGHT":
                            self.completed_count += 1
                        elif m_type == "HEAVY_CPU":
                            if len(self.active_workers) < self.worker_pool_size:
                                self.active_workers.append({
                                    "id": self.main_task["id"],
                                    "type": m_type,
                                    "remaining_ticks": self.main_task["cost"]
                                })
                            else:
                                self.worker_queue.append({
                                    "id": self.main_task["id"],
                                    "type": m_type,
                                    "cost": self.main_task["cost"]
                                })
                        elif m_type == "SYNC_IO":
                            self.kernel_async_io.append({
                                "id": self.main_task["id"],
                                "remaining_ticks": self.main_task["cost"]
                            })
                        self.main_task = None
                    break

            self.current_tick += 1

    def get_busy_str(self):
        if self.main_task is not None:
            return f"{self.main_task['id']}({self.main_task['type']},REM:{self.main_task['remaining_ticks']})"
        return "IDLE"

    def check_health(self):
        # Tuned engine never blocks the main event loop
        return "PROBE_OK"


def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    max_wait_ticks = 10
    worker_pool_size = 4
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "MAX_WAIT_TICKS":
                max_wait_ticks = int(parts[1])
            elif parts[0] == "WORKER_POOL_SIZE":
                worker_pool_size = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    naive = NaiveEventLoop(max_wait_ticks)
    tuned = TunedEventLoop(max_wait_ticks, worker_pool_size)

    out_lines = []

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "ENQUEUE_REQ":
            req_id = act[1]
            req_type = act[2]
            cost = int(act[3]) if len(act) > 3 else 1
            naive.enqueue(req_id, req_type, cost)
            tuned.enqueue(req_id, req_type, cost)

            if req_type == "LIGHT":
                out_lines.append(f"ACT {act_idx} ENQUEUE_REQ ID:{req_id} TYPE:LIGHT")
            else:
                out_lines.append(f"ACT {act_idx} ENQUEUE_REQ ID:{req_id} TYPE:{req_type} COST:{cost}")

        elif cmd == "RUN_TICKS":
            ticks = int(act[1])
            naive.run_ticks(ticks)
            tuned.run_ticks(ticks)

            n_busy = naive.get_busy_str()
            t_busy = tuned.get_busy_str()

            out_lines.append(f"ACT {act_idx} RUN_TICKS {ticks}")
            out_lines.append(f"  NAIVE: TICK:{naive.current_tick} BUSY:{n_busy} QUEUE_WAITING:{len(naive.queue)} COMPLETED:{naive.completed_count} TIMED_OUT:{naive.timed_out_count}")
            out_lines.append(f"  TUNED: TICK:{tuned.current_tick} BUSY:{t_busy} WORKERS_ACTIVE:{len(tuned.active_workers)}/{worker_pool_size} QUEUE_WAITING:{len(tuned.main_queue)} COMPLETED:{tuned.completed_count} TIMED_OUT:{tuned.timed_out_count}")

        elif cmd == "CHECK_HEALTH":
            n_probe = naive.check_health()
            t_probe = tuned.check_health()

            out_lines.append(f"ACT {act_idx} CHECK_HEALTH")
            out_lines.append(f"  NAIVE: PROBE:{n_probe} QUEUE_WAITING:{len(naive.queue)} TIMED_OUT:{naive.timed_out_count}")
            out_lines.append(f"  TUNED: PROBE:{t_probe} QUEUE_WAITING:{len(tuned.main_queue)} TIMED_OUT:{tuned.timed_out_count}")

    # Summary
    n_rate = (naive.timed_out_count / naive.total_requests * 100.0) if naive.total_requests > 0 else 0.0
    t_rate = (tuned.timed_out_count / tuned.total_requests * 100.0) if tuned.total_requests > 0 else 0.0
    saved = naive.timed_out_count - tuned.timed_out_count
    reduction = (saved / naive.timed_out_count * 100.0) if naive.timed_out_count > 0 else 0.0

    out_lines.append(f"SUMMARY TOTAL_REQUESTS:{naive.total_requests}")
    out_lines.append(f"SUMMARY NAIVE COMPLETED:{naive.completed_count} TIMED_OUT:{naive.timed_out_count} TIMEOUT_RATE:{n_rate:.2f}%")
    out_lines.append(f"SUMMARY TUNED COMPLETED:{tuned.completed_count} TIMED_OUT:{tuned.timed_out_count} TIMEOUT_RATE:{t_rate:.2f}%")
    out_lines.append(f"SUMMARY TIMEOUT_REDUCTION:{reduction:.2f}%")
    out_lines.append("SUMMARY EVENT_LOOP_VERDICT: TUNED_OFFLOADING_PREVENTS_STARVATION")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
