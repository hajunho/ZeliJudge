import sys
import json
from collections import OrderedDict

class Page:
    def __init__(self, page_id, ptype="file", dirty=False, is_ws=False):
        self.page_id = page_id
        self.ptype = ptype
        self.dirty = dirty
        self.is_ws = is_ws
        self.gen = 1
        self.tier = 0
        self.refs = 0
        self.pg_ref = 0

class MGLRU:
    def __init__(self, capacity, max_nr_gens=4, max_tiers=4):
        self.capacity = capacity
        self.max_nr_gens = max_nr_gens
        self.max_tiers = max_tiers
        self.min_seq = 1
        self.max_seq = 1
        self.pages = {}
        self.lists = {}
        self._ensure_gen(1)
        
        self.hits = 0
        self.page_faults = 0
        self.evictions = 0
        self.working_set_evictions = 0
        self.writebacks = 0
        self.promotions = 0
        self.evicted_pages = []

    def _ensure_gen(self, g):
        if g not in self.lists:
            self.lists[g] = [[] for _ in range(self.max_tiers)]

    def aging_step(self):
        self.max_seq += 1
        self._ensure_gen(self.max_seq)
        while (self.max_seq - self.min_seq + 1) > self.max_nr_gens:
            old_lists = self.lists.get(self.min_seq, [[] for _ in range(self.max_tiers)])
            for t in range(1, self.max_tiers):
                for pid in old_lists[t]:
                    if pid in self.pages:
                        p = self.pages[pid]
                        new_tier = max(1, p.tier - 1)
                        p.gen = self.max_seq
                        p.tier = new_tier
                        p.refs = new_tier
                        self.lists[self.max_seq][new_tier].append(pid)
                        self.promotions += 1
            tier0 = [pid for pid in old_lists[0] if pid in self.pages]
            del self.lists[self.min_seq]
            self.min_seq += 1
            self._ensure_gen(self.min_seq)
            self.lists[self.min_seq][0] = tier0 + self.lists[self.min_seq][0]

    def evict_one(self):
        while self.min_seq <= self.max_seq:
            tier0 = self.lists[self.min_seq][0]
            while tier0:
                pid = tier0.pop(0)
                if pid in self.pages:
                    p = self.pages.pop(pid)
                    self.evictions += 1
                    self.evicted_pages.append(pid)
                    if p.is_ws:
                        self.working_set_evictions += 1
                    if p.dirty:
                        self.writebacks += 1
                    return pid
            
            if self.min_seq < self.max_seq:
                for t in range(1, self.max_tiers):
                    while self.lists[self.min_seq][t]:
                        pid = self.lists[self.min_seq][t].pop(0)
                        if pid in self.pages:
                            p = self.pages[pid]
                            new_tier = max(1, p.tier - 1)
                            p.gen = self.max_seq
                            p.tier = new_tier
                            p.refs = new_tier
                            self.lists[self.max_seq][new_tier].append(pid)
                            self.promotions += 1
                del self.lists[self.min_seq]
                self.min_seq += 1
            else:
                for t in range(self.max_tiers):
                    while self.lists[self.max_seq][t]:
                        pid = self.lists[self.max_seq][t].pop(0)
                        if pid in self.pages:
                            p = self.pages.pop(pid)
                            self.evictions += 1
                            self.evicted_pages.append(pid)
                            if p.is_ws:
                                self.working_set_evictions += 1
                            if p.dirty:
                                self.writebacks += 1
                            return pid
                return None
        return None

    def touch(self, pid, ptype="file", dirty=False, is_ws=False, cold=False):
        if pid in self.pages:
            self.hits += 1
            p = self.pages[pid]
            if dirty: p.dirty = True
            if is_ws: p.is_ws = True
            p.refs += 1
            
            old_gen = p.gen
            old_tier = p.tier
            if old_gen in self.lists and pid in self.lists[old_gen][old_tier]:
                self.lists[old_gen][old_tier].remove(pid)
            
            new_tier = min(self.max_tiers - 1, old_tier + 1)
            p.tier = new_tier
            if old_gen < self.max_seq:
                self.promotions += 1
            p.gen = self.max_seq
            self._ensure_gen(self.max_seq)
            self.lists[self.max_seq][new_tier].append(pid)
        else:
            self.page_faults += 1
            if len(self.pages) >= self.capacity:
                self.evict_one()
            
            target_gen = self.min_seq if cold else self.max_seq
            p = Page(pid, ptype, dirty, is_ws)
            p.gen = target_gen
            p.tier = 0
            p.refs = 0
            self.pages[pid] = p
            self._ensure_gen(target_gen)
            if cold:
                self.lists[target_gen][0].insert(0, pid)
            else:
                self.lists[target_gen][0].append(pid)

    def mark_dirty(self, pid):
        if pid in self.pages:
            self.pages[pid].dirty = True

    def get_summary(self):
        gen_dist = {}
        for g in range(self.min_seq, self.max_seq + 1):
            if g in self.lists:
                gen_dist[f"gen_{g}"] = {
                    f"tier_{t}": len(self.lists[g][t]) for t in range(self.max_tiers)
                }
        return {
            "hits": self.hits,
            "page_faults": self.page_faults,
            "evictions": self.evictions,
            "working_set_evictions": self.working_set_evictions,
            "writebacks": self.writebacks,
            "promotions": self.promotions,
            "min_seq": self.min_seq,
            "max_seq": self.max_seq,
            "active_generations": self.max_seq - self.min_seq + 1,
            "resident_pages_count": len(self.pages),
            "generation_distribution": gen_dist,
            "evicted_pages": self.evicted_pages
        }

