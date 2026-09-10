import sys
import json
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

class Page:
    def __init__(self, page_id: int, inode: int, size: int = 4096):
        self.page_id = page_id
        self.inode = inode
        self.size = size
        self.dirty_time = 0
        self.state = "CLEAN"

class PageCacheWritebackEngine:
    """
    Linux mm/page-writeback.c & fs/fs-writeback.c simulation:
    - Dirty background threshold (wb_workfn async wake)
    - Dirty hard ratio threshold (balance_dirty_pages synchronous throttle)
    - Aging & dirty_expire_interval flushes
    - fsync synchronous flush per inode
    """
    def __init__(self, 
                 total_ram_pages: int,
                 dirty_background_ratio_pct: int = 20,
                 dirty_ratio_pct: int = 40,
                 dirty_expire_ms: int = 3000):
        self.total_ram_pages = total_ram_pages
        self.dirty_background_pages = (total_ram_pages * dirty_background_ratio_pct) // 100
        self.dirty_threshold_pages = (total_ram_pages * dirty_ratio_pct) // 100
        self.dirty_expire_ms = dirty_expire_ms
        
        self.current_time_ms = 0
        self.pages: Dict[int, Page] = {}
        self.throttled_pids: List[int] = []
        self.flushed_history: List[int] = []

    def get_dirty_count(self) -> int:
        return sum(1 for p in self.pages.values() if p.state in ("DIRTY", "WRITEBACK"))

    def write(self, pid: int, page_id: int, inode: int) -> Dict[str, Any]:
        if page_id not in self.pages:
            self.pages[page_id] = Page(page_id, inode)
            
        p = self.pages[page_id]
        p.state = "DIRTY"
        p.dirty_time = self.current_time_ms
        
        dirty_cnt = self.get_dirty_count()
        throttled = False
        
        if dirty_cnt >= self.dirty_threshold_pages:
            throttled = True
            if pid not in self.throttled_pids:
                self.throttled_pids.append(pid)
                
        background_woken = (dirty_cnt >= self.dirty_background_pages)
        
        return {
            "page_id": page_id,
            "dirty_count": dirty_cnt,
            "throttled": throttled,
            "background_woken": background_woken
        }

    def tick(self, elapsed_ms: int, disk_write_rate_pages_per_sec: int) -> Dict[str, Any]:
        self.current_time_ms += elapsed_ms
        
        pages_capacity = (disk_write_rate_pages_per_sec * elapsed_ms) // 1000
        if pages_capacity < 1 and disk_write_rate_pages_per_sec > 0:
            pages_capacity = 1
            
        dirty_cnt = self.get_dirty_count()
        flusher_active = (dirty_cnt >= self.dirty_background_pages)
        
        flush_candidates = []
        for p in self.pages.values():
            if p.state == "DIRTY":
                is_expired = (self.current_time_ms - p.dirty_time >= self.dirty_expire_ms)
                flush_candidates.append((p, is_expired))
                
        flush_candidates.sort(key=lambda x: (not x[1], x[0].dirty_time, x[0].page_id))
        
        flushed_pages = []
        for p, is_expired in flush_candidates:
            if len(flushed_pages) >= pages_capacity:
                break
            if is_expired or flusher_active:
                p.state = "CLEAN"
                flushed_pages.append(p.page_id)
                self.flushed_history.append(p.page_id)
                if not is_expired and self.get_dirty_count() < self.dirty_background_pages:
                    flusher_active = False

        if self.get_dirty_count() < self.dirty_threshold_pages:
            self.throttled_pids.clear()
            
        return {
            "current_time_ms": self.current_time_ms,
            "flushed_pages": flushed_pages,
            "remaining_dirty": self.get_dirty_count(),
            "throttled_pids": list(self.throttled_pids)
        }

    def fsync(self, inode: int) -> Dict[str, Any]:
        flushed = []
        # Sort by page_id for determinism
        inode_pages = [p for p in self.pages.values() if p.inode == inode and p.state == "DIRTY"]
        inode_pages.sort(key=lambda p: p.page_id)
        
        for p in inode_pages:
            p.state = "CLEAN"
            flushed.append(p.page_id)
            self.flushed_history.append(p.page_id)
            
        if self.get_dirty_count() < self.dirty_threshold_pages:
            self.throttled_pids.clear()
            
        return {
            "inode": inode,
            "flushed_pages": flushed,
            "remaining_dirty": self.get_dirty_count()
        }

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_pages_in_cache": len(self.pages),
            "dirty_pages": self.get_dirty_count(),
            "total_flushed_count": len(self.flushed_history),
            "throttled_pids": list(self.throttled_pids),
            "final_time_ms": self.current_time_ms
        }

def process_trace(data: Dict[str, Any]) -> Dict[str, Any]:
    total_ram = data.get("total_ram_pages", 100)
    bg_ratio = data.get("dirty_background_ratio_pct", 20)
    dirty_ratio = data.get("dirty_ratio_pct", 40)
    expire_ms = data.get("dirty_expire_ms", 3000)
    commands = data.get("commands", [])
    
    engine = PageCacheWritebackEngine(total_ram, bg_ratio, dirty_ratio, expire_ms)
    command_results = []
    
    for cmd in commands:
        op = cmd.get("op")
        if op == "WRITE":
            pid = cmd.get("pid", 100)
            page_id = cmd.get("page_id")
            inode = cmd.get("inode", 1)
            res = engine.write(pid, page_id, inode)
            command_results.append({"op": "WRITE", "result": res})
        elif op == "TICK":
            elapsed = cmd.get("elapsed_ms", 100)
            rate = cmd.get("disk_write_rate_pages_per_sec", 10)
            res = engine.tick(elapsed, rate)
            command_results.append({"op": "TICK", "result": res})
        elif op == "FSYNC":
            inode = cmd.get("inode", 1)
            res = engine.fsync(inode)
            command_results.append({"op": "FSYNC", "result": res})
            
    summary = engine.get_summary()
    return {
        "command_results": command_results,
        "final_summary": summary
    }

def main():
    raw_data = sys.stdin.read().strip()
    if not raw_data:
        return
    data = json.loads(raw_data)
    result = process_trace(data)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
