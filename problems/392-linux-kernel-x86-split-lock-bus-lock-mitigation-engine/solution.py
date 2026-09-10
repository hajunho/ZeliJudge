# -*- coding: utf-8 -*-
"""
ZeliJudge Pro #392: Linux Kernel x86 Split Lock Detection & Bus Lock Mitigation Engine
Implementation in Python 3.
"""
import sys
import json

CACHE_LINE_SIZE = 64
BUS_LOCK_PENALTY_CYCLES = 1000

class SplitLockEngine:
    def __init__(self, config):
        self.policy = config.get("split_lock_policy", "RATELIMIT")
        self.ratelimit_max = config.get("bus_lock_ratelimit", 5)
        self.throttle_delay_ms = config.get("throttle_delay_ms", 20)
        self.num_cores = config.get("num_cores", 8)

        self.total_insns = 0
        self.split_locks_detected = 0
        self.bus_locks_asserted = 0
        self.tasks_killed = 0
        self.throttles_injected = 0
        self.bus_stall_cycles = 0
        self.bus_stall_saved = 0

        self.ratelimit_window_start = 0
        self.current_window_locks = 0
        self.warned_tasks = set()
        self.dead_tasks = set()
        self.events = []

    def execute_insn(self, core_id, task_id, addr, size, is_locked, now_ms):
        self.total_insns += 1
        if task_id in self.dead_tasks:
            self.events.append({
                "op": "EXECUTE",
                "task_id": task_id,
                "status": "FAIL_TASK_DEAD"
            })
            return

        c1 = addr // CACHE_LINE_SIZE
        c2 = (addr + size - 1) // CACHE_LINE_SIZE
        is_split = (c1 != c2)

        if not (is_locked and is_split):
            self.events.append({
                "op": "EXECUTE",
                "core_id": core_id,
                "task_id": task_id,
                "status": "SUCCESS_NORMAL",
                "is_locked": is_locked,
                "cacheline_span": 1
            })
            return

        self.split_locks_detected += 1

        if self.policy == "OFF":
            self.bus_locks_asserted += 1
            stall = BUS_LOCK_PENALTY_CYCLES * (self.num_cores - 1)
            self.bus_stall_cycles += stall
            self.events.append({
                "op": "EXECUTE",
                "core_id": core_id,
                "task_id": task_id,
                "status": "BUS_LOCK_ASSERTED",
                "stall_cycles": stall
            })

        elif self.policy == "WARN":
            is_first_warn = (task_id not in self.warned_tasks)
            self.warned_tasks.add(task_id)
            self.bus_locks_asserted += 1
            stall = BUS_LOCK_PENALTY_CYCLES * (self.num_cores - 1)
            self.bus_stall_cycles += stall
            self.events.append({
                "op": "EXECUTE",
                "core_id": core_id,
                "task_id": task_id,
                "status": "AC_SPLIT_LOCK_WARN" if is_first_warn else "BUS_LOCK_ASSERTED",
                "stall_cycles": stall
            })

        elif self.policy == "FATAL":
            self.tasks_killed += 1
            self.dead_tasks.add(task_id)
            stall_saved = BUS_LOCK_PENALTY_CYCLES * (self.num_cores - 1)
            self.bus_stall_saved += stall_saved
            self.events.append({
                "op": "EXECUTE",
                "core_id": core_id,
                "task_id": task_id,
                "status": "SIGBUS_TERMINATED",
                "reason": "Split lock in FATAL mode",
                "stall_cycles_saved": stall_saved
            })

        elif self.policy == "RATELIMIT":
            if now_ms >= self.ratelimit_window_start + 1000:
                self.ratelimit_window_start = now_ms
                self.current_window_locks = 0

            if self.current_window_locks < self.ratelimit_max:
                self.current_window_locks += 1
                self.bus_locks_asserted += 1
                stall = BUS_LOCK_PENALTY_CYCLES * (self.num_cores - 1)
                self.bus_stall_cycles += stall
                self.events.append({
                    "op": "EXECUTE",
                    "core_id": core_id,
                    "task_id": task_id,
                    "status": "BUS_LOCK_ALLOWED_WITHIN_LIMIT",
                    "window_count": self.current_window_locks,
                    "stall_cycles": stall
                })
            else:
                self.throttles_injected += 1
                stall_saved = BUS_LOCK_PENALTY_CYCLES * (self.num_cores - 1)
                self.bus_stall_saved += stall_saved
                self.events.append({
                    "op": "EXECUTE",
                    "core_id": core_id,
                    "task_id": task_id,
                    "status": "BUS_LOCK_THROTTLED",
                    "penalty_delay_ms": self.throttle_delay_ms,
                    "stall_cycles_saved": stall_saved
                })

    def run_commands(self, commands):
        for cmd in commands:
            if cmd["op"] == "EXECUTE_INSN":
                self.execute_insn(
                    cmd["core_id"],
                    cmd["task_id"],
                    cmd["addr"],
                    cmd["size"],
                    cmd.get("is_locked", False),
                    cmd.get("timestamp_ms", 0)
                )

    def get_result(self):
        return {
            "policy": self.policy,
            "total_insns": self.total_insns,
            "split_locks_detected": self.split_locks_detected,
            "bus_locks_asserted": self.bus_locks_asserted,
            "tasks_killed": self.tasks_killed,
            "throttles_injected": self.throttles_injected,
            "bus_stall_cycles": self.bus_stall_cycles,
            "bus_stall_saved": self.bus_stall_saved,
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

    engine = SplitLockEngine(config)
    engine.run_commands(commands)
    result = engine.get_result()

    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
