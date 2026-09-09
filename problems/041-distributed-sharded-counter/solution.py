#!/usr/bin/env python3
import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)
    
    # 1. NUM_SLOTS <S>
    header_ns = next(it)  # 'NUM_SLOTS'
    num_slots = int(next(it))
    
    # 2. SLOT_CAPACITY <C>
    header_sc = next(it)  # 'SLOT_CAPACITY'
    capacity = int(next(it))
    
    # 3. EVENTS <E>
    header_ev = next(it)  # 'EVENTS'
    num_events = int(next(it))
    
    single_counts = {}
    sharded_counts = {}
    single_w = {}
    sharded_w = {}

    tot_likes = 0
    s_succ = 0
    s_to = 0
    sh_succ = 0
    sh_to = 0
    
    output_lines = []
    
    for _ in range(num_events):
        event_type = next(it)
        if event_type == 'LIKE':
            t = int(next(it))
            u = int(next(it))
            p = next(it)
            
            tot_likes += 1
            w = t // 100
            
            # 1. SINGLE (single slot 0)
            s_used = single_w.get((w, p), 0)
            if s_used < capacity:
                single_w[(w, p)] = s_used + 1
                single_counts[p] = single_counts.get(p, 0) + 1
                s_status = 'SUCCESS'
                s_succ += 1
            else:
                s_to += 1
                s_status = 'LOCK_TIMEOUT'
                
            # 2. SHARDED (S slots)
            slot = u % num_slots
            sh_used = sharded_w.get((w, p, slot), 0)
            if sh_used < capacity:
                sharded_w[(w, p, slot)] = sh_used + 1
                sharded_counts[(p, slot)] = sharded_counts.get((p, slot), 0) + 1
                sh_status = 'SUCCESS'
                sh_succ += 1
            else:
                sh_to += 1
                sh_status = 'LOCK_TIMEOUT'
                
            output_lines.append(f"LIKE {t} USER:{u} POST:{p} SINGLE:{s_status} SHARDED:slot_{slot}:{sh_status}")
            
        elif event_type == 'READ':
            t = int(next(it))
            p = next(it)
            s_cnt = single_counts.get(p, 0)
            sh_cnt = sum(sharded_counts.get((p, slot), 0) for slot in range(num_slots))
            output_lines.append(f"READ {t} POST:{p} SINGLE:{s_cnt} SHARDED:{sh_cnt}")
            
    imp = ((sh_succ - s_succ) / s_succ * 100) if s_succ > 0 else 0.0
    output_lines.append(
        f"SUMMARY TOTAL_LIKES:{tot_likes} SINGLE_SUCCESS:{s_succ} "
        f"SINGLE_TIMEOUTS:{s_to} SHARDED_SUCCESS:{sh_succ} SHARDED_TIMEOUTS:{sh_to} "
        f"THROUGHPUT_IMPROVEMENT:{imp:.1f}%"
    )
    
    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
