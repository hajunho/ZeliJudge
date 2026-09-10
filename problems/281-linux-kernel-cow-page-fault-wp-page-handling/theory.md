# 이론적 배경: 리눅스 커널 가상 메모리 아키텍처, Copy-on-Write (CoW) 및 PageAnonExclusive 최적화

## 1. 전통적인 프로세스 생성의 딜레마와 CoW의 탄생

### 1.1 초기 유닉스의 메모리 복사 병목
초기 유닉스(Unix v6/v7)에서 `fork()` 시스템 콜은 부모 프로세스의 모든 물리 메모리 페이지를 자식 프로세스에게 일대일로 전부 복제(Deep Copy)했습니다.
- 부모가 1GB의 메모리를 사용하고 있다면, `fork()` 한 번에 1GB의 물리 메모리를 새로 할당하고 전체 메모리 복사를 마칠 때까지 부모 프로세스는 CPU를 빼앗긴 채 블로킹(Blocking)되었습니다.
- 더 심각한 문제는 대다수의 유닉스 프로그램이 `fork()` 직후 새로운 바이너리를 실행하기 위해 곧바로 `execve()` 시스템 콜을 호출한다는 점이었습니다.
- `execve()`가 호출되면 방금 힘들게 복사한 1GB의 물리 메모리는 1밀리초도 쓰이지 못한 채 통째로 파기(Free)되었습니다. 이는 엄청난 메모리 버스 대역폭 낭비와 CPU 사이클 낭비였습니다.

### 1.2 지연 평가(Lazy Evaluation)와 Copy-on-Write
1980년대 BSD와 마하(Mach) 커널, 그리고 리눅스는 가상 메모리 페이징 하드웨어(MMU)의 특성을 활용한 **Copy-on-Write (쓰기 시점 복사)** 기법을 도입했습니다:
- `fork()` 시점에는 물리 메모리를 복사하지 않고, 가상 메모리 테이블(PTE)만 복사합니다 ($O(1)$에 수렴).
- 두 프로세스가 동일한 물리 메모리 프레임을 가리키도록 설정하되, PTE의 `W`(Writable) 비트를 꺼서 읽기 전용으로 잠급니다.
- 어느 한쪽이 실제로 메모리를 수정할 때만 하드웨어 페이지 폴트 인터럽트를 발생시켜 해당 4KB 페이지 1개만 복사합니다.

---

## 2. 리눅스 커널 가상 메모리 서브시스템 구조

