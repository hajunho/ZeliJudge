import sys
import json
import copy

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class MemoryFailureEngine:
    def __init__(self, config):
        self.total_pages = config.get("total_pages", 1024)
        self.panic_on_kernel_error = config.get("panic_on_kernel_error", True)
        
        self.pages = {
            i: {
                "state": "FREE_BUDDY",
                "pids": set(),
                "inode": None,
                "is_hwpoison": False
            } for i in range(self.total_pages)
        }
        
        self.total_mce_events = 0
        self.pages_hwpoisoned = 0
        self.clean_cache_evictions = 0
        self.free_pages_isolated = 0
        self.tasks_killed = 0
        self.soft_offlines_succeeded = 0
        self.kernel_panics = 0
        
        self.killed_pids = set()
        self.system_panicked = False
        self.recovery_logs = []
        self.event_logs = []

    def alloc_page(self, current_time, pfn, page_type, pids=None, inode=None):
        if pfn not in self.pages:
            return
        pg = self.pages[pfn]
        pg["state"] = page_type
        pg["pids"] = set(pids) if pids else set()
        pg["inode"] = inode
        self.event_logs.append({
            "time": current_time,
            "event": "ALLOC_PAGE",
            "pfn": pfn,
            "page_type": page_type,
            "pids": sorted(list(pg["pids"])),
            "inode": inode
        })

    def dirty_page(self, current_time, pfn):
        if pfn not in self.pages:
            return
        pg = self.pages[pfn]
        if pg["state"] == "CLEAN_PAGECACHE":
            pg["state"] = "DIRTY_PAGECACHE"
        self.event_logs.append({
            "time": current_time,
            "event": "DIRTY_PAGE",
            "pfn": pfn,
            "new_state": pg["state"]
        })

    def free_page(self, current_time, pfn):
        if pfn not in self.pages or self.pages[pfn]["is_hwpoison"]:
            return
        pg = self.pages[pfn]
        pg["state"] = "FREE_BUDDY"
        pg["pids"] = set()
        pg["inode"] = None
        self.event_logs.append({
            "time": current_time,
            "event": "FREE_PAGE",
            "pfn": pfn
        })

    def mce_inject_error(self, current_time, pfn, severity="UCE", trigger="SYNC_ACCESS", accessing_pid=None):
        self.total_mce_events += 1
        if self.system_panicked:
            return
        if pfn not in self.pages:
            return
            
        pg = self.pages[pfn]
        current_state = pg["state"]
        
        action = None
        result = "SUCCESS"
        killed_in_this_event = []
        
        if current_state == "FREE_BUDDY":
            pg["is_hwpoison"] = True
            pg["state"] = "HWPOISON"
            self.pages_hwpoisoned += 1
            self.free_pages_isolated += 1
            action = "ISOLATED_FREE_PAGE"
            
        elif current_state == "CLEAN_PAGECACHE":
            pg["is_hwpoison"] = True
            pg["state"] = "HWPOISON"
            pg["pids"].clear()
            self.pages_hwpoisoned += 1
            self.clean_cache_evictions += 1
            action = "EVICTED_CLEAN_CACHE"
            
        elif current_state == "DIRTY_PAGECACHE":
            pg["is_hwpoison"] = True
            pg["state"] = "HWPOISON"
            self.pages_hwpoisoned += 1
            sig_code = "BUS_MCEERR_AR" if trigger == "SYNC_ACCESS" else "BUS_MCEERR_AO"
            target_pids = [accessing_pid] if (accessing_pid and accessing_pid in pg["pids"]) else list(pg["pids"])
            for p in target_pids:
                if p not in self.killed_pids:
                    self.killed_pids.add(p)
                    self.tasks_killed += 1
                    killed_in_this_event.append({"pid": p, "sig": "SIGBUS", "si_code": sig_code})
            action = "KILLED_DIRTY_CACHE"
            
        elif current_state == "ANONYMOUS":
            pg["is_hwpoison"] = True
            pg["state"] = "HWPOISON"
            self.pages_hwpoisoned += 1
            sig_code = "BUS_MCEERR_AR" if trigger == "SYNC_ACCESS" else "BUS_MCEERR_AO"
            target_pids = [accessing_pid] if (accessing_pid and accessing_pid in pg["pids"]) else list(pg["pids"])
            for p in target_pids:
                if p not in self.killed_pids:
                    self.killed_pids.add(p)
                    self.tasks_killed += 1
                    killed_in_this_event.append({"pid": p, "sig": "SIGBUS", "si_code": sig_code})
            action = "KILLED_ANONYMOUS"
            
        elif current_state in ("SLAB_KERNEL", "RESERVED_KERNEL"):
            pg["is_hwpoison"] = True
            pg["state"] = "HWPOISON"
            self.pages_hwpoisoned += 1
            self.kernel_panics += 1
            self.system_panicked = True
            action = "KERNEL_PANIC"
            result = "PANIC"
            
        self.recovery_logs.append({
            "time": current_time,
            "pfn": pfn,
            "original_state": current_state,
            "severity": severity,
            "trigger": trigger,
            "action": action,
            "result": result,
            "killed_tasks": killed_in_this_event
        })

    def soft_offline_page(self, current_time, pfn, spare_pfn):
        if self.system_panicked or pfn not in self.pages or spare_pfn not in self.pages:
            return
            
        pg = self.pages[pfn]
        spare_pg = self.pages[spare_pfn]
        
        spare_pg["state"] = pg["state"]
        spare_pg["pids"] = set(pg["pids"])
        spare_pg["inode"] = pg["inode"]
        
        pg["is_hwpoison"] = True
        pg["state"] = "HWPOISON"
        pg["pids"] = set()
        pg["inode"] = None
        
        self.pages_hwpoisoned += 1
        self.soft_offlines_succeeded += 1
        
        self.event_logs.append({
            "time": current_time,
            "event": "SOFT_OFFLINE_PAGE",
            "source_pfn": pfn,
            "spare_pfn": spare_pfn,
            "migrated_state": spare_pg["state"]
        })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "ALLOC_PAGE":
                self.alloc_page(t, ev["pfn"], ev["page_type"], ev.get("pids"), ev.get("inode"))
            elif ev_type == "DIRTY_PAGE":
                self.dirty_page(t, ev["pfn"])
            elif ev_type == "FREE_PAGE":
                self.free_page(t, ev["pfn"])
            elif ev_type == "MCE_INJECT_ERROR":
                self.mce_inject_error(t, ev["pfn"], ev.get("severity", "UCE"), ev.get("trigger", "SYNC_ACCESS"), ev.get("accessing_pid"))
            elif ev_type == "SOFT_OFFLINE_PAGE":
                self.soft_offline_page(t, ev["pfn"], ev["spare_pfn"])

    def get_result(self):
        return {
            "summary": {
                "total_mce_events": self.total_mce_events,
                "pages_hwpoisoned": self.pages_hwpoisoned,
                "clean_cache_evictions": self.clean_cache_evictions,
                "free_pages_isolated": self.free_pages_isolated,
                "tasks_killed": self.tasks_killed,
                "soft_offlines_succeeded": self.soft_offlines_succeeded,
                "kernel_panics": self.kernel_panics,
                "system_panicked": self.system_panicked
            },
            "killed_pids": sorted(list(self.killed_pids)),
            "recovery_logs": self.recovery_logs,
            "event_logs": self.event_logs
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    trace = data.get("trace", [])
    
    engine = MemoryFailureEngine(config)
    engine.run_trace(trace)
    result = engine.get_result()
    print(json.dumps(result, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
