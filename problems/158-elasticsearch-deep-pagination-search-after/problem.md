# #158 10만 번째 페이지 조회했을 뿐인데 왜 Elasticsearch 클러스터가 OOM으로 폭사해요?!: 샤드 딥 페이징(Deep Pagination)과 from + size 한계 vs search_after & Point-in-Time

## 1. 실무 장애 시나리오: "전체 상품 목록 크롤링 쿼리 몇 방에 검색 클러스터가 뻗었다고?!"

글로벌 이커머스 플랫폼 '젤리쇼핑'의 데이터 검색팀은 수천만 건의 상품 및 주문 내역을 실시간 검색하기 위해 **Elasticsearch 분산 클러스터(5개 프라이머리 샤드, 3개 노드)**를 운용하고 있습니다.

어느 날 새벽, 마케팅 데이터 파이프라인 워커와 외부 가격 비교 크롤러가 전체 상품 500만 건을 수집하기 위해 다음과 같이 페이징 파라미터를 증가시키며 대규모 검색 요청을 쏟아부었습니다:

```http
GET /products/_search
{
  "from": 100000,
  "size": 100,
  "sort": [
    { "created_at": "desc" },
    { "id": "asc" }
  ]
}
```

```
                     [ Client / Crawler ]
                              │
                     GET /products/_search
                   from=100,000 & size=100
                              ▼
                ┌───────────────────────────┐
                │  Coordinating Node        │
                │  Broadcasts to 5 Shards   │
                └──────┬─────────────┬──────┘
                       │             │
         ┌─────────────┼─────────────┼─────────────┐
         ▼             ▼             ▼             ▼
    [ Shard 0 ]   [ Shard 1 ]   [ Shard 2 ]   [ Shard 3 ]
   Top 100,100   Top 100,100   Top 100,100   Top 100,100
   docs in heap  docs in heap  docs in heap  docs in heap
         │             │             │             │
         └─────────────┼─────────────┼─────────────┘
                       │ 500,500 Document Headers!
                       ▼
        ┌──────────────────────────────────────────┐
        │ Coordinating Node JVM Heap               │
        │ Must MERGE-SORT 500,500 documents!       │
        │ -> Old Gen Heap Exhaustion (100%)        │
        │ -> Stop-The-World Full GC (30s+)         │
        │ -> Master Disconnect / OOMKilled Disaster│
        └──────────────────────────────────────────┘
```

그러자 믿을 수 없는 참사가 벌어졌습니다:
1. **샤드와 코디네이터 노드의 메모리 폭발**:
   - `from=100000, size=100`을 처리하기 위해 **5개 샤드 각각이 로컬 Lucene 인덱스에서 상위 100,100개의 문서를 메모리에 적재하여 코디네이터 노드로 전송**했습니다!
   - 코디네이터 노드는 5개 샤드에서 날아온 무려 **500,500개의 문서 메타데이터(Score, Sort Value, Doc ID)를 JVM 힙 메모리에 띄워놓고 우선순위 큐(Priority Queue) 글로벌 병합 정렬**을 수행해야 했습니다!
2. **클러스터 전면 다운 (Cascade Failure)**:
   - 크롤러 워커들이 20개 스레드로 딥 페이징을 병렬 호출하자 코디네이터 노드와 데이터 노드들의 JVM Old Gen 힙 메모리가 100% 꽉 차면서 **30초 이상의 Full GC Stop-The-World (STW)**가 발생했습니다.
   - 마스터 노드와의 하트비트가 끊기며 클러스터 상태가 RED로 전환되었고, 결국 OS 커널 OOM Killer에 의해 Elasticsearch 프로세스가 강제 사살(OOMKilled)되는 대재앙이 터졌습니다!

### 주니어 엔지니어의 위험천만한 오답: "index.max_result_window를 1,000,000으로 늘리죠!"
Elasticsearch는 기본적으로 `from + size > 10,000`인 딥 페이징 쿼리를 거부하는 안전 가드레일(`index.max_result_window: 10000`)을 두고 있습니다.
주니어 엔지니어가 에러를 피하려고 이 한도를 무작정 100만으로 풀었다가, 쿼리 단 1방에 수 기가바이트의 힙 메모리를 삼키며 전 노드가 동시 폭사한 것입니다!

---

## 2. 구원 아키텍처: `search_after` & Point-in-Time (PIT)

검색 아키텍처팀은 무거운 글로벌 병합 정렬을 요구하는 `from + size` 방식을 영구 금지하고, Lucene 커서 기반의 **`search_after` (Point-in-Time)** 페이징을 도입했습니다:

1. **커서 기반 $O(1)$ 메모리 탐색**:
   - `search_after`는 이전 페이지의 마지막 문서 정렬 값(Tie-breaker인 `[timestamp, doc_id]`)을 다음 쿼리의 커서로 넘깁니다:
     ```json
     {
       "size": 100,
       "sort": [{ "created_at": "desc" }, { "id": "asc" }],
       "search_after": [1680000000, 9999]
     }
     ```
   - **각 샤드는 `created_at < 1680000000` (또는 타임스탬프가 같을 경우 `id > 9999`)인 조건으로 Lucene B-Tree/FST 인덱스를 인덱스 시크(Index Seek)하여 오직 `size` (100개) 문서만 수집**합니다!
   - 코디네이터 노드는 5개 샤드로부터 $5 	imes 100 = 500$개 문서만 전달받아 병합 정렬합니다.
   - 10만 번째 페이지, 100만 번째 페이지를 조회하더라도 메모리 사용량은 첫 페이지와 완전히 동일한 **$O(K 	imes size)$ 상수 메모리**로 유지됩니다!
2. **타이 브레이커(Tie-breaker)를 통한 결정론적 정렬 보장**:
   - `created_at` 같은 비고유(Non-unique) 필드로만 정렬하면 동일한 시각에 생성된 문서들의 순서가 샤드 병합 시 뒤바뀌어 문서 누락이나 중복이 발생합니다.
   - 반드시 고유 식별자인 `id`(`_id`)를 보조 정렬 키(Tie-breaker)로 지정하여 완전한 전순서(Total Ordering)를 보장해야 합니다.

당신은 Elasticsearch의 샤드 분산 쿼리 엔진을 구현하여, `from + size`의 메모리 폭발 한계를 검증하고 `search_after` 커서 페이징의 $O(1)$ 메모리 최적화를 증명해야 합니다.

---

## 3. 입력 형식 (JSON)

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "cluster": {
    "num_shards": 4,
    "max_result_window": 10000,
    "coordinator_heap_limit_mb": 50.0,
    "doc_overhead_kb": 0.5
  },
  "sort_order": "DESC",
  "documents": [
    { "id": 1, "timestamp": 100, "shard_id": 0 },
    { "id": 2, "timestamp": 200, "shard_id": 1 }
  ],
  "queries": [
    {
      "query_id": "q1",
      "type": "FROM_SIZE",
      "from": 0,
      "size": 10
    },
    {
      "query_id": "q2",
      "type": "SEARCH_AFTER",
      "search_after": [200, 2],
      "size": 10
    }
  ]
}
```

### 필드 명세
* `cluster`:
  * `num_shards`: 클러스터의 샤드 개수 ($K$)
  * `max_result_window`: `from + size`의 최대 허용 한계 (기본 10,000)
  * `coordinator_heap_limit_mb`: 코디네이터 노드의 허용 힙 메모리 한계 (MB)
  * `doc_overhead_kb`: 샤드에서 코디네이터로 전송되는 문서 메타데이터 1건당 메모리 오버헤드 (KB)
* `sort_order`: `"DESC"` (최신순) 또는 `"ASC"` (오래된순).
  * 1차 정렬 키: `timestamp`
  * 2차 정렬 키 (Tie-breaker): `id` (항상 `ASC` 정렬)
* `documents`: 클러스터 내 전체 문서 목록 (`id`, `timestamp`, `shard_id`)
* `queries`: 페이징 쿼리 목록:
  * `type`: `"FROM_SIZE"` 또는 `"SEARCH_AFTER"`
  * `"FROM_SIZE"`: `from`, `size` 파라미터 제공.
  * `"SEARCH_AFTER"`: `search_after` 커서 (`[timestamp, id]` 또는 첫 페이지 시 `null`), `size` 제공.

---

## 4. 출력 형식 (JSON)

표준 출력(stdout)으로 들여쓰기 2칸(`indent=2`)이 적용된 JSON 객체를 출력합니다:

```json
{
  "results": [
    {
      "query_id": "q1",
      "type": "FROM_SIZE",
      "status": "SUCCESS",
      "retrieved_count": 2,
      "shard_docs_scanned": 4,
      "coordinator_memory_kb": 2.0,
      "documents": [2, 1],
      "next_search_after": [100, 1],
      "diagnosis": "SUCCESS: Fetched 2 docs with from+size. Coordinator held 4 docs (2.0KB) in heap."
    }
  ]
}
```

### 상태(status) 및 진단(diagnosis) 규칙
1. `from + size > max_result_window`일 때:
   * `status`: `"RESULT_WINDOW_EXCEEDED"`
   * `diagnosis`: `"REJECTED: Result window [{from+size}] exceeds index.max_result_window [{max_window}]. Use search_after for deep pagination."`
2. 코디네이터 힙 초과 시 (`mem_kb > heap_limit_kb`):
   * `status`: `"COORDINATOR_OOM"`
   * `diagnosis`: `"CRITICAL: Coordinator node Heap OOM! Required {mem_kb:.1f}KB exceeds limit {limit:.1f}KB when merging {docs} documents from {shards} shards."`
3. 정상 성공 시:
   * `"FROM_SIZE"`: `"SUCCESS: Fetched {N} docs with from+size. Coordinator held {total_shard_docs} docs ({mem_kb:.1f}KB) in heap."`
   * `"SEARCH_AFTER"`: `"OPTIMAL: search_after fetched {N} docs using O(1) heap ({mem_kb:.1f}KB for {total_shard_docs} shard docs). Zero deep-paging overhead."`