### 2.1 VMA (`struct vm_area_struct`)와 권한 계층
리눅스에서 프로세스의 메모리 맵(`mm_struct`)은 연속된 가상 주소 구간인 VMA의 레드-블랙 트리(RB-Tree) 및 연결 리스트로 관리됩니다:
- `vm_flags`: VMA 수준의 소프트웨어 정책 권한 (`VM_READ`, `VM_WRITE`, `VM_EXEC`, `VM_SHARED`, `VM_MAYWRITE`).
- `PTE` 권한: CPU MMU 하드웨어가 직접 검사하는 비트 플래그 (`_PAGE_PRESENT`, `_PAGE_RW`, `_PAGE_USER`, `_PAGE_DIRTY`, `_PAGE_ACCESSED`).
- **권한의 괴리(Duality)**:
  - CoW 상태에서는 VMA 수준에서는 분명히 쓰기가 허용되어 있지만(`VM_WRITE` 켜짐), 하드웨어 PTE 수준에서는 쓰기가 금지(`_PAGE_RW` 꺼짐)되어 있습니다.
  - 쓰기 시도 시 CPU는 MMU 수준에서 실패하여 페이지 폴트(#PF)를 일으키고, 커널은 VMA의 `VM_WRITE` 플래그를 확인하여 "정상적인 CoW 상황"임을 판정하고 복사 루틴으로 진입합니다. 만약 VMA에도 `VM_WRITE`가 없다면 즉시 사용자 프로세스에 `SIGSEGV` 시그널을 전달합니다.

### 2.2 `struct page`와 참조 카운팅 (`_refcount` / `_mapcount`)
리눅스 커널에서 시스템의 모든 4KB 물리 메모리 프레임은 `struct page` 구조체로 표현됩니다:
- `page_count(page)`: 이 물리 페이지 프레임을 참조하고 있는 커널/유저 공간의 총 참조 카운터.
- `page_mapcount(page)`: 이 물리 페이지 프레임이 프로세스들의 페이지 테이블(PTE)에 매핑된 총 횟수.
- `fork()` 시 공유되는 익명 페이지의 `page_count`가 1씩 증가합니다.
- CoW가 발생하여 복제가 완료되거나, 프로세스가 `exit()`하여 PTE가 해제되면 `page_count`가 1 감소합니다.

---

## 3. `mm/memory.c`: `do_wp_page()`의 핵심 메커니즘

하드웨어 쓰기 보호 예외가 발생하면 커널은 `do_wp_page()` 함수를 실행합니다:

### 3.1 Zero-Page 특수 처리 (`is_zero_pfn`)
리눅스는 메모리 절약을 위해 `malloc()`이나 익명 `mmap()` 후 처음으로 읽기만 수행하는 가상 페이지들을 물리 메모리의 단일 전역 전용 페이지인 `ZERO_PAGE`로 매핑합니다.
- `ZERO_PAGE`는 내용이 모두 0으로 채워진 읽기 전용 물리 페이지입니다.
- 프로세스가 이 페이지에 쓰기를 시도하면 `do_wp_page`는 `ZERO_PAGE`의 참조 카운트를 건드리지 않고, 새로운 물리 페이지를 할당받아 0으로 초기화한 뒤 쓰기 값을 적용하고 PTE를 새로운 PFN으로 교체합니다.

### 3.2 배타적 단독 소유권 최적화 (`PageAnonExclusive` / Linux 5.16+)
과거 리눅스 커널에는 유명한 **Dirty CoW (CVE-2016-5195)** 취약점이 존재했습니다. `ptrace`나 `get_user_pages()`(GUP)와 `madvise(MADV_DONTNEED)` 간의 경쟁 상태로 인해 읽기 전용 사설 매핑이 오염되는 결함이었습니다.
이 문제를 영구 해결하고 CoW 오버헤드를 극적으로 줄이기 위해 리눅스 5.16 커널(David Hildenbrand 주도)에서는 **`PageAnonExclusive`** 플래그가 도입되었습니다:
- 물리 페이지가 오직 단 1개의 프로세스 페이지 테이블에만 배타적으로 매핑되어 있을 때 `PageAnonExclusive`가 참이 됩니다.
- `do_wp_page()`에 진입했을 때 `page_count(page) == 1`이면, 이 페이지를 공유하는 다른 프로세스가 전혀 없음을 100% 확신할 수 있습니다.
- 따라서 **새로운 물리 메모리를 할당할 필요도 없고(`alloc_page` 불필요), 4KB 메모리를 복사할 필요도 없이(`copy_user_highpage` 불필요)** 즉시 기존 PTE의 쓰기 비트(`_PAGE_RW`)를 켜고 `PageAnonExclusive`를 설정하여 반환합니다.
- 이 최적화 덕분에 부모 프로세스는 자식이 CoW를 한 번 깨고 나면 이후의 모든 쓰기에서 0-알로케이션으로 초고속 실행을 이어갈 수 있습니다.

### 3.3 TLB 플러시와 동시성 제어
- CoW가 일어나 PTE가 변경되면, CPU 코어의 가상 주소 변환 캐시인 **TLB(Translation Lookaside Buffer)**에 남아있는 구 변환 정보를 무효화하기 위해 `flush_tlb_page(vma, address)`를 반드시 호출해야 합니다.
- 다중 스레드 환경에서 동일 페이지에 대한 동시 CoW 폴트를 방지하기 위해 페이지 테이블 락(`pte_lockptr(mm, pmd)`)을 획득한 상태에서 PTE 검사와 갱신이 원자적으로 수행됩니다.
