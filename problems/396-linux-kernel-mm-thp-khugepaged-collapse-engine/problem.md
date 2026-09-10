# 396: 리눅스 커널 메모리 관리 — Transparent Hugepage(THP) khugepaged 백그라운드 스캐닝 및 2MB PMD 붕괴(Collapse) 엔진

## 1. 개요 (Overview)

현대 CPU의 **TLB(Translation Lookaside Buffer)** 는 가상 주소를 물리 주소로 고속 변환해 주는 하드웨어 캐시입니다. 그러나 4KB 기본 페이지(Base Page)를 사용할 경우 L1/L2 TLB 엔트리 수(보통 64~1024개)의 한계로 인해 단 수 메가바이트(MB)의 메모리만 캐싱할 수 있어, 대규모 인메모리 데이터베이스(Redis, PostgreSQL)나 분산 컴퓨팅 환경에서 **TLB 미스(TLB Miss)로 인한 파이프라인 지연이 전체 실행 시간의 15%~30%에 달하는 심각한 병목**을 초래합니다.

이를 해결하기 위해 x86_64 아키텍처의 PMD(Page Middle Directory) 레벨 **2MB 거대 페이지(HugePage)** 를 사용하면, 단 1개의 TLB 엔트리로 512개의 4KB 페이지(2,097,152 바이트)를 한 번에 캐싱할 수 있습니다.

리눅스 커널의 **투명 거대 페이지(THP: Transparent HugePage, `mm/khugepaged.c`)** 서브시스템은 애플리케이션 코드를 수정하지 않고도 백그라운드 커널 스레드인 **`khugepaged`** 를 통해 가상 메모리 공간을 주기적으로 순회 스캔합니다. 만약 2MB에 해당하는 512개의 4KB 페이지 윈도우(`[PMD_START, PMD_END)`)가 충분히 밀집되어 있고 활발히 접근(Referenced)된다면, 512개의 개별 4KB PTE(Page Table Entry)들을 단일 2MB 복합 페이지(Compound Page)로 병합 승격시키는 **붕괴(Collapse, `collapse_huge_page`)** 작업을 실행합니다.

본 문제에서는 리눅스 커널 `khugepaged`의 PMD 윈도우 스캐닝 알고리즘, 미할당 페이지(`max_ptes_none`), 스왑 페이지(`max_ptes_swap`), 공유 페이지(`max_ptes_shared`), 접근 빈도(`min_referenced`) 기반 적격성 검증 상태 머신 및 2MB PMD 붕괴 시뮬레이션 엔진을 설계 및 구현합니다.

---

## 2. khugepaged 아키텍처 다이어그램

```
+========================================================================================+
|                    2MB Aligned PMD Window [0x00000000, 0x00200000)                     |
|                                                                                        |
|  PTE 0      PTE 1      PTE 2                 PTE 510    PTE 511                        |
|  +-------+  +-------+  +-------+             +-------+  +-------+                      |
|  | 4KB   |  | 4KB   |  | SWAP  |  ... ...    | NONE  |  | 4KB   |  (512 x 4KB PTEs)    |
|  | (Hot) |  | (Hot) |  | (Cold)|             | (Zero)|  | (Hot) |                      |
|  +-------+  +-------+  +-------+             +-------+  +-------+                      |
|      \         \          \                    /          /                         |
|       \===================================================/                          |
|                                 ||                                                     |
|              [khugepaged Scanning & Policy Evaluation]                                 |
|              - none_pages <= max_ptes_none (Avoid internal fragmentation)              |
|              - swap_pages <= max_ptes_swap (Prevent IO freeze during swap-in)          |
|              - shared_pages <= max_ptes_shared (Exclude CoW/Shared pages)              |
|              - referenced_pages >= min_referenced (Ensure hot working set)             |
|                                 ||                                                     |
|                     [collapse_huge_page() Execution]                                   |
|                                 ||                                                     |
|  1. Allocate 2MB Physical Compound Page (Order-9 Allocator)                            |
|  2. Synchronously Swap-In Any Swapped Pages (Restore data)                             |
|  3. Zero-fill Any Unallocated (NONE) Pages                                             |
|  4. Copy 512 4KB data into 2MB HugePage                                                |
|  5. Free 4KB Page Table (PTE table freed -> save 4KB kernel memory)                    |
|  6. Atomically Install 2MB PMD Entry & Flush TLB Range                                 |
|                                 ||                                                     |
|                                 VV                                                     |
|  +----------------------------------------------------------------------------------+  |
|  |                Single 2MB Compound HugePage (PMD Mapped)                         |  |
|  |                     [TLB Footprint: 512 -> 1 Entry!]                             |  |
|  +----------------------------------------------------------------------------------+  |
+========================================================================================+
```

