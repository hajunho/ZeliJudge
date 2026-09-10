# -*- coding: utf-8 -*-
"""
ZeliJudge Problem #395 Solution:
Linux Kernel Memory Management: DAMON (Data Access Monitoring Framework) & DAMOS Proactive Reclamation Engine
"""
import sys
import json

# Windows UTF-8 encoding support
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class DamonRegion:
    def __init__(self, start, end, nr_accesses=0, age=0, last_nr_accesses=0):
        self.start = int(start)
        self.end = int(end)
        self.nr_accesses = int(nr_accesses)
        self.last_nr_accesses = int(last_nr_accesses)
        self.age = int(age)

    @property
    def size(self):
        return self.end - self.start

    def to_dict(self):
        return {
            "start": f"0x{self.start:04x}",
            "end": f"0x{self.end:04x}",
            "size_bytes": self.size,
            "nr_accesses": self.nr_accesses,
            "age": self.age
        }

class DamonEngine:
    def __init__(self, config):
        self.sample_interval = int(config.get("sample_interval", 5))
        self.aggr_interval = int(config.get("aggr_interval", 20))
        self.update_interval = int(config.get("update_interval", 40))
        self.min_regions = int(config.get("min_regions", 2))
        self.max_regions = int(config.get("max_regions", 8))
        self.merge_threshold = int(config.get("merge_threshold", 1))

        start_addr = int(config.get("start_addr", 0x1000))
        end_addr = int(config.get("end_addr", 0x9000))
        init_regions = int(config.get("init_regions", 4))

        total_size = end_addr - start_addr
        reg_size = total_size // init_regions
        self.regions = []
        cur = start_addr
        for i in range(init_regions):
            nxt = cur + reg_size if i < init_regions - 1 else end_addr
            self.regions.append(DamonRegion(cur, nxt))
            cur = nxt

        self.current_time = 0
        self.damos_schemes = config.get("damos_schemes", [])
        self.watermarks = config.get("watermarks", None)
        self.free_mem_pct = float(config.get("initial_free_mem_pct", 50.0))

        self.damos_actions_log = []
        self.aggregation_snapshots = []
        self.total_bytes_paged_out = 0
        self.total_bytes_willneed = 0
        self.total_bytes_cold = 0

    def find_region(self, addr):
        for r in self.regions:
            if r.start <= addr < r.end:
                return r
        return None

    def record_access(self, addr):
        r = self.find_region(addr)
        if r:
            r.nr_accesses += 1

    def is_damos_active(self):
        if not self.watermarks:
            return True
        high = float(self.watermarks.get("high", 80.0))
        if self.free_mem_pct >= high:
            return False
        return True

    def apply_damos(self):
        if not self.is_damos_active():
            return

        for scheme in self.damos_schemes:
            acc_min = scheme.get("min_access", 0)
            acc_max = scheme.get("max_access", 999999)
            age_min = scheme.get("min_age", 0)
            age_max = scheme.get("max_age", 999999)
            sz_min = scheme.get("min_size_bytes", 0)
            sz_max = scheme.get("max_size_bytes", 999999999)
            action = scheme.get("action")
            quota_bytes = scheme.get("quota_bytes", 999999999)
            bytes_applied = 0

            for r in self.regions:
                if (acc_min <= r.nr_accesses <= acc_max and
                    age_min <= r.age <= age_max and
                    sz_min <= r.size <= sz_max):

                    sz_to_apply = min(r.size, quota_bytes - bytes_applied)
                    if sz_to_apply > 0:
                        bytes_applied += sz_to_apply
                        if action == "PAGEOUT":
                            self.total_bytes_paged_out += sz_to_apply
                        elif action == "WILLNEED":
                            self.total_bytes_willneed += sz_to_apply
                        elif action == "COLD":
                            self.total_bytes_cold += sz_to_apply

                        self.damos_actions_log.append({
                            "timestamp": self.current_time,
                            "action": action,
                            "region_start": f"0x{r.start:04x}",
                            "region_end": f"0x{r.end:04x}",
                            "applied_bytes": sz_to_apply
                        })
                    if bytes_applied >= quota_bytes:
                        break

    def aggregate(self):
        self.apply_damos()

        snap = {
            "timestamp": self.current_time,
            "free_mem_pct": self.free_mem_pct,
            "num_regions": len(self.regions),
            "regions": [r.to_dict() for r in self.regions]
        }
        self.aggregation_snapshots.append(snap)

        for r in self.regions:
            if abs(r.nr_accesses - r.last_nr_accesses) <= self.merge_threshold:
                r.age += 1
            else:
                r.age = 0
            r.last_nr_accesses = r.nr_accesses
            r.nr_accesses = 0

    def merge_and_split(self):
        # Step 1: Merge adjacent
        new_regions = []
        i = 0
        while i < len(self.regions):
            can_merge = (i + 1 < len(self.regions)) and (len(self.regions) - (len(new_regions) + 1) + 1 >= self.min_regions)
            if can_merge and len(self.regions) > self.min_regions:
                r1 = self.regions[i]
                r2 = self.regions[i+1]
                if abs(r1.last_nr_accesses - r2.last_nr_accesses) <= self.merge_threshold:
                    merged = DamonRegion(
                        start=r1.start,
                        end=r2.end,
                        nr_accesses=0,
                        age=min(r1.age, r2.age),
                        last_nr_accesses=round((r1.last_nr_accesses * r1.size + r2.last_nr_accesses * r2.size) / (r1.size + r2.size))
                    )
                    new_regions.append(merged)
                    i += 2
                    continue
            new_regions.append(self.regions[i])
            i += 1
        self.regions = new_regions

        # Step 2: Split largest
        while len(self.regions) < self.max_regions:
            splittable = [r for r in self.regions if r.size >= 2]
            if not splittable:
                break
            largest = max(splittable, key=lambda r: r.size)
            idx = self.regions.index(largest)
            mid = largest.start + (largest.size // 2)
            r_left = DamonRegion(largest.start, mid, 0, largest.age, largest.last_nr_accesses)
            r_right = DamonRegion(mid, largest.end, 0, largest.age, largest.last_nr_accesses)
            self.regions = self.regions[:idx] + [r_left, r_right] + self.regions[idx+1:]

    def run_simulation(self, access_events, watermark_events=None, max_time=100):
        if watermark_events is None:
            watermark_events = []
        watermark_events = sorted(watermark_events, key=lambda e: e.get("time", 0))
        wm_idx = 0

        access_events = sorted(access_events, key=lambda e: e.get("time", 0))
        ev_idx = 0

        while self.current_time < max_time:
            while wm_idx < len(watermark_events) and watermark_events[wm_idx]["time"] <= self.current_time:
                self.free_mem_pct = float(watermark_events[wm_idx]["free_mem_pct"])
                wm_idx += 1

            while ev_idx < len(access_events) and access_events[ev_idx]["time"] <= self.current_time:
                self.record_access(access_events[ev_idx]["addr"])
                ev_idx += 1

            self.current_time += self.sample_interval

            if self.current_time % self.aggr_interval == 0:
                self.aggregate()

            if self.current_time % self.update_interval == 0:
                self.merge_and_split()

        return {
            "total_simulation_time": self.current_time,
            "final_regions_count": len(self.regions),
            "final_regions": [r.to_dict() for r in self.regions],
            "total_bytes_paged_out": self.total_bytes_paged_out,
            "total_bytes_willneed": self.total_bytes_willneed,
            "total_bytes_cold": self.total_bytes_cold,
            "damos_actions_count": len(self.damos_actions_log),
            "damos_actions_log": self.damos_actions_log,
            "aggregation_snapshots_count": len(self.aggregation_snapshots)
        }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    config = data.get("config", {})
    access_events = data.get("access_events", [])
    watermark_events = data.get("watermark_events", [])
    max_time = data.get("max_time", 100)
    engine = DamonEngine(config)
    res = engine.run_simulation(access_events, watermark_events, max_time)
    print(json.dumps(res, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
