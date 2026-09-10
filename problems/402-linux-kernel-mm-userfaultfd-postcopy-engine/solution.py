# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #402 Solution:
Linux Kernel Memory Management: userfaultfd Post-Copy Live Migration & Demand Paging Engine
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE_SIZE = 4096

class PageSlot:
    def __init__(self, page_addr):
        self.page_addr = int(page_addr)
        self.state = "MISSING"
        self.data_hex = None
        self.waiting_threads = []

class UserfaultfdEngine:
    def __init__(self, config):
        self.start_addr = int(config.get("start_addr", 0x10000))
        self.nr_pages = int(config.get("nr_pages", 8))
        self.end_addr = self.start_addr + self.nr_pages * PAGE_SIZE

        self.pages = {}
        for i in range(self.nr_pages):
            addr = self.start_addr + i * PAGE_SIZE
            self.pages[addr] = PageSlot(addr)

        self.current_tick = 0
        self.fault_queue = []
        self.stats = {
            "page_faults_missing": 0,
            "page_faults_wp": 0,
            "uffdio_copy_ops": 0,
            "uffdio_zeropage_ops": 0,
            "uffdio_wp_ops": 0,
            "threads_resolved": 0
        }

    def get_page(self, addr):
        page_base = addr - (addr % PAGE_SIZE)
        return self.pages.get(page_base, None)

    def trigger_page_fault(self, thread_id, access_addr, access_type="READ"):
        self.current_tick += 1
        page = self.get_page(access_addr)
        if not page:
            return {"status": "SIGSEGV_OUT_OF_BOUNDS", "addr": f"0x{access_addr:08x}"}

        if page.state == "MISSING":
            self.stats["page_faults_missing"] += 1
            fault_record = {
                "tick": self.current_tick,
                "thread_id": thread_id,
                "fault_addr": page.page_addr,
                "access_addr": access_addr,
                "type": "MISSING",
                "access_type": access_type
            }
            self.fault_queue.append(fault_record)
            page.waiting_threads.append(thread_id)
            return {"status": "TRAPPED_USERFAULT_MISSING", "page_addr": f"0x{page.page_addr:08x}"}

        elif page.state == "WP" and access_type == "WRITE":
            self.stats["page_faults_wp"] += 1
            fault_record = {
                "tick": self.current_tick,
                "thread_id": thread_id,
                "fault_addr": page.page_addr,
                "access_addr": access_addr,
                "type": "WP",
                "access_type": "WRITE"
            }
            self.fault_queue.append(fault_record)
            page.waiting_threads.append(thread_id)
            return {"status": "TRAPPED_USERFAULT_WP", "page_addr": f"0x{page.page_addr:08x}"}

        return {"status": "SUCCESS_RESOLVED", "data": page.data_hex}

    def uffdio_copy(self, dst_addr, data_hex, wake_threads=True):
        self.current_tick += 1
        self.stats["uffdio_copy_ops"] += 1
        page = self.get_page(dst_addr)
        if not page:
            return {"status": "EINVAL"}

        page.state = "PRESENT"
        page.data_hex = data_hex

        woken = []
        if wake_threads:
            woken = list(page.waiting_threads)
            self.stats["threads_resolved"] += len(woken)
            page.waiting_threads = []
            self.fault_queue = [f for f in self.fault_queue if f["fault_addr"] != page.page_addr]

        return {"status": "SUCCESS", "dst_addr": f"0x{page.page_addr:08x}", "woken": woken}

    def uffdio_zeropage(self, dst_addr, wake_threads=True):
        self.current_tick += 1
        self.stats["uffdio_zeropage_ops"] += 1
        page = self.get_page(dst_addr)
        if not page:
            return {"status": "EINVAL"}

        page.state = "PRESENT"
        page.data_hex = "00" * PAGE_SIZE

        woken = []
        if wake_threads:
            woken = list(page.waiting_threads)
            self.stats["threads_resolved"] += len(woken)
            page.waiting_threads = []
            self.fault_queue = [f for f in self.fault_queue if f["fault_addr"] != page.page_addr]

        return {"status": "SUCCESS", "dst_addr": f"0x{page.page_addr:08x}", "woken": woken}

    def uffdio_writeprotect(self, target_addr, enable_wp=True):
        self.current_tick += 1
        self.stats["uffdio_wp_ops"] += 1
        page = self.get_page(target_addr)
        if not page:
            return {"status": "EINVAL"}

        if enable_wp:
            page.state = "WP"
        else:
            page.state = "PRESENT"
            woken = list(page.waiting_threads)
            self.stats["threads_resolved"] += len(woken)
            page.waiting_threads = []
            self.fault_queue = [f for f in self.fault_queue if f["fault_addr"] != page.page_addr]

        return {"status": "SUCCESS", "addr": f"0x{page.page_addr:08x}", "state": page.state}

    def run_simulation(self, operations):
        results = []
        for op in operations:
            act = op["action"]
            if act == "FAULT":
                res = self.trigger_page_fault(op["thread_id"], op["addr"], op.get("type", "READ"))
                results.append({"op": act, **res})
            elif act == "UFFDIO_COPY":
                res = self.uffdio_copy(op["dst_addr"], op["data_hex"], op.get("wake", True))
                results.append({"op": act, **res})
            elif act == "UFFDIO_ZEROPAGE":
                res = self.uffdio_zeropage(op["dst_addr"], op.get("wake", True))
                results.append({"op": act, **res})
            elif act == "UFFDIO_WRITEPROTECT":
                res = self.uffdio_writeprotect(op["addr"], op.get("enable_wp", True))
                results.append({"op": act, **res})

        return self.get_summary(results)

    def get_summary(self, op_results=None):
        pages_summary = {}
        for addr in sorted(self.pages.keys()):
            p = self.pages[addr]
            pages_summary[f"0x{addr:08x}"] = {
                "state": p.state,
                "has_data": (p.data_hex is not None),
                "waiting_threads": list(p.waiting_threads)
            }

        return {
            "stats": self.stats,
            "pending_faults_count": len(self.fault_queue),
            "pending_faults": self.fault_queue,
            "pages_state": pages_summary,
            "operation_results": op_results or []
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    operations = data.get("operations", [])
    engine = UserfaultfdEngine(config)
    res = engine.run_simulation(operations)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