---

## 3. 핵심 수리 및 알고리즘 규칙

### 3.1 PMD 윈도우 구조 및 페이징 단위
- 1개 PMD 윈도우는 정확히 512개의 4KB 페이지 슬롯을 포함합니다 ($512 	imes 4096 = 2,097,152 	ext{ 바이트} = 2	ext{MB}$).
- 슬롯 상태:
  - `PRESENT`: 물리 RAM에 로드되어 있는 유효한 4KB 페이지.
  - `NONE`: 미할당(Zero) 페이지.
  - `SWAPPED`: 디스크 스왑 파티션에 내려가 있는 페이지.
  - `SHARED`: 타 프로세스와 공유(CoW) 중인 페이지.
- 각 슬롯은 하드웨어 접근 플래그 `referenced` (True/False)를 보유합니다.

### 3.2 khugepaged 승격 적격성 검증 규칙 (Promotion Criteria)
스캔 대상 PMD에 대해 다음 4가지 커널 한계 조건을 모두 만족해야만 붕괴(Collapse)가 승인됩니다:
1. **미할당 페이지 한계**: $	ext{count}(	ext{NONE}) \le 	ext{max\_ptes\_none}$
   - 너무 많은 빈 페이지를 2MB로 합치면 심각한 내부 단편화(Internal Fragmentation) 메모리 낭비가 발생합니다.
2. **스왑 페이지 한계**: $	ext{count}(	ext{SWAPPED}) \le 	ext{max\_ptes\_swap}$
   - 스왑 인(Swap-In) 동기화 I/O 지연으로 인한 스캐닝 스레드 블로킹 방지.
3. **공유 페이지 한계**: $	ext{count}(	ext{SHARED}) \le 	ext{max\_ptes\_shared}$
   - 공유 메모리의 분리 복잡성 방지.
4. **핫 워킹 세트 검증**: $	ext{count}(	ext{REFERENCED}) \ge 	ext{min\_referenced}$
   - 차가운(Cold) 메모리에 고가의 2MB 연속 물리 메모리를 낭비하지 않도록 보장.

### 3.3 붕괴 실행 및 자원 계량
- 적격성 검증 통과 시:
  - PMD 상태가 `SPLIT_4K`에서 `COLLAPSED_2MB`로 전이됩니다.
  - 512개 PTE를 관리하던 **4KB 크기의 4단계 페이지 테이블 페이지(PTE Page Table Page)가 해제**되어 커널 메모리가 절감됩니다 ($	ext{freed\_pte\_table\_bytes} \mathrel{+}= 4096$).
- 스캔 커서(Cursor):
  - 틱마다 `scan_rate_pmds_per_tick` 개수만큼 순차적으로 PMD를 스캔하며, 끝에 도달하면 원형 링(Round-Robin)처럼 인덱스 0으로 Wrap-Around 순환합니다.
  - 이미 `COLLAPSED_2MB` 상태인 PMD는 스캔 시 스킵(`status: "SKIP"`)됩니다.

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
```json
{
  "config": {
    "max_ptes_none": 64,
    "max_ptes_swap": 16,
    "max_ptes_shared": 0,
    "min_referenced": 64,
    "scan_rate_pmds_per_tick": 1
  },
  "initial_pages": [
    {"pmd_idx": 0, "page_idx": 0, "state": "PRESENT", "referenced": true}
  ],
  "scan_epochs": 1
}
```

### 4.2 출력 형식 (Output Format)
```json
{
  "total_scans": 1,
  "successful_collapses": 1,
  "failed_collapses": 0,
  "failure_reasons": {},
  "freed_pte_table_bytes": 4096,
  "collapse_log": [
    {
      "pmd_idx": 0,
      "start_addr": "0x00000000",
      "end_addr": "0x00200000",
      "pages_collapsed": 512,
      "swapped_in": 0,
      "zero_filled": 0,
      "freed_pte_table_bytes": 4096
    }
  ],
  "pmd_states": {
    "0": {
      "pmd_idx": 0,
      "start_addr": "0x00000000",
      "end_addr": "0x00200000",
      "status": "COLLAPSED_2MB",
      "page_counts": {
        "NONE": 0,
        "PRESENT": 512,
        "SWAPPED": 0,
        "SHARED": 0,
        "REFERENCED": 200
      }
    }
  }
}
```
