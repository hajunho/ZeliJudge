# 리눅스 커널 페이지 캐시 폴리오 및 대형 복합 할당 엔진 (Linux Kernel Page Cache Folios & High-Order Compound Allocation Engine)

## 문제 설명

리눅스 커널 메모리 관리(MM) 서브시스템에서 수십 년간 사용되어 온 `struct page`는 현대의 테라바이트급 메모리와 수십 기가바이트 초고속 NVMe 스토리지 환경에서 심각한 구조적 한계에 부딪혔습니다. 전통적인 리눅스 커널에서는 4KB 단일 페이지, 2MB 대형 페이지(THP)의 헤드 페이지, 그리고 복합 페이지의 테일(Tail) 페이지를 모두 동일한 `struct page *` 타입으로 표현했습니다. 이로 인해 커널 전역에서 이 페이지가 헤드인지 테일인지 확인하기 위해 수없이 `compound_head(page)`를 호출해야 했고, 이는 캐시 라인 미스와 메모리 접근 오버헤드를 유발했습니다.

이를 근본적으로 혁신하기 위해 리눅스 5.16부터 **매튜 윌콕스(Matthew Wilcox)** 주도로 **폴리오(Folio, `struct folio`, `mm/filemap.c`)** 아키텍처가 도입되었습니다:
1. **절대 테일 페이지가 아님을 타입 레벨에서 보장**: `struct folio` 포인터는 항상 Order-0 단일 페이지이거나 Multi-page 복합 할당의 헤드만을 가리킵니다.
2. **페이지 캐시 대형 폴리오(Large Folios)**: 파일을 4KB 단위가 아닌 Order-2(16KB), Order-4(64KB), Order-9(2MB) 등 연속된 블록 단위로 페이지 캐시에 적재합니다.
3. **XArray 트리 탐색 및 락 경합 대폭 절감**: 파일 오프셋을 관리하는 XArray(Radix Tree)에서 16개의 노드를 개별 탐색·잠금하는 대신, 1개의 64KB 대형 폴리오로 일괄 탐색 및 락을 획득하여 TLB 플러시, 락 사이클, 메타데이터 메모리를 극적으로 절감합니다.

당신은 리눅스 커널 메모리 관리 엔지니어로서, **페이지 캐시 주소 공간(`address_space`), XArray 다중 인덱스 매핑, 순차/무작위 지능형 리드어헤드(Readahead), 폴리오 분할(`folio_split`), 더티 플러시(`writeback`) 및 파일 자르기(`truncate`)를 정밀하게 에뮬레이션하는 페이지 캐시 폴리오 엔진**을 구현해야 합니다.

```
+-------------------------------------------------------------------------+
|              Linux Kernel Page Cache Folio Architecture                 |
+-------------------------------------------------------------------------+
| [File I/O Request]                                                      |
|   vfs_read() / vfs_write() (file offset, length)                        |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Address Space: struct address_space & XArray]                          |
|                                                                         |
|   XArray Page Index Slots (4KB Units):                                  |
|   Slot 0   Slot 1   Slot 2   Slot 3   Slot 4   Slot 5  ...  Slot 15     |
|   +---------------------------------+ +-------------------------------+ |
|   | Folio #1 (Order 2: 16KB, 4 pgs) | | Folio #2 (Order 2: 16KB)      | |
|   | [Head Page] [Tail] [Tail] [Tail]| | [Head Page] [Tail] [Tail] ... | |
|   +---------------------------------+ +-------------------------------+ |
|   * Any lookup in range [0..3] returns EXACT SAME Folio #1 pointer!     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| [Folio Lifecycle Operations: mm/filemap.c]                              |
|   - READ: Cache Hit or Readahead Allocation (Order-k Compound Folio)    |
|   - WRITE: In-place Buffer Mutation & DIRTY Flag Accounting             |
|   - SPLIT: Memory Pressure / Partial Truncate (Order-k ---> Order-0)    |
|   - WRITEBACK: Background Flusher Thread Dirty Clearing                 |
|   - TRUNCATE: Boundary-Aware Partial Splitting & Tail Invalidation      |
+-------------------------------------------------------------------------+
```

---

## 엔진 규격 및 알고리즘

### 1. 세션 초기화 (`config`)
- `max_cache_pages`: 최대 캐시 용량 (4KB 페이지 단위)
- `default_readahead_order`: 순차 읽기 시 기본 리드어헤드 차수 (기본값: $2 \implies 16	ext{KB}$, 4페이지)
- `max_folio_order`: 최대 폴리오 차수 (기본값: $4 \implies 64	ext{KB}$, 16페이지)

### 2. 폴리오 생성 및 XArray 매핑
- 차수 $k$인 폴리오는 $2^k$개의 연속된 4KB 페이지를 포함하며, 시작 페이지 인덱스는 반드시 $2^k$의 배수로 정렬됩니다.
- XArray의 시작 인덱스부터 $2^k$개의 모든 슬롯에 동일한 폴리오 객체 참조를 등록합니다.

