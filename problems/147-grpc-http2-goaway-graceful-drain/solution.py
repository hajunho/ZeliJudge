import sys

def solve():
    lines = sys.stdin.read().splitlines()
    if not lines:
        return
    parts = lines[0].strip().split()
    mode = parts[0].upper()
    drain_timeout_ms = int(parts[1])
    rtt_ms = int(parts[2])
    shutdown_ms = int(parts[3])
    
    n = int(lines[1].strip())
    streams = []
    for i in range(2, 2 + n):
        if i < len(lines):
            s_parts = lines[i].strip().split()
            if len(s_parts) >= 3:
                sid = int(s_parts[0])
                send_t = int(s_parts[1])
                dur = int(s_parts[2])
                streams.append((sid, send_t, dur))
                
    one_way = rtt_ms // 2
    completed = 0
    safely_retried = 0
    dropped = 0
    abrupt_resets = 0
    
    if mode == "ABRUPT_CLOSE":
        for sid, send_t, dur in streams:
            arrive_t = send_t + one_way
            finish_t = arrive_t + dur
            if arrive_t <= shutdown_ms:
                if finish_t <= shutdown_ms:
                    completed += 1
                else:
                    dropped += 1
                    abrupt_resets += 1
            else:
                dropped += 1
    else: # GRACEFUL_GOAWAY
        client_knows_goaway_t = shutdown_ms + one_way
        server_second_goaway_t = shutdown_ms + rtt_ms
        hard_deadline = shutdown_ms + drain_timeout_ms
        
        received_by_second_goaway = [sid for sid, send_t, dur in streams if send_t + one_way <= server_second_goaway_t]
        last_stream_id = max(received_by_second_goaway) if received_by_second_goaway else 0
        
        for sid, send_t, dur in streams:
            arrive_t = send_t + one_way
            finish_t = arrive_t + dur
            
            if send_t >= client_knows_goaway_t:
                safely_retried += 1
            else:
                if sid <= last_stream_id and arrive_t <= server_second_goaway_t:
                    if finish_t <= hard_deadline:
                        completed += 1
                    else:
                        dropped += 1
                else:
                    safely_retried += 1
                    
    print(f"COMPLETED: {completed} SAFELY_RETRIED: {safely_retried} DROPPED: {dropped} ABRUPT_RESETS: {abrupt_resets}")

if __name__ == '__main__':
    solve()
