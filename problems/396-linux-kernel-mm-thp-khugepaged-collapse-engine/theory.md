# 396: 리눅스 커널 메모리 관리 — Transparent Hugepage(THP)와 khugepaged 백그라운드 붕괴(Collapse) 아키텍처 심층 이론

## 1. 하드웨어 가상 메모리와 TLB 미스 병목

현대 가상 메모리 시스템에서 CPU의 MMU(Memory Management Unit)는 가상 주소를 물리 주소로 변환하기 위해 4단계(PGD -> P4D -> PUD -> PMD -> PTE) 페이지 테이블 트리를 탐색(Page Table Walk)합니다.
이 변환 과정은 DRAM에 최대 4~5회의 추가 읽기 접근을 유발하므로, CPU는 변환 결과를 TLB(Translation Lookaside Buffer)에 캐싱합니다.

### 1.1 4KB 기본 페이지의 한계
- 4KB 페이지 기준, 1000개의 L2 TLB 엔트리는 고작 $1000 	imes 4	ext{KB} = 4	ext{MB}$의 메모리만을 커버할 수 있습니다.
- 64GB 크기의 메모리 풀을 사용하는 데이터베이스 워크로드에서는 TLB 커버리지(4MB)를 수만 배 초과하여 TLB 미스율이 20%를 상회하며, 이는 메모리 대역폭의 낭비와 극심한 IPC(Instructions Per Cycle) 저하로 이어집니다.

### 1.2 2MB HugePage의 수학적 이점
x86_64 아키텍처의 PMD(Page Middle Directory) 레벨에서 직접 매핑되는 2MB HugePage를 도입할 경우:
$$	ext{TLB Coverage per Entry} = 2	ext{MB} = 512 	imes 4	ext{KB}$$
- 단 1개의 TLB 엔트리로 2MB를 커버하므로 TLB 미스율이 99% 이상 급감합니다.
- 페이지 테이블 트리 탐색 단계가 4단계에서 3단계(PGD -> PUD -> PMD)로 단축되어 Page Walk 오버헤드가 25% 절감됩니다.
- 512개의 개별 4KB PTE 엔트리를 담던 4KB 크기의 PTE 페이지 테이블 페이지가 완전히 해제되므로 시스템 전체의 페이지 테이블 오버헤드 또한 크게 감소합니다.

---

## 2. Transparent HugePage (THP)와 khugepaged

### 2.1 THP의 설계 철학
기존의 `hugetlbfs` 방식은 개발자가 명시적으로 `mmap(MAP_HUGETLB)`을 호출해야 하고, 사전에 예약된 고정 크기 풀에서만 할당되므로 유연성이 부족했습니다.
THP는 애플리케이션의 수정 없이 표준 `malloc()`이나 익명 메모리 매핑에 대해 커널이 투명하게 거대 페이지를 관리해 줍니다.

### 2.2 khugepaged의 역할: 동적 붕괴 (Collapse)
프로세스 실행 초기에는 메모리 단편화나 부분적 할당으로 인해 4KB 페이지 단위로 할당되는 경우가 흔합니다.
커널 데몬 **`khugepaged`** 는 시스템 백그라운드에서 주기적으로 VMA(가상 메모리 영역)를 순회하며, 2MB 단위로 정렬된 PMD 윈도우를 관찰합니다:
1. **스캔 (Scan)**:
   해당 2MB 범위 내 512개 PTE의 상태(Present, None, Swapped, Shared, Referenced)를 전수 집계합니다.
2. **평가 (Evaluation)**:
   - 미할당 페이지 수가 `max_ptes_none`을 초과하면 내부 단편화 방지를 위해 스킵합니다.
   - 스왑된 페이지 수가 `max_ptes_swap`을 초과하면 동기식 I/O 병목 방지를 위해 거부합니다.
   - 접근된(Referenced) 페이지 수가 `min_referenced` 미만인 콜드 메모리는 귀중한 Order-9 연속 물리 메모리를 소모하지 않도록 승격을 거부합니다.
3. **붕괴 (Collapse)**:
   적격성이 입증되면 버디 할당자(Buddy Allocator)로부터 2MB 연속 물리 페이지를 할당받고, PMD 스핀락을 획득한 후 512개 페이지의 데이터를 복사하고 원본 4KB 페이지 테이블을 회수합니다.

---

## 3. 결론

리눅스 커널의 `khugepaged`는 런타임에 메모리 접근 국소성(Locality)과 단편화 비용 사이의 균형을 엄격한 수리적 규칙을 통해 조율하는 자율 최적화 서브시스템입니다.
본 시뮬레이터는 이러한 커널의 4단계 적격성 판정, PTE 회수 및 2MB PMD 붕괴 알고리즘을 완벽하게 재현합니다.
