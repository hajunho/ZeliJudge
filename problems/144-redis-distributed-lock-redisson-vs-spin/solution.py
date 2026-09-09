import sys
import heapq

def simulate(mode, spin_interval, lease_time, watchdog_enabled, reqs):
    EV_RELEASE = 1
    EV_EXPIRE = 2
    EV_WATCHDOG = 3
    EV_ARRIVAL = 4
    EV_POLL = 5
    
    events = []
    for r in reqs:
        heapq.heappush(events, (r[1], EV_ARRIVAL, r[0], r[2]))
        
    watchdog_interval = max(1, lease_time // 3)
    
    lock_owner = None
    lock_token = 0
    
    redis_commands = 0
    premature_expirations = 0
    completed = 0
    max_wait_time = 0
    
    waiting_map = {} # req_id -> (arrival_time, duration)
    pubsub_queue = [] # list of req_id in FIFO order
    
    def grant_lock(t, req_id, duration, arrival_time):
        nonlocal lock_owner, lock_token, redis_commands, max_wait_time
        lock_owner = req_id
        lock_token += 1
        my_token = lock_token
        wait_t = t - arrival_time
        if wait_t > max_wait_time:
            max_wait_time = wait_t
        redis_commands += 1 # Acquire
        
        heapq.heappush(events, (t + duration, EV_RELEASE, req_id, (my_token, duration, arrival_time)))
        
        if watchdog_enabled:
            if duration > watchdog_interval:
                heapq.heappush(events, (t + watchdog_interval, EV_WATCHDOG, req_id, (my_token, t + duration)))
        else:
            if duration > lease_time:
                heapq.heappush(events, (t + lease_time, EV_EXPIRE, req_id, my_token))

    while events:
        t, ev_type, req_id, data = heapq.heappop(events)
        
        if ev_type == EV_ARRIVAL:
            duration = data
            arrival_time = t
            if lock_owner is None:
                grant_lock(t, req_id, duration, arrival_time)
            else:
                if mode == "SPIN_LOCK":
                    redis_commands += 1 # initial try
                    waiting_map[req_id] = (arrival_time, duration)
                    heapq.heappush(events, (t + spin_interval, EV_POLL, req_id, None))
                else: # REDISSON_PUBSUB
                    redis_commands += 2 # initial try + subscribe
                    waiting_map[req_id] = (arrival_time, duration)
                    pubsub_queue.append(req_id)
                    
        elif ev_type == EV_POLL:
            if req_id in waiting_map:
                redis_commands += 1 # poll attempt
                arrival_time, duration = waiting_map[req_id]
                if lock_owner is None:
                    del waiting_map[req_id]
                    grant_lock(t, req_id, duration, arrival_time)
                else:
                    heapq.heappush(events, (t + spin_interval, EV_POLL, req_id, None))
                    
        elif ev_type == EV_WATCHDOG:
            my_token, end_time = data
            if lock_owner == req_id and lock_token == my_token:
                redis_commands += 1 # PEXPIRE renew
                if t + watchdog_interval < end_time:
                    heapq.heappush(events, (t + watchdog_interval, EV_WATCHDOG, req_id, (my_token, end_time)))
                    
        elif ev_type == EV_EXPIRE:
            my_token = data
            if lock_owner == req_id and lock_token == my_token:
                premature_expirations += 1
                lock_owner = None
                if mode == "REDISSON_PUBSUB" and pubsub_queue:
                    next_req = pubsub_queue.pop(0)
                    arr_t, dur = waiting_map.pop(next_req)
                    grant_lock(t, next_req, dur, arr_t)
                    for w in pubsub_queue:
                        redis_commands += 1
                        
        elif ev_type == EV_RELEASE:
            my_token, duration, arrival_time = data
            completed += 1
            redis_commands += 1 # DEL / release
            if lock_owner == req_id and lock_token == my_token:
                lock_owner = None
                if mode == "REDISSON_PUBSUB" and pubsub_queue:
                    next_req = pubsub_queue.pop(0)
                    arr_t, dur = waiting_map.pop(next_req)
                    grant_lock(t, next_req, dur, arr_t)
                    for w in pubsub_queue:
                        redis_commands += 1

    return {
        "completed": completed,
        "redis_commands": redis_commands,
        "premature_expirations": premature_expirations,
        "max_wait_time": max_wait_time
    }

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].strip().split()
    mode = parts[0].upper()
    spin_interval = int(parts[1])
    lease_time = int(parts[2])
    watchdog_enabled = parts[3].lower() == 'true'
    
    n = int(lines[1].strip())
    reqs = []
    for i in range(2, 2 + n):
        if i < len(lines):
            r_parts = lines[i].strip().split()
            if len(r_parts) >= 3:
                rid = int(r_parts[0])
                arr = int(r_parts[1])
                dur = int(r_parts[2])
                reqs.append((rid, arr, dur))
                
    res = simulate(mode, spin_interval, lease_time, watchdog_enabled, reqs)
    print(f"COMPLETED: {res['completed']} REDIS_COMMANDS: {res['redis_commands']} PREMATURE_EXPIRATIONS: {res['premature_expirations']} MAX_WAIT_MS: {res['max_wait_time']}")

if __name__ == '__main__':
    solve()
