# 문제 408: Linux 커널 CMA(Contiguous Memory Allocator) 페이지블록 격리 및 DMA 마이그레이션 엔진

## 문제 설명

현대 고성능 임베디드 및 모바일 SoC(시스템 온 칩, System on Chip), 차량용 자율주행 프로세서, 멀티미디어 가속 플랫폼은 4K/8K 고해상도 카메라 ISP(Image Signal Processor), H.264/HEVC/AV1 하드웨어 비디오 코덱(VPU), GPU 디스플레이 스캔아웃 컨트롤러(Display Controller), 오디오 DSP 등 대용량의 물리적으로 연속된 메모리 버퍼(Physically Contiguous Memory Buffer)를 요구하는 다양한 DMA(Direct Memory Access) 마스터 하드웨어 장치를 탑재하고 있습니다.

만약 이들 장치에 Scatter-Gather를 지원하는 고성능 하드웨어 IOMMU(SMMU)가 없거나, IOMMU가 있더라도 지연 시간(Latency) 최소화 및 전력 소모 절감을 위해 물리적 연속 버퍼를 직접 전달해야 하는 경우, 운영체제는 반드시 물리적으로 인접한 수십~수백 MB 단위의 연속 프레임을 보장해야 합니다.

과거 리눅스 커널에서는 부팅 시점(`mem=...`)에 전용 메모리를 완전히 예약(Carveout Reservation)하여 해당 하드웨어 전용으로 격리해 두는 방식을 주로 사용했습니다. 그러나 이 방식은 장치가 동작하지 않는 평상시에도 수백 MB의 시스템 RAM을 일반 애플리케이션(페이지 캐시, 사용자 힙 등)이 전혀 활용하지 못하고 낭비하게 만드는 심각한 메모리 비효율을 초래했습니다.

이 문제를 근본적으로 해결하기 위해 리눅스 커널 3.5에 공식 도입된 서브시스템이 바로 **CMA (Contiguous Memory Allocator, `mm/cma.c`, `mm/page_isolation.c`, `mm/migrate.c`, `CONFIG_CMA`)**입니다.

### CMA 핵심 동작 메커니즘

1. **평상시 메모리 공용 활용 (`MIGRATE_CMA`)**:
   - 부팅 시 시스템 메모리의 특정 영역을 CMA 영역으로 예약하지만, 평상시에는 커널 버디 시스템(Buddy System)에 편입되어 페이지블록(Pageblock) 마이그레이션 타입을 `MIGRATE_CMA`로 유지합니다.
   - 이 영역은 시스템의 일반적인 이동 가능한 페이지(`GFP_HIGHUSER_MOVABLE`, 파일 시스템 페이지 캐시, 익명 페이지 등)가 자유롭게 점유하여 사용할 수 있습니다.
   - 단, 커널 내부 자료구조, 커널 슬랩(SLAB/SLUB), 페이지 테이블 등 이동이 불가능한 메모리(`UNMOVABLE`)는 CMA 영역에 절대 할당되지 못하도록 차단(`MIGRATE_UNMOVABLE` 격리 규칙)됩니다.

2. **DMA 연속 메모리 요청 시 페이지블록 격리 (`MIGRATE_ISOLATE`)**:
   - 디바이스 드라이버가 `cma_alloc(cma, count, align_order)`를 호출하면, CMA 할당기는 요청된 크기(`count`)와 정렬 조건(`2^align_order`)을 만족하는 물리적 주소 범위(PFN Range)를 탐색합니다.
   - 연속된 영역이 결정되면 해당 영역을 포함하는 페이지블록들을 즉시 `MIGRATE_ISOLATE` 상태로 전이(`start_isolate_page_range()`)시킵니다.
   - 격리된 페이지블록에는 버디 할당기의 신규 페이지 할당이 즉각 중단됩니다.

