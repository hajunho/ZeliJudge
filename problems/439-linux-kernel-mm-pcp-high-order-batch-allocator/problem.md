# Problem #439: 리눅스 커널 메모리 관리: mm/page_alloc.c 고차(High-Order) Per-CPU 페이지 세트(PCP) 락리스 캐시 및 배치 리필·드레인 엔진

## 🌟 개요 (Executive Summary)
현대 수십~수백 코어(64~256 vCPU)를 갖춘 고성능 멀티코어 서버 환경에서, 리눅스 커널의 기본 물리 메모리 할당자(Buddy Allocator)는 각 NUMA 메모리 존(`struct zone`, 예: `ZONE_NORMAL`, `ZONE_DMA32`)마다 단 하나의 전역 스핀락(`zone->lock`)으로 보호됩니다.
만약 수백 개의 CPU 코어가 메모리를 할당(`alloc_pages()`)하고 해제(`free_pages()`)할 때마다 매번 `zone->lock`을 획득해야 한다면, CPU 사이클의 60~70% 이상이 스핀락 대기와 캐시라인 바운싱(Cacheline Bouncing)으로 낭비되어 멀티코어 확장성(Scalability)이 심각하게 붕괴됩니다.

과거 리눅스 커널은 이를 완화하기 위해 코어별 독립 메모리 캐시인 **PCP (Per-CPU Pages / `struct per_cpu_pages`)**를 도입했으나, 이는 오직 **Order-0 (단일 4KB 페이지)**에만 한정되었습니다.
하지만 현대의 초고속 100GbE/200GbE 네트워킹(점보 프레임 skb 버퍼), 페이지 캐시 폴리오(Page Cache Folios), SLUB 슬랩 할당자, 파일 시스템 버퍼 등은 빈번하게 **Order-1 (8KB), Order-2 (16KB), Order-3 (32KB)**의 고차(High-Order) 연속 메모리를 집중적으로 요구합니다. 구형 커널에서는 이러한 모든 고차 할당 요청이 PCP를 우회하여 전역 `zone->lock`에 직접 충돌하는 치명적인 병목이 존재했습니다.

리눅스 커널 5.14+ 및 6.x에서는 커널 메모리 관리 메인테이너 Mel Gorman에 의해 **고차 PCP (High-Order Per-CPU Pages, Order 0..PAGE_ALLOC_COSTLY_ORDER)** 아키텍처가 전격 도입되었습니다:
- **코어별 독립 락리스 LIFO 리스트 (`struct per_cpu_pages`)**: 각 CPU 코어는 Order 0부터 최대 설정 차수(`max_pcp_order`, 기본 Order 3 = 32KB)까지 독립적인 미사용 페이지 리스트를 유지하여 $O(1)$ 시간 내에 0-Lock(무잠금) 패스트패스로 즉시 할당/반환합니다.
- **배치 리필을 통한 락 획득 횟수 상환 (Lock Amortization via Batch Refill)**:
  - 특정 차수의 로컬 PCP 리스트가 고갈된 경우에만 슬로우패스로 진입하여 `zone->lock`을 1회 획득합니다.
  - 전역 버디 할당자로부터 요청된 1개 블록뿐만 아니라 설정된 배치 크기(`batch`, 예: 4개)만큼 일괄 인출하여 1개는 즉시 반환하고 나머지는 로컬 PCP에 비축합니다. 이를 통해 이후 동일 차수 요청의 `zone->lock` 획득 빈도를 $1/\text{batch}$로 급감시킵니다.
- **하이 워터마크(`high`) 기반 자동 일괄 드레인 (Bulk Drain on Capacity Overflow)**:
  - 페이지 해제(`free_unref_page_commit`) 시 로컬 PCP에 반환되어 CPU 캐시 친화도를 극대화합니다.
  - 로컬 CPU에 보관된 총 블록 수가 상한선(`high_watermark`)에 도달하면 `zone->lock`을 1회 획득하여 `batch`개의 블록을 전역 버디 시스템으로 일괄 반환하여 특정 코어의 메모리 독점을 방지합니다.
- **CPU 간 교차 해제 (Cross-CPU Freeing) 및 동적 완전 드레인 (`drain_all_pages`)**:
  - CPU 0에서 할당된 메모리를 CPU 1에서 해제할 때 원격 코어로의 캐시라인 전송 없이 해제 작업을 수행하는 로컬 코어(CPU 1)의 PCP에 즉각 수용됩니다.

