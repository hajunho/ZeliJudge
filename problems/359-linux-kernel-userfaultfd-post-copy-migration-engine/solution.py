import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE_SIZE = 4096

def solve():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    input_data = json.loads(raw_input)
    
    vm_config = input_data.get("vm_config", {})
    start_addr = vm_config.get("start_addr", 0x70000000)
    total_pages = vm_config.get("total_pages", 64)
    end_addr = start_addr + (total_pages * PAGE_SIZE)
    
    page_table = {}
    for i in range(total_pages):
        page_addr = start_addr + (i * PAGE_SIZE)
        page_table[page_addr] = {
            "present": False,
            "write_protected": False,
            "data": None,
            "waiting_threads": []
        }
        
    initial_pages = input_data.get("initial_present_pages", [])
    for p in initial_pages:
        p_addr = (p.get("addr") // PAGE_SIZE) * PAGE_SIZE
        if p_addr in page_table:
            page_table[p_addr]["present"] = True
            page_table[p_addr]["data"] = p.get("data", "INIT_ZERO")
            
    events = input_data.get("events", [])
    event_log = []
    
    trapped_faults = 0
    uffdio_copies = 0
    uffdio_zeropages = 0
    threads_woken = 0
    wp_faults = 0
    
    for ev in events:
        etype = ev.get("type")
        
        if etype == "THREAD_ACCESS":
            tid = ev.get("thread_id")
            raw_addr = ev.get("addr")
            access = ev.get("access_type", "READ")
            
            p_addr = (raw_addr // PAGE_SIZE) * PAGE_SIZE
            if p_addr not in page_table:
                event_log.append({
                    "event": "SEGFAULT_OUT_OF_VMA",
                    "thread_id": tid,
                    "addr": hex(raw_addr),
                    "status": "CRASH"
                })
                continue
                
            entry = page_table[p_addr]
            
            if not entry["present"]:
                trapped_faults += 1
                entry["waiting_threads"].append(tid)
                event_log.append({
                    "event": "UFFD_EVENT_PAGEFAULT",
                    "flag": "UFFD_PAGEFAULT_FLAG_WRITE" if access == "WRITE" else "UFFD_PAGEFAULT_FLAG_READ",
                    "thread_id": tid,
                    "fault_page": hex(p_addr),
                    "status": "THREAD_SUSPENDED_IN_WAITQUEUE"
                })
            elif access == "WRITE" and entry["write_protected"]:
                wp_faults += 1
                entry["waiting_threads"].append(tid)
                event_log.append({
                    "event": "UFFD_EVENT_PAGEFAULT_WP",
                    "thread_id": tid,
                    "fault_page": hex(p_addr),
                    "status": "WRITE_PROTECT_TRAPPED"
                })
            else:
                event_log.append({
                    "event": "HARDWARE_FAST_ACCESS",
                    "thread_id": tid,
                    "addr": hex(raw_addr),
                    "status": "IMMEDIATE_HIT"
                })
                
        elif etype == "UFFDIO_COPY":
            raw_addr = ev.get("addr")
            p_addr = (raw_addr // PAGE_SIZE) * PAGE_SIZE
            data = ev.get("data", "PAYLOAD_COPIED")
            dont_wake = ev.get("dont_wake", False)
            
            if p_addr in page_table:
                entry = page_table[p_addr]
                entry["present"] = True
                entry["data"] = data
                uffdio_copies += 1
                
                woken = []
                if not dont_wake and entry["waiting_threads"]:
                    woken = list(entry["waiting_threads"])
                    threads_woken += len(woken)
                    entry["waiting_threads"].clear()
                    
                event_log.append({
                    "event": "UFFDIO_COPY_APPLIED",
                    "page": hex(p_addr),
                    "status": "PTE_ATOMICALLY_INSTALLED",
                    "threads_woken": woken
                })
                
        elif etype == "UFFDIO_ZEROPAGE":
            raw_addr = ev.get("addr")
            p_addr = (raw_addr // PAGE_SIZE) * PAGE_SIZE
            dont_wake = ev.get("dont_wake", False)
            
            if p_addr in page_table:
                entry = page_table[p_addr]
                entry["present"] = True
                entry["data"] = "ZERO_PAGE_MAPPED"
                uffdio_zeropages += 1
                
                woken = []
                if not dont_wake and entry["waiting_threads"]:
                    woken = list(entry["waiting_threads"])
                    threads_woken += len(woken)
                    entry["waiting_threads"].clear()
                    
                event_log.append({
                    "event": "UFFDIO_ZEROPAGE_APPLIED",
                    "page": hex(p_addr),
                    "status": "ZERO_PTE_INSTALLED",
                    "threads_woken": woken
                })
                
        elif etype == "UFFDIO_WRITEPROTECT":
            raw_addr = ev.get("addr")
            p_addr = (raw_addr // PAGE_SIZE) * PAGE_SIZE
            enable_wp = ev.get("enable_wp", True)
            
            if p_addr in page_table:
                page_table[p_addr]["write_protected"] = enable_wp
                event_log.append({
                    "event": "UFFDIO_WRITEPROTECT_TOGGLED",
                    "page": hex(p_addr),
                    "wp_status": enable_wp
                })
                
        elif etype == "UFFDIO_WAKE":
            raw_addr = ev.get("addr")
            p_addr = (raw_addr // PAGE_SIZE) * PAGE_SIZE
            if p_addr in page_table:
                entry = page_table[p_addr]
                woken = list(entry["waiting_threads"])
                threads_woken += len(woken)
                entry["waiting_threads"].clear()
                event_log.append({
                    "event": "UFFDIO_WAKE_EXPLICIT",
                    "page": hex(p_addr),
                    "threads_woken": woken
                })

    present_count = sum(1 for e in page_table.values() if e["present"])
    completion_pct = round((present_count / total_pages) * 100.0, 1)
    stalled_threads = sum(len(e["waiting_threads"]) for e in page_table.values())
    
    if completion_pct == 100.0 and stalled_threads == 0:
        verdict = "POST_COPY_MIGRATION_CONVERGED"
    elif trapped_faults > 0 and stalled_threads == 0:
        verdict = "UFFD_MISSING_PAGE_RESOLVED"
    else:
        verdict = "UFFD_FAULT_STALL"
        
    output = {
        "engine": "linux_kernel_userfaultfd_postcopy",
        "metrics": {
            "total_pages_in_vma": total_pages,
            "present_pages": present_count,
            "completion_pct": completion_pct,
            "trapped_missing_faults": trapped_faults,
            "write_protect_faults": wp_faults,
            "uffdio_copies": uffdio_copies,
            "uffdio_zeropages": uffdio_zeropages,
            "threads_woken": threads_woken,
            "currently_stalled_threads": stalled_threads
        },
        "verdict": verdict,
        "event_log": event_log
    }
    
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    solve()
