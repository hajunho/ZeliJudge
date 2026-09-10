# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #385: Linux Kernel Queued Spinlock (qspinlock) MCS Node & Cacheline Bouncing Engine
Implementation in Python 3.
"""
import sys
import json

class QSpinlockEngine:
    def __init__(self, config):
        self.num_cpus = config.get("num_cpus", 8)
        self.locked = 0   # 0 or 1
        self.pending = 0  # 0 or 1
        self.tail_cpu = 0 # 1-based CPU index
        self.tail_idx = 0 # nesting index (0..3)

        self.qnodes = {}
        for c in range(1, self.num_cpus + 1):
            self.qnodes[c] = {}
            for idx in range(4):
                self.qnodes[c][idx] = {
                    "cpu": c,
                    "idx": idx,
                    "locked": 0,
                    "next": None
                }

        self.current_holder = None
        self.pending_waiter = None
        self.mcs_queue = []

        self.events = []
        self.cacheline_bounces = 0
        self.ticket_equivalent_bounces = 0
        self.total_acquisitions = 0

    @property
    def lock_val(self):
        tail_val = ((self.tail_cpu << 2) | self.tail_idx) if self.tail_cpu > 0 else 0
        return self.locked | (self.pending << 8) | (tail_val << 16)

    def run_commands(self, commands):
        for cmd in commands:
            op = cmd.get("op")
            if op == "ACQUIRE":
                self._handle_acquire(cmd)
            elif op == "RELEASE":
                self._handle_release(cmd)

    def _handle_acquire(self, cmd):
        cpu = cmd["cpu"]
        idx = cmd.get("idx", 0)
        req_id = cmd["req_id"]

        if self.current_holder is not None and self.current_holder[0] == cpu and self.current_holder[1] == idx:
            self.events.append({
                "op": "ACQUIRE",
                "cpu": cpu,
                "idx": idx,
                "req_id": req_id,
                "status": "FAIL_REENTRANT_DEADLOCK"
            })
            return

        # 1. Fast Path
        if self.locked == 0 and self.pending == 0 and self.tail_cpu == 0:
            self.locked = 1
            self.current_holder = (cpu, idx, req_id)
            self.total_acquisitions += 1
            self.events.append({
                "op": "ACQUIRE",
                "cpu": cpu,
                "idx": idx,
                "req_id": req_id,
                "path": "FAST_PATH",
                "status": "ACQUIRED"
            })
            return

        # 2. Pending Path
        if self.pending == 0 and self.tail_cpu == 0:
            self.pending = 1
            self.pending_waiter = (cpu, idx, req_id)
            self.cacheline_bounces += 1
            self.events.append({
                "op": "ACQUIRE",
                "cpu": cpu,
                "idx": idx,
                "req_id": req_id,
                "path": "PENDING_PATH",
                "status": "WAITING_PENDING"
            })
            return

        # 3. MCS Queue Path
        node = self.qnodes[cpu][idx]
        node["locked"] = 1
        node["next"] = None

        prev_tail_cpu = self.tail_cpu
        prev_tail_idx = self.tail_idx

        self.tail_cpu = cpu
        self.tail_idx = idx
        waiter_entry = (cpu, idx, req_id)
        self.mcs_queue.append(waiter_entry)

        if prev_tail_cpu > 0:
            self.qnodes[prev_tail_cpu][prev_tail_idx]["next"] = (cpu, idx)
            self.events.append({
                "op": "ACQUIRE",
                "cpu": cpu,
                "idx": idx,
                "req_id": req_id,
                "path": "MCS_QUEUE",
                "status": "WAITING_MCS_LINKED",
                "linked_after": [prev_tail_cpu, prev_tail_idx]
            })
        else:
            self.events.append({
                "op": "ACQUIRE",
                "cpu": cpu,
                "idx": idx,
                "req_id": req_id,
                "path": "MCS_QUEUE",
                "status": "WAITING_MCS_HEAD"
            })

    def _handle_release(self, cmd):
        cpu = cmd["cpu"]
        idx = cmd.get("idx", 0)
        req_id = cmd["req_id"]

        if self.current_holder != (cpu, idx, req_id):
            self.events.append({
                "op": "RELEASE",
                "cpu": cpu,
                "idx": idx,
                "req_id": req_id,
                "status": "FAIL_NOT_HOLDER"
            })
            return

        num_waiters = (1 if self.pending_waiter else 0) + len(self.mcs_queue)
        self.ticket_equivalent_bounces += num_waiters * 2

        self.locked = 0
        self.current_holder = None
        self.events.append({
            "op": "RELEASE",
            "cpu": cpu,
            "idx": idx,
            "req_id": req_id,
            "status": "SUCCESS"
        })

        if self.pending_waiter is not None:
            p_cpu, p_idx, p_req = self.pending_waiter
            self.pending_waiter = None
            self.pending = 0
            self.locked = 1
            self.current_holder = (p_cpu, p_idx, p_req)
            self.total_acquisitions += 1
            self.cacheline_bounces += 1
            self.events.append({
                "op": "HANDOFF_PENDING",
                "cpu": p_cpu,
                "idx": p_idx,
                "req_id": p_req,
                "status": "ACQUIRED"
            })
            return

        if self.mcs_queue:
            head_cpu, head_idx, head_req = self.mcs_queue[0]
            self.locked = 1
            self.current_holder = (head_cpu, head_idx, head_req)
            self.total_acquisitions += 1
            self.mcs_queue.pop(0)

            succ = self.qnodes[head_cpu][head_idx]["next"]
            if succ is not None:
                succ_cpu, succ_idx = succ
                self.qnodes[succ_cpu][succ_idx]["locked"] = 0
                self.cacheline_bounces += 1

            if not self.mcs_queue:
                self.tail_cpu = 0
                self.tail_idx = 0

            self.events.append({
                "op": "HANDOFF_MCS",
                "cpu": head_cpu,
                "idx": head_idx,
                "req_id": head_req,
                "status": "ACQUIRED"
            })

    def get_result(self):
        return {
            "lock_val_hex": hex(self.lock_val),
            "locked": self.locked,
            "pending": self.pending,
            "tail_cpu": self.tail_cpu,
            "tail_idx": self.tail_idx,
            "current_holder": list(self.current_holder) if self.current_holder else None,
            "pending_waiter": list(self.pending_waiter) if self.pending_waiter else None,
            "mcs_queue_len": len(self.mcs_queue),
            "cacheline_bounces": self.cacheline_bounces,
            "ticket_equivalent_bounces": self.ticket_equivalent_bounces,
            "total_acquisitions": self.total_acquisitions,
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

    engine = QSpinlockEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
