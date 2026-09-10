import sys
import json
import copy

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class SEVGHCBEngine:
    SVM_VMGEXIT_CPUID = 0x80000001
    SVM_VMGEXIT_MSR = 0x80000002
    SVM_VMGEXIT_IOIO = 0x80000003
    SVM_VMGEXIT_PSC = 0x80000010
    
    GHCB_BITMAP_RAX = (1 << 0)
    GHCB_BITMAP_RBX = (1 << 1)
    GHCB_BITMAP_RCX = (1 << 2)
    GHCB_BITMAP_RDX = (1 << 3)
    GHCB_BITMAP_SW_EXIT_INFO1 = (1 << 4)
    GHCB_BITMAP_SW_EXIT_INFO2 = (1 << 5)

    def __init__(self, config):
        self.guest_vcpus = config.get("guest_vcpus", 4)
        self.snp_active = config.get("snp_active", True)
        
        self.vcpus = {}
        self.page_states = {}
        
        self.total_vc_exceptions = 0
        self.total_vmgexits = 0
        self.successful_emulations = 0
        self.page_state_changes = 0
        self.security_terminations = 0
        
        self.emulations_by_type = {
            "CPUID": 0,
            "MSR": 0,
            "IOIO": 0,
            "PSC": 0
        }
        
        self.vmgexit_logs = []
        self.event_logs = []

    def create_vcpu(self, current_time, vcpu_id):
        self.vcpus[vcpu_id] = {
            "vcpu_id": vcpu_id,
            "state": "RUNNING",
            "regs": {"rax": 0, "rbx": 0, "rcx": 0, "rdx": 0},
            "ghcb": {
                "valid_bitmap": 0,
                "sw_exit_code": 0,
                "sw_exit_info1": 0,
                "sw_exit_info2": 0,
                "rax": 0, "rbx": 0, "rcx": 0, "rdx": 0
            }
        }
        self.event_logs.append({
            "time": current_time,
            "event": "CREATE_VCPU",
            "vcpu_id": vcpu_id
        })

    def guest_exec_op(self, current_time, vcpu_id, op, args=None):
        if vcpu_id not in self.vcpus:
            return
        vcpu = self.vcpus[vcpu_id]
        if vcpu["state"] == "TERMINATED":
            return
            
        args = args or {}
        
        self.total_vc_exceptions += 1
        vcpu["state"] = "HANDLING_VC"
        
        ghcb = vcpu["ghcb"]
        ghcb["valid_bitmap"] = 0
        
        exit_code = 0
        if op == "CPUID":
            exit_code = self.SVM_VMGEXIT_CPUID
            ghcb["rax"] = args.get("function", 0)
            ghcb["rcx"] = args.get("subfunction", 0)
            ghcb["valid_bitmap"] = self.GHCB_BITMAP_RAX | self.GHCB_BITMAP_RCX
            self.emulations_by_type["CPUID"] += 1
            
        elif op == "MSR_READ":
            exit_code = self.SVM_VMGEXIT_MSR
            ghcb["sw_exit_info1"] = 0
            ghcb["rcx"] = args.get("msr_index", 0)
            ghcb["valid_bitmap"] = self.GHCB_BITMAP_SW_EXIT_INFO1 | self.GHCB_BITMAP_RCX
            self.emulations_by_type["MSR"] += 1
            
        elif op == "MSR_WRITE":
            exit_code = self.SVM_VMGEXIT_MSR
            ghcb["sw_exit_info1"] = 1
            ghcb["rcx"] = args.get("msr_index", 0)
            ghcb["rax"] = args.get("value_lo", 0)
            ghcb["rdx"] = args.get("value_hi", 0)
            ghcb["valid_bitmap"] = self.GHCB_BITMAP_SW_EXIT_INFO1 | self.GHCB_BITMAP_RCX | self.GHCB_BITMAP_RAX | self.GHCB_BITMAP_RDX
            self.emulations_by_type["MSR"] += 1
            
        elif op in ("IOIO_IN", "IOIO_OUT"):
            exit_code = self.SVM_VMGEXIT_IOIO
            is_in = (op == "IOIO_IN")
            port = args.get("port", 0x80)
            ghcb["sw_exit_info1"] = (port << 16) | (1 if is_in else 0)
            if not is_in:
                ghcb["rax"] = args.get("value", 0)
                ghcb["valid_bitmap"] = self.GHCB_BITMAP_SW_EXIT_INFO1 | self.GHCB_BITMAP_RAX
            else:
                ghcb["valid_bitmap"] = self.GHCB_BITMAP_SW_EXIT_INFO1
            self.emulations_by_type["IOIO"] += 1
            
        elif op == "PAGE_STATE_CHANGE":
            exit_code = self.SVM_VMGEXIT_PSC
            pfn = args.get("pfn", 0)
            target_state = args.get("target_state", "SHARED")
            ghcb["sw_exit_info1"] = pfn
            ghcb["sw_exit_info2"] = 1 if target_state == "SHARED" else 2
            ghcb["valid_bitmap"] = self.GHCB_BITMAP_SW_EXIT_INFO1 | self.GHCB_BITMAP_SW_EXIT_INFO2
            self.emulations_by_type["PSC"] += 1
            
        ghcb["sw_exit_code"] = exit_code
        
        self.total_vmgexits += 1
        vcpu["state"] = "IN_VMGEXIT"
        
        inject_malicious = args.get("inject_malicious_hypervisor_response", False)
        
        if inject_malicious:
            ghcb["valid_bitmap"] |= 0xFFFF0000
        else:
            if op == "CPUID":
                fn = ghcb["rax"]
                if fn == 0:
                    ghcb["rax"] = 1
                    ghcb["rbx"] = 0x68747541
                    ghcb["rdx"] = 0x69746e65
                    ghcb["rcx"] = 0x444d4163
                elif fn == 1:
                    ghcb["rax"] = 0x00800F12
                    ghcb["rbx"] = 0x00020800
                    ghcb["rcx"] = 0x76823203
                    ghcb["rdx"] = 0x178BFBFF
                ghcb["valid_bitmap"] = self.GHCB_BITMAP_RAX | self.GHCB_BITMAP_RBX | self.GHCB_BITMAP_RCX | self.GHCB_BITMAP_RDX
                
            elif op == "MSR_READ":
                ghcb["rax"] = 0x12345678
                ghcb["rdx"] = 0x00000000
                ghcb["valid_bitmap"] = self.GHCB_BITMAP_RAX | self.GHCB_BITMAP_RDX
                
            elif op == "MSR_WRITE":
                ghcb["valid_bitmap"] = 0
                
            elif op == "IOIO_IN":
                ghcb["rax"] = 0xFF
                ghcb["valid_bitmap"] = self.GHCB_BITMAP_RAX
                
            elif op == "IOIO_OUT":
                ghcb["valid_bitmap"] = 0
                
            elif op == "PAGE_STATE_CHANGE":
                pfn = ghcb["sw_exit_info1"]
                target_state = "SHARED" if ghcb["sw_exit_info2"] == 1 else "PRIVATE"
                self.page_states[pfn] = target_state
                self.page_state_changes += 1
                ghcb["valid_bitmap"] = 0
                
        if (ghcb["valid_bitmap"] & 0xFFFF0000) != 0:
            self.security_terminations += 1
            vcpu["state"] = "TERMINATED"
            self.vmgexit_logs.append({
                "time": current_time,
                "vcpu_id": vcpu_id,
                "op": op,
                "status": "SECURITY_TERMINATION",
                "reason": "GHCB_BITMAP_PROTOCOL_VIOLATION"
            })
            return
            
        if ghcb["valid_bitmap"] & self.GHCB_BITMAP_RAX:
            vcpu["regs"]["rax"] = ghcb["rax"]
        if ghcb["valid_bitmap"] & self.GHCB_BITMAP_RBX:
            vcpu["regs"]["rbx"] = ghcb["rbx"]
        if ghcb["valid_bitmap"] & self.GHCB_BITMAP_RCX:
            vcpu["regs"]["rcx"] = ghcb["rcx"]
        if ghcb["valid_bitmap"] & self.GHCB_BITMAP_RDX:
            vcpu["regs"]["rdx"] = ghcb["rdx"]
            
        self.successful_emulations += 1
        vcpu["state"] = "RUNNING"
        
        self.vmgexit_logs.append({
            "time": current_time,
            "vcpu_id": vcpu_id,
            "op": op,
            "exit_code": hex(exit_code),
            "status": "SUCCESS",
            "regs": copy.deepcopy(vcpu["regs"])
        })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "CREATE_VCPU":
                self.create_vcpu(t, ev["vcpu_id"])
            elif ev_type == "GUEST_EXEC_OP":
                self.guest_exec_op(t, ev["vcpu_id"], ev["op"], ev.get("args"))

    def get_result(self):
        vcpu_results = {}
        for vid, vc in self.vcpus.items():
            vcpu_results[str(vid)] = {
                "vcpu_id": vid,
                "state": vc["state"],
                "regs": vc["regs"]
            }
            
        return {
            "summary": {
                "total_vc_exceptions": self.total_vc_exceptions,
                "total_vmgexits": self.total_vmgexits,
                "successful_emulations": self.successful_emulations,
                "page_state_changes": self.page_state_changes,
                "security_terminations": self.security_terminations,
                "emulations_by_type": self.emulations_by_type
            },
            "page_states": {str(k): v for k, v in self.page_states.items()},
            "vcpus": vcpu_results,
            "vmgexit_logs": self.vmgexit_logs,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = SEVGHCBEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
