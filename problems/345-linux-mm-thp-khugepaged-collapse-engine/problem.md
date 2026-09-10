# Linux Kernel 메모리 관리: THP(Transparent Huge Pages), khugepaged 통합(Collapse) 및 분할(Split) 엔진

## 문제 설명

현대 엔터프라이즈 데이터베이스(PostgreSQL, Redis, MySQL), AI/LLM 학습, 고성능 JVM 환경에서는 수십 기가바이트에서 수 테라바이트에 달하는 방대한 가상 메모리를 운용합니다. 그러나 x86-64 아키텍처의 기본 **4KB 페이지(Page)**를 사용할 경우, 1GB 메모리를 관리하는 데에만 262,144개의 페이지 테이블 엔트리(PTE)가 소모되며 CPU의 **TLB(Translation Lookaside Buffer) 미스(Miss)**율이 폭증하여 CPU 사이클의 30~50%가 메모리 주소 변환(Page Table Walk)에 낭비되는 참사가 발생합니다.

이를 해결하기 위해 리눅스 커널(`mm/huge_memory.c`, `mm/khugepaged.c`)은 유저 애플리케이션의 코드 수정 없이도 OS가 투명하게 2MB 대용량 페이지를 할당하고 관리하는 **THP(Transparent Huge Pages)** 서브시스템을 제공합니다:

```
                            +-------------------------------+
                            |   페이지 폴트 발생 (vaddr)     |
                            +-------------------------------+
                                            |
                                            v
               +---------------------------------------------------------+
               | 1단계: 직접 THP 할당 시도                               |
               | thp_mode == 'always' 또는 (madvise & MADV_HUGEPAGE)     |
               | PMD 범위가 비어있고 물리 메모리 파편화가 없어야 함        |
               +---------------------------------------------------------+
                        |                                       |
                   [할당 성공]                             [파편화/미지원]
                        v                                       v
               2MB PMD 거대 페이지 매핑               4KB 기본 PTE 할당 (폴백)
               TLB 엔트리 1개로 2MB 처리                     |
                        |                                       v
                        |                 +-----------------------------------+
                        |                 | 2단계: khugepaged 백그라운드 스캐너|
                        |                 | 충분한 4KB 페이지(>= 448) 모이면   |
                        |                 | 2MB 거대 페이지로 통합(Collapse)    |
                        |                 +-----------------------------------+
                        |                                       |
                        +-------------------+-------------------+
                                            |
                                            v
               +---------------------------------------------------------+
               | 3단계: munmap / mprotect 발생 시 원자적 분할(Split)     |
               | 2MB PMD 거대 페이지를 다시 512개의 연속 4KB PTE로 복원  |
               +---------------------------------------------------------+
```

본 문제에서는 리눅스 커널의 THP 페이지 폴트 할당, `khugepaged` 데몬의 지연 통합(Collapse), 그리고 거대 페이지 분할(Split) 메커니즘을 정밀하게 시뮬레이션하는 **이산 THP 메모리 관리 엔진**을 구현해야 합니다.

---

## 핵심 메커니즘 및 명세

### 1. 가상 주소 구조 및 크기 규격
- 기본 페이지 크기: `PAGE_SIZE_4K = 4096` 바이트.
- 거대 페이지 크기: `HUGE_PAGE_SIZE_2M = 2097152` 바이트 (512개 4KB 페이지).
- PMD 인덱스: `pmd_index = vaddr // HUGE_PAGE_SIZE_2M`.
- PTE 오프셋: `pte_index = (vaddr % HUGE_PAGE_SIZE_2M) // PAGE_SIZE_4K` ($0 \le 	ext{pte\_index} < 512$).

### 2. 페이지 폴트 (`PAGE_FAULT`)
- 입력: `vaddr`, `madv_huge` (기본 `false`), `memory_fragmented` (기본 `false`)
1. 해당 `pmd_index`가 이미 거대 페이지(`is_huge == true`)라면 `{"status": "ALREADY_MAPPED_HUGE", "vaddr": vaddr, "pmd_index": pmd_index}`를 반환합니다.
2. THP 직접 할당 자격 검사:
   - `thp_mode == "always"`이거나 (`thp_mode == "madvise"`이고 `madv_huge == true`)일 때 가능.
   - 메모리 파편화(`memory_fragmented == false`)가 없고, 해당 PMD 내 512개 PTE가 모두 비어있는 경우:
     - 2MB 연속 물리 프레임(PFN 512개)을 직접 할당하고 `is_huge = true`, `huge_pfn = next_pfn`으로 설정합니다.
     - `next_pfn += 512`, `stats.thp_fault_alloc += 1`.
     - 반환: `{"status": "THP_FAULT_ALLOC_SUCCESS", "vaddr": vaddr, "pmd_index": pmd_index, "huge_pfn": huge_pfn}`
