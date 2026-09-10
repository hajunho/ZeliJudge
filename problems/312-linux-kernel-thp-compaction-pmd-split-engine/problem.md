# 리눅스 커널 THP 듀얼 스캐너 메모리 컴팩션 및 PMD 분할 엔진 (Linux Kernel THP Compaction & PMD Split Engine)

## 문제 설명

수백 기가바이트의 메모리를 사용하는 고성능 인메모리 캐시(Redis), 관계형 데이터베이스(PostgreSQL), 그리고 분산 검색 엔진(Elasticsearch) 클러스터에서 원인을 알 수 없는 간헐적 수 초 단위의 레이턴시 스파이크와 응답 정체(Freeze)가 발생했습니다:

```
[ 1824.912044] redis-server: page allocation stalls for 124ms, order:9, mode:0x40dc0(GFP_TRANSHUGE)
[ 1824.912110] Call Trace:
[ 1824.912120]  __alloc_pages_slowpath+0x42a/0xd80
[ 1824.912135]  compact_zone+0x31a/0x890
[ 1824.912150]  alloc_hugepage_vma+0x92/0x180
```

이 참사의 원인은 리눅스 커널의 **투명한 거대 페이지(Transparent Huge Pages, THP)** 및 **메모리 컴팩션(Memory Compaction, `mm/huge_memory.c`, `mm/compaction.c`)** 동작 방식에 있습니다.

x86-64 아키텍처에서 기본 페이지 크기는 4KB(Order 0)이지만, THP는 연속된 512개의 4KB 페이지(총 2MB, Order 9)를 단일한 **컴파운드 페이지(Compound Page)**로 묶어 페이지 중간 디렉토리(Page Middle Directory, PMD)에 직접 매핑합니다. 이를 통해 TLB(Translation Lookaside Buffer) 미스를 최대 512배 줄여 메모리 집중 워크로드의 처리 성능을 극대화합니다.

그러나 시스템이 장시간 구동되면 **외부 단편화(External Fragmentation)**가 발생하여, 전체 여유 메모리는 충분함에도 2MB 크기의 연속된 물리 메모리 블록을 찾지 못하는 상황이 발생합니다. 이때 커널은 동기식 **직접 컴팩션(Direct Compaction)**을 호출합니다:

1. **듀얼 스캐너(Dual Scanners) 수렴 알고리즘**:
   - **이동 스캐너 (`migrate_scanner`)**: 메모리 존의 시작 지점(낮은 PFN)에서 높은 PFN 방향으로 전진하며 이동 가능한(`movable`) 할당된 4KB 페이지를 찾습니다.
   - **빈 공간 스캐너 (`free_scanner`)**: 메모리 존의 끝 지점(높은 PFN)에서 낮은 PFN 방향으로 후진하며 빈 페이지 프레임(`free`)을 찾습니다.
   - 두 스캐너가 서로를 향해 전진하며, 앞쪽의 할당 페이지를 뒤쪽의 빈 공간으로 복사·이동시킵니다.
   - 스캐너가 교차하거나 목표 크기(Order-K)의 자연 정렬된 연속 빈 블록이 형성되면 컴팩션이 성공적으로 종료됩니다.

2. **컴파운드 페이지 할당 및 PMD 분할 (`split_huge_pmd`)**:
   - 합성된 2MB 연속 블록의 첫 페이지는 `PageHead`로, 나머지 511개 페이지는 `PageTail`로 설정되어 원자적으로 관리됩니다.
   - 이후 프로세스가 `madvise(MADV_DONTNEED)`를 호출하거나 메모리 압박으로 하위 페이지만을 해제해야 할 경우, 커널은 **`split_huge_pmd()`**를 실행하여 2MB 단일 PMD 매핑을 512개의 독립된 4KB PTE 매핑으로 안전하게 분할합니다.

본 문제는 리눅스 커널 가상 메모리 서브시스템의 핵심인 Order-K 정렬 검사, 듀얼 스캐너 메모리 컴팩션, 컴파운드 페이지 할당 및 PMD 분할 알고리즘을 충실하게 모사하는 커널급 가상 메모리 시뮬레이션 엔진을 구현하는 것입니다.

```
                    [ 듀얼 스캐너 메모리 컴팩션 (Compaction) ]
  Zone Start (PFN 0)                                       Zone End (PFN N-1)
         |                                                          |
         v                                                          v
  [ migrate_scanner ] --->                            <--- [ free_scanner ]
  (낮은 PFN에서 전진:                                   (높은 PFN에서 후진:
   이동 가능한 할당 페이지 탐색)                          빈 페이지 프레임 탐색)
         |                                                          |
         +------------------- [ 페이지 이동 (Migration) ] -----------+
                              앞쪽 할당 페이지 -> 뒤쪽 빈 공간
                                       |
                                       v
                    [ 정렬된 Order-K 연속 빈 블록 합성 완료 ]
                                       |
                                       v
                     [ 2MB THP 컴파운드 페이지 할당 ]
                     - Base PFN: PageHead (refcount=1)
                     - Base + 1 ~ 511: PageTail
                                       |
                                       v
                     [ 부분 해제 / 압박 시 PMD 분할 ]
                     split_huge_pmd() -> 512개 독립 4KB PTE 전환
```

---

## 알고리즘 및 상태 전이 명세

