import sys

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return

    max_mem_mb = 2048
    stack_kb = 1024
    fd_kb = 8
    max_threads = 1024

    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        if parts[0] == "MAX_SERVER_MEMORY_MB":
            max_mem_mb = int(parts[1])
        elif parts[0] == "THREAD_STACK_KB":
            stack_kb = int(parts[1])
        elif parts[0] == "FD_BUFFER_KB":
            fd_kb = int(parts[1])
        elif parts[0] == "MAX_ACTIVE_THREADS":
            max_threads = int(parts[1])
        elif parts[0] == "EVENTS":
            break

    # Parse events
    # CONNECT <client_id> <timestamp>
    # DATA <client_id> <bytes> <timestamp>
    # DISCONNECT <client_id> <timestamp>
    events = []
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        parts = line.split()
        ev_type = parts[0]
        if ev_type == "CONNECT":
            # ('CONNECT', timestamp, client_id)
            events.append(('CONNECT', int(parts[2]), parts[1]))
        elif ev_type == "DATA":
            # ('DATA', timestamp, client_id, int(bytes))
            events.append(('DATA', int(parts[3]), parts[1], int(parts[2])))
        elif ev_type == "DISCONNECT":
            # ('DISCONNECT', timestamp, client_id)
            events.append(('DISCONNECT', int(parts[2]), parts[1]))

    # Sort events by timestamp; tie-breakers: DISCONNECT, DATA, CONNECT
    # So disconnections free up slots first
    order_map = {'DISCONNECT': 0, 'DATA': 1, 'CONNECT': 2}
    events.sort(key=lambda x: (x[1], order_map[x[0]]))

    # Model A: THREAD_PER_CONN
    thread_active_clients = set()
    thread_peak_mem_kb = 0
    thread_accepted = 0
    thread_rejected = 0

    # Model B: IO_MULTIPLEXING (epoll)
    # Fixed 4 worker threads
    EPOLL_WORKER_THREADS = 4
    epoll_active_clients = set()
    epoll_base_mem_kb = EPOLL_WORKER_THREADS * stack_kb
    epoll_peak_mem_kb = epoll_base_mem_kb
    epoll_accepted = 0
    epoll_rejected = 0

    total_connect_attempts = 0

    max_mem_kb = max_mem_mb * 1024

    for ev in events:
        ev_type = ev[0]

        if ev_type == "CONNECT":
            total_connect_attempts += 1
            client_id = ev[2]

            # 1. Thread evaluation
            curr_thread_count = len(thread_active_clients)
            curr_thread_mem_kb = curr_thread_count * stack_kb
            if curr_thread_count >= max_threads or (curr_thread_mem_kb + stack_kb) > max_mem_kb:
                t_status = "REJECTED"
                thread_rejected += 1
            else:
                t_status = "SUCCESS"
                thread_accepted += 1
                thread_active_clients.add(client_id)
                curr_thread_mem_kb += stack_kb
                if curr_thread_mem_kb > thread_peak_mem_kb:
                    thread_peak_mem_kb = curr_thread_mem_kb

            t_mem_mb = curr_thread_mem_kb / 1024.0

            # 2. Epoll evaluation
            curr_epoll_count = len(epoll_active_clients)
            curr_epoll_mem_kb = epoll_base_mem_kb + curr_epoll_count * fd_kb
            if (curr_epoll_mem_kb + fd_kb) > max_mem_kb:
                e_status = "REJECTED"
                epoll_rejected += 1
            else:
                e_status = "SUCCESS"
                epoll_accepted += 1
                epoll_active_clients.add(client_id)
                curr_epoll_mem_kb += fd_kb
                if curr_epoll_mem_kb > epoll_peak_mem_kb:
                    epoll_peak_mem_kb = curr_epoll_mem_kb

            e_mem_mb = curr_epoll_mem_kb / 1024.0

            print(f"CONNECT {client_id} THREAD:{t_status},MEM:{t_mem_mb:.2f}MB EPOLL:{e_status},MEM:{e_mem_mb:.2f}MB")

        elif ev_type == "DATA":
            client_id = ev[2]
            t_status = "PROCESSED" if client_id in thread_active_clients else "DROPPED"
            e_status = "PROCESSED" if client_id in epoll_active_clients else "DROPPED"
            print(f"DATA {client_id} THREAD:{t_status} EPOLL:{e_status}")

        elif ev_type == "DISCONNECT":
            client_id = ev[2]
            if client_id in thread_active_clients:
                thread_active_clients.remove(client_id)
            if client_id in epoll_active_clients:
                epoll_active_clients.remove(client_id)
            print(f"DISCONNECT {client_id} THREAD:DISCONNECTED EPOLL:DISCONNECTED")

    t_peak_mb = thread_peak_mem_kb / 1024.0
    e_peak_mb = epoll_peak_mem_kb / 1024.0

    if t_peak_mb > 0:
        mem_saved_pct = ((t_peak_mb - e_peak_mb) / t_peak_mb) * 100.0
    else:
        mem_saved_pct = 0.0

    if total_connect_attempts > 0:
        adv_pct = ((epoll_accepted - thread_accepted) / total_connect_attempts) * 100.0
    else:
        adv_pct = 0.0

    print(f"SUMMARY TOTAL_CONNECTS:{total_connect_attempts}")
    print(f"THREAD MODEL ACCEPTED:{thread_accepted} REJECTED:{thread_rejected} PEAK_MEM:{t_peak_mb:.2f}MB")
    print(f"EPOLL MODEL ACCEPTED:{epoll_accepted} REJECTED:{epoll_rejected} PEAK_MEM:{e_peak_mb:.2f}MB")
    print(f"SUMMARY MEMORY_SAVINGS:{mem_saved_pct:.2f}% CONNECTION_CAPACITY_ADVANTAGE:{adv_pct:.2f}%")

if __name__ == "__main__":
    solve()
