import sys
import json

class PhysicalMemory:
    def __init__(self, max_frames=64):
        self.max_frames = max_frames
        self.next_pfn = 1
        self.free_pfns = []
        self.frames = {
            0: {"refcount": 999999, "anon_exclusive": False, "data": {}}
        }
        
    def alloc_frame(self):
        if self.free_pfns:
            pfn = self.free_pfns.pop(0)
        elif self.next_pfn < self.max_frames:
            pfn = self.next_pfn
            self.next_pfn += 1
        else:
            return None
        self.frames[pfn] = {"refcount": 1, "anon_exclusive": True, "data": {}}
        return pfn
        
    def free_frame(self, pfn):
        if pfn == 0:
            return
        if pfn in self.frames:
            del self.frames[pfn]
            self.free_pfns.append(pfn)
            self.free_pfns.sort()

class Process:
    def __init__(self, pid):
        self.pid = pid
        self.vmas = []
        self.page_table = {}
        
    def find_vma(self, vpn):
        for vma in self.vmas:
            if vma["start"] <= vpn < vma["end"]:
                return vma
        return None

def solve():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    line = sys.stdin.read().strip()
    if not line:
        return
    req = json.loads(line)
    
    max_frames = req.get("system", {}).get("max_physical_frames", 64)
    pm = PhysicalMemory(max_frames)
    procs = {}
    
    stats = {
        "total_page_faults": 0,
        "cow_alloc_copies": 0,
        "cow_page_reuses": 0,
        "cow_zero_page_breaks": 0,
        "demand_page_faults": 0,
        "sigsegv_violations": 0
    }
    
    logs = []
    
    for op_item in req.get("operations", []):
        step = op_item["step"]
        op = op_item["op"]
        
        if op == "PROCESS_CREATE":
            pid = op_item["pid"]
            procs[pid] = Process(pid)
            logs.append({"step": step, "op": op, "pid": pid, "status": "CREATED"})
            
        elif op == "MMAP_ANONYMOUS":
            pid = op_item["pid"]
            p = procs[pid]
            start = op_item["vpn_start"]
            end = op_item["vpn_end"]
            flags = op_item.get("flags", ["READ", "WRITE"])
            p.vmas.append({"start": start, "end": end, "flags": list(flags)})
            logs.append({"step": step, "op": op, "pid": pid, "vpn_range": [start, end], "status": "MAPPED"})
            
        elif op == "FORK":
            parent_pid = op_item["parent_pid"]
            child_pid = op_item["child_pid"]
            parent = procs[parent_pid]
            child = Process(child_pid)
            procs[child_pid] = child
            
            for vma in parent.vmas:
                child.vmas.append(dict(vma))
                
            wrprotected_count = 0
            for vpn, pte in parent.page_table.items():
                if pte["present"]:
                    pfn = pte["pfn"]
                    vma = parent.find_vma(vpn)
                    if vma and "WRITE" in vma["flags"]:
                        pte["writable"] = False
                        wrprotected_count += 1
                    
                    if pfn != 0:
                        pm.frames[pfn]["refcount"] += 1
                        pm.frames[pfn]["anon_exclusive"] = False
                        
                    child.page_table[vpn] = {
                        "present": True,
                        "pfn": pfn,
                        "writable": pte["writable"],
                        "dirty": pte["dirty"]
                    }
                    
            logs.append({
                "step": step,
                "op": op,
                "parent_pid": parent_pid,
                "child_pid": child_pid,
                "wrprotected_pages": wrprotected_count,
                "status": "FORK_COMPLETED"
            })
            
        elif op == "PAGE_READ":
            pid = op_item["pid"]
            vpn = op_item["vpn"]
            offset = op_item.get("offset", 0)
            p = procs[pid]
            vma = p.find_vma(vpn)
            
            if not vma or "READ" not in vma["flags"]:
                stats["sigsegv_violations"] += 1
                logs.append({"step": step, "op": op, "pid": pid, "vpn": vpn, "status": "SIGSEGV_READ_VIOLATION"})
                continue
                
            pte = p.page_table.get(vpn)
            if not pte or not pte["present"]:
                stats["total_page_faults"] += 1
                stats["demand_page_faults"] += 1
                p.page_table[vpn] = {"present": True, "pfn": 0, "writable": False, "dirty": False}
                val = 0
                logs.append({
                    "step": step,
                    "op": op,
                    "pid": pid,
                    "vpn": vpn,
                    "pfn": 0,
                    "val": val,
                    "status": "DEMAND_ZERO_PAGE_MAP"
                })
            else:
                pfn = pte["pfn"]
                frame = pm.frames[pfn]
                val = frame["data"].get(offset, 0)
                logs.append({
                    "step": step,
                    "op": op,
                    "pid": pid,
                    "vpn": vpn,
                    "pfn": pfn,
                    "val": val,
                    "status": "READ_SUCCESS"
                })
                
        elif op == "PAGE_WRITE":
            pid = op_item["pid"]
            vpn = op_item["vpn"]
            offset = op_item.get("offset", 0)
            val = op_item["val"]
            p = procs[pid]
            vma = p.find_vma(vpn)
            
            if not vma or "WRITE" not in vma["flags"]:
                stats["sigsegv_violations"] += 1
                logs.append({"step": step, "op": op, "pid": pid, "vpn": vpn, "status": "SIGSEGV_WRITE_VIOLATION"})
                continue
                
            pte = p.page_table.get(vpn)
            
            if not pte or not pte["present"]:
                stats["total_page_faults"] += 1
                stats["demand_page_faults"] += 1
                new_pfn = pm.alloc_frame()
                pm.frames[new_pfn]["data"][offset] = val
                p.page_table[vpn] = {"present": True, "pfn": new_pfn, "writable": True, "dirty": True}
                logs.append({
                    "step": step,
                    "op": op,
                    "pid": pid,
                    "vpn": vpn,
                    "new_pfn": new_pfn,
                    "status": "DEMAND_PAGE_ALLOC_WRITE"
                })
            elif pte["writable"]:
                pfn = pte["pfn"]
                pm.frames[pfn]["data"][offset] = val
                pte["dirty"] = True
                logs.append({
                    "step": step,
                    "op": op,
                    "pid": pid,
                    "vpn": vpn,
                    "pfn": pfn,
                    "status": "FAST_PATH_WRITE_NO_FAULT"
                })
            else:
                stats["total_page_faults"] += 1
                old_pfn = pte["pfn"]
                
                if old_pfn == 0:
                    stats["cow_zero_page_breaks"] += 1
                    new_pfn = pm.alloc_frame()
                    pm.frames[new_pfn]["data"][offset] = val
                    pte["pfn"] = new_pfn
                    pte["writable"] = True
                    pte["dirty"] = True
                    logs.append({
                        "step": step,
                        "op": op,
                        "pid": pid,
                        "vpn": vpn,
                        "old_pfn": 0,
                        "new_pfn": new_pfn,
                        "status": "COW_ZERO_PAGE_BREAK"
                    })
                elif pm.frames[old_pfn]["refcount"] == 1:
                    stats["cow_page_reuses"] += 1
                    pm.frames[old_pfn]["data"][offset] = val
                    pm.frames[old_pfn]["anon_exclusive"] = True
                    pte["writable"] = True
                    pte["dirty"] = True
                    logs.append({
                        "step": step,
                        "op": op,
                        "pid": pid,
                        "vpn": vpn,
                        "reused_pfn": old_pfn,
                        "status": "COW_REUSE_PAGE_NO_COPY"
                    })
                else:
                    stats["cow_alloc_copies"] += 1
                    new_pfn = pm.alloc_frame()
                    pm.frames[new_pfn]["data"] = dict(pm.frames[old_pfn]["data"])
                    pm.frames[new_pfn]["data"][offset] = val
                    pm.frames[old_pfn]["refcount"] -= 1
                    if pm.frames[old_pfn]["refcount"] == 1:
                        pm.frames[old_pfn]["anon_exclusive"] = True
                    pte["pfn"] = new_pfn
                    pte["writable"] = True
                    pte["dirty"] = True
                    logs.append({
                        "step": step,
                        "op": op,
                        "pid": pid,
                        "vpn": vpn,
                        "old_pfn": old_pfn,
                        "new_pfn": new_pfn,
                        "status": "COW_ALLOC_AND_COPY"
                    })
                    
        elif op == "PROCESS_EXIT":
            pid = op_item["pid"]
            p = procs[pid]
            for vpn, pte in p.page_table.items():
                if pte["present"]:
                    pfn = pte["pfn"]
                    if pfn != 0:
                        pm.frames[pfn]["refcount"] -= 1
                        if pm.frames[pfn]["refcount"] == 1:
                            pm.frames[pfn]["anon_exclusive"] = True
                        elif pm.frames[pfn]["refcount"] == 0:
                            pm.free_frame(pfn)
            del procs[pid]
            logs.append({"step": step, "op": op, "pid": pid, "status": "EXIT_RESOURCES_FREED"})

    active_pages = sum(1 for pfn in pm.frames if pfn != 0)
    
    res = {
        "operations_log": logs,
        "statistics": stats,
        "active_physical_pages": active_pages,
        "allocated_pfns": sorted([pfn for pfn in pm.frames if pfn != 0])
    }
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    solve()
