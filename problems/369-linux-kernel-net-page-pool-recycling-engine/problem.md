# Linux Kernel Network Page Pool: 고속 락리스 Per-CPU 캐시, Ring 버퍼 재활용 및 DMA 수명주기 관리 엔진

## 문제 설명

리눅스 커널의 **페이지 풀(Page Pool / `net/core/page_pool.c`, `include/net/page_pool/types.h`)**은 100GbE/400GbE 초고속 네트워크 인터페이스 카드(NIC) 드라이버와 eXpress Data Path(XDP) 환경에서 패킷 수신(Rx) 시 발생하는 커널 페이지 할당자(Buddy Allocator)의 락 경합 및 IOMMU DMA 매핑 오버헤드를 제거하기 위해 개발된 고성능 무복사(Zero-Copy) 메모리 재활용 서브시스템입니다.

```
                  [ 드라이버 수신 NAPI 루프 (Rx Polling Loop) ]
                                        |
                             (page_pool_alloc_pages)
                                        |
     +----------------------------------+----------------------------------+
     | (1단계: 고속 경로 Fast-Path)       | (2단계: 느린 경로 Slow-Path 1)     | (3단계: 최후의 폴백)
     v                                  v                                  v
[ Per-CPU 할당 캐시 ]              [ 포인터 링 버퍼 ]                 [ 버디 할당자 ]
(alloc_cache: LIFO 스택)           (ptr_ring: FIFO 큐)                (Buddy Allocator)
- 락/원자적 연산 0회               - 다른 코어 반환 페이지            - DMA 매핑 최초 1회 발행
- 단 10~15 CPU 사이클              - refill_batch_size 단위 리필      - IOMMU 페널티 회피
     |                                  ^                                  |
     |                                  |                                  |
     +<---(로컬 NAPI 반환)---------------+<---(원격 CPU / skb 반환)--------+
```

### 핵심 아키텍처 및 재활용 메커니즘

1. **3단계 계층형 페이지 할당 파이프라인**:
   - **1단계: Per-CPU 할당 캐시 (`FAST_CACHE`)**:
     - NAPI 소프트웨어 인터럽트(Softirq) 컨텍스트 내에서 동작하며, 동기화 락이나 원자적(Atomic) 연산 없이 LIFO 배열 스택(`alloc_cache`)에서 직접 페이지를 팝(Pop)합니다.
   - **2단계: 링 버퍼 배치 리필 (`PTR_RING_REFILL`)**:
     - `alloc_cache`가 고갈되면, 다른 코어나 비동기 네트워크 스택에서 반환된 페이지들이 대기 중인 `ptr_ring`에서 최대 `refill_batch_size`개의 페이지를 한꺼번에 꺼내어 `alloc_cache`를 충전한 뒤 반환합니다.
   - **3단계: 버디 할당자 폴백 (`BUDDY_ALLOCATOR_FALLBACK`)**:
     - 캐시와 링 버퍼가 모두 비어 있으면, 버디 할당자로부터 새로운 물리 페이지를 할당받고 장치에 대한 DMA 매핑(`dma_map_page()`)을 최초 1회 수행합니다.

2. **2원화 페이지 반환 및 재활용 경로**:
   - **로컬 직접 반환 (`RECYCLE_DIRECT`)**:
     - 드라이버가 패킷 처리 후 동일 CPU NAPI 컨텍스트에서 즉시 페이지를 반환하는 경로입니다.
     - `alloc_cache`에 여유 공간이 있으면 즉시 LIFO 캐시에 푸시합니다(`RECYCLED_TO_FAST_CACHE`).
     - 캐시가 가득 찬 경우 `ptr_ring`으로 밀어 넣습니다(`RECYCLED_TO_PTR_RING`).
     - 둘 다 가득 차면 풀 오버플로우로 간주하여 DMA를 언맵하고 버디 할당자로 완전 방출합니다(`RELEASED_TO_BUDDY_OVERFLOW`).
   - **원격 CPU 비동기 반환 (`RECYCLE_REMOTE`)**:
     - 상위 프로토콜 스택(TCP/IP)이나 다른 코어에서 `consume_skb()` 등을 통해 페이지를 풀로 돌려보내는 경로입니다.
     - 로컬 캐시를 건드리지 않고 즉시 `ptr_ring`으로 안전하게 삽입됩니다(`RECYCLED_TO_PTR_RING_REMOTE`).
     - 링이 가득 찬 경우 즉시 언맵 및 버디 방출 처리됩니다.

