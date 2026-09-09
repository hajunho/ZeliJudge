#!/usr/bin/env python3
import sys
import heapq
from collections import deque

class Task:
    def __init__(self, task_id, arrive_time, db_before, ext_io, db_after):
        self.task_id = task_id
        self.arrive_time = arrive_time
        self.db_before = db_before
        self.ext_io = ext_io
        self.db_after = db_after

def simulate_naive(P, timeout_ms, tasks):
    N = len(tasks)
    results = [None] * N
    available_conns = P
    wait_queue = deque()  # (req_time, task_idx, duration)
    events = []  # (time, priority, type, data)

    for i, t in enumerate(tasks):
        dur = t.db_before + t.ext_io + t.db_after
        heapq.heappush(events, (t.arrive_time, 2, 'ARRIVE', (i, dur)))

    def try_allocate(current_time):
        nonlocal available_conns
        while wait_queue and available_conns > 0:
            req_time, task_idx, dur = wait_queue.popleft()
            if current_time - req_time <= timeout_ms:
                available_conns -= 1
                heapq.heappush(events, (current_time + dur, 1, 'RELEASE', None))
                results[task_idx] = 'SUCCESS'
            else:
                results[task_idx] = 'TIMEOUT'

    while events:
        time, _, ev_type, data = heapq.heappop(events)
        if ev_type == 'RELEASE':
            available_conns += 1
            try_allocate(time)
        elif ev_type == 'ARRIVE':
            task_idx, dur = data
            if available_conns > 0:
                available_conns -= 1
                heapq.heappush(events, (time + dur, 1, 'RELEASE', None))
                results[task_idx] = 'SUCCESS'
            else:
                wait_queue.append((time, task_idx, dur))

    while wait_queue:
        _, task_idx, _ = wait_queue.popleft()
        results[task_idx] = 'TIMEOUT'

    return results

def simulate_optimized(P, timeout_ms, tasks):
    N = len(tasks)
    results = [None] * N
    available_conns = P
    wait_queue = deque()  # (req_time, task_idx, phase, duration)
    events = []

    for i, t in enumerate(tasks):
        if t.db_before > 0:
            heapq.heappush(events, (t.arrive_time, 2, 'ARRIVE_P1', i))
        else:
            ext_end = t.arrive_time + t.ext_io
            if t.db_after > 0:
                heapq.heappush(events, (ext_end, 2, 'ARRIVE_P3', i))
            else:
                results[i] = 'SUCCESS'

    def try_allocate(current_time):
        nonlocal available_conns
        while wait_queue and available_conns > 0:
            req_time, task_idx, phase, dur = wait_queue.popleft()
            if current_time - req_time <= timeout_ms:
                available_conns -= 1
                heapq.heappush(events, (current_time + dur, 1, 'RELEASE', (task_idx, phase)))
            else:
                results[task_idx] = 'TIMEOUT'

    while events:
        time, _, ev_type, data = heapq.heappop(events)
        if ev_type == 'RELEASE':
            task_idx, phase = data
            available_conns += 1
            try_allocate(time)

            t = tasks[task_idx]
            if phase == 1:
                ext_end = time + t.ext_io
                if t.db_after > 0:
                    heapq.heappush(events, (ext_end, 2, 'ARRIVE_P3', task_idx))
                else:
                    results[task_idx] = 'SUCCESS'
            elif phase == 3:
                results[task_idx] = 'SUCCESS'

        elif ev_type == 'ARRIVE_P1':
            task_idx = data
            dur = tasks[task_idx].db_before
            if available_conns > 0:
                available_conns -= 1
                heapq.heappush(events, (time + dur, 1, 'RELEASE', (task_idx, 1)))
            else:
                wait_queue.append((time, task_idx, 1, dur))

        elif ev_type == 'ARRIVE_P3':
            task_idx = data
            dur = tasks[task_idx].db_after
            if available_conns > 0:
                available_conns -= 1
                heapq.heappush(events, (time + dur, 1, 'RELEASE', (task_idx, 3)))
            else:
                wait_queue.append((time, task_idx, 3, dur))

    while wait_queue:
        _, task_idx, _, _ = wait_queue.popleft()
        results[task_idx] = 'TIMEOUT'

    return results

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)

    # 1. ?? ??: CONFIG POOL_SIZE:<P> TIMEOUT:<timeout_ms>
    cmd = next(it)  # CONFIG
    p_token = next(it)  # POOL_SIZE:<P>
    t_token = next(it)  # TIMEOUT:<timeout_ms>

    P = int(p_token.split(':')[1])
    timeout_ms = int(t_token.split(':')[1])

    # 2. ?? ??
    N = int(next(it))
    tasks = []
    for _ in range(N):
        op = next(it)  # TASK
        tid = next(it)
        arrive = int(next(it))
        db_before = int(next(it))
        ext_io = int(next(it))
        db_after = int(next(it))
        tasks.append(Task(tid, arrive, db_before, ext_io, db_after))

    naive_res = simulate_naive(P, timeout_ms, tasks)
    opt_res = simulate_optimized(P, timeout_ms, tasks)

    naive_success = 0
    opt_success = 0
    saved = 0

    output_lines = []
    for i, t in enumerate(tasks):
        n_status = naive_res[i]
        o_status = opt_res[i]

        if n_status == 'SUCCESS':
            naive_success += 1
        if o_status == 'SUCCESS':
            opt_success += 1
        if n_status == 'TIMEOUT' and o_status == 'SUCCESS':
            saved += 1

        output_lines.append(f"TASK {t.task_id} NAIVE:{n_status} OPTIMIZED:{o_status}")

    output_lines.append(f"SUMMARY NAIVE_SUCCESS:{naive_success}/{N} OPTIMIZED_SUCCESS:{opt_success}/{N} TIMEOUTS_SAVED:{saved}")
    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
