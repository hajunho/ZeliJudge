import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    page_size_kb = 4
    system_ram_kb = 65536
    initial_pages = 10
    actions = []
    mode = "CONFIG"

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
            if parts[0] == "PAGE_SIZE_KB":
                page_size_kb = int(parts[1])
            elif parts[0] == "TOTAL_SYSTEM_RAM_KB":
                system_ram_kb = int(parts[1])
            elif parts[0] == "INITIAL_PAGES":
                initial_pages = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    pages = {str(i): "PRIVATE" for i in range(initial_pages)}
    total_mem_kb = initial_pages * page_size_kb
    initial_mem_kb = total_mem_kb
    peak_mem_kb = total_mem_kb

    active_bgsave = False
    session_shared_pages = 0
    session_dirty_count = 0
    total_bgsave_sessions = 0
    total_cow_faults = 0
    oom_triggered_ever = False
    max_excess_kb = 0

    out_lines = []
    act_idx = 1

    for act in actions:
        cmd = act[0]

        if cmd == "BGSAVE_START":
            if active_bgsave:
                out_lines.append(f"ACT {act_idx} BGSAVE_START ERROR:BGSAVE_ALREADY_IN_PROGRESS TOTAL_MEM_KB:{total_mem_kb}")
            else:
                active_bgsave = True
                total_bgsave_sessions += 1
                session_shared_pages = len(pages)
                session_dirty_count = 0
                for pid in pages:
                    pages[pid] = "COW_SHARED"
                out_lines.append(f"ACT {act_idx} BGSAVE_START SHARED_PAGES:{session_shared_pages} TOTAL_MEM_KB:{total_mem_kb}")

        elif cmd == "READ":
            pid = act[1]
            if pid not in pages:
                out_lines.append(f"ACT {act_idx} READ P{pid} ERROR:PAGE_NOT_FOUND TOTAL_MEM_KB:{total_mem_kb}")
            else:
                out_lines.append(f"ACT {act_idx} READ P{pid} COW_FAULT:FALSE TOTAL_MEM_KB:{total_mem_kb}")

        elif cmd == "WRITE":
            pid = act[1]
            if pid not in pages:
                out_lines.append(f"ACT {act_idx} WRITE P{pid} ERROR:PAGE_NOT_FOUND TOTAL_MEM_KB:{total_mem_kb}")
            else:
                if active_bgsave and pages[pid] == "COW_SHARED":
                    total_cow_faults += 1
                    session_dirty_count += 1
                    pages[pid] = "PRIVATE"
                    total_mem_kb += page_size_kb
                    if total_mem_kb > peak_mem_kb:
                        peak_mem_kb = total_mem_kb

                    if total_mem_kb > system_ram_kb:
                        oom_triggered_ever = True
                        excess = total_mem_kb - system_ram_kb
                        if excess > max_excess_kb:
                            max_excess_kb = excess
                        out_lines.append(f"ACT {act_idx} WRITE P{pid} COW_FAULT:TRUE STATUS:DIRTY_COPIED MEM_INC_KB:+{page_size_kb} TOTAL_MEM_KB:{total_mem_kb} [OOM_KILLER_TRIGGERED]")
                    else:
                        out_lines.append(f"ACT {act_idx} WRITE P{pid} COW_FAULT:TRUE STATUS:DIRTY_COPIED MEM_INC_KB:+{page_size_kb} TOTAL_MEM_KB:{total_mem_kb}")
                else:
                    out_lines.append(f"ACT {act_idx} WRITE P{pid} COW_FAULT:FALSE STATUS:ALREADY_PRIVATE MEM_INC_KB:0 TOTAL_MEM_KB:{total_mem_kb}")

        elif cmd == "ALLOC":
            pid = act[1]
            if pid in pages:
                out_lines.append(f"ACT {act_idx} ALLOC P{pid} ERROR:ALREADY_ALLOCATED TOTAL_MEM_KB:{total_mem_kb}")
            else:
                pages[pid] = "PRIVATE"
                total_mem_kb += page_size_kb
                if total_mem_kb > peak_mem_kb:
                    peak_mem_kb = total_mem_kb

                if total_mem_kb > system_ram_kb:
                    oom_triggered_ever = True
                    excess = total_mem_kb - system_ram_kb
                    if excess > max_excess_kb:
                        max_excess_kb = excess
                    out_lines.append(f"ACT {act_idx} ALLOC P{pid} STATUS:ALLOCATED MEM_INC_KB:+{page_size_kb} TOTAL_MEM_KB:{total_mem_kb} [OOM_KILLER_TRIGGERED]")
                else:
                    out_lines.append(f"ACT {act_idx} ALLOC P{pid} STATUS:ALLOCATED MEM_INC_KB:+{page_size_kb} TOTAL_MEM_KB:{total_mem_kb}")

        elif cmd == "BGSAVE_FINISH":
            if not active_bgsave:
                out_lines.append(f"ACT {act_idx} BGSAVE_FINISH ERROR:NO_ACTIVE_BGSAVE TOTAL_MEM_KB:{total_mem_kb}")
            else:
                active_bgsave = False
                for pid in pages:
                    if pages[pid] == "COW_SHARED":
                        pages[pid] = "PRIVATE"
                released_kb = session_dirty_count * page_size_kb
                total_mem_kb -= released_kb
                dirty_ratio = (session_dirty_count / session_shared_pages * 100.0) if session_shared_pages > 0 else 0.0
                out_lines.append(f"ACT {act_idx} BGSAVE_FINISH DIRTY_PAGES:{session_dirty_count}/{session_shared_pages} ({dirty_ratio:.1f}%) RELEASED_KB:{released_kb} TOTAL_MEM_KB:{total_mem_kb}")

        act_idx += 1

    spike_ratio = (peak_mem_kb / initial_mem_kb) if initial_mem_kb > 0 else 1.00
    out_lines.append(f"SUMMARY TOTAL_ACTIONS:{len(actions)}")
    out_lines.append(f"SUMMARY TOTAL_BGSAVE_SESSIONS:{total_bgsave_sessions}")
    out_lines.append(f"SUMMARY TOTAL_COW_FAULTS:{total_cow_faults}")
    out_lines.append(f"SUMMARY INITIAL_MEM_KB:{initial_mem_kb}")
    out_lines.append(f"SUMMARY PEAK_MEM_KB:{peak_mem_kb} (SYSTEM_LIMIT_KB:{system_ram_kb})")
    out_lines.append(f"SUMMARY MEMORY_SPIKE_RATIO:{spike_ratio:.2f}x")
    if oom_triggered_ever:
        out_lines.append(f"SUMMARY OOM_INCIDENT: OOM_KILLER_INVOKED (MAX_EXCESS_KB:{max_excess_kb})")
    else:
        out_lines.append("SUMMARY OOM_INCIDENT: NONE")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