본 문제에서는 리눅스 커널 `mm/page_alloc.c`의 고차 PCP 락리스 패스트패스, 배치 리필, 하이 워터마크 일괄 드레인 및 멀티코어 락 획득 회계 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
   [ CPU Core k: alloc_pages(order) ]
                   │
         order <= max_pcp_order?
        ┌──────────┴──────────┐
       Yes                    No
        │                     │
        ▼                     ▼
 [ Check Local PCP[order] ]   [ Fallback to Main Buddy Allocator ]
        │                     [ Acquires zone->lock directly ]
  Is list non-empty?
 ┌──────┴──────┐
Yes            No (PCP Miss)
 │             │
 │             ▼
 │     [ Acquire zone->lock ] ◄── Global Zone Spinlock
 │     Fetch 'batch' blocks from Zone Buddy Free Lists
 │     cpu.count += (batch - 1)
 │     cpu.bulk_refills++
 │     zone_lock_count++
 │     Deposit (batch-1) to PCP[order]
 │     Return 1 block to Caller
 │     status = ALLOC_PCP_REFILL
 │             │
 └─────────────┼──────────────┐
               ▼              ▼
       [ Pop from LIFO ]  [ Complete ]
       cpu.count--
       cpu.local_hits++
       lock_acquired = False
       status = ALLOC_PCP_HIT (0-Lock!)

 ─────────────────────────────────────────────────────────────────────────────
   [ CPU Core k: free_pages(order) ]
                   │
   Push to local PCP[order] (LIFO)
   cpu.count++
   Is cpu.count >= high_watermark?
        ┌──────────┴──────────┐
       Yes                    No
        │                     │
        ▼                     ▼
 [ Acquire zone->lock ]      status = FREE_PCP_CACHED (0-Lock!)
 Drain 'batch' blocks to Zone
 cpu.count -= drained
 cpu.bulk_drains++
 status = FREE_PCP_DRAINED
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "num_cpus": 4,
    "max_pcp_order": 3,
    "batch": 4,
    "high_watermark": 12,
    "zone_pfn_start": 65536
  },
  "trace": [
    {"op": "PCP_ALLOC", "cpu_id": 0, "order": 2, "handle_id": "H1"},
    {"op": "PCP_ALLOC", "cpu_id": 0, "order": 2, "handle_id": "H2"},
    {"op": "PCP_FREE", "cpu_id": 0, "handle_id": "H1"},
    {"op": "DRAIN_CPU", "cpu_id": 0},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `num_cpus` (int, default=4): 시스템의 논리 CPU 코어 수.
  - `max_pcp_order` (int, default=3): PCP에 캐싱되는 최대 버디 차수 (0=4KB, 1=8KB, 2=16KB, 3=32KB).
  - `batch` (int, default=4): 1회 존 락 획득 시 리필/드레인하는 블록 단위.
  - `high_watermark` (int, default=12): 코어별 최대 보관 가능 블록 수. 초과 시 드레인 발생.
  - `zone_pfn_start` (int, default=0x10000): 버디 존 초기 PFN.
- `trace` 명령어:
  1. `PCP_ALLOC`:
     - `cpu_id` (int): 할당을 요청한 CPU 코어 ID.
     - `order` (int): 요청 차수 ($0 \le \text{order} \le \text{max\_pcp\_order}$).
     - `handle_id` (str): 할당 핸들 식별자.
  2. `PCP_FREE`:
     - `cpu_id` (int): 해제를 수행하는 CPU 코어 ID.
     - `handle_id` (str): 해제 대상 핸들 식별자.
  3. `DRAIN_CPU`:
     - `cpu_id` (int): 지정된 코어의 모든 PCP 블록을 전역 버디 존으로 강제 일괄 반환.
  4. `GET_STATS`:
     - 전역 존 락 획득 횟수 및 코어별 상세 통계 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "PCP_ALLOC",
      "cpu_id": 0,
      "handle_id": "H1",
      "order": 2,
      "pfn": 65560,
      "status": "ALLOC_PCP_REFILL",
      "lock_acquired": true,
      "cpu_pcp_count": 3
    },
    ...
  ],
  "summary": {
    "zone_lock_count": 1,
    "total_local_hits": 1,
    "total_bulk_refills": 1,
    "total_bulk_drains": 0,
    "active_allocations": 1,
    "total_pcp_blocks_cached": 3
  }
}
```
