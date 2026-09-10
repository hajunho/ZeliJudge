# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #441 Solution:
Linux Kernel Tracing: kernel/trace/ring_buffer.c Ftrace Lockless Multi-Context Ring Buffer Engine
(kernel/trace/ring_buffer.c, include/linux/ring_buffer.h, kernel/trace/trace.c)
"""

import sys
import json

# Ensure UTF-8 streams on Windows
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

CONTEXT_PRIO = {
    "TASK": 0,
    "SOFTIRQ": 1,
    "HARDIRQ": 2,
    "NMI": 3
}


class FtraceRingBufferEngine:
    def __init__(self, config):
        self.num_cpus = config.get("num_cpus", 2)
        self.page_size = config.get("page_size", 4096)
        self.pages_per_cpu = config.get("pages_per_cpu", 4)
        self.overwrite_mode = config.get("overwrite_mode", True)
        self.page_capacity = self.page_size - 16
        
        self.cpus = {}
        for c in range(self.num_cpus):
            pages = []
            for p in range(self.pages_per_cpu):
                pages.append({
                    "page_id": p,
                    "write_bytes": 0,
                    "commit_bytes": 0,
                    "entries_count": 0
                })
            self.cpus[c] = {
                "pages": pages,
                "head_idx": 0,
                "tail_idx": 0,
                "active_context_stack": [],
                "overwritten_events": 0,
                "dropped_events": 0,
                "total_committed_events": 0,
                "total_committed_bytes": 0
            }
            
        self.active_reservations = {}

    def execute_command(self, cmd):
        op = cmd.get("op")
        if op == "RESERVE_EVENT":
            return self._reserve_event(cmd)
        elif op == "COMMIT_EVENT":
            return self._commit_event(cmd)
        elif op == "CONSUME_PAGE":
            return self._consume_page(cmd)
        elif op == "GET_STATS":
            return self._get_stats(cmd)
        else:
            return {"op": op, "status": "UNKNOWN_OP"}

    def _reserve_event(self, cmd):
        event_id = cmd["event_id"]
        cpu_id = cmd["cpu_id"]
        context = cmd.get("context", "TASK")
        length = cmd.get("length", 32)
        
        if cpu_id not in self.cpus or context not in CONTEXT_PRIO:
            return {"op": "RESERVE_EVENT", "event_id": event_id, "status": "EINVAL"}
            
        cpu = self.cpus[cpu_id]
        
        if cpu["active_context_stack"]:
            curr_prio = CONTEXT_PRIO[cpu["active_context_stack"][-1]]
            new_prio = CONTEXT_PRIO[context]
            if new_prio <= curr_prio:
                return {
                    "op": "RESERVE_EVENT",
                    "event_id": event_id,
                    "status": "ERROR_NESTING_VIOLATION",
                    "current_context": cpu["active_context_stack"][-1],
                    "requested_context": context
                }
                
        tail = cpu["pages"][cpu["tail_idx"]]
        
        if tail["write_bytes"] + length <= self.page_capacity:
            offset = tail["write_bytes"]
            tail["write_bytes"] += length
            allocated_page_idx = cpu["tail_idx"]
            status = "RESERVED_CURRENT_PAGE"
        else:
            next_idx = (cpu["tail_idx"] + 1) % self.pages_per_cpu
            if next_idx == cpu["head_idx"]:
                if self.overwrite_mode:
                    lost_entries = cpu["pages"][next_idx]["entries_count"]
                    cpu["overwritten_events"] += lost_entries
                    cpu["head_idx"] = (cpu["head_idx"] + 1) % self.pages_per_cpu
                    
                    cpu["pages"][next_idx]["write_bytes"] = length
                    cpu["pages"][next_idx]["commit_bytes"] = 0
                    cpu["pages"][next_idx]["entries_count"] = 0
                    cpu["tail_idx"] = next_idx
                    allocated_page_idx = next_idx
                    offset = 0
                    status = "RESERVED_PAGE_ROLLED_OVERWRITE"
                else:
                    cpu["dropped_events"] += 1
                    return {
                        "op": "RESERVE_EVENT",
                        "event_id": event_id,
                        "status": "DROPPED_BUFFER_FULL",
                        "cpu_id": cpu_id
                    }
            else:
                cpu["pages"][next_idx]["write_bytes"] = length
                cpu["pages"][next_idx]["commit_bytes"] = 0
                cpu["pages"][next_idx]["entries_count"] = 0
                cpu["tail_idx"] = next_idx
                allocated_page_idx = next_idx
                offset = 0
                status = "RESERVED_PAGE_ROLLED"
                
        cpu["active_context_stack"].append(context)
        self.active_reservations[event_id] = {
            "event_id": event_id,
            "cpu_id": cpu_id,
            "page_idx": allocated_page_idx,
            "offset": offset,
            "length": length,
            "context": context
        }
        
        return {
            "op": "RESERVE_EVENT",
            "event_id": event_id,
            "cpu_id": cpu_id,
            "page_idx": allocated_page_idx,
            "offset": offset,
            "length": length,
            "status": status,
            "nesting_depth": len(cpu["active_context_stack"])
        }

    def _commit_event(self, cmd):
        event_id = cmd["event_id"]
        if event_id not in self.active_reservations:
            return {"op": "COMMIT_EVENT", "event_id": event_id, "status": "NOT_FOUND"}
            
        res = self.active_reservations.pop(event_id)
        cpu = self.cpus[res["cpu_id"]]
        page = cpu["pages"][res["page_idx"]]
        
        page["commit_bytes"] += res["length"]
        page["entries_count"] += 1
        cpu["total_committed_events"] += 1
        cpu["total_committed_bytes"] += res["length"]
        
        if res["context"] in cpu["active_context_stack"]:
            cpu["active_context_stack"].remove(res["context"])
            
        return {
            "op": "COMMIT_EVENT",
            "event_id": event_id,
            "cpu_id": res["cpu_id"],
            "page_idx": res["page_idx"],
            "committed_bytes": page["commit_bytes"],
            "status": "COMMITTED_SUCCESS"
        }

    def _consume_page(self, cmd):
        cpu_id = cmd["cpu_id"]
        if cpu_id not in self.cpus:
            return {"op": "CONSUME_PAGE", "status": "EINVAL"}
            
        cpu = self.cpus[cpu_id]
        head_page = cpu["pages"][cpu["head_idx"]]
        
        if head_page["commit_bytes"] == 0 and cpu["head_idx"] == cpu["tail_idx"]:
            return {
                "op": "CONSUME_PAGE",
                "cpu_id": cpu_id,
                "status": "BUFFER_EMPTY",
                "entries_consumed": 0
            }
            
        entries = head_page["entries_count"]
        bytes_read = head_page["commit_bytes"]
        consumed_page_id = head_page["page_id"]
        
        head_page["write_bytes"] = 0
        head_page["commit_bytes"] = 0
        head_page["entries_count"] = 0
        
        if cpu["head_idx"] != cpu["tail_idx"]:
            cpu["head_idx"] = (cpu["head_idx"] + 1) % self.pages_per_cpu
            
        return {
            "op": "CONSUME_PAGE",
            "cpu_id": cpu_id,
            "consumed_page_id": consumed_page_id,
            "entries_consumed": entries,
            "bytes_consumed": bytes_read,
            "status": "PAGE_CONSUMED",
            "new_head_idx": cpu["head_idx"]
        }

    def _get_stats(self, cmd):
        cpus_stat = {}
        for c in range(self.num_cpus):
            cpu = self.cpus[c]
            cpus_stat[str(c)] = {
                "head_idx": cpu["head_idx"],
                "tail_idx": cpu["tail_idx"],
                "total_committed_events": cpu["total_committed_events"],
                "total_committed_bytes": cpu["total_committed_bytes"],
                "overwritten_events": cpu["overwritten_events"],
                "dropped_events": cpu["dropped_events"],
                "active_nesting": len(cpu["active_context_stack"])
            }
        return {
            "op": "GET_STATS",
            "overwrite_mode": self.overwrite_mode,
            "cpus": cpus_stat
        }

    def run_trace(self, trace):
        results = []
        for cmd in trace:
            res = self.execute_command(cmd)
            results.append(res)
            
        total_comm = sum(c["total_committed_events"] for c in self.cpus.values())
        total_bytes = sum(c["total_committed_bytes"] for c in self.cpus.values())
        total_over = sum(c["overwritten_events"] for c in self.cpus.values())
        total_drop = sum(c["dropped_events"] for c in self.cpus.values())
        
        summary = {
            "total_committed_events": total_comm,
            "total_committed_bytes": total_bytes,
            "total_overwritten_events": total_over,
            "total_dropped_events": total_drop,
            "remaining_reservations": len(self.active_reservations)
        }
        return {"events": results, "summary": summary}


def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = FtraceRingBufferEngine(config)
    output = engine.run_trace(trace)
    print(json.dumps(output, separators=(',', ':'), ensure_ascii=False))


if __name__ == "__main__":
    solve()
