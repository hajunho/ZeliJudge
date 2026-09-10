# 문제 #277: 대규모 메모리 단편화(Memory Fragmentation) 속 2MB THP(Transparent Huge Page) 할당 실패를 어떻게 극복할까요?!: 리눅스 커널 메모리 컴팩션(Memory Compaction) 및 이동 스캐너-유휴 스캐너(Migrate & Free Scanners) 수렴 압축 엔진

## 1. 개요 (Story & Context)
고성능 데이터베이스(Redis, PostgreSQL, MySQL)나 대규모 AI 추론 엔진을 장시간 운영하다 보면, 시스템 전체에 사용 가능한 물리 메모리(Free Memory)가 수십 기가바이트 이상 넉넉히 남아있음에도 불구하고 **2MB 투명 대형 페이지(Transparent Huge Page, THP)** 또는 연속된 물리 메모리 버퍼(order-9, 512 페이지) 할당 요청이 계속해서 실패하는 기현상이 발생합니다!

이 현상의 주원인은 바로 **외부 단편화(External Memory Fragmentation)**입니다.
리눅스 커널의 기본 물리 메모리 할당 단위는 버디 할당자(Buddy Allocator)로 동작합니다. 여러 프로세스가 메모리를 불규칙하게 할당하고 해제하면서, 4KB 크기의 작은 페이지들이 물리 주소 공간 전체에 바둑판처럼 흩뿌려지게 됩니다. 그 결과, 아무리 전체 유휴 페이지의 합이 커도 512개의 연속된(Contiguous) 물리 페이지로 구성된 order-9 버디 블록을 단 하나도 만들 수 없게 됩니다.

이 문제를 근본적으로 해결하기 위해 리눅스 커널은 2.6.35부터 **메모리 컴팩션(Memory Compaction, `mm/compaction.c`)** 서브시스템을 도입했습니다.
컴팩션 엔진은 존(Zone)의 양 끝에서 서로를 향해 다가가는 **양방향 스캐너(Dual-Scanner Convergence)**를 구동합니다:
1. **이동 스캐너(Migration Scanner)**: 존의 시작점(`zone_start_pfn`)에서 시작하여 낮은 PFN에서 높은 PFN으로 전진하며, 이동 가능한 유효 페이지(`PAGE_ALLOCATED_MOVABLE`)들을 순차적으로 격리(Isolate)합니다. 단, 커널 슬랩이나 DMA 버퍼 같은 이동 불가 페이지블록(`MIGRATE_UNMOVABLE`)은 통째로 건너뜁니다!
2. **유휴 스캐너(Free Scanner)**: 존의 끝점(`zone_end_pfn`)에서 시작하여 높은 PFN에서 낮은 PFN으로 후진하며, 비어 있는 유휴 슬롯(`PAGE_FREE`)들을 탐색합니다.
3. **페이지 마이그레이션(Page Migration)**: 낮은 PFN의 이동 대상 페이지를 높은 PFN의 유휴 슬롯으로 복사(Copy)한 뒤, 원래 자리를 해제(Free)합니다!
4. 이를 통해 낮은 PFN 영역에 연속된 거대한 빈 공간이 형성되면서, 버디 정렬 조건(`pfn % (1 << target_order) == 0`)을 만족하는 대형 버디 블록이 즉각 합성됩니다!

여러분은 커널 가상 메모리 서브시스템의 코어 엔지니어로서, 양방향 스캐너 수렴 알고리즘과 워터마크 검증, 단편화 지수(Fragmentation Index) 산출 및 페이지블록 격리 로직을 갖춘 **리눅스 커널 메모리 컴팩션 시뮬레이터**를 완벽하게 구현해야 합니다!

---

## 2. 입출력 규격 및 컴팩션 규칙

### 2.1 페이지 상태(Page State) 정의
- `0` (`PAGE_FREE`): 미할당 유휴 페이지.
- `1` (`PAGE_ALLOCATED_MOVABLE`): 이동 가능한 프로세스 익명 페이지(Anonymous Page) 또는 페이지 캐시.
- `2` (`PAGE_ALLOCATED_UNMOVABLE`): 커널 슬랩, 페이지 테이블, DMA 링버퍼 등 물리적 이동이 불가능한 고정 페이지.

