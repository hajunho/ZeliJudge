import sys
import math
from bisect import bisect_left, bisect_right

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "TABLE"
    records = []
    queries = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "TABLE_DATA":
            mode = "TABLE"
            continue
        elif line == "QUERIES":
            mode = "QUERIES"
            continue

        parts = line.split()
        if mode == "TABLE":
            rid = int(parts[0])
            cat = parts[1]
            price = int(parts[2])
            dt = parts[3]
            sku = parts[4]
            records.append((rid, cat, price, dt, sku))
        elif mode == "QUERIES":
            queries.append(parts)

    N = len(records)
    H = max(1, math.ceil(math.log2(N))) if N > 0 else 1

    # Build B-Tree Indexes (Sorted lists of tuples)
    # (indexed_val, record_id)
    price_idx = sorted([(r[2], r[0]) for r in records])
    date_idx = sorted([(r[3], r[0]) for r in records])
    sku_idx = sorted([(r[4], r[0]) for r in records])

    out_lines = []
    naive_total_examined = 0
    sargable_total_examined = 0
    accuracy_ok = True

    for q_idx, q in enumerate(queries, 1):
        cmd = q[0]
        q_str = " ".join(q)
        out_lines.append(f"ACT {q_idx} {q_str}")

        naive_matches = []
        sargable_matches = []
        sargable_examined = H

        if cmd == "QUERY_PRICE_ARITHMETIC":
            multiplier = float(q[1])
            op = q[2]
            target_val = float(q[3])

            # 1. Naive Full Table Scan
            for r in records:
                val = r[2] * multiplier
                if op == ">=" and val >= target_val - 1e-9:
                    naive_matches.append(r[0])
                elif op == ">" and val > target_val + 1e-9:
                    naive_matches.append(r[0])
                elif op == "<=" and val <= target_val + 1e-9:
                    naive_matches.append(r[0])
                elif op == "<" and val < target_val - 1e-9:
                    naive_matches.append(r[0])

            # 2. SARGable Transformation & Index Range Scan
            # Transform: price (op) boundary
            if op == ">=":
                # price >= ceil(target_val / multiplier)
                low_price = math.ceil(target_val / multiplier - 1e-9)
                left = bisect_left(price_idx, (low_price, -1))
                right = len(price_idx)
            elif op == ">":
                # price >= floor(target_val / multiplier) + 1
                low_price = math.floor(target_val / multiplier + 1e-9) + 1
                left = bisect_left(price_idx, (low_price, -1))
                right = len(price_idx)
            elif op == "<=":
                # price <= floor(target_val / multiplier)
                high_price = math.floor(target_val / multiplier + 1e-9)
                left = 0
                right = bisect_right(price_idx, (high_price, float('inf')))
            elif op == "<":
                # price <= ceil(target_val / multiplier) - 1
                high_price = math.ceil(target_val / multiplier - 1e-9) - 1
                left = 0
                right = bisect_right(price_idx, (high_price, float('inf')))

            range_items = price_idx[left:right]
            sargable_matches = [item[1] for item in range_items]
            sargable_examined += len(range_items)

        elif cmd == "QUERY_DATE_YEAR":
            target_year = int(q[1])

            # 1. Naive Full Scan
            for r in records:
                if int(r[3][:4]) == target_year:
                    naive_matches.append(r[0])

            # 2. SARGable Transformation: Range Scan [YYYY-01-01, YYYY-12-31]
            low_dt = f"{target_year:04d}-01-01"
            high_dt = f"{target_year:04d}-12-31"

            left = bisect_left(date_idx, (low_dt, -1))
            right = bisect_right(date_idx, (high_dt, float('inf')))
            range_items = date_idx[left:right]
            sargable_matches = [item[1] for item in range_items]
            sargable_examined += len(range_items)

        elif cmd == "QUERY_SKU_PREFIX":
            prefix = q[1]

            # 1. Naive Full Scan
            for r in records:
                if r[4].startswith(prefix):
                    naive_matches.append(r[0])

            # 2. SARGable Transformation: Range Scan [prefix, prefix + \uffff]
            low_sku = prefix
            high_sku = prefix + "\uffff"

            left = bisect_left(sku_idx, (low_sku, -1))
            right = bisect_right(sku_idx, (high_sku, float('inf')))
            range_items = sku_idx[left:right]
            sargable_matches = [item[1] for item in range_items]
            sargable_examined += len(range_items)

        elif cmd == "QUERY_SKU_SUBSTRING":
            length = int(q[1])
            target_val = q[2]

            # 1. Naive Full Scan
            for r in records:
                if r[4][:length] == target_val:
                    naive_matches.append(r[0])

            # 2. SARGable Transformation: Equivalent to prefix search for target_val
            prefix = target_val
            low_sku = prefix
            high_sku = prefix + "\uffff"

            left = bisect_left(sku_idx, (low_sku, -1))
            right = bisect_right(sku_idx, (high_sku, float('inf')))
            range_items = sku_idx[left:right]
            sargable_matches = [item[1] for item in range_items]
            sargable_examined += len(range_items)

        naive_examined = N
        naive_total_examined += naive_examined
        sargable_total_examined += sargable_examined

        if sorted(naive_matches) != sorted(sargable_matches):
            accuracy_ok = False

        saved = max(0, naive_examined - sargable_examined)
        out_lines.append(f"  NAIVE: PLAN=FULL_TABLE_SCAN ROWS_EXAMINED:{naive_examined} ROWS_MATCHED:{len(naive_matches)}")
        out_lines.append(f"  SARGABLE: PLAN=INDEX_RANGE_SCAN ROWS_EXAMINED:{sargable_examined} ROWS_MATCHED:{len(sargable_matches)} ROWS_SAVED:{saved}")

    # Summary
    out_lines.append(f"SUMMARY NAIVE TOTAL_ROWS_EXAMINED:{naive_total_examined}")
    out_lines.append(f"SUMMARY SARGABLE TOTAL_ROWS_EXAMINED:{sargable_total_examined}")

    total_saved = naive_total_examined - sargable_total_examined
    reduction = (total_saved / naive_total_examined * 100.0) if naive_total_examined > 0 else 0.0
    out_lines.append(f"SUMMARY ROWS_SAVED:{total_saved} (SCAN_REDUCTION:{reduction:.2f}%)")

    acc_str = "100% IDENTICAL RESULTS" if accuracy_ok else "MISMATCH_DETECTED"
    out_lines.append(f"SUMMARY ACCURACY_CHECK: {acc_str}")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
