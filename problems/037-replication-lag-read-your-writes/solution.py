#!/usr/bin/env python3
import sys
import bisect

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)
    
    # 1. SAFE_WINDOW <W>
    header_sw = next(it)  # 'SAFE_WINDOW'
    safe_window = int(next(it))
    
    # 2. EVENTS <E>
    header_ev = next(it)  # 'EVENTS'
    num_events = int(next(it))
    
    master_lsn = 0
    # doc_id -> list of (lsn, val)
    docs_history = {}
    # doc_id -> list of lsn
    docs_lsns = {}
    # user_id -> (time, lsn)
    user_last_write = {}
    # replica_id -> applied_lsn
    replica_lsn = {}
    
    output_lines = []
    total_reads = 0
    naive_failures = 0
    tw_failures = 0
    tw_master_reads = 0
    lsn_master_reads = 0
    
    for _ in range(num_events):
        event_type = next(it)
        if event_type == 'WRITE':
            t = int(next(it))
            u = next(it)
            doc = next(it)
            val = next(it)
            
            master_lsn += 1
            if doc not in docs_history:
                docs_history[doc] = []
                docs_lsns[doc] = []
            docs_history[doc].append((master_lsn, val))
            docs_lsns[doc].append(master_lsn)
            user_last_write[u] = (t, master_lsn)
            
        elif event_type == 'SYNC':
            t = int(next(it))
            rep = next(it)
            applied_lsn = int(next(it))
            replica_lsn[rep] = applied_lsn
            
        elif event_type == 'READ':
            t = int(next(it))
            u = next(it)
            doc = next(it)
            rep = next(it)
            
            total_reads += 1
            
            # Master latest state
            latest_lsn = docs_lsns[doc][-1] if (doc in docs_lsns and docs_lsns[doc]) else 0
            
            # Replica state for this doc
            rep_cur_lsn = replica_lsn.get(rep, 0)
            if doc not in docs_lsns or not docs_lsns[doc]:
                rep_status = 'NOT_FOUND'
                master_status = 'NOT_FOUND'
            else:
                master_status = 'OK'
                idx = bisect.bisect_right(docs_lsns[doc], rep_cur_lsn) - 1
                if idx < 0:
                    rep_status = 'NOT_FOUND'
                elif docs_lsns[doc][idx] < latest_lsn:
                    rep_status = 'STALE'
                else:
                    rep_status = 'OK'
                    
            # 1. NAIVE
            naive_route = rep
            naive_status = rep_status
            if naive_status != 'OK':
                naive_failures += 1
                
            # 2. TIME_WINDOW
            uw = user_last_write.get(u)
            if uw and (t - uw[0] < safe_window):
                tw_route = 'MASTER'
                tw_status = master_status
                tw_master_reads += 1
            else:
                tw_route = rep
                tw_status = rep_status
            if tw_status != 'OK':
                tw_failures += 1
                
            # 3. LSN_AWARE
            req_lsn = uw[1] if uw else 0
            if rep_cur_lsn >= req_lsn:
                lsn_route = rep
                lsn_status = rep_status
            else:
                lsn_route = 'MASTER'
                lsn_status = master_status
                lsn_master_reads += 1
                
            output_lines.append(
                f"READ {t} USER:{u} DOC:{doc} "
                f"NAIVE:{naive_route}:{naive_status} "
                f"TIME_WINDOW:{tw_route}:{tw_status} "
                f"LSN_AWARE:{lsn_route}:{lsn_status}"
            )
            
    saved_master = tw_master_reads - lsn_master_reads
    output_lines.append(
        f"SUMMARY TOTAL_READS:{total_reads} "
        f"NAIVE_FAILURES:{naive_failures} "
        f"TIME_WINDOW_FAILURES:{tw_failures} "
        f"TIME_WINDOW_MASTER_READS:{tw_master_reads} "
        f"LSN_AWARE_MASTER_READS:{lsn_master_reads} "
        f"MASTER_LOAD_SAVED:{saved_master}"
    )
    
    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
