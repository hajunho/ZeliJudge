import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class MPKEngine:
    PKEY_DISABLE_ACCESS = 0x1
    PKEY_DISABLE_WRITE = 0x2
    
    def __init__(self, config):
        self.num_cpus = config.get("num_cpus", 4)
        self.page_size = config.get("page_size", 4096)
        
        # Key 0 is reserved for default memory, keys 1-15 available for allocation
        self.allocated_pkeys = {0}
        
        # Memory mappings: list of VMAs
        self.vmas = []
        
        self.default_init_pkru = config.get("default_init_pkru", 0)
        self.threads = {}
        
        # Stats
        self.total_accesses = 0
        self.successful_accesses = 0
        self.pkru_violations = 0
        self.vma_permission_faults = 0
        self.wrpkru_count = 0
        self.tlb_shootdowns_avoided = 0
        self.pkey_alloc_count = 0
        self.pkey_free_count = 0
        
        self.access_logs = []
        self.event_logs = []

    def create_thread(self, current_time, thread_id, cpu_id=0, initial_pkru=None):
        if initial_pkru is None:
            initial_pkru = self.default_init_pkru
        self.threads[thread_id] = {
            "thread_id": thread_id,
            "cpu_id": cpu_id,
            "pkru": initial_pkru
        }
        self.event_logs.append({
            "time": current_time,
            "event": "CREATE_THREAD",
            "thread_id": thread_id,
            "cpu_id": cpu_id,
            "pkru": f"0x{initial_pkru:08x}"
        })

    def pkey_alloc(self, current_time, thread_id, flags=0, init_val=0):
        self.pkey_alloc_count += 1
        allocated_key = None
        for k in range(1, 16):
            if k not in self.allocated_pkeys:
                allocated_key = k
                break
        
        if allocated_key is None:
            ret = -28 # -ENOSPC
        else:
            self.allocated_pkeys.add(allocated_key)
            ret = allocated_key
            if thread_id in self.threads:
                th = self.threads[thread_id]
                shift = allocated_key * 2
                mask = ~(0x3 << shift) & 0xFFFFFFFF
                val = (init_val & 0x3) << shift
                th["pkru"] = (th["pkru"] & mask) | val
                
        self.event_logs.append({
            "time": current_time,
            "event": "PKEY_ALLOC",
            "thread_id": thread_id,
            "flags": flags,
            "init_val": init_val,
            "ret_pkey": ret
        })
        return ret

    def pkey_free(self, current_time, thread_id, pkey):
        self.pkey_free_count += 1
        if pkey <= 0 or pkey > 15 or pkey not in self.allocated_pkeys:
            ret = -22 # -EINVAL
        else:
            self.allocated_pkeys.remove(pkey)
            ret = 0
            
        self.event_logs.append({
            "time": current_time,
            "event": "PKEY_FREE",
            "thread_id": thread_id,
            "pkey": pkey,
            "ret": ret
        })
        return ret

    def mmap(self, current_time, start_addr, size, prot="rw", pkey=0):
        end_addr = start_addr + size
        vma = {
            "start": start_addr,
            "end": end_addr,
            "size": size,
            "prot": prot,
            "pkey": pkey
        }
        self.vmas.append(vma)
        self.event_logs.append({
            "time": current_time,
            "event": "MMAP",
            "start": start_addr,
            "end": end_addr,
            "prot": prot,
            "pkey": pkey
        })

    def pkey_mprotect(self, current_time, thread_id, addr, size, prot, pkey):
        if pkey not in self.allocated_pkeys:
            ret = -22 # -EINVAL
            self.event_logs.append({
                "time": current_time,
                "event": "PKEY_MPROTECT",
                "thread_id": thread_id,
                "addr": addr,
                "size": size,
                "prot": prot,
                "pkey": pkey,
                "ret": ret
            })
            return ret
            
        end_addr = addr + size
        affected = 0
        for vma in self.vmas:
            if max(vma["start"], addr) < min(vma["end"], end_addr):
                vma["prot"] = prot
                vma["pkey"] = pkey
                affected += 1
                
        ret = 0 if affected > 0 else -14 # -EFAULT if not mapped
        self.event_logs.append({
            "time": current_time,
            "event": "PKEY_MPROTECT",
            "thread_id": thread_id,
            "addr": addr,
            "size": size,
            "prot": prot,
            "pkey": pkey,
            "affected_vmas": affected,
            "ret": ret
        })
        return ret

    def wrpkru(self, current_time, thread_id, new_pkru):
        self.wrpkru_count += 1
        self.tlb_shootdowns_avoided += 1
        old_pkru = 0
        if thread_id in self.threads:
            old_pkru = self.threads[thread_id]["pkru"]
            self.threads[thread_id]["pkru"] = new_pkru & 0xFFFFFFFF
            
        self.event_logs.append({
            "time": current_time,
            "event": "WRPKRU",
            "thread_id": thread_id,
            "old_pkru": f"0x{old_pkru:08x}",
            "new_pkru": f"0x{(new_pkru & 0xFFFFFFFF):08x}"
        })

    def set_thread_pkey_rights(self, current_time, thread_id, pkey, disable_access=False, disable_write=False):
        if thread_id not in self.threads or pkey < 0 or pkey > 15:
            return
        th = self.threads[thread_id]
        shift = pkey * 2
        bits = 0
        if disable_access:
            bits |= 0x1
        if disable_write:
            bits |= 0x2
        mask = ~(0x3 << shift) & 0xFFFFFFFF
        new_pkru = (th["pkru"] & mask) | (bits << shift)
        self.wrpkru(current_time, thread_id, new_pkru)

    def mem_access(self, current_time, thread_id, addr, access_type="READ"):
        self.total_accesses += 1
        if thread_id not in self.threads:
            log_entry = {
                "time": current_time,
                "thread_id": thread_id,
                "addr": addr,
                "access_type": access_type,
                "status": "SEGV_MAPERR",
                "fault_reason": "THREAD_NOT_FOUND",
                "pkey": None
            }
            self.access_logs.append(log_entry)
            return
            
        target_vma = None
        for vma in self.vmas:
            if vma["start"] <= addr < vma["end"]:
                target_vma = vma
                break
                
        if not target_vma:
            log_entry = {
                "time": current_time,
                "thread_id": thread_id,
                "addr": addr,
                "access_type": access_type,
                "status": "SEGV_MAPERR",
                "fault_reason": "ADDRESS_UNMAPPED",
                "pkey": None
            }
            self.access_logs.append(log_entry)
            return

        pkey = target_vma["pkey"]
        vma_prot = target_vma["prot"]
        
        # 1. Check VMA level permissions
        if access_type == "WRITE" and "w" not in vma_prot:
            self.vma_permission_faults += 1
            log_entry = {
                "time": current_time,
                "thread_id": thread_id,
                "addr": addr,
                "access_type": access_type,
                "status": "SEGV_ACCERR",
                "fault_reason": "VMA_READ_ONLY",
                "pkey": pkey
            }
            self.access_logs.append(log_entry)
            return

        # 2. Check Hardware MPK / PKRU register
        th = self.threads[thread_id]
        pkru = th["pkru"]
        shift = pkey * 2
        pkey_rights = (pkru >> shift) & 0x3
        ad = (pkey_rights & 0x1) != 0
        wd = (pkey_rights & 0x2) != 0

        if ad:
            self.pkru_violations += 1
            log_entry = {
                "time": current_time,
                "thread_id": thread_id,
                "addr": addr,
                "access_type": access_type,
                "status": "SEGV_PKUERR",
                "fault_reason": "PKRU_ACCESS_DISABLE",
                "pkey": pkey,
                "si_code": "SEGV_PKUERR",
                "si_pkey": pkey
            }
            self.access_logs.append(log_entry)
            return
            
        if access_type == "WRITE" and wd:
            self.pkru_violations += 1
            log_entry = {
                "time": current_time,
                "thread_id": thread_id,
                "addr": addr,
                "access_type": access_type,
                "status": "SEGV_PKUERR",
                "fault_reason": "PKRU_WRITE_DISABLE",
                "pkey": pkey,
                "si_code": "SEGV_PKUERR",
                "si_pkey": pkey
            }
            self.access_logs.append(log_entry)
            return

        # Access succeeded
        self.successful_accesses += 1
        log_entry = {
            "time": current_time,
            "thread_id": thread_id,
            "addr": addr,
            "access_type": access_type,
            "status": "SUCCESS",
            "fault_reason": None,
            "pkey": pkey
        }
        self.access_logs.append(log_entry)

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "CREATE_THREAD":
                self.create_thread(t, ev["thread_id"], ev.get("cpu_id", 0), ev.get("initial_pkru"))
            elif ev_type == "MMAP":
                self.mmap(t, ev["start"], ev["size"], ev.get("prot", "rw"), ev.get("pkey", 0))
            elif ev_type == "PKEY_ALLOC":
                self.pkey_alloc(t, ev["thread_id"], ev.get("flags", 0), ev.get("init_val", 0))
            elif ev_type == "PKEY_FREE":
                self.pkey_free(t, ev["thread_id"], ev["pkey"])
            elif ev_type == "PKEY_MPROTECT":
                self.pkey_mprotect(t, ev["thread_id"], ev["addr"], ev["size"], ev.get("prot", "rw"), ev["pkey"])
            elif ev_type == "WRPKRU":
                self.wrpkru(t, ev["thread_id"], ev["new_pkru"])
            elif ev_type == "SET_RIGHTS":
                self.set_thread_pkey_rights(t, ev["thread_id"], ev["pkey"], ev.get("disable_access", False), ev.get("disable_write", False))
            elif ev_type == "MEM_ACCESS":
                self.mem_access(t, ev["thread_id"], ev["addr"], ev.get("access_type", "READ"))

    def get_result(self):
        return {
            "summary": {
                "total_accesses": self.total_accesses,
                "successful_accesses": self.successful_accesses,
                "pkru_violations": self.pkru_violations,
                "vma_permission_faults": self.vma_permission_faults,
                "wrpkru_count": self.wrpkru_count,
                "tlb_shootdowns_avoided": self.tlb_shootdowns_avoided,
                "pkeys_allocated_count": len(self.allocated_pkeys) - 1
            },
            "allocated_pkeys": sorted(list(self.allocated_pkeys)),
            "thread_states": {
                str(tid): {
                    "thread_id": tid,
                    "cpu_id": th["cpu_id"],
                    "pkru": f"0x{th['pkru']:08x}"
                } for tid, th in self.threads.items()
            },
            "access_logs": self.access_logs,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = MPKEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