3. 자격이 없거나 파편화된 경우 4KB 기본 페이지로 폴백:
   - 해당 `pte_index`가 비어있다면 `pfn = next_pfn`, `next_pfn += 1`, `stats.thp_fault_fallback += 1`.
   - 반환: `{"status": "PTE_4K_ALLOC_SUCCESS", "vaddr": vaddr, "pmd_index": pmd_index, "pte_index": pte_index, "pfn": pfn}`
   - 이미 매핑되어 있다면: `{"status": "ALREADY_MAPPED_4K", "vaddr": vaddr, "pmd_index": pmd_index, "pte_index": pte_index}`

### 3. khugepaged 백그라운드 통합 (`COLLAPSE`)
- 입력: `pmd_index`
- 해당 PMD가 이미 거대 페이지이면 `{"status": "ALREADY_HUGE", "pmd_index": pmd_index}`.
- 빈 PTE 수(`none_count = 512 - present_count`)를 계산합니다.
- 만약 `none_count > max_ptes_none`이면 페이지 밀도가 너무 희소하므로 통합을 건너뜁니다:
  - 반환: `{"status": "COLLAPSE_SKIPPED_TOO_SPARSE", "pmd_index": pmd_index, "present_ptes": present_count, "required_min": 512 - max_ptes_none}`
- 조건을 만족하면($	ext{present\_count} \ge 512 - 	ext{max\_ptes\_none}$):
  - 신규 2MB 거대 페이지를 할당(`huge_pfn = next_pfn`, `next_pfn += 512`)하고 `is_huge = true`로 승격합니다.
  - 기존 4KB PTE들은 모두 비우며, `stats.thp_collapse_alloc += 1`.
  - 반환: `{"status": "COLLAPSE_SUCCESS", "pmd_index": pmd_index, "huge_pfn": huge_pfn, "collapsed_4k_pages": present_count}`

### 4. 거대 페이지 원자적 분할 (`SPLIT`)
- 입력: `pmd_index`
- 거대 페이지가 아니라면 `{"status": "NOT_HUGE", "pmd_index": pmd_index}`.
- 거대 페이지(`huge_pfn`)를 해제하고, 512개의 연속된 4KB PTE(`ptes[i] = huge_pfn + i`)로 원자적으로 재분배합니다.
- `is_huge = false`, `huge_pfn = null`, `stats.thp_split_count += 1`.
- 반환: `{"status": "SPLIT_SUCCESS", "pmd_index": pmd_index, "restored_ptes": 512}`

### 5. 상태 조회 (`GET_PMD_STATUS`, `GET_STATS`)
- `GET_PMD_STATUS`: `pmd_index`, `is_huge`, `huge_pfn`, `present_4k_ptes` 반환.
- `GET_STATS`: `thp_mode`, `total_pmds`, `huge_pmds_count`, 전체 누적 통계(`stats`) 반환.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "thp_mode": "always",
    "max_ptes_none": 64
  },
  "operations": [
    { "op": "PAGE_FAULT", "vaddr": 0 },
    { "op": "GET_PMD_STATUS", "pmd_index": 0 },
    { "op": "SPLIT", "pmd_index": 0 },
    { "op": "GET_STATS" }
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과를 담은 JSON 배열을 공백 없이(compact) 출력합니다.

---

## 제약 사항

- $0 \le 	ext{vaddr} \le 10^{14}$
- $0 \le 	ext{pmd\_index} \le 10000$
- $0 \le 	ext{max\_ptes\_none} \le 511$
- 연산 수 $N \le 5000$
- 시간 복잡도: 각 연산당 $O(1)$ ~ $O(512)$, 전체 $O(N)$ 이내.
