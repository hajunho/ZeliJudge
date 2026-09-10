# 리눅스 커널 HugeTLB 자이갠틱 페이지(1GB) 및 CMA 아키텍처 이론

## 1. 하드웨어 메모리 가상화와 1GB PUD 매핑

현대 x86-64 아키텍처의 4단계 페이징(4-Level Paging) 구조:
- **CR3**: PGD (Page Global Directory, 512 엔트리, 512GB 커버)
- **Level 3**: PUD (Page Upper Directory, 512 엔트리, 1GB 커버)
- **Level 2**: PMD (Page Middle Directory, 512 엔트리, 2MB 커버)
- **Level 1**: PTE (Page Table Entry, 512 엔트리, 4KB 커버)

전통적인 4KB 매핑에서는 가상 주소를 물리 주소로 변환하기 위해 4번의 메모리 접근(Memory Reference)이 발생합니다.
반면 PUD 엔트리의 **Page Size(PS) 비트(Bit 7)**를 1로 설정하면, PMD와 PTE 단계를 완전히 건너뛰고 PUD 레벨에서 즉시 1GB 물리 프레임으로 직결됩니다:
$$\text{Virtual Address}[29:0] \implies \text{Physical Offset within 1GB Page}$$

이로 인해:
1. **D-TLB 효율 극대화**: 단 64개의 TLB 엔트리로 64GB 메모리를 100% 캐싱 가능.
2. **페이지 테이블 메모리 절감**: 1GB 매핑당 PMD/PTE 테이블 513개(약 2MB 이상의 커널 메타데이터) 절약.
3. **TLB Shootdown 인터럽트 제거**: 멀티코어 환경에서 메모리 해제 시 발생하는 IPI(Inter-Processor Interrupt) 폭풍 극적 완화.

---

## 2. Order-18의 저주와 버디 할당자의 물리적 한계

리눅스 커널의 물리 메모리 관리자(Buddy Allocator, `mm/page_alloc.c`)는 $2^{\text{order}}$ 크기의 연속된 블록 단위로 메모리를 관리합니다:
- Order 0: 4 KB
- Order 9: 2 MB
- Order 10: 4 MB (`MAX_ORDER - 1` 기본값)
- ...
- **Order 18**: $2^{18} \times 4\,\text{KB} = 1\,\text{GB}$

리눅스 커널의 `free_area[]` 배열은 기본적으로 Order 10까지만 배열 인덱스를 할당합니다.
설령 커널 설정(`CONFIG_FORCE_MAX_ZONEORDER`)을 변경하여 Order 18을 지원하도록 컴파일하더라도, 시스템이 가동된 지 수 분만 지나면 시스템 메모리는 페이지 캐시, 커널 dentry/inode 슬랩, 유저 익명 페이지로 파편화(External Fragmentation)되어 262,144개의 연속된 빈 프레임이 자연적으로 존재할 확률은 수학적으로 0에 가깝습니다.

---

## 3. CMA (Contiguous Memory Allocator)의 핵심 원리

CMA(`mm/cma.c`)는 임베디드 멀티미디어(4K/8K 카메라 센서, DSP DMA) 및 엔터프라이즈 HugeTLB를 위해 고안된 하이브리드 예약 메커니즘입니다:

### 3.1 이중 마이그레이션 타입 (`MIGRATE_CMA`)
- CMA 영역으로 지정된 페이지 프레임들은 버디 할당자에서 특별한 마이그레이션 타입인 `MIGRATE_CMA`로 태깅됩니다.
- 일반적인 메모리 할당 요청 중 **이동 가능한 메모리(`GFP_HIGHUSER_MOVABLE`, Page Cache, Anonymous)**만이 이 영역에 할당될 수 있습니다.
- 절대 이동할 수 없는 커널 슬랩(`kmalloc`, `kmem_cache`)이나 커널 스택, 페이지 테이블 등 `MIGRATE_UNMOVABLE` 요청은 CMA 영역에 절대 할당되지 않습니다.

### 3.2 런타임 연속성 복구 (`cma_alloc()`)
1GB 연속 블록이 요청되면:
1. **범위 격리(Pageblock Isolation)**: 대상 1GB 영역을 `MIGRATE_ISOLATE`로 전환하여 새로운 할당 요청이 들어오지 못하도록 차단합니다.
2. **LRU 분리 및 이동(`migrate_pages()`)**: 슬롯 내에 존재하는 모든 이동 가능 페이지를 스캔하여 일반 시스템 메모리의 빈 공간으로 복사하고, 프로세스의 PTE를 새로운 주소로 리매핑합니다.
3. **핀된 페이지(`Pinned Page`) 방어**: 만약 디바이스 드라이버가 Direct I/O를 위해 `get_user_pages()`를 호출하여 페이지 참조 카운트(`_refcount`)를 증가시켰거나 버퍼 락(`lock_page`)을 걸고 있다면 마이그레이션이 불가능하므로, CMA는 `EBUSY`를 반환하고 다른 슬롯을 탐색합니다.

---

## 4. HugeTLB 수명주기 및 Cgroup 회계

리눅스 커널의 `struct hstate` 구조체는 자이갠틱 페이지 풀을 다음 변수들로 추적합니다:
- `nr_huge_pages`: 시스템에 존재하는 총 자이갠틱 페이지 수.
- `free_huge_pages`: 프로세스에 매핑되지 않고 풀에 대기 중인 페이지 수.
- `surplus_huge_pages`: 관리자가 지정한 정적 예약치를 초과하여 CMA에서 임시로 끌어다 쓴 동적 초과 페이지 수.

### 4.1 반환 시의 차별화된 동작 (`free_huge_page()`)
```c
if (h->surplus_huge_pages) {
    /* Surplus 페이지는 메모리 낭비를 막기 위해 즉시 CMA로 해체 */
    destroy_compound_gigantic_page(page, order);
    cma_release(cma, page, 1 << order);
    h->surplus_huge_pages--;
    h->nr_huge_pages--;
} else {
    /* 영구 예약 페이지는 재사용을 위해 풀의 프리 리스트에 반환 */
    enqueue_huge_page(h, page);
    h->free_huge_pages++;
}
```

### 4.2 Cgroup 강제 정책 (`mm/hugetlb_cgroup.c`)
멀티테넌트 쿠버네티스 노드나 가상화 호스트에서 특정 데이터베이스 컨테이너가 1GB 페이지를 독점하여 호스트 전체의 OOM을 유발하지 않도록, `cgroup v2`의 `hugetlb.1GB.max` 및 `hugetlb.1GB.current` 인터페이스를 통해 서브시스템 레벨에서 엄격한 상한선을 강제합니다.