3. **이동 가능 페이지의 원자적 대피(Migration) 및 롤백(Rollback)**:
   - 격리된 범위 내에 이미 파일 캐시나 유저 페이지가 적재되어 있는 경우, 커널은 페이지 마이그레이션 서브시스템(`migrate_pages()`)을 구동하여 해당 페이지들을 일반 버디 시스템의 이동 가능 풀(`buddy_movable_pool`)로 투명하게 대피(Evacuation)시킵니다.
   - **고정 페이지(Pinned Page) 충돌 방어**: 만약 대피 대상 페이지 중 `get_user_pages()`나 direct I/O 등에 의해 고정(`is_pinned == True`)된 페이지가 단 하나라도 존재한다면, 메모리 마이그레이션이 원천적으로 불가능하므로 즉시 `CMA_ERR_PINNED_PAGE_COLLISION` 오류와 함께 전체 격리 상태를 원자적으로 롤백(`undo_isolate_page_range()`)하고 할당에 실패합니다.
   - **버디 메모리 고갈 방어**: 버디 시스템에 이동 대상 페이지를 수용할 여유 메모리가 부족한 경우, `CMA_ERR_MIGRATION_NO_MEM` 오류와 함께 전체 격리 상태를 롤백합니다.
   - 모든 점유 페이지가 성공적으로 대피 완료되면 해당 물리 프레임들을 DMA 요청 장치에게 독점 연속 버퍼로 할당합니다.

4. **DMA 메모리 반환 및 복원 (`cma_release()`)**:
   - 디바이스 드라이버가 작업을 마치고 `cma_release()`를 호출하면 연속 버퍼가 해제됩니다.
   - 해당 페이지블록 내에 더 이상 활성화된 다른 DMA 할당이 존재하지 않는다면, 페이지블록의 상태를 다시 `MIGRATE_CMA`로 환원시켜 일반 시스템 이동 가능 페이지들이 다시 활용할 수 있도록 복원합니다.

여러분은 리눅스 커널의 CMA 메모리 할당기, 페이지블록 격리 상태 머신, 버디 시스템 상호 작용 및 페이지 마이그레이션/롤백 제어 엔진을 충실히 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                        Linux Kernel CMA & Page Migration Engine                                  |
+==================================================================================================+

   [ Multimedia / Camera / GPU Drivers ]          [ User Applications & Page Cache ]
                    |                                                    |
                    | cma_alloc(size, align)                             | alloc_pages(GFP_HIGHUSER_MOVABLE)
                    v                                                    v