### 3. 연산(Operations) 정의
1. **`READ` (`offset`, `length`, `sequential_hint`)**:
   - `start_page = offset // 4096`, `end_page = (offset + length - 1) // 4096`
   - 페이지 범위 순회 중 XArray 룩업 수행:
     - **Cache Hit**: 폴리오가 이미 존재하면 `cache_hits` 증가.
     - **Cache Miss**: 미존재 시 `cache_misses` 증가, `sequential_hint`가 참이면 `default_readahead_order`, 거짓이면 Order-0으로 폴리오 할당 및 `UPTODATE` 설정.
   - 접근한 고유 폴리오마다 1회의 락 사이클(`lock_cycles`) 계측.
2. **`WRITE` (`offset`, `data_hex`)**:
   - 바이트 데이터를 대상 폴리오 슬라이스에 복사하고, 폴리오를 `DIRTY` 상태로 표시(`dirty_folios` 갱신).
3. **`SPLIT` (`page_index`)**:
   - 대상 페이지가 속한 차수 $k > 0$ 폴리오를 $2^k$개의 Order-0 개별 단일 페이지 폴리오로 분할.
   - 분할된 각 서브 폴리오는 원본의 데이터 및 더티 상태를 상속하며, XArray의 각 슬롯을 갱신.
4. **`FLUSH`**:
   - 모든 더티 폴리오의 `DIRTY` 플래그를 해제하고 디스크로 플러시 에뮬레이션(`dirty_folios = 0`).
5. **`TRUNCATE` (`new_size`)**:
   - 파일의 새 끝 페이지 인덱스 `new_end_page = (new_size + 4095) // 4096`
   - 경계에 걸친 폴리오(`start_index < new_end_page < start_index + num_pages`)는 먼저 Order-0으로 `SPLIT` 수행.
   - `new_end_page` 이상의 모든 폴리오를 XArray 및 캐시에서 안전하게 축출(`truncated_folios` 계측).

### 4. 메타데이터 및 효율성 통계
- **캐시 적중률 (`hit_ratio`)**: $rac{cache\_hits}{cache\_hits + cache\_misses}$
- **메타데이터 절감률 (`metadata_savings_pct`)**:
  - 전통적인 4KB 페이지 추적 대비 대형 폴리오 집약으로 절감된 메타데이터 비율:
    $$MetadataSavings = \left(1.0 - rac{	ext{Active Folios Count}}{	ext{Cached Pages Count}}ight) 	imes 100.0$$

---

## 입력 형식

표준 입력(`sys.stdin`)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "max_cache_pages": 1024,
    "default_readahead_order": 2,
    "max_folio_order": 4
  },
  "operations": [
    {"op": "READ", "offset": 0, "length": 65536, "sequential_hint": true},
    {"op": "WRITE", "offset": 4096, "data_hex": "deadbeef"},
    {"op": "SPLIT", "page_index": 0},
    {"op": "FLUSH"},
    {"op": "TRUNCATE", "new_size": 16384}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 공백 없는 압축 JSON(`separators=(',', ':')`)을 출력합니다:
```json
{
  "execution_log": [
    {"op": "READ", "result": {"end_page": 15, "folios_touched": 4, "start_page": 0, "status": "OK"}},
    {"op": "WRITE", "result": {"bytes_written": 4, "folios_touched": 1, "status": "OK"}},
    {"op": "SPLIT", "result": {"original_folio_id": 1, "original_order": 2, "status": "SPLIT_OK", "sub_folios_created": 4}},
    {"op": "FLUSH", "result": {"flushed_count": 1, "status": "FLUSHED"}},
    {"op": "TRUNCATE", "result": {"new_size": 16384, "status": "TRUNCATED", "truncated_folios": 3}}
  ],
  "final_summary": {
    "active_folios_count": 4,
    "cached_pages_count": 4,
    "folios_detail": [
      {"id": 5, "is_dirty": false, "num_pages": 1, "order": 0, "start_index": 0},
      {"id": 6, "is_dirty": false, "num_pages": 1, "order": 0, "start_index": 1},
      {"id": 7, "is_dirty": false, "num_pages": 1, "order": 0, "start_index": 2},
      {"id": 8, "is_dirty": false, "num_pages": 1, "order": 0, "start_index": 3}
    ],
    "hit_ratio": 0.5,
    "metadata_savings_pct": 0.0,
    "stats": {
      "bytes_read": 65536,
      "bytes_written": 4,
      "cache_hits": 1,
      "cache_misses": 4,
      "dirty_folios": 0,
      "folios_allocated": 4,
      "folios_split": 1,
      "folios_truncated": 3,
      "lock_cycles": 5,
      "read_requests": 1,
      "write_requests": 1,
      "xarray_lookup_traversals": 5
    }
  }
}
```
