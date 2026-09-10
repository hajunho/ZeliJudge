import sys
import json
from collections import OrderedDict

PAGE_SIZE = 4096

class TLB:
    def __init__(self, capacity=64):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.flush_count = 0
        self.hits = 0
        self.misses = 0

    def lookup(self, vpn, current_pcid):
        if vpn in self.entries:
            pfn, entry_pcid, is_global = self.entries[vpn]
            if is_global or entry_pcid == current_pcid or entry_pcid is None:
                self.entries.move_to_end(vpn)
                self.hits += 1
                return pfn
        self.misses += 1
        return None

    def insert(self, vpn, pfn, pcid, is_global=False):
        if vpn in self.entries:
            self.entries.move_to_end(vpn)
        elif len(self.entries) >= self.capacity:
            self.entries.popitem(last=False)
        self.entries[vpn] = (pfn, pcid, is_global)

    def flush_non_global(self, pcid_to_flush=None):
        self.flush_count += 1
        to_del = []
        for vpn, (pfn, pcid, is_global) in self.entries.items():
            if not is_global:
                if pcid_to_flush is None or pcid == pcid_to_flush:
                    to_del.append(vpn)
        for vpn in to_del:
            del self.entries[vpn]

    def inv_individual(self, vpn, pcid_target):
        if vpn in self.entries:
            _, pcid, is_global = self.entries[vpn]
            if is_global or pcid == pcid_target or pcid is None or pcid_target is None:
                del self.entries[vpn]

