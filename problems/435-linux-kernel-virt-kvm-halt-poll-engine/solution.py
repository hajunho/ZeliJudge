# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #435 Solution:
Linux Kernel Virtualization: KVM vCPU Dynamic Halt-Polling Engine
(virt/kvm/kvm_main.c, include/linux/kvm_host.h, CONFIG_HAVE_KVM_IRQ_BYPASS)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")


class KvmVcpuHaltPoll:
    def __init__(self, vcpu_id, config):
        self.vcpu_id = vcpu_id
        self.halt_poll_ns = config.get("initial_halt_poll_ns", 0)
        self.max_halt_poll_ns = config.get("max_halt_poll_ns", 200000)
        self.halt_poll_ns_grow = config.get("halt_poll_ns_grow", 2)
        self.halt_poll_ns_shrink = config.get("halt_poll_ns_shrink", 2)
        self.halt_poll_ns_grow_start = config.get("halt_poll_ns_grow_start", 10000)
        self.context_switch_cost_ns = config.get("context_switch_cost_ns", 15000)
        
        self.state = "RUNNING"
        self.poll_success_count = 0
        self.poll_fail_count = 0
        self.total_poll_time_ns = 0
        self.total_saved_latency_ns = 0

    def halt(self, event_delay_ns):
        initial_poll_limit = self.halt_poll_ns

        if initial_poll_limit > 0:
            if event_delay_ns <= initial_poll_limit:
                poll_time = event_delay_ns
                self.total_poll_time_ns += poll_time
                self.poll_success_count += 1
                
                if self.halt_poll_ns == 0:
                    self.halt_poll_ns = self.halt_poll_ns_grow_start
                else:
                    self.halt_poll_ns = min(self.max_halt_poll_ns, self.halt_poll_ns * self.halt_poll_ns_grow)
                
                saved = max(0, self.context_switch_cost_ns - poll_time)
                self.total_saved_latency_ns += saved
                self.state = "RUNNING"
                
                return {
                    "op": "VCPU_HALT",
                    "vcpu_id": self.vcpu_id,
                    "status": "HALT_POLL_HIT",
                    "poll_time_ns": poll_time,
                    "new_halt_poll_ns": self.halt_poll_ns,
                    "saved_latency_ns": saved,
                    "state": self.state
                }
            else:
                poll_time = initial_poll_limit
                self.total_poll_time_ns += poll_time
                self.poll_fail_count += 1
                
                if self.halt_poll_ns_shrink == 0:
                    self.halt_poll_ns = 0
                else:
                    self.halt_poll_ns = self.halt_poll_ns // self.halt_poll_ns_shrink
                    
                self.state = "SLEEPING"
                sleep_time = event_delay_ns - poll_time
                self.state = "RUNNING"
                
                return {
                    "op": "VCPU_HALT",
                    "vcpu_id": self.vcpu_id,
                    "status": "HALT_POLL_MISS_SLEEP",
                    "wasted_poll_time_ns": poll_time,
                    "sleep_time_ns": sleep_time,
                    "new_halt_poll_ns": self.halt_poll_ns,
                    "state": self.state
                }
        else:
            self.poll_fail_count += 1
            if event_delay_ns <= self.max_halt_poll_ns:
                self.halt_poll_ns = self.halt_poll_ns_grow_start
                
            self.state = "RUNNING"
            return {
                "op": "VCPU_HALT",
                "vcpu_id": self.vcpu_id,
                "status": "DIRECT_SLEEP_NO_POLL",
                "sleep_time_ns": event_delay_ns,
                "new_halt_poll_ns": self.halt_poll_ns,
                "state": self.state
            }


class KvmHaltPollManager:
    def __init__(self, config):
        self.config = config
        self.vcpus = {}
        for vid in config.get("vcpus", [0, 1]):
            self.vcpus[vid] = KvmVcpuHaltPoll(vid, config)

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "VCPU_HALT":
            vid = cmd["vcpu_id"]
            delay = cmd["event_delay_ns"]
            return self.vcpus[vid].halt(delay)
        elif op == "SET_PARAMS":
            vid = cmd["vcpu_id"]
            if "halt_poll_ns" in cmd:
                self.vcpus[vid].halt_poll_ns = cmd["halt_poll_ns"]
            if "max_halt_poll_ns" in cmd:
                self.vcpus[vid].max_halt_poll_ns = cmd["max_halt_poll_ns"]
            return {
                "op": "SET_PARAMS",
                "vcpu_id": vid,
                "status": "PARAMS_UPDATED",
                "halt_poll_ns": self.vcpus[vid].halt_poll_ns,
                "max_halt_poll_ns": self.vcpus[vid].max_halt_poll_ns
            }
        elif op == "GET_VCPU_STATS":
            vid = cmd["vcpu_id"]
            v = self.vcpus[vid]
            return {
                "op": "GET_VCPU_STATS",
                "vcpu_id": vid,
                "halt_poll_ns": v.halt_poll_ns,
                "poll_success_count": v.poll_success_count,
                "poll_fail_count": v.poll_fail_count,
                "total_poll_time_ns": v.total_poll_time_ns,
                "total_saved_latency_ns": v.total_saved_latency_ns
            }
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        summary = {
            "total_poll_success": sum(v.poll_success_count for v in self.vcpus.values()),
            "total_poll_fails": sum(v.poll_fail_count for v in self.vcpus.values()),
            "total_poll_time_ns": sum(v.total_poll_time_ns for v in self.vcpus.values()),
            "total_saved_latency_ns": sum(v.total_saved_latency_ns for v in self.vcpus.values()),
            "final_vcpus_poll_ns": {str(vid): v.halt_poll_ns for vid, v in self.vcpus.items()}
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    mgr = KvmHaltPollManager(config)
    output = mgr.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
