import json
import re
import sys

def normalize_sql(query_text, use_bind_variables=False):
    normalized = " ".join(query_text.strip().split())
    if not use_bind_variables:
        return normalized
    # Replace quoted strings with ?
    s = re.sub(r"'[^']*'", "?", normalized)
    # Replace integer/float numbers with ?
    s = re.sub(r"\b\d+(\.\d+)?\b", "?", s)
    return s

def solve(data):
    use_bind_variables = data.get("use_bind_variables", False)
    cache_capacity = data.get("shared_pool_cursor_capacity", 50)
    hard_parse_cpu_cost_ms = data.get("hard_parse_cpu_cost_ms", 10.0)
    soft_parse_cpu_cost_ms = data.get("soft_parse_cpu_cost_ms", 0.1)
    execution_cost_ms = data.get("execution_cost_ms", 1.0)
    
    queries = data.get("queries", [])
    
    library_cache = {}
    lru_order = []
    
    total_hard_parses = 0
    total_soft_parses = 0
    cache_evictions = 0
    total_cpu_time_ms = 0.0
    
    query_results = []
    
    for q in queries:
        qid = q["query_id"]
        raw_sql = q["raw_sql"]
        
        sql_key = normalize_sql(raw_sql, use_bind_variables=use_bind_variables)
        
        is_hit = (sql_key in library_cache)
        
        if is_hit:
            total_soft_parses += 1
            parse_type = "SOFT_PARSE"
            parse_cost = soft_parse_cpu_cost_ms
            library_cache[sql_key]["hit_count"] += 1
            if sql_key in lru_order:
                lru_order.remove(sql_key)
            lru_order.append(sql_key)
        else:
            total_hard_parses += 1
            parse_type = "HARD_PARSE"
            parse_cost = hard_parse_cpu_cost_ms
            
            if len(library_cache) >= cache_capacity:
                evicted_key = lru_order.pop(0)
                del library_cache[evicted_key]
                cache_evictions += 1
                
            plan_id = f"PLAN_{len(library_cache) + 1:04d}"
            library_cache[sql_key] = {"hit_count": 1, "plan_id": plan_id}
            lru_order.append(sql_key)
            
        elapsed = parse_cost + execution_cost_ms
        total_cpu_time_ms += elapsed
        
        query_results.append({
            "query_id": qid,
            "sql_key": sql_key,
            "parse_type": parse_type,
            "elapsed_ms": round(elapsed, 2)
        })
        
    total_queries = len(queries)
    hard_parse_ratio = round((total_hard_parses / max(total_queries, 1)) * 100.0, 2)
    soft_parse_ratio = round((total_soft_parses / max(total_queries, 1)) * 100.0, 2)
    
    if hard_parse_ratio >= 80.0 and total_queries >= 20:
        verdict = "HARD_PARSE_STORM_CPU_EXHAUSTION"
    elif cache_evictions > 10:
        verdict = "SHARED_POOL_THRASHING_LRU_CHURN"
    elif soft_parse_ratio >= 70.0:
        verdict = "OPTIMAL_BIND_VARIABLE_REUSE"
    else:
        verdict = "MODERATE_PARSE_OVERHEAD"
        
    summary = {
        "use_bind_variables": use_bind_variables,
        "total_queries": total_queries,
        "total_hard_parses": total_hard_parses,
        "total_soft_parses": total_soft_parses,
        "hard_parse_ratio_pct": hard_parse_ratio,
        "soft_parse_ratio_pct": soft_parse_ratio,
        "cache_evictions": cache_evictions,
        "distinct_plans_cached": len(library_cache),
        "total_cpu_time_ms": round(total_cpu_time_ms, 2),
        "overall_verdict": verdict
    }
    
    return {
        "summary": summary,
        "sample_query_results": query_results[:10]
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
