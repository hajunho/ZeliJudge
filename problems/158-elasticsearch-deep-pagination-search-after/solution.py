import json
import sys

def solve_es(input_data):
    cluster = input_data.get("cluster", {})
    num_shards = int(cluster.get("num_shards", 4))
    max_window = int(cluster.get("max_result_window", 10000))
    heap_limit_kb = float(cluster.get("coordinator_heap_limit_mb", 50.0)) * 1024.0
    doc_overhead_kb = float(cluster.get("doc_overhead_kb", 0.5))

    sort_order = input_data.get("sort_order", "DESC")
    reverse = (sort_order == "DESC")

    docs_by_shard = {i: [] for i in range(num_shards)}
    for d in input_data.get("documents", []):
        sid = int(d["shard_id"])
        docs_by_shard[sid].append(d)

    def doc_sort_key(doc):
        return (-doc["timestamp"] if reverse else doc["timestamp"], doc["id"])

    for s in range(num_shards):
        docs_by_shard[s].sort(key=doc_sort_key)

    results = []

    for q in input_data.get("queries", []):
        qid = q["query_id"]
        qtype = q["type"]
        size = int(q["size"])

        if qtype == "FROM_SIZE":
            from_offset = int(q.get("from", 0))

            if from_offset + size > max_window:
                results.append({
                    "query_id": qid,
                    "type": qtype,
                    "status": "RESULT_WINDOW_EXCEEDED",
                    "retrieved_count": 0,
                    "shard_docs_scanned": 0,
                    "coordinator_memory_kb": 0.0,
                    "documents": [],
                    "diagnosis": f"REJECTED: Result window [{from_offset + size}] exceeds index.max_result_window [{max_window}]. Use search_after for deep pagination."
                })
                continue

            target_depth = from_offset + size
            shard_collected = []
            total_shard_docs = 0

            for s in range(num_shards):
                local_docs = docs_by_shard[s][:target_depth]
                total_shard_docs += len(local_docs)
                shard_collected.extend(local_docs)

            mem_kb = total_shard_docs * doc_overhead_kb
            if mem_kb > heap_limit_kb:
                results.append({
                    "query_id": qid,
                    "type": qtype,
                    "status": "COORDINATOR_OOM",
                    "retrieved_count": 0,
                    "shard_docs_scanned": total_shard_docs,
                    "coordinator_memory_kb": round(mem_kb, 1),
                    "documents": [],
                    "diagnosis": f"CRITICAL: Coordinator node Heap OOM! Required {mem_kb:.1f}KB exceeds limit {heap_limit_kb:.1f}KB when merging {total_shard_docs} documents from {num_shards} shards."
                })
                continue

            shard_collected.sort(key=doc_sort_key)
            page = shard_collected[from_offset : from_offset + size]
            retrieved_ids = [d["id"] for d in page]

            last_doc = page[-1] if page else None
            next_cursor = [last_doc["timestamp"], last_doc["id"]] if last_doc else None

            results.append({
                "query_id": qid,
                "type": qtype,
                "status": "SUCCESS",
                "retrieved_count": len(page),
                "shard_docs_scanned": total_shard_docs,
                "coordinator_memory_kb": round(mem_kb, 1),
                "documents": retrieved_ids,
                "next_search_after": next_cursor,
                "diagnosis": f"SUCCESS: Fetched {len(page)} docs with from+size. Coordinator held {total_shard_docs} docs ({mem_kb:.1f}KB) in heap."
            })

        elif qtype == "SEARCH_AFTER":
            cursor = q.get("search_after")
            shard_collected = []
            total_shard_docs = 0

            for s in range(num_shards):
                matching = []
                for doc in docs_by_shard[s]:
                    if cursor is not None:
                        c_ts, c_id = cursor
                        if reverse:
                            if doc["timestamp"] > c_ts:
                                continue
                            elif doc["timestamp"] == c_ts and doc["id"] <= c_id:
                                continue
                        else:
                            if doc["timestamp"] < c_ts:
                                continue
                            elif doc["timestamp"] == c_ts and doc["id"] <= c_id:
                                continue
                    matching.append(doc)
                    if len(matching) == size:
                        break
                total_shard_docs += len(matching)
                shard_collected.extend(matching)

            mem_kb = total_shard_docs * doc_overhead_kb
            shard_collected.sort(key=doc_sort_key)
            page = shard_collected[:size]
            retrieved_ids = [d["id"] for d in page]

            last_doc = page[-1] if page else None
            next_cursor = [last_doc["timestamp"], last_doc["id"]] if last_doc else None

            results.append({
                "query_id": qid,
                "type": qtype,
                "status": "SUCCESS",
                "retrieved_count": len(page),
                "shard_docs_scanned": total_shard_docs,
                "coordinator_memory_kb": round(mem_kb, 1),
                "documents": retrieved_ids,
                "next_search_after": next_cursor,
                "diagnosis": f"OPTIMAL: search_after fetched {len(page)} docs using O(1) heap ({mem_kb:.1f}KB for {total_shard_docs} shard docs). Zero deep-paging overhead."
            })

    return {"results": results}

if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if raw:
        inp = json.loads(raw)
        res = solve_es(inp)
        print(json.dumps(res, indent=2))