### 1. 물리 메모리 존 초기화
- 총 페이지 수: `total_pages` (기본값: 32)
- 거대 페이지 차수: `hugepage_order` (기본값: 3, 크기 $L = 2^{	ext{order}}$ 페이지)
- 각 페이지 프레임 $pfn \in [0, 	ext{total\_pages}-1]$:
  - `state`: `"FREE"` 또는 `"ALLOCATED"`
  - `page_type`: `"REGULAR_4K"`
  - `movable`: 기본 `True` (커널 고정 페이지는 `False`)
  - `refcount`: 기본 0

### 2. 정렬된 연속 빈 블록 탐색 (Aligned Block Search)
- 거대 페이지는 반드시 $L$의 배수 주소(자연 정렬, Natural Alignment)에서 시작해야 합니다.
- `base = 0, L, 2L, ...` 순서대로 탐색하여, 구간 $[base, base + L - 1]$의 모든 페이지의 `state`가 `"FREE"`인 최초의 `base` PFN을 찾습니다.
- 발견되면 해당 `base` 반환, 없으면 `-1` 반환.

### 3. 직접 컴팩션 알고리즘 (`compact_zone`)
정렬된 블록이 존재하지 않을 때 실행:
1. `mig_pfn = 0`, `free_pfn = total_pages - 1`, `migrated = 0`
2. `mig_pfn < free_pfn`인 동안 루프:
   - `mig_pfn` 전진: `state == "ALLOCATED"`이고 `movable == True`이며 `page_type == "REGULAR_4K"`인 페이지 탐색.
   - `free_pfn` 후진: `state == "FREE"`인 페이지 탐색.
   - `mig_pfn < free_pfn`이면:
     - `free_pfn` 프레임으로 상태 복사 (`ALLOCATED`, `vma_id`, `movable`, `refcount` 이전)
     - `mig_pfn` 프레임 초기화 (`FREE`, `REGULAR_4K`, `refcount = 0`)
     - `migrated += 1`, `mig_pfn += 1`, `free_pfn -= 1`
     - 정렬된 빈 블록이 조기 합성되었는지 확인 후, 형성되었으면 루프 조기 탈출.
3. 컴팩션 종료 후 정렬된 연속 블록이 생성되었는지 재검사.

### 4. 명령 시계열 처리

#### 1) `ALLOC_THP` (투명한 거대 페이지 할당)
- 정렬된 연속 빈 블록 탐색:
  - 존재 시: 즉시 할당 (`status = "DIRECT_ALLOCATION"`)
  - 부재 시: 직접 컴팩션 가동 $	o$ 재탐색:
    - 합성 성공 시: `status = "COMPACTED_AND_ALLOCATED"`
    - 합성 실패 시: `status = "ALLOCATION_FAILED_OUT_OF_CONTIGUITY"`
- 할당 성공 시:
  - `base` 페이지: `page_type = "HUGE_2M_HEAD"`, `refcount = 1`, `movable = False`
  - `base + 1 ~ base + L - 1` 페이지: `page_type = "HUGE_2M_TAIL"`, `refcount = 0`, `movable = False`

#### 2) `SPLIT_HUGE_PMD` (거대 PMD 분할)
- 입력: 분할 대상 PFN `pfn`.
- `pfn`이 거대 페이지의 Head 또는 Tail에 속해 있는지 확인:
  - Tail인 경우 역방향으로 탐색하여 Head PFN을 도출합니다.
  - Head를 찾은 경우:
    - Head부터 $L$개의 페이지를 모두 `page_type = "REGULAR_4K"`, `refcount = 1`, `movable = True`로 전환합니다.
    - 상태: `"SPLIT_SUCCESS"`, `subpages_split = L`.
  - 거대 페이지가 아닌 경우: `"SPLIT_ERROR_NOT_HUGE_PAGE"`.

#### 3) `FREE_PAGES` (페이지 해제)
- 지정된 PFN 목록의 페이지를 `"FREE"`, `"REGULAR_4K"`, `refcount = 0`, `movable = True`로 복구합니다.

---

## 입력 형식 (Input JSON Schema)

```json
{
  "config": {
    "total_pages": 16,
    "hugepage_order": 2
  },
  "initial_allocations": [
    {
      "vma_id": "vma-frag",
      "pfns": [0, 4, 8, 12],
      "movable": true
    }
  ],
  "commands": [
    {
      "op": "ALLOC_THP",
      "vma_id": "vma-huge1"
    }
  ]
}
```

---

## 출력 형식 (Output JSON Schema)

```json
{
  "summary": {
    "total_pages": 16,
    "hugepage_len": 4,
    "free_pages_count": 8,
    "allocated_pages_count": 8,
    "active_thp_count": 1,
    "compaction_runs": 1,
    "pages_migrated_total": 1,
    "pmd_splits_count": 0
  },
  "command_history": [
    {
      "command_index": 1,
      "op": "ALLOC_THP",
      "vma_id": "vma-huge1",
      "details": {
        "status": "COMPACTED_AND_ALLOCATED",
        "base_pfn": 0,
        "hugepage_len": 4,
        "compaction_migrated_pages": 1
      }
    }
  ]
}
```

---

## 제약 조건

- $8 \le 	ext{total\_pages} \le 1,024$
- $1 \le 	ext{hugepage\_order} \le 6$
- $1 \le 	ext{commands} \le 100$
- 표준 입력(`sys.stdin`)으로부터 UTF-8 JSON 문자열을 수신하고, 결과를 `json.dumps(..., ensure_ascii=False)`로 표준 출력에 인쇄합니다.
