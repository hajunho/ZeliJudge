# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #432 Solution:
Linux Kernel Virtualization: KVM vCPU Paravirtualized Spinlocks (PV Spinlocks) & PV Kick / Halt Engine
(arch/x86/kernel/kvm.c, kernel/locking/qspinlock_paravirt.h, CONFIG_PARAVIRT_SPINLOCKS)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class PvSpinlockEngine:
    def __init__(self, config):
        self.spin_threshold = config.get("spin_threshold", 512)
        self.cycles_per_spin = config.get("cycles_per_spin", 2)
        self.cycles_halted_cost = config.get("cycles_halted_cost", 50)
        self.host_timeslice_cycles = config.get("host_timeslice_cycles", 10000)
        
        self.lock_owner = None
        self.wait_queue = []
        self.vcpus = {}
        for vcpu_id in config.get("vcpus", [0, 1, 2, 3]):
            self.vcpus[vcpu_id] = {"state": "RUNNING", "is_holding_lock": False}
            
        self.pv_fastpath_locks = 0
        self.pv_waits_halted = 0
        self.pv_kicks_issued = 0
        self.lhp_detected_count = 0
        self.total_spins = 0
        self.total_cycles_consumed = 0
        self.total_cycles_saved = 0

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "ACQUIRE":
            return self._acquire(cmd)
        elif op == "RELEASE":
            return self._release(cmd)
        elif op == "HOST_PREEMPT":
            return self._host_preempt(cmd)
        elif op == "HOST_RESUME":
            return self._host_resume(cmd)
        elif op == "GET_STATE":
            return self._get_state(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _acquire(self, cmd):
        vcpu_id = cmd["vcpu_id"]
        
        if self.lock_owner is None and len(self.wait_queue) == 0:
            self.lock_owner = vcpu_id
            self.vcpus[vcpu_id]["is_holding_lock"] = True
            self.pv_fastpath_locks += 1
            return {
                "op": "ACQUIRE",
                "vcpu_id": vcpu_id,
                "status": "ACQUIRED_FASTPATH",
                "cycles": 1,
                "lock_owner": self.lock_owner
            }

        lhp_detected = False
        if self.lock_owner is not None and self.vcpus[self.lock_owner]["state"] == "PREEMPTED":
            lhp_detected = True
            self.lhp_detected_count += 1

        spins_simulated = min(cmd.get("requested_spins", self.spin_threshold), self.spin_threshold)
        self.total_spins += spins_simulated
        spin_cycles = spins_simulated * self.cycles_per_spin
        self.total_cycles_consumed += spin_cycles

        self.pv_waits_halted += 1
        waiter_entry = {"vcpu_id": vcpu_id, "state": "HALTED"}
        self.wait_queue.append(waiter_entry)

        wasted_if_no_pv = self.host_timeslice_cycles
        cycles_saved = max(0, wasted_if_no_pv - (spin_cycles + self.cycles_halted_cost))
        self.total_cycles_saved += cycles_saved

        return {
            "op": "ACQUIRE",
            "vcpu_id": vcpu_id,
            "status": "PV_WAIT_HALTED",
            "lhp_detected": lhp_detected,
            "spins": spins_simulated,
            "spin_cycles": spin_cycles,
            "cycles_saved": cycles_saved,
            "lock_owner": self.lock_owner,
            "queue_position": len(self.wait_queue)
        }

    def _release(self, cmd):
        vcpu_id = cmd["vcpu_id"]
        if self.lock_owner != vcpu_id:
            return {
                "op": "RELEASE",
                "vcpu_id": vcpu_id,
                "status": "EPERM_NOT_LOCK_OWNER",
                "current_owner": self.lock_owner
            }

        self.vcpus[vcpu_id]["is_holding_lock"] = False
        self.lock_owner = None

        if not self.wait_queue:
            return {
                "op": "RELEASE",
                "vcpu_id": vcpu_id,
                "status": "RELEASED_NO_WAITERS",
                "new_owner": None
            }

        next_waiter = self.wait_queue.pop(0)
        next_vcpu = next_waiter["vcpu_id"]
        
        kick_issued = False
        if next_waiter["state"] == "HALTED":
            kick_issued = True
            self.pv_kicks_issued += 1

        self.lock_owner = next_vcpu
        self.vcpus[next_vcpu]["is_holding_lock"] = True

        return {
            "op": "RELEASE",
            "vcpu_id": vcpu_id,
            "status": "RELEASED_HANDOFF",
            "new_owner": next_vcpu,
            "pv_kick_issued": kick_issued,
            "remaining_waiters": len(self.wait_queue)
        }

    def _host_preempt(self, cmd):
        vcpu_id = cmd["vcpu_id"]
        self.vcpus[vcpu_id]["state"] = "PREEMPTED"
        is_lhp = (self.lock_owner == vcpu_id)
        return {
            "op": "HOST_PREEMPT",
            "vcpu_id": vcpu_id,
            "status": "VCPU_PREEMPTED",
            "was_holding_lock": is_lhp
        }

    def _host_resume(self, cmd):
        vcpu_id = cmd["vcpu_id"]
        self.vcpus[vcpu_id]["state"] = "RUNNING"
        return {
            "op": "HOST_RESUME",
            "vcpu_id": vcpu_id,
            "status": "VCPU_RESUMED",
            "is_holding_lock": (self.lock_owner == vcpu_id)
        }

    def _get_state(self, cmd):
        return {
            "op": "GET_STATE",
            "lock_owner": self.lock_owner,
            "wait_queue": [w["vcpu_id"] for w in self.wait_queue],
            "vcpus": {str(vid): v["state"] for vid, v in self.vcpus.items()}
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "pv_fastpath_locks": self.pv_fastpath_locks,
            "pv_waits_halted": self.pv_waits_halted,
            "pv_kicks_issued": self.pv_kicks_issued,
            "lhp_detected_count": self.lhp_detected_count,
            "total_spins": self.total_spins,
            "total_cycles_consumed": self.total_cycles_consumed,
            "total_cycles_saved": self.total_cycles_saved,
            "final_lock_owner": self.lock_owner,
            "final_queue_length": len(self.wait_queue)
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = PvSpinlockEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