+--------------------------------------------------------------------------------------------------+
| Linux Kernel Memory Management (mm/cma.c, mm/page_isolation.c, mm/migrate.c)                     |
|                                                                                                  |
|  [ Buddy System Pools ]                                                                          |
|   - buddy_unmovable_pool : Kernel Slabs, Page Tables (Strictly rejects CMA access)               |
|   - buddy_movable_pool   : User Heap, Anonymous Memory, Evacuation Target for CMA                |
|                                                                                                  |
|  [ CMA Reserved Physical Memory Region (Base PFN ~ Base PFN + Size) ]                           |
|   +-------------------+-------------------+-------------------+-------------------+              |
|   | PageBlock 0       | PageBlock 1       | PageBlock 2       | PageBlock 3       |              |
|   | (PFN 2048..2111)  | (PFN 2112..2175)  | (PFN 2176..2239)  | (PFN 2240..2303)  |              |
|   +-------------------+-------------------+-------------------+-------------------+              |
|   | MIGRATE_CMA       | MIGRATE_ISOLATE   | MIGRATE_ISOLATE   | MIGRATE_CMA       |              |
|   | [Movable Cache]   | [DMA Buffer: VPU] | [DMA Buffer: VPU] | [Movable Cache]   |              |
|   +-------------------+-------------------+-------------------+-------------------+              |
|            ^                                        |                                            |
|            |                                        | Evacuate / migrate_pages()                 |
|            +--- Normal Movable Pages allowed        v                                            |
|                 when buddy has high pressure      [ Buddy Movable Memory Pool ]                  |
|                                                                                                  |
|  [ CMA Allocation State Machine ]                                                                |
|    1. Scan Bitmap for aligned contiguous free PFNs (2^align_order)                               |
|    2. Isolate PageBlocks: MIGRATE_CMA ---> MIGRATE_ISOLATE                                       |
|    3. Scan occupied pages:                                                                       |
|       - ANY page is PINNED?         ---> ABORT & ROLLBACK (CMA_ERR_PINNED_PAGE_COLLISION)        |
|       - Buddy movable memory FULL?  ---> ABORT & ROLLBACK (CMA_ERR_MIGRATION_NO_MEM)             |
|       - Otherwise                   ---> MIGRATE pages to Buddy Movable Pool                     |
|    4. Success: Mark pages as DMA-owned                                                           |
|    5. Release: Free pages, revert PageBlocks to MIGRATE_CMA if no active DMA exists              |
+==================================================================================================+
```

---

## 상세 요구사항 및 동작 규칙

### 1. 시스템 설정 파라미터 (`config`)
- `cma_base_pfn`: CMA 영역의 시작 물리 프레임 번호 (기본값: `2048`)
- `cma_size_pages`: CMA 관리 총 페이지 수 (기본값: `256`)
- `pageblock_size`: 하나의 페이지블록 크기 (페이지 수, 기본값: `64`)
- `buddy_movable_capacity`: 버디 시스템의 이동 가능 메모리 풀 총 용량 (페이지 단위, 기본값: `512`)
- `buddy_unmovable_capacity`: 버디 시스템의 이동 불가 메모리 풀 총 용량 (페이지 단위, 기본값: `256`)

### 2. 이벤트 트레이스 연산 (`trace`)

1. **`ALLOC_BUDDY_MOVABLE`**:
   - 일반 유저 이동 가능 메모리 또는 페이지 캐시 할당.
   - 먼저 버디 시스템의 `buddy_movable_free`를 확인합니다.
   - 여유가 있다면 버디 풀에서 차감(`buddy_movable_free -= count`)합니다.
   - 버디 풀이 부족한 경우, CMA 영역의 유휴 페이지 중 `MIGRATE_CMA` 상태인 페이지블록의 빈 페이지를 탐색하여 임시 점유(`pool="CMA"`, `owner=owner`, `data_id=data_id`)할 수 있습니다.
   - 양쪽 모두 부족한 경우 할당 가능한 수량만큼만 부분 할당되거나 거절됩니다.

2. **`ALLOC_BUDDY_UNMOVABLE`**:
   - 커널 내부 자료구조, 슬랩 메모리 할당.
   - 반드시 버디 시스템의 `buddy_unmovable_free`에서만 할당되어야 합니다.
   - 만약 버디 이동 불가 풀이 부족하더라도 **CMA 영역으로는 절대로 유출/할당될 수 없습니다** (`ERR_REJECTED_UNMOVABLE_ALLOC` 정책).

3. **`FREE_BUDDY_MOVABLE` / `FREE_BUDDY_UNMOVABLE`**:
   - 버디 또는 CMA 영역에 적재된 메모리 해제.

4. **`PIN_PAGE` / `UNPIN_PAGE`**:
   - 지정된 PFN의 페이지를 I/O 또는 하드웨어 드라이버 사용을 위해 락(Pin)하거나 해제합니다 (`is_pinned = True / False`).

5. **`CMA_ALLOC`**:
   - DMA 디바이스(`dev_name`, `alloc_id`)의 연속 메모리 할당 요청.
   - `count`개의 물리적으로 연속된 페이지를 요구하며, 시작 PFN은 `2^align_order`의 배수여야 합니다.
   - **1단계: 영역 탐색**:
     - CMA 전체 영역 중 정렬을 만족하고, `count` 크기만큼 연속된 유효 범위(`[pfn, pfn + count)`)를 First-Fit으로 탐색합니다.
     - 단, 이미 다른 DMA 장치가 점유 중인 페이지가 포함된 범위는 후보가 될 수 없습니다.
     - 만족하는 범위가 없으면 `CMA_ERR_NO_CONTIGUOUS_SPACE` 실패를 기록합니다.
   - **2단계: 페이지블록 격리 전이**:
     - 선택된 범위에 걸치는 모든 페이지블록의 상태를 `MIGRATE_ISOLATE`로 전이시킵니다.
   - **3단계: 이동 가능 페이지 검사 및 대피(Migration)**:
     - 선택된 범위 내에 기존 이동 가능 페이지(파일 캐시 등)가 존재하는지 확인합니다.
     - 만약 해당 페이지 중 `is_pinned == True`인 페이지가 하나라도 있다면:
       - 즉시 마이그레이션을 중단하고, 격리했던 페이지블록들을 이전 상태로 롤백 복원합니다.
       - 실패 원인 `CMA_ERR_PINNED_PAGE_COLLISION`을 기록합니다.
     - 대피해야 할 총 페이지 수(`migrating_count`)가 버디 시스템의 `buddy_movable_free`보다 크다면:
       - 대피 공간 부족으로 즉시 중단하고 페이지블록 격리를 롤백 복원합니다.
       - 실패 원인 `CMA_ERR_MIGRATION_NO_MEM`을 기록합니다.
     - 검사를 모두 통과하면:
       - 점유된 페이지들을 버디 시스템의 이동 가능 풀로 대피(`buddy_movable_free -= migrating_count`, `total_migrated_pages += migrating_count`)시키고 CMA 페이지를 클리어합니다.
   - **4단계: DMA 연속 버퍼 점유**:
     - `[start_pfn, start_pfn + count)`의 모든 페이지에 `owner="DMA"`, `dma_alloc_id=alloc_id`, `is_free=False`를 마킹합니다.
     - `cma_alloc_success`를 1 증가시키고 할당 정보를 기록합니다.

6. **`CMA_RELEASE`**:
   - `alloc_id`에 해당하는 DMA 연속 할당을 해제합니다.
   - 해당 범위의 모든 페이지를 유휴(`is_free=True`, `owner=None`, `dma_alloc_id=None`) 상태로 환원합니다.
   - 해제된 영역이 속한 페이지블록들에 대해, 더 이상 활성 DMA 할당이 남아있지 않다면 페이지블록 상태를 다시 `MIGRATE_CMA`로 복원합니다.

---

## 입출력 형식 (JSON)

### 입력 형식 (Standard Input)

```json
{
  "config": {
    "cma_base_pfn": 2048,
    "cma_size_pages": 256,
    "pageblock_size": 64,
    "buddy_movable_capacity": 512,
    "buddy_unmovable_capacity": 256
  },
  "trace": [
    {
      "time": 0,
      "type": "ALLOC_BUDDY_MOVABLE",
      "owner": "page_cache",
      "count": 500,
      "data_id": "cache_chunk_1"
    },
    {
      "time": 2,
      "type": "CMA_ALLOC",
      "alloc_id": "dma_vpu_0",
      "dev_name": "vpu_decoder",
      "count": 64,
      "align_order": 6
    },
    {
      "time": 10,
      "type": "CMA_RELEASE",
      "alloc_id": "dma_vpu_0"
    }
  ]
}
```

### 출력 형식 (Standard Output)

공백 없이 압축된 단일 라인 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 출력해야 합니다:

```json
{
  "summary": {
    "cma_alloc_success": 1,
    "cma_alloc_failures": 0,
    "total_migrated_pages": 52,
    "cma_used_pages": 0,
    "cma_free_pages": 256,
    "buddy_movable_free": 64,
    "buddy_unmovable_free": 256
  },
  "pageblocks": [
    {
      "block_id": 0,
      "start_pfn": 2048,
      "migratetype": "MIGRATE_CMA",
      "cma_active_count": 0,
      "movable_cache_count": 52
    },
    {
      "block_id": 1,
      "start_pfn": 2112,
      "migratetype": "MIGRATE_CMA",
      "cma_active_count": 0,
      "movable_cache_count": 0
    }
  ],
  "active_dma_allocations": {},
  "operation_logs": [
    {
      "time": 0,
      "op": "ALLOC_BUDDY_MOVABLE",
      "status": "SUCCESS",
      "allocated_buddy": 500,
      "allocated_cma": 0
    },
    {
      "time": 2,
      "op": "CMA_ALLOC",
      "alloc_id": "dma_vpu_0",
      "dev_name": "vpu_decoder",
      "status": "SUCCESS",
      "start_pfn": 2048,
      "count": 64,
      "migrated_pages": 0
    },
    {
      "time": 10,
      "op": "CMA_RELEASE",
      "alloc_id": "dma_vpu_0",
      "status": "SUCCESS",
      "freed_pages": 64
    }
  ]
}
```
