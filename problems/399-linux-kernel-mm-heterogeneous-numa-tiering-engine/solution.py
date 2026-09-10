# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #399 Solution:
Linux Kernel Memory Management: Heterogeneous NUMA Memory Tiering Engine
"""
import sys
import json

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class MemoryTier:
    def __init__(self, tier_id, name, capacity_pages, latency_ns, bandwidth_gbps):
        self.tier_id = int(tier_id)
        self.name = name
        self.capacity_pages = int(capacity_pages)
        self.latency_ns = int(latency_ns)
        self.bandwidth_gbps = float(bandwidth_gbps)
        self.pages = {}

    @property
    def free_pages(self):
        return self.capacity_pages - len(self.pages)

class PageRecord:
    def __init__(self, page_id, tier_id, initial_hotness=0):
        self.page_id = str(page_id)
        self.tier_id = int(tier_id)
        self.access_count = int(initial_hotness)
        self.last_access_tick = 0
        self.numa_hinting_faults = 0

    def to_dict(self):
        return {
            "page_id": self.page_id,
            "tier_id": self.tier_id,
            "access_count": self.access_count,
            "numa_hinting_faults": self.numa_hinting_faults
        }

class NUMATieringEngine:
    def __init__(self, config):
        self.fast_capacity = int(config.get("fast_capacity_pages", 10))
        self.slow_capacity = int(config.get("slow_capacity_pages", 50))
        self.hot_threshold_faults = int(config.get("hot_threshold_faults", 3))
        self.max_migrations_per_tick = int(config.get("max_migrations_per_tick", 2))

        self.tiers = {
            0: MemoryTier(0, "FAST_TIER_0", self.fast_capacity, latency_ns=60, bandwidth_gbps=800.0),
            1: MemoryTier(1, "SLOW_TIER_1", self.slow_capacity, latency_ns=180, bandwidth_gbps=150.0)
        }
        self.pages = {}
        self.current_tick = 0

        self.stats = {
            "numa_hinting_faults": 0,
            "promotions_to_fast": 0,
            "demotions_to_slow": 0,
            "throttled_migrations": 0,
            "total_accesses": 0
        }
        self.migration_log = []

    def allocate_page(self, page_id, preferred_tier=0):
        target_tier = preferred_tier
        if self.tiers[target_tier].free_pages <= 0:
            target_tier = 1 if preferred_tier == 0 else 0
        p = PageRecord(page_id, target_tier)
        self.pages[page_id] = p
        self.tiers[target_tier].pages[page_id] = p
        return p

    def record_access(self, page_id, is_hinting_fault=False):
        self.current_tick += 1
        self.stats["total_accesses"] += 1
        if page_id not in self.pages:
            return {"status": "NOT_FOUND"}

        p = self.pages[page_id]
        p.access_count += 1
        p.last_access_tick = self.current_tick

        if is_hinting_fault:
            p.numa_hinting_faults += 1
            self.stats["numa_hinting_faults"] += 1

        return {"status": "OK", "page": p.to_dict()}

    def balance_and_migrate(self):
        self.current_tick += 1
        promotions_done = 0

        t1_candidates = [
            p for p in self.tiers[1].pages.values()
            if p.numa_hinting_faults >= self.hot_threshold_faults
        ]
        t1_candidates.sort(key=lambda p: (p.numa_hinting_faults, p.access_count, -int(p.page_id.replace("P", "") if p.page_id.replace("P", "").isdigit() else 0)), reverse=True)

        for hot_page in t1_candidates:
            if promotions_done >= self.max_migrations_per_tick:
                self.stats["throttled_migrations"] += 1
                break

            if self.tiers[0].free_pages <= 0:
                t0_pages = list(self.tiers[0].pages.values())
                if not t0_pages:
                    break
                coldest_t0 = min(t0_pages, key=lambda p: (p.numa_hinting_faults, p.access_count, p.last_access_tick))
                if hot_page.numa_hinting_faults <= coldest_t0.numa_hinting_faults and hot_page.access_count <= coldest_t0.access_count:
                    continue

                del self.tiers[0].pages[coldest_t0.page_id]
                coldest_t0.tier_id = 1
                coldest_t0.numa_hinting_faults = 0
                self.tiers[1].pages[coldest_t0.page_id] = coldest_t0
                self.stats["demotions_to_slow"] += 1

                self.migration_log.append({
                    "tick": self.current_tick,
                    "action": "DEMOTE",
                    "page_id": coldest_t0.page_id,
                    "from_tier": 0,
                    "to_tier": 1
                })

            del self.tiers[1].pages[hot_page.page_id]
            hot_page.tier_id = 0
            hot_page.numa_hinting_faults = 0
            self.tiers[0].pages[hot_page.page_id] = hot_page
            self.stats["promotions_to_fast"] += 1
            promotions_done += 1

            self.migration_log.append({
                "tick": self.current_tick,
                "action": "PROMOTE",
                "page_id": hot_page.page_id,
                "from_tier": 1,
                "to_tier": 0
            })

    def run_simulation(self, operations):
        for op in operations:
            act = op["action"]
            if act == "ALLOC":
                self.allocate_page(op["page_id"], op.get("preferred_tier", 0))
            elif act == "ACCESS":
                self.record_access(op["page_id"], is_hinting_fault=op.get("is_hinting_fault", False))
            elif act == "BALANCE":
                self.balance_and_migrate()

        return self.get_summary()

    def get_summary(self):
        fast_pages = sorted(list(self.tiers[0].pages.keys()))
        slow_pages = sorted(list(self.tiers[1].pages.keys()))
        return {
            "fast_tier_occupancy": f"{len(fast_pages)}/{self.fast_capacity}",
            "slow_tier_occupancy": f"{len(slow_pages)}/{self.slow_capacity}",
            "stats": self.stats,
            "fast_tier_pages": fast_pages,
            "slow_tier_pages": slow_pages,
            "migration_log": self.migration_log
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    operations = data.get("operations", [])
    engine = NUMATieringEngine(config)
    res = engine.run_simulation(operations)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
