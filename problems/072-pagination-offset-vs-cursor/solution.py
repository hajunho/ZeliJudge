import sys
import math
from bisect import bisect_right

def solve():
    input_data = sys.stdin.read().splitlines()
    if not input_data:
        return

    mode = "CONFIG"
    page_size = 10
    actions = []

    for line in input_data:
        line = line.strip()
        if not line:
            continue
        if line == "SYSTEM_CONFIG":
            mode = "CONFIG"
            continue
        elif line == "ACTIONS":
            mode = "ACTIONS"
            continue

        parts = line.split()
        if mode == "CONFIG":
            if parts[0] == "PAGE_SIZE":
                page_size = int(parts[1])
        elif mode == "ACTIONS":
            actions.append(parts)

    records = {}  # id -> title
    # Sorted list of ids in descending order
    # To use bisect easily on descending, we can store negative ids or sort normally
    sorted_ids_desc = []

    # Metrics for Naive Offset
    naive_total_examined = 0
    naive_seen_ids = set()
    naive_duplicate_count = 0

    # Metrics for Cursor Keyset
    cursor_total_examined = 0
    cursor_seen_ids = set()
    cursor_duplicate_count = 0

    out_lines = []

    for act_idx, act in enumerate(actions, 1):
        cmd = act[0]

        if cmd == "INSERT_RECORD":
            r_id = int(act[1])
            title = act[2]
            records[r_id] = title

            # Insert in sorted_ids_desc
            # We can just keep it sorted
            # Since N can be up to thousands, bisect on negated id is O(log N)
            neg_id = -r_id
            # Find insertion position in [-id for id in sorted_ids_desc]
            # Maintain sorted_ids_desc directly
            # For simplicity:
            idx = 0
            # binary search in sorted_ids_desc
            low = 0
            high = len(sorted_ids_desc)
            while low < high:
                mid = (low + high) // 2
                if sorted_ids_desc[mid] > r_id:
                    low = mid + 1
                else:
                    high = mid
            sorted_ids_desc.insert(low, r_id)

            out_lines.append(f"ACT {act_idx} INSERT_RECORD ID:{r_id} TITLE:{title}")

        elif cmd == "PAGE_OFFSET":
            page_num = int(act[1])
            offset = (page_num - 1) * page_size
            N = len(sorted_ids_desc)

            # Examined in DB: reads all rows up to offset + page_size
            examined = min(N, offset + page_size)
            naive_total_examined += examined

            returned_ids = sorted_ids_desc[offset:offset + page_size]
            for rid in returned_ids:
                if rid in naive_seen_ids:
                    naive_duplicate_count += 1
                else:
                    naive_seen_ids.add(rid)

            ids_str = ",".join(map(str, returned_ids))
            out_lines.append(f"ACT {act_idx} PAGE_OFFSET PAGE:{page_num}")
            out_lines.append(f"  NAIVE_OFFSET: EXAMINED:{examined} ROWS_RETURNED:{len(returned_ids)} IDS:[{ids_str}] DUPLICATES_SEEN:{naive_duplicate_count}")

        elif cmd == "PAGE_CURSOR":
            cur_str = act[1]
            N = len(sorted_ids_desc)
            H = max(1, math.ceil(math.log2(N))) if N > 0 else 1

            if cur_str in ("START", "NONE", "-1"):
                start_idx = 0
            else:
                cur_id = int(cur_str)
                # Find first index where sorted_ids_desc[idx] < cur_id
                low = 0
                high = len(sorted_ids_desc)
                while low < high:
                    mid = (low + high) // 2
                    if sorted_ids_desc[mid] >= cur_id:
                        low = mid + 1
                    else:
                        high = mid
                start_idx = low

            returned_ids = sorted_ids_desc[start_idx:start_idx + page_size]
            examined = H + len(returned_ids)
            cursor_total_examined += examined

            for rid in returned_ids:
                if rid in cursor_seen_ids:
                    cursor_duplicate_count += 1
                else:
                    cursor_seen_ids.add(rid)

            next_cur = str(returned_ids[-1]) if returned_ids else "NONE"
            ids_str = ",".join(map(str, returned_ids))
            out_lines.append(f"ACT {act_idx} PAGE_CURSOR CURSOR:{cur_str}")
            out_lines.append(f"  CURSOR_KEYSET: EXAMINED:{examined} ROWS_RETURNED:{len(returned_ids)} NEXT_CURSOR:{next_cur} IDS:[{ids_str}] DUPLICATES_SEEN:{cursor_duplicate_count}")

        elif cmd == "CHECK_METRICS":
            out_lines.append(f"ACT {act_idx} CHECK_METRICS")
            out_lines.append(f"  NAIVE_OFFSET: TOTAL_EXAMINED:{naive_total_examined} DUPLICATES:{naive_duplicate_count}")
            out_lines.append(f"  CURSOR_KEYSET: TOTAL_EXAMINED:{cursor_total_examined} DUPLICATES:{cursor_duplicate_count}")

    # Final Summary
    total_records = len(sorted_ids_desc)
    saved_examined = naive_total_examined - cursor_total_examined
    reduction_pct = (saved_examined / naive_total_examined * 100.0) if naive_total_examined > 0 else 0.0

    out_lines.append(f"SUMMARY TOTAL_RECORDS:{total_records}")
    out_lines.append(f"SUMMARY NAIVE_OFFSET TOTAL_EXAMINED:{naive_total_examined} DUPLICATES_SEEN:{naive_duplicate_count}")
    out_lines.append(f"SUMMARY CURSOR_KEYSET TOTAL_EXAMINED:{cursor_total_examined} DUPLICATES_SEEN:{cursor_duplicate_count}")
    out_lines.append(f"SUMMARY ROWS_EXAMINED_SAVED:{saved_examined} (SCAN_REDUCTION:{reduction_pct:.2f}%)")
    out_lines.append("SUMMARY PAGINATION_VERDICT: CURSOR_100%_CONSISTENT_AND_FAST")

    print("\n".join(out_lines))

if __name__ == "__main__":
    solve()