class Legacy2List:
    def __init__(self, capacity, inactive_ratio=0.5):
        self.capacity = capacity
        self.inactive_target = max(1, int(capacity * inactive_ratio))
        self.active = OrderedDict()
        self.inactive = OrderedDict()
        self.pages = {}
        self.hits = 0
        self.page_faults = 0
        self.evictions = 0
        self.working_set_evictions = 0
        self.writebacks = 0
        self.evicted_pages = []

    def evict_one(self):
        if len(self.inactive) <= len(self.active) and len(self.active) > 0:
            pid, _ = self.active.popitem(last=False)
            self.pages[pid].pg_ref = 0
            self.inactive[pid] = True
            
        while self.inactive:
            pid, _ = self.inactive.popitem(last=False)
            p = self.pages[pid]
            if p.pg_ref == 1:
                p.pg_ref = 0
                self.inactive[pid] = True
            else:
                del self.pages[pid]
                self.evictions += 1
                self.evicted_pages.append(pid)
                if p.is_ws:
                    self.working_set_evictions += 1
                if p.dirty:
                    self.writebacks += 1
                return pid
        
        if self.active:
            pid, _ = self.active.popitem(last=False)
            p = self.pages.pop(pid)
            self.evictions += 1
            self.evicted_pages.append(pid)
            if p.is_ws:
                self.working_set_evictions += 1
            if p.dirty:
                self.writebacks += 1
            return pid
        return None

    def touch(self, pid, ptype="file", dirty=False, is_ws=False, cold=False):
        if pid in self.pages:
            self.hits += 1
            p = self.pages[pid]
            if dirty: p.dirty = True
            if is_ws: p.is_ws = True
            
            if pid in self.inactive:
                if p.pg_ref == 0:
                    p.pg_ref = 1
                else:
                    del self.inactive[pid]
                    p.pg_ref = 0
                    self.active[pid] = True
            elif pid in self.active:
                p.pg_ref = 1
                self.active.move_to_end(pid)
        else:
            self.page_faults += 1
            if len(self.pages) >= self.capacity:
                self.evict_one()
            p = Page(pid, ptype, dirty, is_ws)
            self.pages[pid] = p
            self.inactive[pid] = True

    def mark_dirty(self, pid):
        if pid in self.pages:
            self.pages[pid].dirty = True

    def get_summary(self):
        return {
            "hits": self.hits,
            "page_faults": self.page_faults,
            "evictions": self.evictions,
            "working_set_evictions": self.working_set_evictions,
            "writebacks": self.writebacks,
            "active_pages_count": len(self.active),
            "inactive_pages_count": len(self.inactive),
            "resident_pages_count": len(self.pages),
            "evicted_pages": self.evicted_pages
        }

def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return
    data = json.loads(raw)
    
    cap = data.get("capacity", 8)
    max_gens = data.get("max_nr_gens", 4)
    max_tiers = data.get("max_tiers", 4)
    ops = data.get("operations", [])
    
    mglru = MGLRU(cap, max_gens, max_tiers)
    legacy = Legacy2List(cap)
    
    for op in ops:
        code = op.get("op")
        if code in ("ALLOC", "TOUCH"):
            pid = op.get("page_id")
            ptype = op.get("type", "file")
            dirty = op.get("dirty", False)
            is_ws = op.get("is_working_set", False)
            cold = op.get("cold", False)
            mglru.touch(pid, ptype, dirty, is_ws, cold)
            legacy.touch(pid, ptype, dirty, is_ws, cold)
        elif code == "MARK_DIRTY":
            pid = op.get("page_id")
            mglru.mark_dirty(pid)
            legacy.mark_dirty(pid)
        elif code == "AGING":
            mglru.aging_step()
        elif code == "RECLAIM":
            nr = op.get("nr_to_reclaim", 1)
            for _ in range(nr):
                mglru.evict_one()
                legacy.evict_one()
        elif code == "STREAM_READ":
            pages = op.get("pages", [])
            cold = op.get("cold", False)
            for pid in pages:
                mglru.touch(pid, "file", False, False, cold)
                legacy.touch(pid, "file", False, False, cold)
                
    m_res = mglru.get_summary()
    l_res = legacy.get_summary()
    
    delta_ws = l_res["working_set_evictions"] - m_res["working_set_evictions"]
    analysis = {
        "working_set_protection_delta": delta_ws,
        "thrashing_prevented": (m_res["working_set_evictions"] == 0 and l_res["working_set_evictions"] > 0),
        "mglru_cache_hit_rate": round(m_res["hits"] / (m_res["hits"] + m_res["page_faults"]), 4) if (m_res["hits"] + m_res["page_faults"]) > 0 else 0.0,
        "legacy_cache_hit_rate": round(l_res["hits"] / (l_res["hits"] + l_res["page_faults"]), 4) if (l_res["hits"] + l_res["page_faults"]) > 0 else 0.0
    }
    
    out = {
        "mglru": m_res,
        "legacy_2list": l_res,
        "analysis": analysis
    }
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
