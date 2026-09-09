import sys
from collections import deque

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    c_num = int(input_data[0])
    p_num = int(input_data[1])
    max_poll_interval = int(input_data[2])
    strategy = input_data[3]
    
    n = int(input_data[4])
    idx = 5
    
    partition_queues = [deque() for _ in range(p_num + 1)]
    for _ in range(n):
        mid = int(input_data[idx])
        pid = int(input_data[idx+1])
        ptime = int(input_data[idx+2])
        idx += 3
        partition_queues[pid].append((mid, ptime))
        
    # Initial partition assignment: round-robin
    consumer_partitions = {c: [] for c in range(1, c_num + 1)}
    for p in range(1, p_num + 1):
        c = ((p - 1) % c_num) + 1
        consumer_partitions[c].append(p)
        
    active_consumers = set(range(1, c_num + 1))
    
    processed_unique = set()
    duplicate_count = 0
    rebalance_count = 0
    total_stw = 0
    
    # Simulate processing per consumer
    # In this model, each partition's messages are processed sequentially
    # If a consumer exceeds max_poll_interval during a batch (here the whole queue assigned to it),
    # it gets kicked out.
    
    # We simulate tick-by-tick or batch execution per consumer
    for c in range(1, c_num + 1):
        if c not in active_consumers:
            continue
        parts = list(consumer_partitions[c])
        for p in parts:
            elapsed = 0
            in_batch_processed = []
            while partition_queues[p]:
                mid, ptime = partition_queues[p][0]
                if elapsed + ptime > max_poll_interval:
                    # Consumer c exceeds max_poll_interval and is kicked out!
                    rebalance_count += 1
                    stw_penalty = 5 if strategy == "EAGER" else 1
                    total_stw += stw_penalty
                    active_consumers.remove(c)
                    
                    # in_batch_processed are uncommitted, so they are re-queued at the front
                    # and will be reprocessed, causing duplicates!
                    for r_mid, r_time in reversed(in_batch_processed):
                        partition_queues[p].appendleft((r_mid, r_time))
                        
                    # Reassign all partitions of c to remaining active consumers
                    remaining = sorted(list(active_consumers))
                    if remaining:
                        # assign p to remaining consumer with fewest partitions
                        target_c = min(remaining, key=lambda x: len(consumer_partitions[x]))
                        consumer_partitions[target_c].append(p)
                    break
                else:
                    partition_queues[p].popleft()
                    elapsed += ptime
                    if mid in processed_unique:
                        duplicate_count += 1
                    else:
                        processed_unique.add(mid)
                    in_batch_processed.append((mid, ptime))
            if c not in active_consumers:
                break

    # Process any remaining messages by remaining active consumers
    for c in sorted(list(active_consumers)):
        for p in consumer_partitions[c]:
            while partition_queues[p]:
                mid, ptime = partition_queues[p].popleft()
                if mid in processed_unique:
                    duplicate_count += 1
                else:
                    processed_unique.add(mid)

    print(f"PROCESSED_UNIQUE: {len(processed_unique)} DUPLICATE: {duplicate_count} REBALANCES: {rebalance_count} STW_SEC: {total_stw}")

if __name__ == '__main__':
    solve()
