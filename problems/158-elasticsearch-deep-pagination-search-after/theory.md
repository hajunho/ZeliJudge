# [CS Deep Dive] Elasticsearch 분산 검색과 딥 페이징의 메모리 복잡도 분석

## 1. 분산 샤드 아키텍처와 Query-then-Fetch 메커니즘

Elasticsearch는 대용량 데이터를 $K$개의 독립적인 **Lucene 인덱스(샤드, Shard)**로 수평 분할(Sharding)하여 저장합니다.

클라이언트가 검색 요청을 보내면, 요청을 받은 노드는 **코디네이터 노드(Coordinating Node)** 역할을 수행하며 2단계(Two-Phase)로 쿼리를 실행합니다:

```
[ Phase 1: Query Phase ]
1. Coordinating Node가 쿼리를 모든 대상 샤드로 브로드캐스트.
2. 각 샤드는 로컬 Lucene 인덱스를 검색하여 상위 (from + size)개 문서의 메타데이터(Doc ID + Sort Values)만 반환.
3. Coordinating Node가 모든 샤드의 메타데이터를 수집하여 글로벌 병합 정렬(Priority Queue)을 수행.
4. 상위 [from, from + size) 구간의 최종 승자 문서 ID 확정.

[ Phase 2: Fetch Phase ]
5. 확정된 size개의 문서 ID에 대해서만 해당 문서가 존재하는 샤드로 _source 원본 데이터를 요청하여 클라이언트에 응답.
```

---

## 2. `from + size` 딥 페이징의 알고리즘 복잡도 폭탄

`from = 100,000, size = 100`, 샤드 개수 $K = 5$인 경우:

1. **샤드 레벨 메모리 오버헤드**:
   각 샤드는 상위 $100,100$개의 문서를 우선순위 큐에 유지해야 합니다.
2. **네트워크 전송량**:
   각 샤드가 코디네이터 노드로 $100,100$개의 문서 헤더를 전송하므로, 네트워크를 타고 전송되는 총 헤더 수는 다음과 같습니다:
   $$N_{network} = K \times (from + size) = 5 \times 100,100 = 500,500 \text{ documents}$$
3. **코디네이터 노드 메모리 복잡도**:
   코디네이터 노드는 $500,500$개의 문서를 힙 메모리에 적재해야 합니다:
   $$\text{Memory}_{coordinator} = O(K \cdot (from + size))$$
4. **글로벌 병합 정렬 CPU 복잡도**:
   $$O(K \cdot (from + size) \cdot \log(from + size))$$

$from$이 수만, 수십만 단위로 증가하면 메모리 사용량이 선형($O(N)$)으로 폭증하여 **JVM Old Gen 힙이 고갈되고 Full GC Stop-The-World 또는 OOM Killer**에 의해 노드가 폭사하게 됩니다.

---

## 3. `search_after` 커서 페이징의 $O(1)$ 최적화 원리

`search_after`는 이전 페이지의 마지막 문서 정렬 값(Tie-breaker 포함)을 일종의 **북마크(Bookmark / Cursor)** 로 활용합니다.

```
[ Lucene Index B-Tree Scan ]
Index: [... 1680000000:doc9998, 1680000000:doc9999, 1679999990:doc10000 ...]
                                       ▲
                   search_after cursor │ (Fast B-Tree Seek!)
                                       └─► Read only next 100 docs!
```

### 수학적 효율성 비교
| 항목 | `from + size` | `search_after` |
| :--- | :--- | :--- |
| **샤드당 스캔 문서 수** | $O(from + size)$ (깊어질수록 선형 증가) | **$O(size)$ (항상 고정 상수)** |
| **코디네이터 노드 메모리** | $O(K \cdot (from + size))$ (**메모리 폭발**) | **$O(K \cdot size)$ (완전한 $O(1)$ 상수 메모리)** |
| **10만 번째 페이지 비용** | 500,500개 문서 적재 $\to$ **OOM 크래시** | 500개 문서 적재 $\to$ **초경량 0ms 응답** |
| **인덱싱 동시 발생 시** | **Pagination Drift** (문서 누락/중복 발생) | **Point-in-Time (PIT)** 결합 시 스냅샷 완벽 보장 |

---

## 4. 실무 아키텍처 체크리스트

1. **`index.max_result_window` 절대 임의 증설 금지**:
   - 10,000 기본 가드레일을 100,000 이상으로 푸는 행위는 장애로 직결됩니다.
   - 대용량 데이터 내보내기나 크롤러 API는 무조건 `search_after`로 전환하십시오.
2. **타이 브레이커(Tie-breaker) 필수 지정**:
   - `search_after` 쿼리 작성 시 `sort` 필드의 마지막에는 반드시 유니크한 필드(`_id` 또는 `doc_id`)를 `asc`로 포함해야 페이징 일관성이 유지됩니다.
3. **Point In Time (PIT) API 결합**:
   - Elasticsearch 7.10+ 및 OpenSearch에서는 PIT(Point in Time) API를 생성한 후 `search_after`를 수행하면, 페이징 도중 새로운 문서가 인덱싱되거나 삭제되어도 최초 쿼리 시점의 스냅샷 뷰가 $100\%$ 보장되어 데이터 정합성이 완벽해집니다.
