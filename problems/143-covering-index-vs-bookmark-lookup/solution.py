import json
import math
import sys

def solve(data):
    total_rows = data.get("total_rows", 100000)
    rows_per_page = data.get("rows_per_page", 100)
    index_rows_per_page = data.get("index_rows_per_page", 500)
    
    sequential_io_cost_per_page = data.get("sequential_io_cost_per_page", 1.0)
    random_io_cost_per_page = data.get("random_io_cost_per_page", 4.0)
    clustering_factor_ratio = data.get("clustering_factor_ratio", 0.8)
    
    matching_rows = data.get("matching_rows", 5000)
    is_covering_index = data.get("is_covering_index", False)
    force_plan = data.get("force_plan", "AUTO")
    
    total_data_pages = math.ceil(total_rows / rows_per_page) if total_rows > 0 else 0
    
    # 1. Full Table Scan Cost
    fts_cost = round(total_data_pages * sequential_io_cost_per_page, 2)
    
    # 2. Index Scan Cost
    index_leaf_pages = math.ceil(matching_rows / index_rows_per_page) if matching_rows > 0 else 0
    index_leaf_cost = index_leaf_pages * sequential_io_cost_per_page
    
    def calculate_visited_pages(m_rows):
        if m_rows <= 0 or total_data_pages <= 0:
            return 0
        clustered_pages = min(total_data_pages, math.ceil(m_rows / rows_per_page))
        unclustered_pages = total_data_pages * (1.0 - math.exp(-m_rows / total_data_pages))
        visited = (1.0 - clustering_factor_ratio) * clustered_pages + clustering_factor_ratio * unclustered_pages
        return min(total_data_pages, max(1, round(visited)))
        
    if is_covering_index or matching_rows == 0:
        bookmark_lookup_pages = 0
        bookmark_lookup_cost = 0.0
    else:
        bookmark_lookup_pages = calculate_visited_pages(matching_rows)
        bookmark_lookup_cost = bookmark_lookup_pages * random_io_cost_per_page
        
    total_index_cost = round(index_leaf_cost + bookmark_lookup_cost, 2)
    
    # 3. Plan Selection
    if force_plan == "FORCE_INDEX":
        chosen_plan = "INDEX_ONLY_COVERING_SCAN" if is_covering_index else "INDEX_RANGE_SCAN"
        final_cost = total_index_cost
    elif force_plan == "FORCE_FTS":
        chosen_plan = "FULL_TABLE_SCAN"
        final_cost = fts_cost
    else: # AUTO
        if total_index_cost <= fts_cost:
            chosen_plan = "INDEX_ONLY_COVERING_SCAN" if is_covering_index else "INDEX_RANGE_SCAN"
            final_cost = total_index_cost
        else:
            chosen_plan = "FULL_TABLE_SCAN"
            final_cost = fts_cost
            
    selectivity_pct = round((matching_rows / total_rows) * 100.0, 2) if total_rows > 0 else 0.0
    
    # Tipping point estimation (for non-covering index):
    tipping_point_pct = 0.0
    if not is_covering_index and total_rows > 0 and total_data_pages > 0:
        low, high = 1, total_rows
        best_m = total_rows
        for _ in range(30):
            mid = (low + high) / 2.0
            v_pages = calculate_visited_pages(mid)
            idx_cost = (mid / index_rows_per_page) * sequential_io_cost_per_page + v_pages * random_io_cost_per_page
            if idx_cost >= fts_cost:
                best_m = mid
                high = mid
            else:
                low = mid
        tipping_point_pct = round((best_m / total_rows) * 100.0, 2)
    else:
        tipping_point_pct = 100.0
        
    # Verdict
    if force_plan == "FORCE_INDEX" and total_index_cost > fts_cost:
        verdict = "FORCED_INDEX_PERFORMANCE_DISASTER"
    elif is_covering_index:
        verdict = "COVERING_INDEX_ZERO_BOOKMARK_LOOKUP"
    elif chosen_plan == "FULL_TABLE_SCAN" and selectivity_pct >= tipping_point_pct:
        verdict = "TIPPING_POINT_EXCEEDED_FTS_FASTER"
    elif chosen_plan == "INDEX_RANGE_SCAN":
        verdict = "OPTIMAL_INDEX_RANGE_SCAN"
    else:
        verdict = "BALANCED_PLAN"
        
    summary = {
        "total_rows": total_rows,
        "matching_rows": matching_rows,
        "selectivity_pct": selectivity_pct,
        "total_data_pages": total_data_pages,
        "clustering_factor_ratio": clustering_factor_ratio,
        "is_covering_index": is_covering_index,
        "force_plan": force_plan,
        "full_table_scan_cost": fts_cost,
        "index_scan_cost": total_index_cost,
        "bookmark_lookup_pages": bookmark_lookup_pages,
        "bookmark_lookup_cost": round(bookmark_lookup_cost, 2),
        "chosen_execution_plan": chosen_plan,
        "final_execution_cost": final_cost,
        "tipping_point_estimated_pct": tipping_point_pct,
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary
    }

if __name__ == "__main__":
    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            sys.exit(0)
        input_data = json.loads(raw_input)
        result = solve(input_data)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