3. **풀 수명주기 드레인 (`DRAIN_POOL`)**:
   - 네트워크 인터페이스가 다운(`ip link set down`)되거나 드라이버가 언로드될 때, `alloc_cache`와 `ptr_ring`에 보관된 모든 유휴 페이지들을 일괄 순회하여 DMA 매핑을 해제하고 시스템 메모리로 반환합니다.

본 문제에서는 이 3단계 계층 할당, 고속 캐시 및 링 버퍼 재활용, DMA 회계 통계를 충실히 시뮬레이션하는 페이지 풀 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "pool_size": 4,
  "alloc_cache_size": 2,
  "refill_batch_size": 2,
  "dma_sync_enabled": true,
  "operations": [
    {"op": "ALLOC_PAGE"},
    {"op": "ALLOC_PAGE"},
    {"op": "RECYCLE_DIRECT", "page_id": 1},
    {"op": "ALLOC_PAGE"},
    {"op": "RECYCLE_REMOTE", "page_id": 2},
    {"op": "ALLOC_PAGE"},
    {"op": "DRAIN_POOL"}
  ]
}
```

### 파라미터 규격
- `pool_size` (정수, 기본 32): 원격 반환용 포인터 링 버퍼(`ptr_ring`)의 최대 수용 페이지 수.
- `alloc_cache_size` (정수, 기본 8): 로컬 Per-CPU 할당 캐시의 최대 수용 페이지 수.
- `refill_batch_size` (정수, 기본 4): 캐시 고갈 시 `ptr_ring`에서 한 번에 가져올 최대 페이지 수.
- `dma_sync_enabled` (불리언, 기본 true): DMA 캐시 동기화 카운트 활성화 여부.
- `operations` (배열): 순차 실행할 네트워크 드라이버 메모리 제어 연산 목록.
  - `ALLOC_PAGE`: 신규 패킷 수신 버퍼용 페이지 할당 요청.
  - `RECYCLE_DIRECT`: 로컬 NAPI 컨텍스트에서의 고속 페이지 반환 (`page_id`).
  - `RECYCLE_REMOTE`: 원격 코어 또는 TCP 스택에서의 비동기 페이지 반환 (`page_id`).
  - `DRAIN_POOL`: 풀 내부 유휴 페이지 일괄 회수 및 DMA 언맵.

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 객체를 공백 없이 출력합니다:

```json
{
  "pool_size": 4,
  "alloc_cache_size": 2,
  "refill_batch_size": 2,
  "dma_sync_enabled": true,
  "final_state": {
    "alloc_cache": [],
    "ptr_ring": [],
    "in_flight_pages_count": 2,
    "dma_mapped_pages_count": 2
  },
  "stats": {
    "alloc_requests": 4,
    "alloc_fast_cache_hit": 1,
    "alloc_ptr_ring_refill": 1,
    "alloc_buddy_allocator_fallback": 2,
    "recycle_fast_cache": 1,
    "recycle_ptr_ring": 1,
    "recycle_ring_overflow_drops": 0,
    "dma_map_count": 2,
    "dma_unmap_count": 0,
    "dma_sync_count": 4
  },
  "op_log": [
    {
      "op": "ALLOC_PAGE",
      "page_id": 1,
      "source": "BUDDY_ALLOCATOR_FALLBACK",
      "alloc_cache_count": 0,
      "ptr_ring_count": 0
    }
  ]
}
```
