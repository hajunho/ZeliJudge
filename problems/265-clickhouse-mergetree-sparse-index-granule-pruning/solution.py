import sys
import json
import math

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def satisfies_condition(val, cond):
    if "eq" in cond and val != cond["eq"]:
        return False
    if "neq" in cond and val == cond["neq"]:
        return False
    if "gt" in cond and val <= cond["gt"]:
        return False
    if "gte" in cond and val < cond["gte"]:
        return False
    if "lt" in cond and val >= cond["lt"]:
        return False
    if "lte" in cond and val > cond["lte"]:
        return False
    if "in" in cond and val not in cond["in"]:
        return False
    return True

def row_matches_where(row, where):
    for col, cond in where.items():
        val = row.get(col)
        if not satisfies_condition(val, cond):
            return False
    return True

def granule_overlaps_query(start_key, end_key, pk_cols, where):
    n_cols = len(pk_cols)
    for i in range(n_cols):
        col = pk_cols[i]
        s_val = start_key[i]
        e_val = end_key[i]

        cond = where.get(col)
        if cond:
            if "eq" in cond:
                target = cond["eq"]
                if target < s_val or target > e_val:
                    return False
                if target == s_val and s_val < e_val:
                    if i + 1 < n_cols:
                        next_col = pk_cols[i+1]
                        next_cond = where.get(next_col)
                        if next_cond:
                            c_max = next_cond.get("lte", next_cond.get("lt", next_cond.get("eq")))
                            if c_max is not None and c_max < start_key[i+1]:
                                return False
                elif target == e_val and s_val < e_val:
                    if i + 1 < n_cols:
                        next_col = pk_cols[i+1]
                        next_cond = where.get(next_col)
                        if next_cond:
                            c_min = next_cond.get("gte", next_cond.get("gt", next_cond.get("eq")))
                            if c_min is not None and c_min > end_key[i+1]:
                                return False
                if s_val == e_val == target:
                    continue
                else:
                    return True

            c_min = cond.get("gte", cond.get("gt"))
            c_max = cond.get("lte", cond.get("lt"))
            if c_min is not None and e_val < c_min:
                return False
            if c_max is not None and s_val > c_max:
                return False

        if s_val != e_val:
            break

    return True

