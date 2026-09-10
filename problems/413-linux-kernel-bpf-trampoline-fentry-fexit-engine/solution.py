import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class TrampolineEngine:
    def __init__(self, config):
        self.num_cpus = config.get("num_cpus", 4)
        self.kprobe_cost_ns = config.get("kprobe_cost_ns", 150)
        self.trampoline_base_ns = config.get("trampoline_base_ns", 2)
        self.bpf_prog_cost_ns = config.get("bpf_prog_cost_ns", 3)
        self.funcs = config.get("funcs", {})
        
        self.trampolines = {f: {"fentry": [], "fmod_ret": [], "fexit": []} for f in self.funcs}
        self.bpf_prog_active = [0] * self.num_cpus
        
        self.total_invocations = 0
        self.fentry_invocations = 0
        self.fexit_invocations = 0
        self.fmod_ret_overrides = 0
        self.bypassed_orig_funcs = 0
        self.recursion_suppressed_count = 0
        self.total_trampoline_overhead_ns = 0
        self.legacy_kprobe_equivalent_overhead_ns = 0
        self.invocation_logs = []
        self.event_logs = []

    def attach_prog(self, current_time, func_id, prog_id, prog_type, override_ret_val=None, causes_recursion_func=None):
        if func_id not in self.trampolines:
            return
        prog = {
            "prog_id": prog_id,
            "type": prog_type,
            "override_ret_val": override_ret_val,
            "causes_recursion_func": causes_recursion_func
        }
        if prog_type == "FENTRY":
            self.trampolines[func_id]["fentry"].append(prog)
        elif prog_type == "FMOD_RET":
            self.trampolines[func_id]["fmod_ret"].append(prog)
        elif prog_type == "FEXIT":
            self.trampolines[func_id]["fexit"].append(prog)
            
        self.event_logs.append({
            "time": current_time,
            "event": "ATTACH_PROG",
            "func_id": func_id,
            "prog_id": prog_id,
            "type": prog_type
        })

    def detach_prog(self, current_time, func_id, prog_id):
        if func_id not in self.trampolines:
            return
        t = self.trampolines[func_id]
        t["fentry"] = [p for p in t["fentry"] if p["prog_id"] != prog_id]
        t["fmod_ret"] = [p for p in t["fmod_ret"] if p["prog_id"] != prog_id]
        t["fexit"] = [p for p in t["fexit"] if p["prog_id"] != prog_id]
        self.event_logs.append({
            "time": current_time,
            "event": "DETACH_PROG",
            "func_id": func_id,
            "prog_id": prog_id
        })

    def invoke_func(self, current_time, func_id, cpu_id, args):
        if func_id not in self.funcs:
            return None
        self.total_invocations += 1
        t = self.trampolines.get(func_id, {"fentry": [], "fmod_ret": [], "fexit": []})
        total_progs_count = len(t["fentry"]) + len(t["fmod_ret"]) + len(t["fexit"])
        
        has_trampoline = total_progs_count > 0
        trampoline_overhead = 0
        kprobe_equiv = 0
        if has_trampoline:
            trampoline_overhead = self.trampoline_base_ns + total_progs_count * self.bpf_prog_cost_ns
            self.total_trampoline_overhead_ns += trampoline_overhead
            kprobe_equiv = total_progs_count * self.kprobe_cost_ns
            self.legacy_kprobe_equivalent_overhead_ns += kprobe_equiv
            
        executed_fentry = []
        executed_fexit = []
        effective_ret_val = self.funcs[func_id]["orig_ret"]
        orig_func_executed = True
        fmod_ret_applied = None
        
        # Phase 1: fentry
        for p in t["fentry"]:
            if self.bpf_prog_active[cpu_id] > 0:
                self.recursion_suppressed_count += 1
                executed_fentry.append({"prog_id": p["prog_id"], "status": "RECURSION_SUPPRESSED"})
                continue
            self.bpf_prog_active[cpu_id] += 1
            self.fentry_invocations += 1
            executed_fentry.append({"prog_id": p["prog_id"], "status": "EXECUTED"})
            if p.get("causes_recursion_func"):
                self.invoke_func(current_time, p["causes_recursion_func"], cpu_id, [0])
            self.bpf_prog_active[cpu_id] -= 1
            
        # Phase 2: fmod_ret
        for p in t["fmod_ret"]:
            if self.bpf_prog_active[cpu_id] > 0:
                self.recursion_suppressed_count += 1
                continue
            self.bpf_prog_active[cpu_id] += 1
            override = p.get("override_ret_val")
            if override is not None and override != 0:
                self.fmod_ret_overrides += 1
                self.bypassed_orig_funcs += 1
                orig_func_executed = False
                effective_ret_val = override
                fmod_ret_applied = {"prog_id": p["prog_id"], "override_val": override}
                self.bpf_prog_active[cpu_id] -= 1
                break
            self.bpf_prog_active[cpu_id] -= 1
            
        # Phase 3: fexit
        for p in t["fexit"]:
            if self.bpf_prog_active[cpu_id] > 0:
                self.recursion_suppressed_count += 1
                executed_fexit.append({"prog_id": p["prog_id"], "status": "RECURSION_SUPPRESSED"})
                continue
            self.bpf_prog_active[cpu_id] += 1
            self.fexit_invocations += 1
            executed_fexit.append({"prog_id": p["prog_id"], "status": "EXECUTED", "observed_ret": effective_ret_val})
            if p.get("causes_recursion_func"):
                self.invoke_func(current_time, p["causes_recursion_func"], cpu_id, [0])
            self.bpf_prog_active[cpu_id] -= 1
            
        inv_log = {
            "time": current_time,
            "func_id": func_id,
            "cpu_id": cpu_id,
            "args": args,
            "orig_func_executed": orig_func_executed,
            "ret_val": effective_ret_val,
            "trampoline_overhead_ns": trampoline_overhead,
            "executed_fentry": executed_fentry,
            "executed_fexit": executed_fexit,
            "fmod_ret_applied": fmod_ret_applied
        }
        self.invocation_logs.append(inv_log)
        return effective_ret_val

    def run_trace(self, trace):
        for ev in trace:
            ev_type = ev.get("type")
            t = ev.get("time", 0)
            if ev_type == "ATTACH_PROG":
                self.attach_prog(t, ev["func_id"], ev["prog_id"], ev["prog_type"], ev.get("override_ret_val"), ev.get("causes_recursion_func"))
            elif ev_type == "DETACH_PROG":
                self.detach_prog(t, ev["func_id"], ev["prog_id"])
            elif ev_type == "INVOKE_FUNC":
                self.invoke_func(t, ev["func_id"], ev.get("cpu_id", 0), ev.get("args", []))

    def get_result(self):
        return {
            "summary": {
                "total_invocations": self.total_invocations,
                "fentry_invocations": self.fentry_invocations,
                "fexit_invocations": self.fexit_invocations,
                "fmod_ret_overrides": self.fmod_ret_overrides,
                "bypassed_orig_funcs": self.bypassed_orig_funcs,
                "recursion_suppressed_count": self.recursion_suppressed_count,
                "total_trampoline_overhead_ns": self.total_trampoline_overhead_ns,
                "legacy_kprobe_equivalent_overhead_ns": self.legacy_kprobe_equivalent_overhead_ns,
                "saved_overhead_ns": self.legacy_kprobe_equivalent_overhead_ns - self.total_trampoline_overhead_ns
            },
            "trampolines": self.trampolines,
            "invocation_logs": self.invocation_logs,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = TrampolineEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
