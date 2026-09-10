import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def simulate_memcg(data):
    sys_cfg = data.get("system_config", {})
    psi_cfg = sys_cfg.get("psi_thresholds", {})
    some_warn = psi_cfg.get("some_warn_pct", 15.0)
    some_crit = psi_cfg.get("some_crit_pct", 35.0)
    full_crit = psi_cfg.get("full_crit_pct", 20.0)
    throttle_factor = sys_cfg.get("throttle_factor_ms", 50)
    max_throttle = sys_cfg.get("max_throttle_ms", 1000)

    cgroups_init = data.get("cgroups", [])
    cgroup_states = {}
    for cg in cgroups_init:
        cid = cg["id"]
        cgroup_states[cid] = {
            "id": cid,
            "memory_min_mb": cg.get("memory_min_mb", 0),
            "memory_low_mb": cg.get("memory_low_mb", 0),
            "memory_high_mb": cg.get("memory_high_mb", 0),
            "memory_max_mb": cg.get("memory_max_mb", None),
            "oom_score_adj": cg.get("oom_score_adj", 0),
            "oom_group": cg.get("oom_group", False),
            "anon_mb": cg.get("initial_anon_mb", 0),
            "file_mb": cg.get("initial_file_mb", 0),
            "total_usage_mb": cg.get("initial_anon_mb", 0) + cg.get("initial_file_mb", 0),
            "oom_kill_count": 0,
            "throttle_time_ms_total": 0,
            "psi_some_avg10": 0.0,
            "psi_full_avg10": 0.0,
            "status": "STATUS_HEALTHY"
        }

    # EWMA alpha for 1s sample with 10s window: 1 - exp(-1/10) ~ 0.09516258
    alpha10 = 1.0 - math.exp(-1.0 / 10.0)

    events = data.get("events", [])
    step_history = []

    for ev in events:
        step_idx = ev.get("step", len(step_history) + 1)
        allocs = ev.get("cgroup_allocations", {})
        global_pressure = ev.get("global_pressure_mb", 0)
        stalls = ev.get("stall_samples", {})

        # 1. Apply Allocations
        for cid, cg in cgroup_states.items():
            if cid in allocs:
                d_anon = allocs[cid].get("anon_delta_mb", 0)
                d_file = allocs[cid].get("file_delta_mb", 0)
                cg["anon_mb"] = max(0, cg["anon_mb"] + d_anon)
                cg["file_mb"] = max(0, cg["file_mb"] + d_file)
            cg["total_usage_mb"] = cg["anon_mb"] + cg["file_mb"]

        # 2. Local Limit Enforcement: memory.high (throttling & proactive reclaim)
        step_throttled = {}
        for cid, cg in cgroup_states.items():
            high = cg["memory_high_mb"]
            step_throttle_ms = 0
            if high and high > 0 and cg["total_usage_mb"] > high:
                overshoot_pct = ((cg["total_usage_mb"] - high) / high) * 100.0
                step_throttle_ms = min(max_throttle, round(overshoot_pct * throttle_factor))
                cg["throttle_time_ms_total"] += step_throttle_ms

                # Proactive reclaim in return to userspace
                needed = cg["total_usage_mb"] - high
                proactive_reclaim = min(cg["file_mb"], needed)
                cg["file_mb"] -= proactive_reclaim
                cg["total_usage_mb"] -= proactive_reclaim

            step_throttled[cid] = step_throttle_ms

        # 3. Local Limit Enforcement: memory.max & OOM Killer
        step_oom = {}
        for cid, cg in cgroup_states.items():
            max_limit = cg["memory_max_mb"]
            oom_killed = False
            if max_limit and max_limit > 0 and cg["total_usage_mb"] > max_limit:
                # Direct reclaim attempt
                needed = cg["total_usage_mb"] - max_limit
                direct_reclaim = min(cg["file_mb"], needed)
                cg["file_mb"] -= direct_reclaim
                cg["total_usage_mb"] -= direct_reclaim

                # Still over limit -> OOM
                if cg["total_usage_mb"] > max_limit:
                    oom_killed = True
                    cg["oom_kill_count"] += 1
                    if cg["oom_group"]:
                        # Kill whole cgroup
                        cg["anon_mb"] = 0
                        cg["file_mb"] = 0
                        cg["total_usage_mb"] = 0
                    else:
                        # Kill largest process: prune anon down to max_limit
                        cg["anon_mb"] = max(0, max_limit - cg["file_mb"])
                        cg["total_usage_mb"] = cg["anon_mb"] + cg["file_mb"]

            step_oom[cid] = oom_killed

        # 4. Global Reclaim Allocation across cgroups
        reclaimed_global = {}
        low_breached = False
        if global_pressure > 0:
            excesses = {}
            for cid, cg in cgroup_states.items():
                low = cg["memory_low_mb"]
                usage = cg["total_usage_mb"]
                if usage > low:
                    excesses[cid] = usage - low
                else:
                    excesses[cid] = 0

            total_excess = sum(excesses.values())
            if total_excess > 0:
                for cid, exc in excesses.items():
                    if exc > 0:
                        target = min(exc, round((exc / total_excess) * global_pressure))
                        file_avail = cgroup_states[cid]["file_mb"]
                        rec = min(target, file_avail)
                        cgroup_states[cid]["file_mb"] -= rec
                        cgroup_states[cid]["total_usage_mb"] -= rec
                        reclaimed_global[cid] = rec
                    else:
                        reclaimed_global[cid] = 0
            else:
                # Penetrate memory.low down to memory.min
                low_breached = True
                penetrate_excess = {}
                for cid, cg in cgroup_states.items():
                    min_lim = cg["memory_min_mb"]
                    usage = cg["total_usage_mb"]
                    if usage > min_lim:
                        penetrate_excess[cid] = usage - min_lim
                    else:
                        penetrate_excess[cid] = 0
                tot_pen = sum(penetrate_excess.values())
                if tot_pen > 0:
                    for cid, p_exc in penetrate_excess.items():
                        if p_exc > 0:
                            target = min(p_exc, round((p_exc / tot_pen) * global_pressure))
                            file_avail = cgroup_states[cid]["file_mb"]
                            rec = min(target, file_avail)
                            cgroup_states[cid]["file_mb"] -= rec
                            cgroup_states[cid]["total_usage_mb"] -= rec
                            reclaimed_global[cid] = rec
                        else:
                            reclaimed_global[cid] = 0

        # 5. PSI Calculation & Status Evaluation
        step_cgroup_metrics = {}
        for cid, cg in cgroup_states.items():
            sample_data = stalls.get(cid, {})
            active_t = sample_data.get("active_threads", 1)
            stalled_t = sample_data.get("stalled_threads", 0)
            all_stalled = sample_data.get("all_threads_stalled", False)

            sample_some_pct = (stalled_t / active_t * 100.0) if active_t > 0 else 0.0
            sample_full_pct = 100.0 if all_stalled else 0.0

            # Update EWMA
            cg["psi_some_avg10"] = round(alpha10 * sample_some_pct + (1.0 - alpha10) * cg["psi_some_avg10"], 2)
            cg["psi_full_avg10"] = round(alpha10 * sample_full_pct + (1.0 - alpha10) * cg["psi_full_avg10"], 2)

            # Determine Health Status & Action
            if step_oom.get(cid, False):
                status = "STATUS_OOM_KILLED"
                action = "RESTART_CONTAINER"
            elif cg["psi_full_avg10"] >= full_crit or cg["psi_some_avg10"] >= some_crit:
                status = "STATUS_CRITICAL_STALL"
                action = "SCALE_REPLICAS_OR_SHED_LOAD"
            elif cg["psi_some_avg10"] >= some_warn:
                status = "STATUS_PRESSURE_WARNING"
                action = "PROACTIVE_CACHE_TRIM"
            elif step_throttled.get(cid, 0) > 0:
                status = "STATUS_THROTTLED"
                action = "ALLOCATION_THROTTLED"
            else:
                status = "STATUS_HEALTHY"
                action = "NONE"

            cg["status"] = status

            step_cgroup_metrics[cid] = {
                "total_usage_mb": cg["total_usage_mb"],
                "anon_mb": cg["anon_mb"],
                "file_mb": cg["file_mb"],
                "throttle_delay_ms": step_throttled.get(cid, 0),
                "oom_killed": step_oom.get(cid, False),
                "global_reclaimed_mb": reclaimed_global.get(cid, 0),
                "psi_some_avg10": cg["psi_some_avg10"],
                "psi_full_avg10": cg["psi_full_avg10"],
                "status": status,
                "action": action
            }

        step_history.append({
            "step": step_idx,
            "low_protection_breached": low_breached,
            "cgroups": step_cgroup_metrics
        })

    cgroup_summaries = {}
    for cid, cg in cgroup_states.items():
        cgroup_summaries[cid] = {
            "final_usage_mb": cg["total_usage_mb"],
            "final_anon_mb": cg["anon_mb"],
            "final_file_mb": cg["file_mb"],
            "total_oom_kills": cg["oom_kill_count"],
            "total_throttle_ms": cg["throttle_time_ms_total"],
            "final_psi_some_avg10": cg["psi_some_avg10"],
            "final_psi_full_avg10": cg["psi_full_avg10"],
            "final_status": cg["status"]
        }

    return {
        "total_steps_simulated": len(step_history),
        "cgroup_summaries": cgroup_summaries,
        "step_history": step_history
    }

def solve(data):
    return simulate_memcg(data)

def main():
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return
        data = json.loads(raw)
        res = solve(data)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"Error: {e}\\n")

if __name__ == "__main__":
    main()
