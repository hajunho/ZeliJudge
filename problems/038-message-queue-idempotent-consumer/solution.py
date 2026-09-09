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
    
    # State for MSG_ONLY
    mo_seen_msgs = set()
    
    # State for FULL
    full_seen_msgs = set()
    full_seen_biz = set()
    
    naive_cost = 0
    mo_cost = 0
    full_cost = 0
    biz_dups_blocked = 0
    
    output_lines = []
    
    for _ in range(num_events):
        token_op = next(it)  # 'RECEIVE'
        msg_id = next(it)
        biz_key = next(it)
        amount = int(next(it))
        
        # 1. NAIVE
        naive_status = 'EXECUTED'
        naive_cost += amount
        
        # 2. MSG_ONLY
        if msg_id in mo_seen_msgs:
            mo_status = 'SKIPPED_MSG_DUP'
        else:
            mo_status = 'EXECUTED'
            mo_seen_msgs.add(msg_id)
            mo_cost += amount
            
        # 3. FULL
        if msg_id in full_seen_msgs:
            full_status = 'SKIPPED_MSG_DUP'
        elif biz_key in full_seen_biz:
            full_status = 'SKIPPED_BIZ_DUP'
            full_seen_msgs.add(msg_id)
            biz_dups_blocked += 1
        else:
            full_status = 'EXECUTED'
            full_seen_msgs.add(msg_id)
            full_seen_biz.add(biz_key)
            full_cost += amount
            
        output_lines.append(f"MSG {msg_id} BIZ:{biz_key} NAIVE:{naive_status} MSG_ONLY:{mo_status} FULL:{full_status}")
        
    saved = naive_cost - full_cost
    output_lines.append(
        f"SUMMARY TOTAL_MSGS:{num_events} NAIVE_COST:{naive_cost} "
        f"MSG_ONLY_COST:{mo_cost} FULL_COST:{full_cost} TOTAL_COST_SAVED:{saved} "
        f"BIZ_DUPS_BLOCKED:{biz_dups_blocked}"
    )
    
    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