### 2.2 버디 정렬(Buddy Alignment) 조건
크기 $2^K$ 페이지(order $K$)의 버디 블록이 유효하게 성립하려면:
1. 시작 PFN이 반드시 $2^K$의 배수여야 합니다: `start_pfn % (1 << K) == 0`.
2. `start_pfn`부터 `start_pfn + (1 << K) - 1`까지의 모든 $2^K$개 페이지의 상태가 `0` (`PAGE_FREE`)이어야 합니다.

### 2.3 외부 단편화 지수(External Fragmentation Index) 공식
$$\text{frag\_index} = \begin{cases} 0 & (\text{free\_pages} < \text{target\_pages}) \\ 0 & (\text{max\_available\_order} \ge \text{target\_order}) \\ \min\left(1000, \max\left(0, \text{round}\left(1000 \times \left(1 - \frac{2^{\text{max\_available\_order}}}{\text{free\_pages}}\right)\right)\right)\right) & (\text{그 외}) \end{cases}$$
- 1000에 가까울수록 메모리는 충분하지만 단편화로 인해 할당이 불가능한 전형적인 컴팩션 적기 상태를 의미합니다.

### 2.4 컴팩션 실행 단계
1. **워터마크 검증(Watermark Check)**:
   - `initial_free_pages < min_watermark_pages + target_pages`인 경우, 인터럽트 핸들러나 필수 시스템 메모리 고갈을 방지하기 위해 컴팩션을 즉시 건너뜁니다 (`status: "COMPACT_SKIPPED_WATERMARK"`).
2. **사전 충족 검사(Already Satisfied Check)**:
   - 이미 버디 정렬 조건을 만족하는 order-$K$ 유휴 블록이 존재하는 경우, 페이지 이동 없이 즉시 반환합니다 (`status: "COMPACT_ALREADY_SATISFIED"`).
3. **양방향 스캐너 수렴 루프(Two-Scanner Loop)**:
   - `migrate_pfn = zone_start_pfn`, `free_pfn = zone_end_pfn - 1`에서 시작.
   - `migrate_scanner`:
     - 페이지블록이 `migratetype == "UNMOVABLE"`이면 해당 페이지블록의 남은 PFN을 통째로 건너뜁니다.
     - `state == PAGE_ALLOCATED_MOVABLE`인 페이지를 찾을 때까지 전진.
   - `free_scanner`:
     - `state == PAGE_FREE`인 유휴 페이지를 찾을 때까지 후진.
   - `migrate_pfn < free_pfn`이면:
     - `pfn_to_page[free_pfn]["state"] = PAGE_ALLOCATED_MOVABLE`
     - `pfn_to_page[migrate_pfn]["state"] = PAGE_FREE`
     - `migrated_count += 1`
     - 매 이동 직후 버디 정렬된 order-$K$ 블록이 형성되었는지 검사하여, 생성되었다면 즉시 성공 종료 (`status: "COMPACT_SUCCESS"`).
   - 두 스캐너가 서로 교차하거나 만날 때까지 반복 (`migrate_pfn >= free_pfn`).
   - 스캐너가 수렴할 때까지 요구 order-$K$ 블록을 만들지 못하면 `status: "COMPACT_FAILED_EXHAUSTED"` 반환.

---

## 3. 입력 형식
```json
{
  "zone_start_pfn": 1024,
  "pageblock_size": 16,
  "target_order": 3,
  "min_watermark_pages": 4,
  "pageblocks": [
    {
      "pfn_start": 1024,
      "migratetype": "MOVABLE",
      "pages": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 0]
    },
    {
      "pfn_start": 1040,
      "migratetype": "MOVABLE",
      "pages": [1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0]
    }
  ]
}
```

## 4. 출력 형식
```json
{
  "status": "COMPACT_SUCCESS",
  "initial_stats": {
    "total_pages": 32,
    "free_pages": 20,
    "max_available_order": 2,
    "fragmentation_index": 800
  },
  "compaction_result": {
    "target_order": 3,
    "target_pages": 8,
    "migrated_pages_count": 4,
    "migrate_scanner_final_pfn": 1030,
    "free_scanner_final_pfn": 1052,
    "scanners_converged": false,
    "allocated_buddy_pfn": 1024
  },
  "final_stats": {
    "free_pages": 20,
    "max_available_order": 3,
    "target_order_available": true
  },
  "final_pageblocks": [
    {
      "pfn_start": 1024,
      "migratetype": "MOVABLE",
      "free_count": 13,
      "pages": [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0]
    },
    {
      "pfn_start": 1040,
      "migratetype": "MOVABLE",
      "free_count": 7,
      "pages": [1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 1, 1, 1, 1]
    }
  ]
}
```
