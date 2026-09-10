import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class CETShadowStackEngine:
    def __init__(self, config):
        self.max_threads = config.get("max_threads", 8)
        self.default_shstk_size = config.get("default_shstk_size", 1024)
        
        self.threads = {}
        
        self.total_calls = 0
        self.total_rets = 0
        self.successful_rets = 0
        self.cp_exceptions = 0
        self.rop_attacks_blocked = 0
        self.shadow_stack_write_violations = 0
        
        self.event_logs = []
        self.security_alerts = []

    def create_thread(self, current_time, thread_id):
        self.threads[thread_id] = {
            "thread_id": thread_id,
            "shstk_enabled": False,
            "shstk_locked": False,
            "data_stack": [],
            "shadow_stack": [],
            "is_alive": True
        }
        self.event_logs.append({
            "time": current_time,
            "event": "CREATE_THREAD",
            "thread_id": thread_id
        })

    def arch_prctl(self, current_time, thread_id, cmd, arg=None):
        if thread_id not in self.threads:
            return -3 # -ESRCH
        th = self.threads[thread_id]
        ret = 0
        
        if cmd == "ARCH_SHSTK_ENABLE":
            if th["shstk_locked"]:
                ret = -1 # -EPERM
            else:
                th["shstk_enabled"] = True
        elif cmd == "ARCH_SHSTK_DISABLE":
            if th["shstk_locked"]:
                ret = -1 # -EPERM
            else:
                th["shstk_enabled"] = False
        elif cmd == "ARCH_SHSTK_LOCK":
            th["shstk_locked"] = True
        elif cmd == "ARCH_SHSTK_ALLOC_SHSTK":
            ret = 0x7FFF0000 + thread_id * 0x1000
        else:
            ret = -22 # -EINVAL
            
        self.event_logs.append({
            "time": current_time,
            "event": "ARCH_PRCTL",
            "thread_id": thread_id,
            "cmd": cmd,
            "ret": ret,
            "shstk_enabled": th["shstk_enabled"],
            "shstk_locked": th["shstk_locked"]
        })
        return ret

    def call_func(self, current_time, thread_id, func_name, ret_addr):
        self.total_calls += 1
        if thread_id not in self.threads or not self.threads[thread_id]["is_alive"]:
            return
        th = self.threads[thread_id]
        
        th["data_stack"].append({"func": func_name, "ret_addr": ret_addr})
        
        if th["shstk_enabled"]:
            th["shadow_stack"].append({"func": func_name, "ret_addr": ret_addr})
            
        self.event_logs.append({
            "time": current_time,
            "event": "CALL_FUNC",
            "thread_id": thread_id,
            "func": func_name,
            "ret_addr": f"0x{ret_addr:08x}",
            "shstk_pushed": th["shstk_enabled"],
            "stack_depth": len(th["data_stack"])
        })

    def ret_func(self, current_time, thread_id):
        self.total_rets += 1
        if thread_id not in self.threads or not self.threads[thread_id]["is_alive"]:
            return
        th = self.threads[thread_id]
        
        if not th["data_stack"]:
            return
            
        popped_data = th["data_stack"].pop()
        actual_ret = popped_data["ret_addr"]
        
        if th["shstk_enabled"]:
            if not th["shadow_stack"]:
                self.cp_exceptions += 1
                th["is_alive"] = False
                alert = {
                    "time": current_time,
                    "thread_id": thread_id,
                    "type": "CONTROL_PROTECTION_EXCEPTION",
                    "reason": "SHADOW_STACK_UNDERFLOW",
                    "si_code": "SEGV_CPERR"
                }
                self.security_alerts.append(alert)
                return
                
            popped_shstk = th["shadow_stack"].pop()
            expected_ret = popped_shstk["ret_addr"]
            
            if actual_ret != expected_ret:
                self.cp_exceptions += 1
                self.rop_attacks_blocked += 1
                th["is_alive"] = False
                alert = {
                    "time": current_time,
                    "thread_id": thread_id,
                    "type": "CONTROL_PROTECTION_EXCEPTION",
                    "reason": "SHADOW_STACK_MISMATCH",
                    "si_code": "SEGV_CPERR",
                    "expected_ret": f"0x{expected_ret:08x}",
                    "corrupted_ret": f"0x{actual_ret:08x}"
                }
                self.security_alerts.append(alert)
                self.event_logs.append({
                    "time": current_time,
                    "event": "RET_FUNC",
                    "thread_id": thread_id,
                    "status": "CP_EXCEPTION",
                    "actual_ret": f"0x{actual_ret:08x}",
                    "expected_ret": f"0x{expected_ret:08x}"
                })
                return
                
        self.successful_rets += 1
        self.event_logs.append({
            "time": current_time,
            "event": "RET_FUNC",
            "thread_id": thread_id,
            "status": "SUCCESS",
            "ret_addr": f"0x{actual_ret:08x}"
        })

    def attack_rop_corrupt_stack(self, current_time, thread_id, offset, fake_ret_addr):
        if thread_id not in self.threads or not self.threads[thread_id]["is_alive"]:
            return
        th = self.threads[thread_id]
        if not th["data_stack"]:
            return
            
        target_idx = len(th["data_stack"]) - 1 - offset
        if 0 <= target_idx < len(th["data_stack"]):
            orig_ret = th["data_stack"][target_idx]["ret_addr"]
            th["data_stack"][target_idx]["ret_addr"] = fake_ret_addr
            self.event_logs.append({
                "time": current_time,
                "event": "ATTACK_ROP_CORRUPT_STACK",
                "thread_id": thread_id,
                "target_idx": target_idx,
                "orig_ret": f"0x{orig_ret:08x}",
                "fake_ret": f"0x{fake_ret_addr:08x}"
            })

    def direct_mem_write(self, current_time, thread_id, target, addr, value):
        if thread_id not in self.threads:
            return
        th = self.threads[thread_id]
        
        if target == "SHADOW_STACK":
            self.shadow_stack_write_violations += 1
            alert = {
                "time": current_time,
                "thread_id": thread_id,
                "type": "PAGE_FAULT_EXCEPTION",
                "reason": "SHADOW_STACK_WRITE_PROTECTED",
                "si_code": "SEGV_ACCERR",
                "addr": f"0x{addr:08x}"
            }
            self.security_alerts.append(alert)
            self.event_logs.append({
                "time": current_time,
                "event": "DIRECT_MEM_WRITE",
                "thread_id": thread_id,
                "target": target,
                "status": "FAULT_PAGE_PROTECTION"
            })
        else:
            self.event_logs.append({
                "time": current_time,
                "event": "DIRECT_MEM_WRITE",
                "thread_id": thread_id,
                "target": target,
                "status": "SUCCESS"
            })

    def incssp(self, current_time, thread_id, count):
        if thread_id not in self.threads or not self.threads[thread_id]["is_alive"]:
            return
        th = self.threads[thread_id]
        unwound = 0
        while count > 0 and th["shadow_stack"]:
            th["shadow_stack"].pop()
            count -= 1
            unwound += 1
        while unwound > 0 and th["data_stack"]:
            th["data_stack"].pop()
            unwound -= 1
            
        self.event_logs.append({
            "time": current_time,
            "event": "INCSSP",
            "thread_id": thread_id,
            "unwound_frames": unwound
        })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "CREATE_THREAD":
                self.create_thread(t, ev["thread_id"])
            elif ev_type == "ARCH_PRCTL":
                self.arch_prctl(t, ev["thread_id"], ev["cmd"], ev.get("arg"))
            elif ev_type == "CALL_FUNC":
                self.call_func(t, ev["thread_id"], ev["func"], ev["ret_addr"])
            elif ev_type == "RET_FUNC":
                self.ret_func(t, ev["thread_id"])
            elif ev_type == "ATTACK_ROP_CORRUPT_STACK":
                self.attack_rop_corrupt_stack(t, ev["thread_id"], ev.get("offset", 0), ev["fake_ret_addr"])
            elif ev_type == "DIRECT_MEM_WRITE":
                self.direct_mem_write(t, ev["thread_id"], ev["target"], ev["addr"], ev.get("value", 0))
            elif ev_type == "INCSSP":
                self.incssp(t, ev["thread_id"], ev["count"])

    def get_result(self):
        return {
            "summary": {
                "total_calls": self.total_calls,
                "total_rets": self.total_rets,
                "successful_rets": self.successful_rets,
                "cp_exceptions": self.cp_exceptions,
                "rop_attacks_blocked": self.rop_attacks_blocked,
                "shadow_stack_write_violations": self.shadow_stack_write_violations,
                "active_threads": sum(1 for th in self.threads.values() if th["is_alive"])
            },
            "thread_states": {
                str(tid): {
                    "thread_id": tid,
                    "shstk_enabled": th["shstk_enabled"],
                    "shstk_locked": th["shstk_locked"],
                    "data_stack_depth": len(th["data_stack"]),
                    "shadow_stack_depth": len(th["shadow_stack"]),
                    "is_alive": th["is_alive"]
                } for tid, th in self.threads.items()
            },
            "security_alerts": self.security_alerts,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = CETShadowStackEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
