# 심층 시스템 이론: 리눅스 커널 HugeTLB Vmemmap 최적화 (HVO / `mm/hugetlb_vmemmap.c`) 및 테일 페이지 재매핑 아키텍처

## 1. SPARSEMEM_VMEMMAP 메모리 모델과 메타데이터 오버헤드

현대 64비트 x86-64 및 ARM64 리눅스 커널은 물리 메모리를 효율적으로 추적하기 위해 **`SPARSEMEM_VMEMMAP`** 가상 메모리 모델을 사용합니다.

### 1) 1:1 불변 선형 매핑
시스템 내의 모든 물리 메모리 프레임(Page Frame Number, PFN)에 대해, 커널은 `vmemmap`이라는 거대한 연속 가상 주소 공간에 64바이트 크기의 `struct page`를 1:1로 직접 매핑합니다:
$$\text{struct page *page} = \text{vmemmap} + \text{pfn}$$
- 이 직접 주소 변환 덕분에 `pfn_to_page()`와 `page_to_pfn()` 연산은 단 1번의 덧셈/뺄셈/시프트 명령어($O(1)$)로 수행됩니다.
- 그러나 이 우아한 설계의 대가는 **물리 메모리의 약 1.56% (64B / 4KB)**가 오직 메타데이터용 RAM으로 영구 고정된다는 점입니다.

---

## 2. 거대 페이지(HugeTLB)에서의 중복 메타데이터 발견

거대 페이지(HugePage)는 커널 수준에서 단일 복합 페이지(Compound Page)로 취급됩니다:
- **Head Page (Page 0)**: 거대 페이지의 참조 카운트(`_refcount`), 플래그(`flags`), 파괴자 함수, 매핑 정보를 독점적으로 보유합니다.
- **Tail Pages (Page 1 ~ 511 / Page 1 ~ 262,143)**:
  테일 페이지들의 `struct page`는 독자적인 상태를 가지지 않습니다. 오직 `compound_head` 포인터를 통해 헤드 페이지를 역참조하는 역할만 수행합니다.

### 1) 낭비되는 물리 메모리의 수치적 규모
- 2MB 거대 페이지 1개: 8개의 vmemmap 4KB 페이지(32KB) 점유.
- 1GB 거대 페이지 1개: 4,096개의 vmemmap 4KB 페이지(16MB) 점유.
- 1TB RAM을 1GB 거대 페이지로 가득 채운 하이퍼바이저 노드:
  $$1024 \times 16\text{ MB} = 16\text{ GB}$$
  순수하게 테일 `struct page` 메타데이터를 저장하기 위해 16GB의 고속 DDR5 RAM이 허공으로 사라집니다.

---

## 3. HVO (HugeTLB Vmemmap Optimization)의 혁신적 설계

ByteDance의 커널 엔지니어 Muchun Song에 의해 제안되어 리눅스 5.14에 머지된 HVO(`CONFIG_HUGETLB_PAGE_OPTIMIZE_VMEMMAP`)는 가상 메모리의 페이지 테이블 리매핑을 통해 이 낭비를 원천 제거합니다.

```
[HVO 페이지 테이블 재매핑 파이프라인]:
1. HugePage 할당 (2MB)
2. Head vmemmap page (Page 0) 및 First Tail page (Page 1) 보존
3. Remaining Tail vmemmap pages (Page 2 ~ 7) 탐색
4. Page 2~7의 PTE 엔트리를 Page 1의 물리 PFN으로 교체 (PTE Remap)
5. flush_tlb_kernel_range()를 통한 커널 TLB 플러시
6. Page 2~7에 할당되어 있던 원래의 물리 4KB 페이지 7개를 free_page()로 버디 반환!
```

### 1) 절감률 (Memory Overhead Reduction Ratio)
- **2MB 거대 페이지**:
  $$\frac{7}{8} = 87.5\% \text{ 메타데이터 절감 (28KB 회수)}$$
- **1GB 기가 페이지**:
  $$\frac{4095}{4096} \approx 99.976\% \text{ 메타데이터 절감 (16,380KB 회수)}$$

---

## 4. 읽기 전용(Read-Only) 매핑과 무결성 보호

여러 가상 주소(`vmemmap` Page 1부터 Page 7)가 물리적으로 단 하나의 Page 1 프레임을 공유하므로, 심각한 동시성 및 데이터 오염 위험이 존재합니다.

### 1) 공유 테일 쓰기 차단 (RO Enforcement)
- 만약 어떤 커널 루틴이나 드라이버가 Tail 3의 `struct page` 필드를 쓰려고 시도하면, 동일한 물리 페이지를 공유하는 Tail 1, Tail 2, Tail 4~7의 메타데이터까지 동시에 변조됩니다.
- 따라서 커널은 HVO가 적용된 테일 페이지들의 PTE에서 **`_PAGE_RW` (쓰기 가능 비트)를 제거하고 읽기 전용(Read-Only)**으로 봉인합니다.
- 불법적인 쓰기 시도 시 하드웨어 MMU가 즉시 페이지 폴트(`PAGE_FAULT_RO`)를 일으켜 데이터 오염을 완벽히 차단합니다.

---

## 5. 해체(Dissolve)와 버디 할당자 메모리 복원 제약

프로세스가 HugePage를 반환하거나 분할(Dissolve)할 때, 커널은 HVO를 역으로 되돌려야(De-optimize) 합니다:
1. 버디 할당자로부터 7개(1GB의 경우 4,095개)의 새로운 물리 4KB 페이지를 할당받음.
2. 각 페이지의 PTE를 개별 물리 PFN으로 복원하고 쓰기 권한 복구.
3. 테일 `struct page`의 기본 상태를 재초기화.
4. 비로소 2MB 연속 블록을 정상 버디 블록으로 해체.

만약 시스템 메모리가 극도로 고갈되어 버디 할당자로부터 필요한 4KB 페이지를 빌려올 수 없다면, 커널은 안전을 위해 **`-ENOMEM`을 반환하며 해체 작업을 중단**합니다. 이는 불완전한 상태에서 시스템 패닉이 발생하는 것을 방지하기 위한 핵심 방어벽입니다.

---

## 6. 결론

HVO는 페이징 하드웨어의 가상-물리 매핑 유연성을 극한까지 활용하여, 테라바이트급 클라우드 서버에서 수십 기가바이트의 메모리를 공짜로 회수하는 획기적인 커널 메모리 최적화 기법입니다.
