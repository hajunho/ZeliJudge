import sys
import json
import math

def solve():
    input_data = sys.stdin.read().strip()
    if not input_data:
        return
    
    data = json.loads(input_data)
    config = data.get("config", {})
    format_type = config.get("storage_format", "COLUMNAR")  # ROW_ORIENTED or COLUMNAR
    row_group_size = int(config.get("row_group_size", 64000))
    zone_maps_enabled = bool(config.get("zone_maps_enabled", True))
    disk_bandwidth_mbps = float(config.get("disk_read_bandwidth_mbps", 500.0))
    sla_timeout_ms = float(config.get("query_sla_timeout_ms", 100.0))

    schema = data.get("schema", {})
    total_rows = int(schema.get("total_rows", 1000000))
    columns = schema.get("columns", [])

    query = data.get("query", {})
    projected_cols = query.get("projected_columns", [])
    predicates = query.get("predicates", [])
    if "predicate" in query and query["predicate"]:
        predicates = [query["predicate"]]

    num_row_groups = int(math.ceil(total_rows / row_group_size))

    accessed_col_names = set(projected_cols)
    for p in predicates:
        if "column" in p:
            accessed_col_names.add(p["column"])

    cols_by_name = {c["name"]: c for c in columns}
    row_size_bytes = sum(c.get("uncompressed_bytes_per_value", 4) for c in columns)

    total_bytes_read = 0.0
    scanned_row_groups = 0
    skipped_row_groups = 0
    dict_explosion_detected = False

    if format_type == "ROW_ORIENTED":
        scanned_row_groups = num_row_groups
        skipped_row_groups = 0
        total_bytes_read = total_rows * row_size_bytes
        cpu_time_ms = total_rows * 0.00005
    else:  # COLUMNAR
        for rg_idx in range(num_row_groups):
            rg_start_row = rg_idx * row_group_size
            rg_end_row = min(total_rows, (rg_idx + 1) * row_group_size)
            rg_rows = rg_end_row - rg_start_row

            skip_rg = False
            if zone_maps_enabled and predicates:
                for pred in predicates:
                    pred_col = cols_by_name.get(pred.get("column"))
                    if pred_col and pred_col.get("is_sorted"):
                        min_val = pred_col.get("min_val", 0)
                        max_val = pred_col.get("max_val", 1000000)
                        step = (max_val - min_val) / num_row_groups
                        rg_min = min_val + (rg_idx * step)
                        rg_max = min_val + ((rg_idx + 1) * step)

                        op = pred.get("op", "=")
                        target = pred.get("val", 0)

                        if op == ">=" and rg_max < target:
                            skip_rg = True
                            break
                        elif op == "<=" and rg_min > target:
                            skip_rg = True
                            break
                        elif op == ">" and rg_max <= target:
                            skip_rg = True
                            break
                        elif op == "<" and rg_min >= target:
                            skip_rg = True
                            break
                        elif op == "=" and (target < rg_min or target > rg_max):
                            skip_rg = True
                            break

            if skip_rg:
                skipped_row_groups += 1
                continue

            scanned_row_groups += 1

            for col_name in accessed_col_names:
                col = cols_by_name.get(col_name, {})
                raw_bytes = col.get("uncompressed_bytes_per_value", 4)
                cardinality = col.get("cardinality", total_rows)
                is_sorted = col.get("is_sorted", False)
                encoding = col.get("encoding", "AUTO")

                if encoding == "AUTO":
                    if is_sorted and cardinality <= 50:
                        chosen_enc = "RLE"
                    elif cardinality <= 256:
                        chosen_enc = "DICTIONARY"
                    elif cardinality <= 16:
                        chosen_enc = "BIT_PACKING"
                    else:
                        chosen_enc = "PLAIN"
                else:
                    chosen_enc = encoding

                if chosen_enc == "DICTIONARY":
                    if cardinality > (rg_rows * 0.8):
                        dict_explosion_detected = True
                        col_bytes = rg_rows * raw_bytes * 1.25
                    else:
                        dict_size = cardinality * raw_bytes
                        id_size = 1 if cardinality <= 256 else 2
                        col_bytes = dict_size + (rg_rows * id_size)
                elif chosen_enc == "RLE":
                    col_bytes = rg_rows * (raw_bytes / 25.0)
                elif chosen_enc == "BIT_PACKING":
                    bits_per_val = max(1, math.ceil(math.log2(cardinality + 1)))
                    col_bytes = (rg_rows * bits_per_val) / 8.0
                else:
                    col_bytes = rg_rows * raw_bytes

                total_bytes_read += col_bytes

        cpu_time_ms = (scanned_row_groups * row_group_size) * 0.00001

    total_bytes_read_mb = total_bytes_read / (1024.0 * 1024.0)
    io_time_ms = (total_bytes_read_mb / disk_bandwidth_mbps) * 1000.0 if disk_bandwidth_mbps > 0 else 0.0
    total_query_latency_ms = io_time_ms + cpu_time_ms

    raw_uncompressed_mb = (total_rows * row_size_bytes) / (1024.0 * 1024.0)
    data_reduction_ratio = max(0.0, 1.0 - (total_bytes_read_mb / raw_uncompressed_mb)) if raw_uncompressed_mb > 0 else 0.0

    if dict_explosion_detected:
        status = "FAILED"
        verdict = "DICTIONARY_CARDINALITY_EXPLOSION_FALLBACK"
    elif format_type == "ROW_ORIENTED":
        if total_query_latency_ms > sla_timeout_ms:
            status = "FAILED"
            verdict = "ROW_STORE_SCAN_BANDWIDTH_EXHAUSTION"
        else:
            status = "SUCCESS"
            verdict = "STANDARD_ROW_SCAN_SUCCESS"
    else:  # COLUMNAR
        if total_query_latency_ms > sla_timeout_ms:
            status = "FAILED"
            verdict = "QUERY_SLA_TIMEOUT_EXCEEDED"
        elif skipped_row_groups > 0 and data_reduction_ratio >= 0.75:
            status = "SUCCESS"
            verdict = "OPTIMAL_COLUMNAR_VECTORIZED_SCAN"
        else:
            status = "SUCCESS"
            verdict = "COLUMNAR_NO_ZONE_MAP_PARTIAL_SCAN"

    result = {
        "status": status,
        "verdict": verdict,
        "metrics": {
            "storage_format": format_type,
            "total_bytes_read_mb": round(total_bytes_read_mb, 2),
            "raw_uncompressed_mb": round(raw_uncompressed_mb, 2),
            "data_reduction_ratio": round(data_reduction_ratio, 4),
            "total_row_groups": num_row_groups,
            "skipped_row_groups": skipped_row_groups,
            "scanned_row_groups": scanned_row_groups,
            "total_query_latency_ms": round(total_query_latency_ms, 2)
        }
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    solve()
