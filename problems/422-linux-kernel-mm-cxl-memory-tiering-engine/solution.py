import sys
import json

class CXLMemoryTieringEngine:
    def __init__(self, config):
        self.top_tier_cap = config.get("top_tier_capacity", 10)
        self.slow_tier_cap = config.get("slow_tier_capacity", 20)
        self.high_watermark = config.get("high_watermark", 0.8)
        self.low_watermark = config.get("low_watermark", 0.5)
        self.promotion_threshold = config.get("promotion_threshold", 2)
        
        self.pages = {}
        self.total_allocations = 0
        self.total_accesses = 0
        self.pages_demoted = 0
        self.pages_promoted = 0
        self.swap_to_disk_avoided = 0
        
        self.tier_logs = []
        self.event_logs = []

    def _tier0_pages(self):
        return [p for p in self.pages.values() if p["tier"] == 0]

    def _tier1_pages(self):
        return [p for p in self.pages.values() if p["tier"] == 1]

    def alloc_page(self, current_time, page_id, is_pinned=False):
        tier0 = self._tier0_pages()
        target_tier = 0
        
        if len(tier0) >= self.top_tier_cap:
            demoted = self._demote_coldest_page(current_time)
            if not demoted:
                tier1 = self._tier1_pages()
                if len(tier1) < self.slow_tier_cap:
                    target_tier = 1
                else:
                    self.event_logs.append({
                        "time": current_time,
                        "event": "ALLOC_FAILED_ENOMEM",
                        "page_id": page_id
                    })
                    return False
                    
        self.pages[page_id] = {
            "page_id": page_id,
            "tier": target_tier,
            "access_count": 0,
            "last_access_time": current_time,
            "is_pinned": is_pinned
        }
        self.total_allocations += 1
        self.event_logs.append({
            "time": current_time,
            "event": "ALLOC_PAGE",
            "page_id": page_id,
            "tier": target_tier,
            "is_pinned": is_pinned
        })
        return True

    def _demote_coldest_page(self, current_time):
        tier1 = self._tier1_pages()
        if len(tier1) >= self.slow_tier_cap:
            return False
            
        tier0_candidates = [p for p in self._tier0_pages() if not p["is_pinned"]]
        if not tier0_candidates:
            return False
            
        tier0_candidates.sort(key=lambda p: (p["access_count"], p["last_access_time"]))
        cold_page = tier0_candidates[0]
        
        cold_page["tier"] = 1
        self.pages_demoted += 1
        self.swap_to_disk_avoided += 1
        
        self.tier_logs.append({
            "time": current_time,
            "action": "DEMOTE",
            "page_id": cold_page["page_id"],
            "from_tier": 0,
            "to_tier": 1,
            "reason": "TOP_TIER_PRESSURE"
        })
        return True

    def access_page(self, current_time, page_id):
        if page_id not in self.pages:
            return
        self.total_accesses += 1
        pg = self.pages[page_id]
        pg["access_count"] += 1
        pg["last_access_time"] = current_time
        
        if pg["tier"] == 1 and pg["access_count"] >= self.promotion_threshold:
            self._promote_page(current_time, pg)

    def _promote_page(self, current_time, pg):
        tier0 = self._tier0_pages()
        if len(tier0) >= self.top_tier_cap:
            demoted = self._demote_coldest_page(current_time)
            if not demoted:
                return
                
        pg["tier"] = 0
        self.pages_promoted += 1
        self.tier_logs.append({
            "time": current_time,
            "action": "PROMOTE",
            "page_id": pg["page_id"],
            "from_tier": 1,
            "to_tier": 0,
            "reason": "HOT_PAGE_THRESHOLD_REACHED"
        })

    def memory_pressure_reclaim(self, current_time):
        target_count = int(self.top_tier_cap * self.low_watermark)
        while len(self._tier0_pages()) > target_count:
            if not self._demote_coldest_page(current_time):
                break

    def free_page(self, current_time, page_id):
        if page_id in self.pages:
            del self.pages[page_id]
            self.event_logs.append({
                "time": current_time,
                "event": "FREE_PAGE",
                "page_id": page_id
            })

    def run_trace(self, trace):
        for ev in trace:
            t = ev.get("time", 0)
            ev_type = ev.get("type")
            if ev_type == "ALLOC_PAGE":
                self.alloc_page(t, ev["page_id"], ev.get("is_pinned", False))
            elif ev_type == "ACCESS_PAGE":
                self.access_page(t, ev["page_id"])
            elif ev_type == "MEMORY_PRESSURE_RECLAIM":
                self.memory_pressure_reclaim(t)
            elif ev_type == "FREE_PAGE":
                self.free_page(t, ev["page_id"])

    def get_result(self):
        return {
            "summary": {
                "total_allocations": self.total_allocations,
                "total_accesses": self.total_accesses,
                "pages_demoted": self.pages_demoted,
                "pages_promoted": self.pages_promoted,
                "swap_to_disk_avoided": self.swap_to_disk_avoided,
                "tier0_usage": len(self._tier0_pages()),
                "tier1_usage": len(self._tier1_pages())
            },
            "tier_logs": self.tier_logs,
            "event_logs": self.event_logs
        }

def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    
    engine = CXLMemoryTieringEngine(data.get("config", {}))
    engine.run_trace(data.get("trace", []))
    res = engine.get_result()
    print(json.dumps(res, separators=(',', ':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
