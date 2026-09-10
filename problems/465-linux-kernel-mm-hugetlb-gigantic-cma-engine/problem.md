# 리눅스 커널 HugeTLB 1GB 자이갠틱 페이지(Gigantic Page) 할당 및 CMA 예약 엔진

## 1. 개요 및 배경

엔터프라이즈 환경에서 테라바이트(TB) 단위의 메모리를 사용하는 고성능 인메모리 데이터베이스(SAP HANA, Aerospike, Redis)나 초고속 패킷 처리(DPDK, NFV) 애플리케이션은 CPU의 TLB(Translation Lookaside Buffer) 미스로 인한 심각한 성능 저하를 겪습니다. 기본 4KB 페이징 환경에서는 1TB 메모리를 매핑하기 위해 268,435,456개의 페이지 테이블 엔트리(PTE)가 필요하여, CPU L1/L2 D-TLB 캐시가 지속적으로 축출(Eviction)되고 4단계 페이지 테이블 워크(Page Table Walk) 오버헤드가 CPU 사이클의 30% 이상을 낭비합니다.

2MB Huge Page(PMD 레벨 매핑)를 사용해도 1TB에는 524,288개의 페이지가 필요하지만, **1GB Gigantic Page**(x86-64 PUD 레벨 매핑)를 도입하면 단 1,024개의 엔트리만으로 1TB 전체를 완벽하게 커버할 수 있습니다!

하지만 1GB 자이갠틱 페이지의 동적 할당에는 커널 메모리 관리의 본질적인 장벽이 존재합니다:
1. **Order-18 연속 물리 메모리 요구**: 1GB는 262,144개($2^{18}$)의 연속된 4KB 물리 프레임을 요구합니다.
2. **버디 할당자(Buddy Allocator)의 한계**: 리눅스 표준 버디 할당자의 최대 할당 차수는 보통 `MAX_ORDER - 1 = 10`(4MB)에 불과하여, 런타임에 일반 버디 할당자로부터 1GB 연속 메모리를 할당받는 것은 **물리적으로 불가능**합니다.

리눅스 커널은 이를 해결하기 위해 두 가지 메커니즘을 지원합니다:
1. **부팅 시점 정적 예약 (`boot_gigantic_pages`)**: 부팅 파라미터(`default_hugepagesz=1G hugepagesz=1G hugepages=N`)를 통해 커널 메모리 블록(`memblock`) 단계에서 버디 할당자가 초기화되기 전에 물리 메모리를 선점합니다.
2. **CMA(Contiguous Memory Allocator, `mm/cma.c`) 기반 동적 할당**:
   - 부팅 시 거대한 연속 물리 메모리 영역을 예약해 둡니다.
   - 평상시에는 이 영역을 페이지 캐시나 익명 메모리 등 이동 가능한 페이지(`MIGRATE_MOVABLE`)가 자유롭게 사용하여 메모리 낭비를 방지합니다.
   - 런타임에 1GB 자이갠틱 페이지 요청이 발생하면, CMA는 해당 1GB 슬롯 내의 이동 가능 페이지들을 일반 메모리 영역으로 일괄 마이그레이션(`migrate_pages()`)한 뒤 슬롯을 비워 1GB HugeTLB 페이지(`struct hstate`)로 전환합니다.
   - 만약 해당 슬롯에 커널 슬랩이나 DMA 핀(`GUP: get_user_pages`) 등으로 인해 고정된 비이동 페이지(`MIGRATE_UNMOVABLE`, `unmovable_pinned > 0`)가 존재하면 마이그레이션은 즉시 `EBUSY_PAGE_PINNED`로 실패합니다.
3. **HugeTLB 오버커밋(Surplus) 및 Cgroup 제어**:
   - 정적 풀 초과 할당 시 `surplus_huge_pages`로 관리되며, 사용 종료(`free_huge_page()`) 시 풀에 보관되지 않고 즉시 CMA 영역으로 해제(`DISSOLVED_TO_CMA`)됩니다.
   - `hugetlb` cgroup 컨트롤러(`mm/hugetlb_cgroup.c`)를 통해 테넌트별 최대 사용량을 강제합니다.

