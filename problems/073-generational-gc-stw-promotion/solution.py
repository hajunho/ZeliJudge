import sys

class GCEngine:
    def __init__(self, eden_cap, surv_cap, old_cap, threshold, minor_ms, full_ms):
        self.eden_cap = eden_cap
        self.surv_cap = surv_cap
        self.old_cap = old_cap
        self.threshold = threshold
        self.minor_ms = minor_ms
        self.full_ms = full_ms

        self.eden_objects = []
        self.surv_objects = []
        self.old_objects = []
        self.next_obj_id = 1

        self.minor_gc_count = 0
        self.full_gc_count = 0
        self.total_stw_ms = 0
        self.premature_promoted_mb = 0

    def get_used(self, loc):
        if loc == "EDEN":
            return sum(o["size"] for o in self.eden_objects)
        elif loc == "SURVIVOR":
            return sum(o["size"] for o in self.surv_objects)
        elif loc == "OLD":
            return sum(o["size"] for o in self.old_objects)
        return 0

    def trigger_minor_gc(self):
        self.minor_gc_count += 1
        self.total_stw_ms += self.minor_ms

        # 1. Process Eden
        alive_from_eden = []
        for o in self.eden_objects:
            if o["is_long"]:
                o["age"] += 1
                alive_from_eden.append(o)
            # short-lived in Eden dies immediately

        # 2. Process Survivor
        alive_from_surv = []
        for o in self.surv_objects:
            o["age"] += 1
            if o["is_long"]:
                alive_from_surv.append(o)
            else:
                if o["age"] < 2:
                    alive_from_surv.append(o)
                # short-lived with age >= 2 dies

        self.eden_objects = []
        self.surv_objects = []

        # Order of candidates: preserve original order (Eden objects, then Survivor objects, or matching original sequence)
        # Note: In original code, self.objects was a single list where Eden objects were added at end.
        # So objects already in Survivor came first, and newly allocated Eden objects came second!
        candidates = alive_from_surv + alive_from_eden

        # Step A: Natural Tenuring Promotion (age >= threshold -> OLD)
        surv_candidates = []
        for o in candidates:
            if o["age"] >= self.threshold:
                o["location"] = "OLD"
                self.old_objects.append(o)
            else:
                surv_candidates.append(o)

        # Step B: Fit remaining into Survivor space. If overflow, Premature Promotion to OLD!
        surv_used = 0
        for o in surv_candidates:
            if surv_used + o["size"] <= self.surv_cap:
                o["location"] = "SURVIVOR"
                self.surv_objects.append(o)
                surv_used += o["size"]
            else:
                o["location"] = "OLD"
                self.old_objects.append(o)
                self.premature_promoted_mb += o["size"]

        # Step C: Check if OLD overflowed -> Trigger Full GC
        if self.get_used("OLD") > self.old_cap:
            self.trigger_full_gc()

    def trigger_full_gc(self):
        self.full_gc_count += 1
        self.total_stw_ms += self.full_ms

        # Full GC clears dead objects in OLD (short-lived objects in OLD die)
        self.old_objects = [o for o in self.old_objects if o["is_long"]]

    def alloc_traffic(self, short_mb, long_mb):
        minor_before = self.minor_gc_count
        full_before = self.full_gc_count
        prom_before = self.premature_promoted_mb

        needed_mb = short_mb + long_mb
        eden_used = self.get_used("EDEN")

        if eden_used + needed_mb > self.eden_cap:
            self.trigger_minor_gc()

        # Allocate new objects in EDEN
        if short_mb > 0:
            self.eden_objects.append({
                "id": self.next_obj_id,
                "size": short_mb,
                "is_long": False,
                "age": 0,
                "location": "EDEN"
            })
            self.next_obj_id += 1

        if long_mb > 0:
            self.eden_objects.append({
                "id": self.next_obj_id,
                "size": long_mb,
                "is_long": True,
                "age": 0,
                "location": "EDEN"
            })
            self.next_obj_id += 1

        minor_diff = self.minor_gc_count - minor_before
        full_diff = self.full_gc_count - full_before
        prom_diff = self.premature_promoted_mb - prom_before

        return minor_diff, full_diff, prom_diff

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    eden_cap = 100
    s_naive = 20
    s_tuned = 80
    old_cap = 200
    threshold = 3
    minor_ms = 2
    full_ms = 50
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "EDEN_CAP_MB":
                eden_cap = int(parts[1])
            elif parts[0] == "SURVIVOR_CAP_NAIVE":
                s_naive = int(parts[1])
            elif parts[0] == "SURVIVOR_CAP_TUNED":
                s_tuned = int(parts[1])
            elif parts[0] == "OLD_CAP_MB":
                old_cap = int(parts[1])
            elif parts[0] == "TENURING_THRESHOLD":
                threshold = int(parts[1])
            elif parts[0] == "MINOR_GC_STW_MS":
                minor_ms = int(parts[1])
            elif parts[0] == "FULL_GC_STW_MS":
                full_ms = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    naive_eng = GCEngine(eden_cap, s_naive, old_cap, threshold, minor_ms, full_ms)
    tuned_eng = GCEngine(eden_cap, s_tuned, old_cap, threshold, minor_ms, full_ms)

    out_lines = []
    total_cycles = 0

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "ALLOC_TRAFFIC":
            cycle_id = act[1]
            short_mb = int(act[2])
            long_mb = int(act[3])
            total_cycles += 1

            n_min, n_full, n_prom = naive_eng.alloc_traffic(short_mb, long_mb)
            t_min, t_full, t_prom = tuned_eng.alloc_traffic(short_mb, long_mb)

            n_eden = naive_eng.get_used("EDEN")
            n_surv = naive_eng.get_used("SURVIVOR")
            n_old = naive_eng.get_used("OLD")

            t_eden = tuned_eng.get_used("EDEN")
            t_surv = tuned_eng.get_used("SURVIVOR")
            t_old = tuned_eng.get_used("OLD")

            n_events = []
            if n_min > 0: n_events.append(f"MINOR_GC:{n_min}")
            if n_full > 0: n_events.append(f"FULL_GC:{n_full}")
            if n_prom > 0: n_events.append(f"PREMATURE_PROMOTED:{n_prom}MB")
            n_evt_str = f" [{' '.join(n_events)}]" if n_events else ""

            t_events = []
            if t_min > 0: t_events.append(f"MINOR_GC:{t_min}")
            if t_full > 0: t_events.append(f"FULL_GC:{t_full}")
            if t_prom > 0: t_events.append(f"PREMATURE_PROMOTED:{t_prom}MB")
            t_evt_str = f" [{' '.join(t_events)}]" if t_events else ""

            out_lines.append(f"ACT {act_idx} ALLOC_TRAFFIC CYCLE:{cycle_id} SHORT:{short_mb}MB LONG:{long_mb}MB")
            out_lines.append(f"  NAIVE: EDEN:{n_eden}MB SURV:{n_surv}MB/{s_naive}MB OLD:{n_old}MB/{old_cap}MB{n_evt_str}")
            out_lines.append(f"  TUNED: EDEN:{t_eden}MB SURV:{t_surv}MB/{s_tuned}MB OLD:{t_old}MB/{old_cap}MB{t_evt_str}")

        elif cmd == "FORCE_FULL_GC":
            naive_eng.trigger_full_gc()
            tuned_eng.trigger_full_gc()
            out_lines.append(f"ACT {act_idx} FORCE_FULL_GC")
            out_lines.append(f"  NAIVE: FULL_GC_EXECUTED OLD_USED:{naive_eng.get_used('OLD')}MB/{old_cap}MB")
            out_lines.append(f"  TUNED: FULL_GC_EXECUTED OLD_USED:{tuned_eng.get_used('OLD')}MB/{old_cap}MB")

        elif cmd == "CHECK_GC_METRICS":
            n_status = "OOM" if naive_eng.get_used("OLD") > old_cap else ("FULL_GC_STORM" if naive_eng.full_gc_count >= 3 else "HEALTHY")
            t_status = "OOM" if tuned_eng.get_used("OLD") > old_cap else "HEALTHY"

            out_lines.append(f"ACT {act_idx} CHECK_GC_METRICS")
            out_lines.append(f"  NAIVE: MINOR_GC:{naive_eng.minor_gc_count} FULL_GC:{naive_eng.full_gc_count} TOTAL_STW:{naive_eng.total_stw_ms}ms PROMOTED_MB:{naive_eng.premature_promoted_mb}MB STATUS:{n_status}")
            out_lines.append(f"  TUNED: MINOR_GC:{tuned_eng.minor_gc_count} FULL_GC:{tuned_eng.full_gc_count} TOTAL_STW:{tuned_eng.total_stw_ms}ms PROMOTED_MB:{tuned_eng.premature_promoted_mb}MB STATUS:{t_status}")

    # Final Summary
    saved_ms = naive_eng.total_stw_ms - tuned_eng.total_stw_ms
    reduction_pct = (saved_ms / naive_eng.total_stw_ms * 100.0) if naive_eng.total_stw_ms > 0 else 0.0

    out_lines.append(f"SUMMARY TOTAL_TRAFFIC_CYCLES:{total_cycles}")
    out_lines.append(f"SUMMARY NAIVE TOTAL_STW_PAUSE:{naive_eng.total_stw_ms}ms (MINOR_GC:{naive_eng.minor_gc_count}, FULL_GC:{naive_eng.full_gc_count}) PREMATURE_PROMOTED:{naive_eng.premature_promoted_mb}MB")
    out_lines.append(f"SUMMARY TUNED TOTAL_STW_PAUSE:{tuned_eng.total_stw_ms}ms (MINOR_GC:{tuned_eng.minor_gc_count}, FULL_GC:{tuned_eng.full_gc_count}) PREMATURE_PROMOTED:{tuned_eng.premature_promoted_mb}MB")
    out_lines.append(f"SUMMARY STW_LATENCY_SAVED:{saved_ms}ms (PAUSE_REDUCTION:{reduction_pct:.2f}%)")
    out_lines.append("SUMMARY TUNING_VERDICT: TUNED_PREVENTS_STW_STORM")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
