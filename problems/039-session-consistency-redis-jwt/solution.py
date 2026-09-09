#!/usr/bin/env python3
import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)
    
    # 1. EVENTS <N>
    header_ev = next(it)  # 'EVENTS'
    num_events = int(next(it))
    
    # 1. LOCAL
    local_sessions = {}  # server_id -> set of user_id
    
    # 2. STICKY
    sticky_target = {}   # user_id -> server_id
    sticky_sessions = {} # server_id -> set of user_id
    
    # 3. REDIS
    redis_sessions = set() # set of user_id
    
    alive_servers = set()
    
    local_ok = 0
    sticky_ok = 0
    redis_ok = 0
    total_req = 0
    
    output_lines = []
    
    for _ in range(num_events):
        event_type = next(it)
        if event_type == 'LOGIN':
            t = int(next(it))
            u = next(it)
            s = next(it)
            
            alive_servers.add(s)
            
            # LOCAL
            if s not in local_sessions:
                local_sessions[s] = set()
            local_sessions[s].add(u)
            
            # STICKY
            sticky_target[u] = s
            if s not in sticky_sessions:
                sticky_sessions[s] = set()
            sticky_sessions[s].add(u)
            
            # REDIS
            redis_sessions.add(u)
            
        elif event_type == 'CRASH':
            t = int(next(it))
            s = next(it)
            alive_servers.discard(s)
            if s in local_sessions:
                local_sessions[s].clear()
            if s in sticky_sessions:
                sticky_sessions[s].clear()
                
        elif event_type == 'RECOVER':
            t = int(next(it))
            s = next(it)
            alive_servers.add(s)
            if s not in local_sessions:
                local_sessions[s] = set()
            if s not in sticky_sessions:
                sticky_sessions[s] = set()
                
        elif event_type == 'LOGOUT':
            t = int(next(it))
            u = next(it)
            for s in local_sessions:
                local_sessions[s].discard(u)
            for s in sticky_sessions:
                sticky_sessions[s].discard(u)
            sticky_target.pop(u, None)
            redis_sessions.discard(u)
            
        elif event_type == 'REQUEST':
            t = int(next(it))
            u = next(it)
            routed_s = next(it)
            alive_servers.add(routed_s) # ensure server known
            
            total_req += 1
            
            # 1. LOCAL
            if routed_s in alive_servers and u in local_sessions.get(routed_s, set()):
                loc_status = 'AUTH_OK'
                local_ok += 1
            else:
                loc_status = 'SESSION_LOST'
                
            # 2. STICKY
            target_s = sticky_target.get(u)
            if target_s and target_s in alive_servers:
                act_s = target_s
            else:
                act_s = routed_s
                
            if act_s in alive_servers and u in sticky_sessions.get(act_s, set()):
                stk_status = 'AUTH_OK'
                sticky_ok += 1
            else:
                stk_status = 'SESSION_LOST'
                
            # 3. REDIS
            if routed_s in alive_servers and u in redis_sessions:
                red_status = 'AUTH_OK'
                redis_ok += 1
            else:
                red_status = 'SESSION_LOST'
                
            output_lines.append(f"REQ {t} USER:{u} LOCAL:{loc_status} STICKY:{stk_status} REDIS:{red_status}")
            
    saved = redis_ok - local_ok
    output_lines.append(
        f"SUMMARY TOTAL_REQUESTS:{total_req} LOCAL_AUTH_OK:{local_ok} "
        f"STICKY_AUTH_OK:{sticky_ok} REDIS_AUTH_OK:{redis_ok} REDIS_SESSIONS_SAVED:{saved}"
    )
    
    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
