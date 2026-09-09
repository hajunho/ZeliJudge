import sys
from collections import defaultdict

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    num_cores = 2
    var_lines = {}
    actions = []
    mode = "CONFIG"

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "VARIABLES":
            mode = "VARIABLES"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "CORES":
                num_cores = int(parts[1])
        elif mode == "VARIABLES":
            vname = parts[0]
            offset = int(parts[1])
            var_lines[vname] = offset // 64
        elif mode == "ACTIONS":
            actions.append(parts)

    all_cores = [f"C{i}" for i in range(num_cores)]
    valid_cores_set = set(all_cores)

    # states[core][line_id] = 'I', 'S', 'E', 'M'
    states = {c: defaultdict(lambda: 'I') for c in all_cores}

    total_cycles = 0
    total_hits = 0
    total_misses = 0
    total_upgrades = 0
    total_invals = 0

    out_lines = []
    act_idx = 1

    for act in actions:
        cmd = act[0]
        core = act[1]
        var = act[2]

        if core not in valid_cores_set:
            out_lines.append(f"ACT {act_idx} {cmd} {core} {var} ERROR:INVALID_CORE")
            act_idx += 1
            continue

        if var not in var_lines:
            out_lines.append(f"ACT {act_idx} {cmd} {core} {var} ERROR:VARIABLE_NOT_FOUND")
            act_idx += 1
            continue

        line_id = var_lines[var]
        before = states[core][line_id]

        if cmd == "READ":
            if before in ('M', 'E', 'S'):
                after = before
                result = "HIT"
                invals = 0
                cycles = 1
                total_hits += 1
            else:  # before == 'I'
                other_has = False
                for other in all_cores:
                    if other != core:
                        ostate = states[other][line_id]
                        if ostate == 'M':
                            states[other][line_id] = 'S'
                            other_has = True
                        elif ostate == 'E':
                            states[other][line_id] = 'S'
                            other_has = True
                        elif ostate == 'S':
                            other_has = True
                after = 'S' if other_has else 'E'
                states[core][line_id] = after
                result = "MISS"
                invals = 0
                cycles = 100
                total_misses += 1

        elif cmd == "WRITE":
            if before in ('M', 'E'):
                after = 'M'
                states[core][line_id] = 'M'
                result = "HIT"
                invals = 0
                cycles = 1
                total_hits += 1
            elif before == 'S':
                invals = 0
                for other in all_cores:
                    if other != core:
                        if states[other][line_id] != 'I':
                            states[other][line_id] = 'I'
                            invals += 1
                after = 'M'
                states[core][line_id] = 'M'
                result = "UPGRADE"
                cycles = 100
                total_upgrades += 1
            else:  # before == 'I'
                invals = 0
                for other in all_cores:
                    if other != core:
                        if states[other][line_id] != 'I':
                            states[other][line_id] = 'I'
                            invals += 1
                after = 'M'
                states[core][line_id] = 'M'
                result = "MISS"
                cycles = 100
                total_misses += 1

        total_cycles += cycles
        total_invals += invals

        out_lines.append(f"ACT {act_idx} {cmd} {core} {var} LINE:{line_id} BEFORE:{before} AFTER:{after} RESULT:{result} INVALS:{invals} CYCLES:{cycles}")
        act_idx += 1

    out_lines.append(f"SUMMARY TOTAL_ACTIONS:{len(actions)}")
    out_lines.append(f"SUMMARY TOTAL_CYCLES:{total_cycles}")
    out_lines.append(f"SUMMARY TOTAL_HITS:{total_hits}")
    out_lines.append(f"SUMMARY TOTAL_MISSES:{total_misses}")
    out_lines.append(f"SUMMARY TOTAL_UPGRADES:{total_upgrades}")
    out_lines.append(f"SUMMARY TOTAL_INVALIDATIONS:{total_invals}")
    if total_invals > 0:
        out_lines.append(f"SUMMARY FALSE_SHARING_DETECTED: TRUE (INVALIDATIONS:{total_invals})")
    else:
        out_lines.append("SUMMARY FALSE_SHARING_DETECTED: FALSE")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
