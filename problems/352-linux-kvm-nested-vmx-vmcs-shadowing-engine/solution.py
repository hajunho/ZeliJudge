import sys
import json

def canonical_address(addr):
    # 64-bit canonical check: bits 48..63 must equal bit 47
    sign_bit = (addr >> 47) & 1
    high_bits = (addr >> 48) & 0xFFFF
    expected = 0xFFFF if sign_bit == 1 else 0x0000
    return high_bits == expected

def simulate_nested_vmx(input_data):
    config = input_data.get("config", {})
    t_vmexit_l0 = config.get("t_vmexit_l0", 1200)
    t_vmentry = config.get("t_vmentry", 800)
    t_shadow_access = config.get("t_shadow_access", 10)
    t_reflect_overhead = config.get("t_reflect_overhead", 400)
    t_l0_handle = config.get("t_l0_handle", 600)
    
    shadow_vmcs_enabled = config.get("shadow_vmcs_enabled", False)
    vmread_bitmap = set(config.get("vmread_bitmap", []))
    vmwrite_bitmap = set(config.get("vmwrite_bitmap", []))
    
    cr0_fixed0 = config.get("cr0_fixed0", 0x80000001)
    cr0_fixed1 = config.get("cr0_fixed1", 0xFFFFFFFF)
    cr4_fixed0 = config.get("cr4_fixed0", 0x00002000)
    cr4_fixed1 = config.get("cr4_fixed1", 0xFFFFFFFF)

    vmcs01 = {
        "PIN_BASED_VM_EXEC_CONTROL": config.get("vmcs01_pin", 0x00000001),
        "CPU_BASED_VM_EXEC_CONTROL": config.get("vmcs01_cpu", 0x00000000),
        "SECONDARY_VM_EXEC_CONTROL": config.get("vmcs01_sec", 0x00000000),
        "EXCEPTION_BITMAP": config.get("vmcs01_exc", 0x00000000),
    }

    current_vmcs12_ptr = None
    vmcs12 = {}
    vmcs02 = {}
    active_level = "L1"
    
    l1_regs = dict(config.get("l1_initial_regs", {"rip": 0x400000, "rsp": 0x7FFFFFF0, "rax": 0}))
    l2_regs = dict(config.get("l2_initial_regs", {"rip": 0x800000, "rsp": 0x3FFFFFF0, "rax": 0}))
    
    metrics = {
        "total_cycles": 0,
        "l0_vm_exits_total": 0,
        "l0_vm_exits_shadow_trapped": 0,
        "l0_vm_exits_unreflected_l0": 0,
        "l1_reflected_vm_exits": 0,
        "shadow_bypassed_reads": 0,
        "shadow_bypassed_writes": 0,
        "vm_entries_to_l2": 0,
        "consistency_checks_passed": 0,
        "consistency_checks_failed": 0
    }
    
    commands = input_data.get("commands", [])
    event_log = []

    for cmd in commands:
        op = cmd.get("op")
        
        if op == "VMPTRLD":
            gpa = cmd.get("gpa")
            if shadow_vmcs_enabled:
                metrics["total_cycles"] += t_shadow_access
            else:
                metrics["total_cycles"] += t_vmexit_l0
                metrics["l0_vm_exits_total"] += 1
                metrics["l0_vm_exits_shadow_trapped"] += 1
            current_vmcs12_ptr = gpa
            event_log.append(f"VMPTRLD loaded GPA 0x{gpa:X}")

        elif op == "VMWRITE":
            field = cmd.get("field")
            val = cmd.get("value")
            
            trapped = True
            if shadow_vmcs_enabled and (field not in vmwrite_bitmap):
                trapped = False
                
            if trapped:
                metrics["total_cycles"] += t_vmexit_l0
                metrics["l0_vm_exits_total"] += 1
                metrics["l0_vm_exits_shadow_trapped"] += 1
            else:
                metrics["total_cycles"] += t_shadow_access
                metrics["shadow_bypassed_writes"] += 1
                
            if current_vmcs12_ptr is not None:
                vmcs12[field] = val
                event_log.append(f"VMWRITE {field}=0x{val:X} (trapped={trapped})")
            else:
                event_log.append(f"VMWRITE {field} FAILED (no active vmcs12)")

        elif op == "VMREAD":
            field = cmd.get("field")
            trapped = True
            if shadow_vmcs_enabled and (field not in vmread_bitmap):
                trapped = False
                
            if trapped:
                metrics["total_cycles"] += t_vmexit_l0
                metrics["l0_vm_exits_total"] += 1
                metrics["l0_vm_exits_shadow_trapped"] += 1
            else:
                metrics["total_cycles"] += t_shadow_access
                metrics["shadow_bypassed_reads"] += 1
                
            val = vmcs12.get(field, 0)
            event_log.append(f"VMREAD {field}=0x{val:X} (trapped={trapped})")

        elif op in ("VMLAUNCH", "VMRESUME"):
            metrics["total_cycles"] += t_vmexit_l0
            metrics["l0_vm_exits_total"] += 1
            
            valid = True
            err_reason = ""
            
            if current_vmcs12_ptr is None:
                valid = False
                err_reason = "NO_ACTIVE_VMCS12"
            else:
                g_cr0 = vmcs12.get("GUEST_CR0", 0)
                g_cr4 = vmcs12.get("GUEST_CR4", 0)
                if (g_cr0 & cr0_fixed0) != cr0_fixed0 or (g_cr0 & (~cr0_fixed1 & 0xFFFFFFFF)) != 0:
                    valid = False
                    err_reason = "CR0_FIXED_BITS_VIOLATION"
                elif (g_cr4 & cr4_fixed0) != cr4_fixed0 or (g_cr4 & (~cr4_fixed1 & 0xFFFFFFFF)) != 0:
                    valid = False
                    err_reason = "CR4_FIXED_BITS_VIOLATION"
                else:
                    host_rip = vmcs12.get("HOST_RIP", 0)
                    host_rsp = vmcs12.get("HOST_RSP", 0)
                    if not canonical_address(host_rip):
                        valid = False
                        err_reason = "HOST_RIP_NON_CANONICAL"
                    elif not canonical_address(host_rsp):
                        valid = False
                        err_reason = "HOST_RSP_NON_CANONICAL"
            
            if valid:
                metrics["consistency_checks_passed"] += 1
                pin12 = vmcs12.get("PIN_BASED_VM_EXEC_CONTROL", 0)
                cpu12 = vmcs12.get("CPU_BASED_VM_EXEC_CONTROL", 0)
                sec12 = vmcs12.get("SECONDARY_VM_EXEC_CONTROL", 0)
                exc12 = vmcs12.get("EXCEPTION_BITMAP", 0)
                
                vmcs02 = {
                    "PIN_BASED_VM_EXEC_CONTROL": vmcs01["PIN_BASED_VM_EXEC_CONTROL"] | pin12,
                    "CPU_BASED_VM_EXEC_CONTROL": vmcs01["CPU_BASED_VM_EXEC_CONTROL"] | cpu12,
                    "SECONDARY_VM_EXEC_CONTROL": vmcs01["SECONDARY_VM_EXEC_CONTROL"] | sec12,
                    "EXCEPTION_BITMAP": vmcs01["EXCEPTION_BITMAP"] | exc12
                }
                
                active_level = "L2"
                l2_regs["rip"] = vmcs12.get("GUEST_RIP", l2_regs["rip"])
                l2_regs["rsp"] = vmcs12.get("GUEST_RSP", l2_regs["rsp"])
                metrics["vm_entries_to_l2"] += 1
                metrics["total_cycles"] += t_vmentry
                event_log.append(f"{op} succeeded -> entered L2 (RIP=0x{l2_regs['rip']:X})")
            else:
                metrics["consistency_checks_failed"] += 1
                vmcs12["VM_INSTRUCTION_ERROR"] = err_reason
                event_log.append(f"{op} consistency failure: {err_reason}")

        elif op == "L2_EXECUTE":
            exec_cycles = cmd.get("cycles", 0)
            metrics["total_cycles"] += exec_cycles
            event = cmd.get("event")
            
            if active_level != "L2":
                event_log.append(f"L2_EXECUTE skipped (active_level is {active_level})")
                continue
                
            if event:
                ev_type = event.get("type")
                rip_advance = event.get("rip_advance", 0)
                l2_regs["rip"] += rip_advance
                
                reflected_to_l1 = False
                handled_by_l0 = False
                exit_reason = 0
                exit_qual = 0
                
                if ev_type == "CPUID":
                    reflected_to_l1 = True
                    exit_reason = 10
                    exit_qual = 0
                    
                elif ev_type == "IO_INSTRUCTION":
                    port = event.get("port", 0)
                    cpu12 = vmcs12.get("CPU_BASED_VM_EXEC_CONTROL", 0)
                    cpu01 = vmcs01.get("CPU_BASED_VM_EXEC_CONTROL", 0)
                    if (cpu12 & 0x01000000) != 0:
                        reflected_to_l1 = True
                        exit_reason = 30
                        exit_qual = port
                    elif (cpu01 & 0x01000000) != 0:
                        handled_by_l0 = True
                        exit_reason = 30
                        exit_qual = port
                        
                elif ev_type == "CR3_WRITE":
                    new_cr3 = event.get("cr3", 0)
                    cpu12 = vmcs12.get("CPU_BASED_VM_EXEC_CONTROL", 0)
                    cpu01 = vmcs01.get("CPU_BASED_VM_EXEC_CONTROL", 0)
                    if (cpu12 & 0x00008000) != 0:
                        reflected_to_l1 = True
                        exit_reason = 28
                        exit_qual = 0x3
                    elif (cpu01 & 0x00008000) != 0:
                        handled_by_l0 = True
                    vmcs12["GUEST_CR3"] = new_cr3

                elif ev_type == "PAGE_FAULT":
                    error_code = event.get("error_code", 0)
                    cr2 = event.get("cr2", 0)
                    exc12 = vmcs12.get("EXCEPTION_BITMAP", 0)
                    pfec_mask = vmcs12.get("PAGE_FAULT_ERROR_CODE_MASK", 0)
                    pfec_match = vmcs12.get("PAGE_FAULT_ERROR_CODE_MATCH", 0)
                    
                    if (exc12 & (1 << 14)) != 0 and ((error_code & pfec_mask) == pfec_match):
                        reflected_to_l1 = True
                        exit_reason = 0
                        exit_qual = cr2
                    else:
                        handled_by_l0 = True
                        
                elif ev_type == "EXTERNAL_INTERRUPT":
                    irq = event.get("irq", 0)
                    pin01 = vmcs01.get("PIN_BASED_VM_EXEC_CONTROL", 0)
                    pin12 = vmcs12.get("PIN_BASED_VM_EXEC_CONTROL", 0)
                    if (pin01 & 0x00000001) != 0:
                        handled_by_l0 = True
                    elif (pin12 & 0x00000001) != 0:
                        reflected_to_l1 = True
                        exit_reason = 1
                        exit_qual = irq
                        
                elif ev_type == "EPT_VIOLATION":
                    gpa = event.get("gpa", 0)
                    sec12 = vmcs12.get("SECONDARY_VM_EXEC_CONTROL", 0)
                    is_l1_violation = event.get("is_l1_violation", False)
                    if (sec12 & 0x00000002) != 0 and is_l1_violation:
                        reflected_to_l1 = True
                        exit_reason = 48
                        exit_qual = gpa
                    else:
                        handled_by_l0 = True

                if reflected_to_l1:
                    metrics["total_cycles"] += t_vmexit_l0 + t_reflect_overhead
                    metrics["l0_vm_exits_total"] += 1
                    metrics["l1_reflected_vm_exits"] += 1
                    
                    vmcs12["GUEST_RIP"] = l2_regs["rip"]
                    vmcs12["GUEST_RSP"] = l2_regs["rsp"]
                    vmcs12["VM_EXIT_REASON"] = exit_reason
                    vmcs12["EXIT_QUALIFICATION"] = exit_qual
                    
                    l1_regs["rip"] = vmcs12.get("HOST_RIP", 0)
                    l1_regs["rsp"] = vmcs12.get("HOST_RSP", 0)
                    active_level = "L1"
                    event_log.append(f"Exit reflected to L1: reason={exit_reason} -> L1 RIP=0x{l1_regs['rip']:X}")
                    
                elif handled_by_l0:
                    metrics["total_cycles"] += t_vmexit_l0 + t_l0_handle
                    metrics["l0_vm_exits_total"] += 1
                    metrics["l0_vm_exits_unreflected_l0"] += 1
                    event_log.append(f"Exit handled internally by L0: ev={ev_type} -> L2 remains active (RIP=0x{l2_regs['rip']:X})")
                else:
                    event_log.append(f"Event {ev_type} executed without exit")

    return {
        "final_level": active_level,
        "l1_state": l1_regs,
        "l2_state": l2_regs,
        "vmcs12_state": {
            "GUEST_RIP": vmcs12.get("GUEST_RIP"),
            "GUEST_RSP": vmcs12.get("GUEST_RSP"),
            "VM_EXIT_REASON": vmcs12.get("VM_EXIT_REASON"),
            "EXIT_QUALIFICATION": vmcs12.get("EXIT_QUALIFICATION"),
            "VM_INSTRUCTION_ERROR": vmcs12.get("VM_INSTRUCTION_ERROR")
        },
        "vmcs02_merged_controls": vmcs02,
        "metrics": metrics,
        "event_log_count": len(event_log)
    }

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    result = simulate_nested_vmx(data)
    sys.stdout.write(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
