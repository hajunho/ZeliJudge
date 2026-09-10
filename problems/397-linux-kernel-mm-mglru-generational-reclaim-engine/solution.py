# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #397 Solution:
Linux Kernel Memory Management: Multi-Gen LRU (MGLRU) Generational Reclaim Engine
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class PageFolio:
    def __init__(self, page_id, size_bytes=4096, initial_gen=0, initial_tier=0):
        self.page_id = str(page_id)
        self.size_bytes = int(size_bytes)
        self.gen = int(initial_gen)
        self.tier = int(initial_tier)
        self.referenced = False
        self.evicted = False

    def to_dict(self):
        return {
            "page_id": self.page_id,
            "size_bytes": self.size_bytes,
            "gen": self.gen,
            "tier": self.tier,
            "referenced": self.referenced,
            "evicted": self.evicted
        }

class MGLRUEngine:
    def __init__(self, config):
        self.max_nr_gens = int(config.get("max_nr_gens", 4))
        self.min_seq = 0
        self.max_seq = 0
        self.pages = {}
        self.gens = {0: []}
        self.evicted_pages = []
        self.promoted_pages = []
        self.total_reclaimed_bytes = 0

    def add_page(self, page_id, size_bytes=4096, tier=0):
        p = PageFolio(page_id, size_bytes, initial_gen=self.max_seq, initial_tier=tier)
        self.pages[page_id] = p
        self.gens[self.max_seq].append(page_id)
        return p

    def record_access(self, page_id):
        if page_id in self.pages and not self.pages[page_id].evicted:
            p = self.pages[page_id]
            p.referenced = True
            if p.tier < 3:
                p.tier += 1

    def inc_max_seq(self):
        new_max = self.max_seq + 1
        self.gens[new_max] = []

        for g in range(self.min_seq, self.max_seq + 1):
            still_in_g = []
            for pid in self.gens[g]:
                p = self.pages[pid]
                if p.evicted:
                    continue
                if p.referenced:
                    p.referenced = False
                    p.gen = new_max
                    self.gens[new_max].append(pid)
                    self.promoted_pages.append(pid)
                else:
                    still_in_g.append(pid)
            self.gens[g] = still_in_g

        self.max_seq = new_max

        while (self.max_seq - self.min_seq + 1) > self.max_nr_gens:
            self.try_evict_from_min_seq(reclaim_all=True)

    def try_evict_from_min_seq(self, bytes_to_reclaim=None, reclaim_all=False):
        reclaimed = 0

        while (self.min_seq < self.max_seq) or reclaim_all:
            g_pages = self.gens.get(self.min_seq, [])
            if not g_pages:
                if self.min_seq < self.max_seq:
                    del self.gens[self.min_seq]
                    self.min_seq += 1
                    continue
                else:
                    break

            active_pids = [pid for pid in g_pages if not self.pages[pid].evicted]
            if not active_pids:
                del self.gens[self.min_seq]
                self.min_seq += 1
                continue

            remaining_pids = []
            for pid in active_pids:
                p = self.pages[pid]
                if p.referenced:
                    p.referenced = False
                    p.gen = self.max_seq
                    self.gens[self.max_seq].append(pid)
                    self.promoted_pages.append(pid)
                    continue

                if p.tier > 0:
                    p.tier -= 1
                    remaining_pids.append(pid)
                    continue

                p.evicted = True
                self.evicted_pages.append(pid)
                reclaimed += p.size_bytes
                self.total_reclaimed_bytes += p.size_bytes

                if bytes_to_reclaim and reclaimed >= bytes_to_reclaim and not reclaim_all:
                    break

            self.gens[self.min_seq] = [pid for pid in remaining_pids if not self.pages[pid].evicted]

            if not self.gens[self.min_seq]:
                if self.min_seq < self.max_seq:
                    del self.gens[self.min_seq]
                    self.min_seq += 1

            if bytes_to_reclaim and reclaimed >= bytes_to_reclaim and not reclaim_all:
                break

            if not reclaim_all and (self.max_seq - self.min_seq + 1) <= self.max_nr_gens:
                break

        return reclaimed

    def run_simulation(self, operations):
        for op in operations:
            act = op["action"]
            if act == "ADD_PAGE":
                self.add_page(op["page_id"], op.get("size_bytes", 4096), op.get("tier", 0))
            elif act == "ACCESS":
                self.record_access(op["page_id"])
            elif act == "AGING_TICK":
                self.inc_max_seq()
            elif act == "EVICT":
                bytes_req = op.get("bytes", 4096)
                self.try_evict_from_min_seq(bytes_to_reclaim=bytes_req)

        return self.get_summary()

    def get_summary(self):
        active_pages = {pid: self.pages[pid].to_dict() for pid in sorted(self.pages.keys())}
        gen_distribution = {}
        for g in range(self.min_seq, self.max_seq + 1):
            if g in self.gens:
                gen_distribution[str(g)] = [pid for pid in self.gens[g] if not self.pages[pid].evicted]

        return {
            "min_seq": self.min_seq,
            "max_seq": self.max_seq,
            "nr_active_gens": self.max_seq - self.min_seq + 1,
            "total_reclaimed_bytes": self.total_reclaimed_bytes,
            "evicted_pages": self.evicted_pages,
            "promoted_pages": self.promoted_pages,
            "gen_distribution": gen_distribution,
            "pages": active_pages
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    operations = data.get("operations", [])
    engine = MGLRUEngine(config)
    res = engine.run_simulation(operations)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
