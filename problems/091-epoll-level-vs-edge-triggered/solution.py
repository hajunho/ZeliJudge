import sys

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    modes = {}
    rcv_buf = {}
    et_ready = {}
    read_since_last_wait = {}
    last_ready_lt_fds = set()

    total_bytes_arrived = 0
    total_bytes_read = 0
    busy_loop_events = 0
    marooned_data_events = 0

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
        if mode == "ACTIONS":
            actions.append(parts)

    out_lines = []
    act_idx = 1

    for act in actions:
        cmd = act[0]

        if cmd == "REGISTER":
            fd = int(act[1])
            m = act[2]
            modes[fd] = m
            rcv_buf[fd] = 0
            et_ready[fd] = False
            read_since_last_wait[fd] = 0
            out_lines.append(f"ACT {act_idx} REGISTER FD:{fd} MODE:{m}")

        elif cmd == "ARRIVE":
            fd = int(act[1])
            b = int(act[2])
            rcv_buf[fd] = rcv_buf.get(fd, 0) + b
            total_bytes_arrived += b
            if modes.get(fd) == 'ET':
                et_ready[fd] = True
            out_lines.append(f"ACT {act_idx} ARRIVE FD:{fd} BYTES:+{b} TOTAL_BUF:{rcv_buf[fd]} READY:TRUE")

        elif cmd == "READ":
            fd = int(act[1])
            limit = int(act[2])
            cur_buf = rcv_buf.get(fd, 0)
            actual = min(cur_buf, limit)
            rcv_buf[fd] = cur_buf - actual
            total_bytes_read += actual
            read_since_last_wait[fd] = read_since_last_wait.get(fd, 0) + actual
            rem = rcv_buf[fd]

            if actual == 0:
                status = "EAGAIN"
            elif rem == 0:
                status = "DRAINED"
            else:
                status = f"REMAINING:{rem}"

            out_lines.append(f"ACT {act_idx} READ FD:{fd} REQUESTED:{limit} READ:{actual} REMAINING:{rem} STATUS:{status}")

        elif cmd == "EPOLL_WAIT":
            ready_fds = []
            for fd in sorted(modes.keys()):
                if modes[fd] == 'LT':
                    if rcv_buf.get(fd, 0) > 0:
                        ready_fds.append(fd)
                elif modes[fd] == 'ET':
                    if et_ready.get(fd, False):
                        ready_fds.append(fd)
                        et_ready[fd] = False

            is_busy_loop = False
            for fd in ready_fds:
                if modes[fd] == 'LT':
                    if fd in last_ready_lt_fds and read_since_last_wait.get(fd, 0) == 0:
                        is_busy_loop = True
                        break

            is_marooned = False
            for fd in modes:
                if modes[fd] == 'ET':
                    if rcv_buf.get(fd, 0) > 0 and fd not in ready_fds:
                        is_marooned = True
                        break

            if is_busy_loop:
                busy_loop_events += 1
            if is_marooned:
                marooned_data_events += 1

            last_ready_lt_fds = set(f for f in ready_fds if modes[f] == 'LT')
            for fd in ready_fds:
                read_since_last_wait[fd] = 0

            flags = []
            if is_busy_loop:
                flags.append("[BUSY_LOOP_SPIN]")
            if is_marooned:
                flags.append("[MAROONED_DATA_DETECTED]")

            flag_str = (" " + " ".join(flags)) if flags else ""
            fds_str = ",".join(f"FD:{f}" for f in ready_fds)
            out_lines.append(f"ACT {act_idx} EPOLL_WAIT READY:[{fds_str}]{flag_str}")

        act_idx += 1

    remaining_unread = total_bytes_arrived - total_bytes_read
    if busy_loop_events > 0 and marooned_data_events > 0:
        health = "DEGRADED (BUSY_LOOP & MAROONED)"
    elif busy_loop_events > 0:
        health = "BUSY_LOOP_BURNING"
    elif marooned_data_events > 0:
        health = "DATA_MAROONED_STARVATION"
    else:
        health = "HEALTHY"

    out_lines.append(f"SUMMARY TOTAL_ACTIONS:{len(actions)}")
    out_lines.append(f"SUMMARY TOTAL_BYTES_ARRIVED:{total_bytes_arrived}")
    out_lines.append(f"SUMMARY TOTAL_BYTES_READ:{total_bytes_read}")
    out_lines.append(f"SUMMARY REMAINING_UNREAD_BYTES:{remaining_unread}")
    out_lines.append(f"SUMMARY BUSY_LOOP_EVENTS:{busy_loop_events}")
    out_lines.append(f"SUMMARY MAROONED_DATA_EVENTS:{marooned_data_events}")
    out_lines.append(f"SUMMARY I_O_HEALTH: {health}")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