본 과제에서는 리눅스 커널의 HugeTLB 1GB 자이갠틱 페이지 풀 관리, CMA 슬롯 상태 전이, 페이지 마이그레이션, 오버커밋 서플러스 수명주기, 그리고 Cgroup 한도 검증을 정밀하게 시뮬레이션하는 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------+
|                        HugeTLB Cgroup Controller (cgroups)                        |
|   [ Tenant A: max 4, cur 2 ]              [ Tenant B: max 2, cur 1 ]              |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (ALLOC_GIGANTIC_PAGE / FREE_GIGANTIC_PAGE)
+-----------------------------------------------------------------------------------+
|                       HugeTLB hstate Pool (1GB Gigantic)                          |
|                                                                                   |
|  [ Persistent Pool (free_huge_pages) ]     [ Surplus Tracker (surplus_huge_pages) ]|
|   - Reusable Boot Pages                     - Overcommit Dynamic Pages            |
|   - Returned to Pool on Free                - Dissolved to CMA on Free            |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (Need new 1GB physical slot)
+-----------------------------------------------------------------------------------+
|               Contiguous Memory Allocator (CMA) 1GB Slots Array                   |
|                                                                                   |
|  [ Slot 0: GIGANTIC ]    [ Slot 1: CMA_FREE ]    [ Slot 2: CMA_MOVABLE_OCCUPIED ] |
|   - Owned by HugeTLB      - Immediately Usable    - 262,144 Movable Pages         |
|                                                   - Target for Page Migration     |
|                                                   - Fails if Pinned/Unmovable     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (migrate_pages)
+-----------------------------------------------------------------------------------+
|             General Buddy Allocator (Evacuated Page Cache / Anon RAM)             |
+-----------------------------------------------------------------------------------+
```

---

## 3. 핵심 규칙 및 상태 전이 모델

### 3.1 슬롯 상태 및 페이지 관리
CMA 영역은 `cma_size_gb`개의 1GB 슬롯으로 분할됩니다:
- `GIGANTIC_ALLOCATED`: HugeTLB 1GB 페이지로 활성화됨.
- `CMA_FREE`: 비어 있는 연속 1GB 블록.
- `CMA_MOVABLE_OCCUPIED`: 일반 시스템 페이지 캐시가 임시 점유 중인 블록.

### 3.2 할당 파이프라인 (`ALLOC_GIGANTIC_PAGE`)
1. **Cgroup 제한 검사**:
   지정된 `cgroup_id`의 `current + 1 > max`인 경우, `ENOSPC_CGROUP_LIMIT` 반환.
2. **영구 풀(Persistent Pool) 우선 할당**:
   `free_huge_pages > 0`인 경우:
   - `free_pool`에서 페이지 1개를 꺼내 할당.
   - `free_huge_pages -= 1`, `cgroup.current += 1`.
   - `source = "PERSISTENT_POOL"`, `migrated_pages = 0`.
3. **CMA 동적 서플러스(Surplus) 할당**:
   `free_huge_pages == 0`인 경우:
   - `surplus_huge_pages >= max_overcommit_surplus`이면 `ENOMEM_SURPLUS_EXHAUSTED` 반환.
   - CMA 슬롯을 순회하여:
     - 1순위: `CMA_FREE` 슬롯 탐색.
     - 2순위: `CMA_MOVABLE_OCCUPIED` 슬롯 탐색:
       - 만약 `unmovable_pinned > 0`이면 `EBUSY_PAGE_PINNED` 반환.
       - 모두 이동 가능하면 슬롯 내의 `movable_pages`를 모두 버디 시스템으로 마이그레이션.
     - 가용 슬롯이 전혀 없으면 `ENOMEM_FRAGMENTATION` 반환.
   - 가용 슬롯을 `GIGANTIC_ALLOCATED`로 전이시키고 `surplus_huge_pages += 1`, `nr_huge_pages += 1`.
   - `source = "CMA_FREE"` 또는 `"CMA_MIGRATION"`.

### 3.3 반환 파이프라인 (`FREE_GIGANTIC_PAGE`)
1. 활성 할당 목록에서 해당 요청 해제, cgroup `current -= 1`.
2. 할당이 **서플러스(Surplus)** 페이지였던 경우:
   - HugeTLB 풀에 남기지 않고 즉시 CMA로 환원!
   - `surplus_huge_pages -= 1`, `nr_huge_pages -= 1`.
   - 슬롯 상태를 `CMA_FREE`로 전이.
   - `action = "DISSOLVED_TO_CMA"`.
3. 할당이 **영구(Persistent)** 페이지였던 경우:
   - HugeTLB 가용 풀로 반환: `free_huge_pages += 1`, `free_pool.append(page)`.
   - `action = "RETURNED_TO_POOL"`.

### 3.4 영구 페이지 해체 (`DISSOLVE_GIGANTIC_PAGE`)
- 관리자가 `/sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages` 값을 낮추는 시나리오.
- 슬롯이 `GIGANTIC_ALLOCATED`이고 현재 프로세스가 사용 중이지 않아 `free_pool`에 존재하는 경우에만 성공.
- 슬롯을 `CMA_FREE`로 전환하고 `free_huge_pages -= 1`, `nr_huge_pages -= 1`, `persistent_target -= 1`.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {
    "total_memory_gb": 64,
    "cma_size_gb": 8,
    "boot_gigantic_pages": 3,
    "max_overcommit_surplus": 2,
    "cgroup_limits": {
      "cg_db": 4
    }
  },
  "operations": [
    {"type": "QUERY_HUGETLB_INFO"},
    {"type": "ALLOC_GIGANTIC_PAGE", "req_id": "req-1", "cgroup_id": "cg_db"},
    {"type": "POPULATE_CMA_MOVABLE", "slot_id": 4, "movable_pages": 262144, "unmovable_pinned": 0},
    {"type": "FREE_GIGANTIC_PAGE", "req_id": "req-1"}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 1,
      "type": "ALLOC_GIGANTIC_PAGE",
      "status": "SUCCESS",
      "req_id": "req-1",
      "source": "PERSISTENT_POOL",
      "page_id": "boot-huge-0",
      "slot_id": 0,
      "migrated_pages": 0
    }
  ],
  "summary": {
    "total_operations": 4,
    "successful_allocations": 1,
    "failed_allocations": 0,
    "total_migrated_pages": 0,
    "final_nr_huge_pages": 3,
    "final_free_huge_pages": 3,
    "final_surplus_huge_pages": 0,
    "cgroup_usage": {
      "cg_db": {"current": 0, "max": 4}
    }
  }
}
```