class KPTISimulation:
    def __init__(self, config):
        self.enable_kpti = config.get("enable_kpti", True)
        self.enable_pcid = config.get("enable_pcid", True)
        self.tlb_capacity = config.get("tlb_capacity", 64)
        self.cr3_switch_cost = config.get("cr3_switch_cost_cycles", 50 if self.enable_pcid else 200)
        self.tlb_miss_penalty = config.get("tlb_miss_penalty_cycles", 100)
        self.invpcid_cost = config.get("invpcid_cost_cycles", 80)
        self.trampoline_overhead = config.get("trampoline_overhead_cycles", 30)
        self.base_mem_cycle = config.get("base_mem_cycle", 4)
        
        self.tlb = TLB(capacity=self.tlb_capacity)
        self.cpu_mode = "USER"
        
        self.user_pcid = 1
        self.kernel_pcid = 1 | 0x800 if self.enable_pcid else None
        self.current_pcid = self.user_pcid if self.enable_pcid else None
        
        self.kernel_pgd = {}
        self.user_pgd = {}
        
        self.total_cycles = 0
        self.cr3_switch_cycles = 0
        self.tlb_miss_cycles = 0
        self.trampoline_cycles = 0
        self.invpcid_cycles = 0
        self.execution_cycles = 0
        
        self.meltdown_attempts = 0
        self.meltdown_blocked = 0
        self.meltdown_leaks = 0
        self.event_log = []

    def map_page(self, vaddr, pfn, is_kernel=False, is_trampoline=False, is_global=False):
        vpn = vaddr >> 12
        self.kernel_pgd[vpn] = (pfn, is_kernel, is_trampoline, is_global)
        if not self.enable_kpti:
            self.user_pgd[vpn] = (pfn, is_kernel, is_trampoline, is_global)
        else:
            if not is_kernel or is_trampoline:
                self.user_pgd[vpn] = (pfn, is_kernel, is_trampoline, is_global)

    def unmap_page(self, vaddr):
        vpn = vaddr >> 12
        if vpn in self.kernel_pgd:
            del self.kernel_pgd[vpn]
        if vpn in self.user_pgd:
            del self.user_pgd[vpn]
        
        if self.enable_pcid:
            self.invpcid_cycles += self.invpcid_cost
            self.total_cycles += self.invpcid_cost
            self.tlb.inv_individual(vpn, self.user_pcid)
            self.tlb.inv_individual(vpn, self.kernel_pcid)
        else:
            self.tlb.inv_individual(vpn, None)

    def switch_to_kernel_cr3(self):
        cycles = 0
        if self.enable_kpti:
            cycles += self.trampoline_overhead
            self.trampoline_cycles += self.trampoline_overhead
            
            cycles += self.cr3_switch_cost
            self.cr3_switch_cycles += self.cr3_switch_cost
            
            if not self.enable_pcid:
                self.tlb.flush_non_global()
            else:
                self.current_pcid = self.kernel_pcid
        self.cpu_mode = "KERNEL"
        self.total_cycles += cycles

    def switch_to_user_cr3(self):
        cycles = 0
        if self.enable_kpti:
            cycles += self.cr3_switch_cost
            self.cr3_switch_cycles += self.cr3_switch_cost
            
            cycles += self.trampoline_overhead
            self.trampoline_cycles += self.trampoline_overhead
            
            if not self.enable_pcid:
                self.tlb.flush_non_global()
            else:
                self.current_pcid = self.user_pcid
        self.cpu_mode = "USER"
        self.total_cycles += cycles

    def access_memory(self, vaddr, is_speculative=False):
        vpn = vaddr >> 12
        cycles = self.base_mem_cycle
        self.execution_cycles += self.base_mem_cycle
        
        pfn = self.tlb.lookup(vpn, self.current_pcid)
        active_pgd = self.kernel_pgd if (self.cpu_mode == "KERNEL" or not self.enable_kpti) else self.user_pgd
        
        if pfn is None:
            cycles += self.tlb_miss_penalty
            self.tlb_miss_cycles += self.tlb_miss_penalty
            
            if vpn not in active_pgd:
                if is_speculative:
                    self.meltdown_attempts += 1
                    self.meltdown_blocked += 1
                    self.event_log.append({
                        "vaddr": hex(vaddr),
                        "status": "SPECULATIVE_BLOCKED_UNMAPPED",
                        "cycles": cycles
                    })
                    self.total_cycles += cycles
                    return False
                else:
                    self.event_log.append({
                        "vaddr": hex(vaddr),
                        "status": "PAGE_FAULT",
                        "cycles": cycles
                    })
                    self.total_cycles += cycles
                    return False
            
            entry_pfn, is_kernel, is_trampoline, is_global = active_pgd[vpn]
            self.tlb.insert(vpn, entry_pfn, self.current_pcid, is_global=is_global)
            pfn = entry_pfn
        else:
            entry_pfn, is_kernel, is_trampoline, is_global = active_pgd.get(vpn, (pfn, False, False, False))

        if is_kernel and not is_trampoline and self.cpu_mode == "USER":
            if is_speculative:
                self.meltdown_attempts += 1
                if self.enable_kpti:
                    self.meltdown_blocked += 1
                else:
                    self.meltdown_leaks += 1
                    self.event_log.append({
                        "vaddr": hex(vaddr),
                        "status": "SPECULATIVE_LEAK_SUCCESS",
                        "cycles": cycles
                    })
                    self.total_cycles += cycles
                    return True
            else:
                self.event_log.append({
                    "vaddr": hex(vaddr),
                    "status": "PERMISSION_FAULT_GP",
                    "cycles": cycles
                })
                self.total_cycles += cycles
                return False

        self.event_log.append({
            "vaddr": hex(vaddr),
            "status": "SUCCESS",
            "cycles": cycles
        })
        self.total_cycles += cycles
        return True

    def run(self, mappings, instructions):
        for m in mappings:
            self.map_page(
                m["vaddr"],
                m["pfn"],
                is_kernel=m.get("is_kernel", False),
                is_trampoline=m.get("is_trampoline", False),
                is_global=m.get("is_global", False)
            )
            
        for inst in instructions:
            op = inst["op"]
            if op == "USER_ACCESS":
                self.access_memory(inst["vaddr"], is_speculative=inst.get("is_speculative", False))
            elif op == "KERNEL_ACCESS":
                self.access_memory(inst["vaddr"], is_speculative=False)
            elif op == "SYSCALL_ENTRY":
                self.switch_to_kernel_cr3()
            elif op == "SYSCALL_EXIT":
                self.switch_to_user_cr3()
            elif op == "UNMAP":
                self.unmap_page(inst["vaddr"])
                
        return self.generate_result()

    def generate_result(self):
        total_lookups = self.tlb.hits + self.tlb.misses
        hit_ratio = round(self.tlb.hits / total_lookups, 4) if total_lookups > 0 else 0.0
        
        return {
            "summary": {
                "total_cycles": self.total_cycles,
                "execution_cycles": self.execution_cycles,
                "cr3_switch_cycles": self.cr3_switch_cycles,
                "tlb_miss_cycles": self.tlb_miss_cycles,
                "trampoline_cycles": self.trampoline_cycles,
                "invpcid_cycles": self.invpcid_cycles
            },
            "tlb_metrics": {
                "total_lookups": total_lookups,
                "hits": self.tlb.hits,
                "misses": self.tlb.misses,
                "hit_ratio": hit_ratio,
                "flush_count": self.tlb.flush_count
            },
            "security_audit": {
                "enable_kpti": self.enable_kpti,
                "enable_pcid": self.enable_pcid,
                "meltdown_attempts": self.meltdown_attempts,
                "meltdown_blocked": self.meltdown_blocked,
                "meltdown_leaks": self.meltdown_leaks,
                "is_vulnerable": self.meltdown_leaks > 0
            }
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    
    input_data = json.loads(raw_input)
    config = input_data.get("config", {})
    mappings = input_data.get("mappings", [])
    instructions = input_data.get("instructions", [])
    
    sim = KPTISimulation(config)
    result = sim.run(mappings, instructions)
    
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
