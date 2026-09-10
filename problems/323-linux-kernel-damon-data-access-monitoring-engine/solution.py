import sys
import json
import copy

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def parse_int(val):
    if isinstance(val, str):
        return int(val, 0)
    return int(val)

class DAMONRegion:
    def __init__(self, start: int, end: int, nr_accesses: int = 0, age: int = 0):
        self.start = start
        self.end = end
        self.nr_accesses = nr_accesses
        self.last_nr_accesses = nr_accesses
        self.age = age

    @property
    def size(self) -> int:
        return self.end - self.start

    def to_dict(self):
        return {
            "start": f"0x{self.start:x}",
            "end": f"0x{self.end:x}",
            "size": self.size,
            "last_nr_accesses": self.last_nr_accesses,
            "age": self.age
        }

class DAMOSScheme:
    def __init__(self, cfg: dict):
        self.scheme_id = cfg["scheme_id"]
        self.action = cfg["action"] # PAGEOUT, LRU_PRIO, LRU_DEPRIO, STAT
        self.min_sz = parse_int(cfg.get("min_sz", 0))
        self.max_sz = parse_int(cfg.get("max_sz", 0x7FFFFFFFFFFFFFFF))
        self.min_nr_accesses = parse_int(cfg.get("min_nr_accesses", 0))
        self.max_nr_accesses = parse_int(cfg.get("max_nr_accesses", 1000000))
        self.min_age = parse_int(cfg.get("min_age", 0))
        self.max_age = parse_int(cfg.get("max_age", 1000000))
        self.sz_quota_bytes = parse_int(cfg.get("sz_quota_bytes", 0))
        self.weight_sz = parse_int(cfg.get("weight_sz", 1))
        self.weight_nr_accesses = parse_int(cfg.get("weight_nr_accesses", 1))
        self.weight_age = parse_int(cfg.get("weight_age", 1))

        self.nr_tried = 0
        self.sz_tried = 0
        self.nr_applied = 0
        self.sz_applied = 0
        self.quota_exceeds = 0

    def matches(self, region: DAMONRegion) -> bool:
        sz = region.size
        acc = region.last_nr_accesses
        age = region.age
        if not (self.min_sz <= sz <= self.max_sz):
            return False
        if not (self.min_nr_accesses <= acc <= self.max_nr_accesses):
            return False
        if not (self.min_age <= age <= self.max_age):
            return False
        return True

    def calculate_score(self, region: DAMONRegion) -> int:
        pages = region.size // 4096
        return (self.weight_sz * pages + 
                self.weight_nr_accesses * region.last_nr_accesses + 
                self.weight_age * region.age)

    def to_dict(self):
        return {
            "scheme_id": self.scheme_id,
            "action": self.action,
            "nr_tried": self.nr_tried,
            "sz_tried": self.sz_tried,
            "nr_applied": self.nr_applied,
            "sz_applied": self.sz_applied,
            "quota_exceeds": self.quota_exceeds
        }

