#!/usr/bin/env python3
import sys

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)
    
    # 1. INITIAL_SHARDS <K>
    header_is = next(it)  # 'INITIAL_SHARDS'
    K = int(next(it))
    
    # 2. EVENTS <N>
    header_ev = next(it)  # 'EVENTS'
    num_events = int(next(it))
    
    user_items = {}       # user_id -> list of data_id
    dir_user_shard = {}   # user_id -> shard_id
    dir_shard_counts = {s: 0 for s in range(K)}
    
    total_inserts = 0
    total_lookups = 0
    total_rebalances = 0
    total_hash_mig = 0
    total_dir_mig = 0
    
    output_lines = []
    
    for _ in range(num_events):
        event_type = next(it)
        if event_type == 'INSERT':
            u = int(next(it))
            d = next(it)
            total_inserts += 1
            
            if u not in user_items:
                user_items[u] = []
            user_items[u].append(d)
            
            # 1. HASH
            h_shard = u % K
            
            # 2. DIR
            if u in dir_user_shard:
                d_shard = dir_user_shard[u]
            else:
                # Least loaded shard (tie-breaker: smallest shard ID)
                best_s = min(dir_shard_counts.keys(), key=lambda s: (dir_shard_counts[s], s))
                dir_user_shard[u] = best_s
                d_shard = best_s
            dir_shard_counts[d_shard] += 1
            
            output_lines.append(f"INSERT USER:{u} DATA:{d} HASH:shard_{h_shard} DIR:shard_{d_shard}")
            
        elif event_type == 'LOOKUP':
            u = int(next(it))
            total_lookups += 1
            h_shard = u % K
            d_shard = dir_user_shard.get(u, -1)
            output_lines.append(f"LOOKUP USER:{u} HASH:shard_{h_shard} DIR:shard_{d_shard}")
            
        elif event_type == 'ADD_SHARD':
            total_rebalances += 1
            old_K = K
            new_K = K + 1
            K = new_K
            
            # 1. HASH migration
            hash_mig = 0
            for u, items in user_items.items():
                if (u % old_K) != (u % new_K):
                    hash_mig += len(items)
            total_hash_mig += hash_mig
            
            # 2. DIR migration
            new_s = old_K
            dir_shard_counts[new_s] = 0
            total_items = sum(len(items) for items in user_items.values())
            target = total_items // new_K
            dir_mig = 0
            
            while dir_shard_counts[new_s] < target:
                cand_shards = [s for s in dir_shard_counts if s != new_s]
                # Most loaded shard (tie-breaker: smallest shard ID)
                max_s = min(cand_shards, key=lambda s: (-dir_shard_counts[s], s))
                if dir_shard_counts[max_s] <= target:
                    break
                    
                u_candidates = sorted([u for u, s in dir_user_shard.items() if s == max_s])
                if not u_candidates:
                    break
                    
                move_u = u_candidates[0]
                cnt = len(user_items[move_u])
                dir_user_shard[move_u] = new_s
                dir_shard_counts[max_s] -= cnt
                dir_shard_counts[new_s] += cnt
                dir_mig += cnt
                
            total_dir_mig += dir_mig
            saved = hash_mig - dir_mig
            output_lines.append(
                f"REBALANCE SHARDS:{new_K} HASH_MIGRATED:{hash_mig} DIR_MIGRATED:{dir_mig} MIGRATIONS_SAVED:{saved}"
            )
            
    total_saved = total_hash_mig - total_dir_mig
    output_lines.append(
        f"SUMMARY TOTAL_INSERTS:{total_inserts} TOTAL_LOOKUPS:{total_lookups} "
        f"TOTAL_REBALANCES:{total_rebalances} TOTAL_HASH_MIGRATED:{total_hash_mig} "
        f"TOTAL_DIR_MIGRATED:{total_dir_mig} TOTAL_MIGRATIONS_SAVED:{total_saved}"
    )
    
    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
