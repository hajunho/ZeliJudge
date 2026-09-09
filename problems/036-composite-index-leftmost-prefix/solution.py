#!/usr/bin/env python3
import sys
from decimal import Decimal, ROUND_HALF_UP

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    it = iter(input_data)
    
    # 1. INDEX <K> <col_1> ... <col_K>
    header_idx = next(it)  # 'INDEX'
    K = int(next(it))
    index_cols = [next(it) for _ in range(K)]
    
    # 2. TABLE_SIZE <N>
    header_ts = next(it)   # 'TABLE_SIZE'
    table_size = int(next(it))
    
    # 3. QUERIES <Q>
    header_q = next(it)    # 'QUERIES'
    Q = int(next(it))
    
    output_lines = []
    full_scans = 0
    total_scanned = 0
    total_opt_scanned = 0
    
    for _ in range(Q):
        token_q = next(it)  # 'QUERY'
        qid = next(it)
        M = int(next(it))   # number of conditions
        
        conds = {}
        for _ in range(M):
            col = next(it)
            op = next(it)
            sel = Decimal(next(it))
            conds[col] = {'op': op, 'selectivity': sel}
            
        # --- Evaluate Current Index ---
        seek_keys = []
        has_range = False
        
        for col in index_cols:
            if col not in conds:
                break
            if has_range:
                break
            seek_keys.append(col)
            if conds[col]['op'] == 'RANGE':
                has_range = True
                
        access_type = 'INDEX_SEEK' if seek_keys else 'TABLE_FULL_SCAN'
        if access_type == 'TABLE_FULL_SCAN':
            full_scans += 1
            scanned_rows = table_size
        else:
            seek_sel = Decimal('1')
            for c in seek_keys:
                seek_sel *= conds[c]['selectivity']
            scanned_rows = int((Decimal(table_size) * seek_sel).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if table_size > 0:
                scanned_rows = max(1, scanned_rows)
                
        total_sel = Decimal('1')
        for c in conds:
            total_sel *= conds[c]['selectivity']
            
        if table_size > 0:
            returned_rows = int((Decimal(table_size) * total_sel).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            returned_rows = min(scanned_rows, returned_rows)
        else:
            returned_rows = 0
            
        if scanned_rows > 0:
            waste = (Decimal(scanned_rows - returned_rows) / Decimal(scanned_rows) * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        else:
            waste = Decimal('0.0')
            
        # --- Optimal Index Recommendation ---
        equal_cols = sorted([c for c in conds if conds[c]['op'] == '='], key=lambda c: (conds[c]['selectivity'], c))
        range_cols = sorted([c for c in conds if conds[c]['op'] == 'RANGE'], key=lambda c: (conds[c]['selectivity'], c))
        opt_index = equal_cols + range_cols
        opt_seek_keys = equal_cols + (range_cols[:1] if range_cols else [])
        
        if opt_seek_keys:
            opt_seek_sel = Decimal('1')
            for c in opt_seek_keys:
                opt_seek_sel *= conds[c]['selectivity']
            opt_scanned = int((Decimal(table_size) * opt_seek_sel).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if table_size > 0:
                opt_scanned = max(1, opt_scanned)
        else:
            opt_scanned = table_size
        opt_scanned = min(scanned_rows, opt_scanned)
        
        total_scanned += scanned_rows
        total_opt_scanned += opt_scanned
        
        seek_str = f"[{','.join(seek_keys)}]" if seek_keys else "NONE"
        opt_idx_str = f"[{','.join(opt_index)}]" if opt_index else "NONE"
        
        output_lines.append(
            f"QUERY {qid} ACCESS:{access_type} SEEK_KEYS:{seek_str} SCANNED:{scanned_rows} "
            f"RETURNED:{returned_rows} WASTE:{waste:.1f}% OPTIMAL_INDEX:{opt_idx_str} OPTIMAL_SCANNED:{opt_scanned}"
        )
        
    rows_saved = total_scanned - total_opt_scanned
    output_lines.append(
        f"SUMMARY TOTAL_QUERIES:{Q} FULL_SCANS:{full_scans} TOTAL_SCANNED:{total_scanned} "
        f"TOTAL_OPTIMAL_SCANNED:{total_opt_scanned} ROWS_SAVED:{rows_saved}"
    )
    
    sys.stdout.write("\n".join(output_lines) + "\n")

if __name__ == '__main__':
    solve()