class DAMONEngine:
    def __init__(self, raw_config: dict):
        config = copy.deepcopy(raw_config)
        self.base_addr = parse_int(config.get("base_addr", 0x10000000))
        self.limit_addr = parse_int(config.get("limit_addr", 0x50000000))
        self.min_nr_regions = parse_int(config.get("min_nr_regions", 5))
        self.max_nr_regions = parse_int(config.get("max_nr_regions", 50))
        self.sample_interval_us = parse_int(config.get("sample_interval_us", 5000))
        self.aggr_interval_us = parse_int(config.get("aggr_interval_us", 100000))
        self.samples_per_aggr = max(1, self.aggr_interval_us // self.sample_interval_us)
        
        self.merge_threshold = parse_int(config.get("merge_threshold", 2))
        self.age_merge_threshold = parse_int(config.get("age_merge_threshold", 5))
        self.max_region_size = parse_int(config.get("max_region_size", 0x10000000))

        self.current_tick = 0
        self.aggr_count = 0
        
        init_regions_cfg = config.get("initial_regions", [])
        self.regions = []
        if init_regions_cfg:
            for r_cfg in init_regions_cfg:
                self.regions.append(DAMONRegion(
                    start=parse_int(r_cfg["start"]),
                    end=parse_int(r_cfg["end"]),
                    nr_accesses=parse_int(r_cfg.get("nr_accesses", 0)),
                    age=parse_int(r_cfg.get("age", 0))
                ))
        else:
            total_sz = self.limit_addr - self.base_addr
            step = (total_sz // self.min_nr_regions // 4096) * 4096
            curr = self.base_addr
            for i in range(self.min_nr_regions):
                nxt = curr + step if i < self.min_nr_regions - 1 else self.limit_addr
                self.regions.append(DAMONRegion(curr, nxt))
                curr = nxt

        self.schemes = {}
        for s_cfg in config.get("schemes", []):
            s = DAMOSScheme(s_cfg)
            self.schemes[s.scheme_id] = s

        self.total_pageout_bytes = 0
        self.total_prio_bytes = 0
        self.total_deprio_bytes = 0
        self.query_logs = []

    def sample_tick(self, accessed_addrs: list):
        self.current_tick += 1
        hit_regions = set()
        for raw_addr in accessed_addrs:
            addr = parse_int(raw_addr)
            for idx, r in enumerate(self.regions):
                if r.start <= addr < r.end:
                    hit_regions.add(idx)
                    break

        for idx in hit_regions:
            self.regions[idx].nr_accesses += 1

        if self.current_tick % self.samples_per_aggr == 0:
            self._do_aggregation()

    def force_aggregate(self):
        self._do_aggregation()

    def update_scheme(self, scheme_cfg: dict):
        s = DAMOSScheme(scheme_cfg)
        self.schemes[s.scheme_id] = s

    def _do_aggregation(self):
        self.aggr_count += 1
        
        # 1. Update age and last_nr_accesses
        for r in self.regions:
            if abs(r.nr_accesses - r.last_nr_accesses) <= 1:
                r.age += 1
            else:
                r.age = 0
            r.last_nr_accesses = r.nr_accesses
            r.nr_accesses = 0

        # 2. Merge regions if possible
        i = 0
        while i < len(self.regions) - 1:
            if len(self.regions) <= self.min_nr_regions:
                break
            r1 = self.regions[i]
            r2 = self.regions[i + 1]

            acc_diff = abs(r1.last_nr_accesses - r2.last_nr_accesses)
            age_diff = abs(r1.age - r2.age)
            combined_sz = r1.size + r2.size

            if (acc_diff <= self.merge_threshold and 
                age_diff <= self.age_merge_threshold and 
                combined_sz <= self.max_region_size):
                
                new_start = r1.start
                new_end = r2.end
                weighted_acc = (r1.last_nr_accesses * r1.size + r2.last_nr_accesses * r2.size) // combined_sz
                merged_age = min(r1.age, r2.age)
                
                merged_r = DAMONRegion(new_start, new_end, nr_accesses=0, age=merged_age)
                merged_r.last_nr_accesses = weighted_acc
                
                self.regions[i] = merged_r
                self.regions.pop(i + 1)
            else:
                i += 1

        # 3. Split regions if under max_nr_regions
        if len(self.regions) < self.max_nr_regions:
            candidates = []
            for idx, r in enumerate(self.regions):
                if r.size >= 8192:
                    score = r.size * (r.last_nr_accesses + 1)
                    candidates.append((score, idx))
            candidates.sort(key=lambda x: (x[0], -self.regions[x[1]].start), reverse=True)

            available_splits = self.max_nr_regions - len(self.regions)
            split_indices = set()
            for _, idx in candidates[:available_splits]:
                split_indices.add(idx)

            new_regions = []
            for idx, r in enumerate(self.regions):
                if idx in split_indices:
                    half = r.size // 2
                    half = (half // 4096) * 4096
                    if half == 0:
                        half = 4096
                    mid = r.start + half
                    
                    r_left = DAMONRegion(r.start, mid, nr_accesses=0, age=r.age)
                    r_left.last_nr_accesses = r.last_nr_accesses
                    
                    r_right = DAMONRegion(mid, r.end, nr_accesses=0, age=r.age)
                    r_right.last_nr_accesses = r.last_nr_accesses
                    
                    new_regions.append(r_left)
                    new_regions.append(r_right)
                else:
                    new_regions.append(r)
            self.regions = new_regions

        # 4. Apply DAMOS schemes
        self._apply_schemes()

    def _apply_schemes(self):
        for scheme_id in sorted(self.schemes.keys()):
            scheme = self.schemes[scheme_id]
            matching_regions = []
            for r in self.regions:
                if scheme.matches(r):
                    score = scheme.calculate_score(r)
                    matching_regions.append((score, r))

            scheme.nr_tried += len(matching_regions)
            scheme.sz_tried += sum(r.size for _, r in matching_regions)

            if not matching_regions:
                continue

            matching_regions.sort(key=lambda x: (x[0], -x[1].start), reverse=True)

            quota_rem = scheme.sz_quota_bytes if scheme.sz_quota_bytes > 0 else 0x7FFFFFFFFFFFFFFF
            for score, r in matching_regions:
                if r.size <= quota_rem:
                    quota_rem -= r.size
                    scheme.nr_applied += 1
                    scheme.sz_applied += r.size
                    self._execute_action(scheme.action, r.size)
                else:
                    if quota_rem > 0:
                        scheme.nr_applied += 1
                        scheme.sz_applied += quota_rem
                        self._execute_action(scheme.action, quota_rem)
                        quota_rem = 0
                    scheme.quota_exceeds += 1

    def _execute_action(self, action: str, bytes_applied: int):
        if action == "PAGEOUT":
            self.total_pageout_bytes += bytes_applied
        elif action == "LRU_PRIO":
            self.total_prio_bytes += bytes_applied
        elif action == "LRU_DEPRIO":
            self.total_deprio_bytes += bytes_applied

    def run_commands(self, commands: list):
        for cmd in commands:
            cmd_type = cmd["type"]
            if cmd_type == "SAMPLE":
                ticks = cmd.get("ticks", 1)
                accesses = cmd.get("accesses", [])
                for _ in range(ticks):
                    self.sample_tick(accesses)
            elif cmd_type == "FORCE_AGGR":
                self.force_aggregate()
            elif cmd_type == "UPDATE_SCHEME":
                self.update_scheme(cmd["scheme"])
            elif cmd_type == "QUERY_REGIONS":
                self.query_logs.append({
                    "tick": self.current_tick,
                    "nr_regions": len(self.regions),
                    "regions": [r.to_dict() for r in self.regions]
                })
            elif cmd_type == "QUERY_STATS":
                self.query_logs.append({
                    "tick": self.current_tick,
                    "aggr_count": self.aggr_count,
                    "actions": {
                        "total_pageout_bytes": self.total_pageout_bytes,
                        "total_prio_bytes": self.total_prio_bytes,
                        "total_deprio_bytes": self.total_deprio_bytes
                    }
                })

    def get_final_result(self) -> dict:
        return {
            "total_ticks": self.current_tick,
            "aggr_count": self.aggr_count,
            "nr_regions": len(self.regions),
            "regions": [r.to_dict() for r in self.regions],
            "schemes": {sid: self.schemes[sid].to_dict() for sid in sorted(self.schemes.keys())},
            "actions_summary": {
                "total_pageout_bytes": self.total_pageout_bytes,
                "total_prio_bytes": self.total_prio_bytes,
                "total_deprio_bytes": self.total_deprio_bytes
            },
            "query_logs": self.query_logs
        }

def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    data = json.loads(raw)
    engine = DAMONEngine(data["config"])
    engine.run_commands(data.get("commands", []))
    result = engine.get_final_result()
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