def run_clickhouse_simulation(data):
    config = data["config"]
    queries = data["queries"]

    pk_cols = config["primary_key"]
    granule_size = config.get("granule_size", 8192)
    marks_per_block = config.get("marks_per_compressed_block", 2)
    skipping_indices = config.get("data_skipping_indices", [])
    rows = config["rows"]

    # Sort rows by primary key
    rows = sorted(rows, key=lambda r: tuple(r[c] for c in pk_cols))

    total_rows = len(rows)
    num_granules = math.ceil(total_rows / granule_size) if total_rows > 0 else 0

    granules = []
    primary_index = []
    for g in range(num_granules):
        s_idx = g * granule_size
        e_idx = min(total_rows, (g + 1) * granule_size) - 1
        first_row = rows[s_idx]
        last_row = rows[e_idx]
        start_key = tuple(first_row[c] for c in pk_cols)
        last_key = tuple(last_row[c] for c in pk_cols)

        primary_index.append(list(start_key))
        compressed_block_id = g // marks_per_block
        uncompressed_offset = (g % marks_per_block) * granule_size

        granules.append({
            "granule_id": g,
            "start_row_idx": s_idx,
            "end_row_idx": e_idx,
            "row_count": e_idx - s_idx + 1,
            "start_key": start_key,
            "end_key": last_key,
            "compressed_block_id": compressed_block_id,
            "uncompressed_offset": uncompressed_offset
        })

    skipping_index_data = {}
    for idx_def in skipping_indices:
        col = idx_def["column"]
        itype = idx_def["type"]
        granularity = idx_def.get("granularity", 1)
        blocks = []
        num_blocks = math.ceil(num_granules / granularity) if num_granules > 0 else 0
        for b in range(num_blocks):
            g_start = b * granularity
            g_end = min(num_granules, (b + 1) * granularity)
            vals = []
            for g in range(g_start, g_end):
                r_start = granules[g]["start_row_idx"]
                r_end = granules[g]["end_row_idx"]
                for r in range(r_start, r_end + 1):
                    vals.append(rows[r][col])

            if itype == "minmax":
                b_min = min(vals) if vals else None
                b_max = max(vals) if vals else None
                blocks.append({
                    "block_id": b,
                    "granule_range": [g_start, g_end - 1],
                    "min": b_min,
                    "max": b_max
                })
            elif itype == "set":
                val_set = sorted(list(set(vals))) if vals else []
                blocks.append({
                    "block_id": b,
                    "granule_range": [g_start, g_end - 1],
                    "set": val_set
                })
        skipping_index_data[idx_def["name"]] = {
            "def": idx_def,
            "blocks": blocks
        }

    query_results = []
    for q in queries:
        qid = q["query_id"]
        where = q.get("where", {})

        pk_surviving = []
        for g in granules:
            if granule_overlaps_query(g["start_key"], g["end_key"], pk_cols, where):
                pk_surviving.append(g["granule_id"])

        final_surviving = set(pk_surviving)
        for idx_name, idx_info in skipping_index_data.items():
            col = idx_info["def"]["column"]
            itype = idx_info["def"]["type"]
            if col in where:
                cond = where[col]
                for b in idx_info["blocks"]:
                    g_s, g_e = b["granule_range"]
                    if any(gid in final_surviving for gid in range(g_s, g_e + 1)):
                        should_skip = False
                        if itype == "minmax":
                            b_min = b["min"]
                            b_max = b["max"]
                            if b_min is not None and b_max is not None:
                                if "eq" in cond and (cond["eq"] < b_min or cond["eq"] > b_max):
                                    should_skip = True
                                elif "gt" in cond and b_max <= cond["gt"]:
                                    should_skip = True
                                elif "gte" in cond and b_max < cond["gte"]:
                                    should_skip = True
                                elif "lt" in cond and b_min >= cond["lt"]:
                                    should_skip = True
                                elif "lte" in cond and b_min > cond["lte"]:
                                    should_skip = True
                        elif itype == "set":
                            v_set = set(b["set"])
                            if "eq" in cond and cond["eq"] not in v_set:
                                should_skip = True
                            elif "in" in cond and not any(v in v_set for v in cond["in"]):
                                should_skip = True

                        if should_skip:
                            for gid in range(g_s, g_e + 1):
                                final_surviving.discard(gid)

        surviving_list = sorted(list(final_surviving))
        skipped_list = [g["granule_id"] for g in granules if g["granule_id"] not in final_surviving]

        loaded_blocks = sorted(list(set(granules[gid]["compressed_block_id"] for gid in surviving_list)))
        rows_scanned = sum(granules[gid]["row_count"] for gid in surviving_list)

        matching_rows = []
        for gid in surviving_list:
            g = granules[gid]
            for r_idx in range(g["start_row_idx"], g["end_row_idx"] + 1):
                row = rows[r_idx]
                if row_matches_where(row, where):
                    matching_rows.append(row)

        skip_ratio = round(len(skipped_list) / num_granules, 4) if num_granules > 0 else 0.0
        pruning_eff = round(1.0 - (rows_scanned / total_rows), 4) if total_rows > 0 else 0.0

        query_results.append({
            "query_id": qid,
            "total_granules": num_granules,
            "granules_read_count": len(surviving_list),
            "granules_skipped_count": len(skipped_list),
            "granules_read": surviving_list,
            "granules_skipped": skipped_list,
            "skip_ratio": skip_ratio,
            "compressed_blocks_loaded": loaded_blocks,
            "compressed_blocks_count": len(loaded_blocks),
            "total_compressed_blocks": math.ceil(num_granules / marks_per_block) if num_granules > 0 else 0,
            "rows_scanned": rows_scanned,
            "matching_rows_count": len(matching_rows),
            "pruning_efficiency": pruning_eff,
            "matching_rows": matching_rows
        })

    return {
        "part_summary": {
            "total_rows": total_rows,
            "granule_size": granule_size,
            "total_granules": num_granules,
            "total_compressed_blocks": math.ceil(num_granules / marks_per_block) if num_granules > 0 else 0,
            "primary_key": pk_cols,
            "primary_index_entries": len(primary_index)
        },
        "query_evaluations": query_results
    }

def main():
    raw_input = sys.stdin.read().strip()
    if not raw_input:
        return
    data = json.loads(raw_input)
    res = run_clickhouse_simulation(data)
    print(json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    main()
