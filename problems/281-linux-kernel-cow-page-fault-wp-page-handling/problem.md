# 문제 #281: fork() 후 10GB 메모리를 어떻게 1ms 만에 복사할까요?!: Linux Kernel mm/memory.c Copy-on-Write (CoW) 페이지 폴트(#PF), do_wp_page() 및 PageAnonExclusive 상태 머신 엔진

## 1. 개요 (Story & Context)
고성능 인메모리 데이터베이스인 Redis는 디스크 영속성을 위해 백그라운드 스냅샷(`BGSAVE` 또는 `AOF rewrite`)을 생성할 때 리눅스 표준 시스템 콜인 `fork()`를 호출합니다. 
수십 GB의 RAM을 사용하는 거대한 프로세스가 `fork()`를 호출할 때, 만약 자식 프로세스를 위해 부모 프로세스의 10GB 메모리 공간 전체를 물리적으로 진짜 복사한다면 수백 MB/s의 메모리 버스 대역폭을 소모하며 수십 초 동안 Redis 서버 전체가 멈추는 대재앙이 발생할 것입니다.

하지만 실제로 `fork()` 시스템 콜은 단 **1ms 안팎의 초고속**으로 반환됩니다! 이것이 가능한 이유는 리눅스 커널 가상 메모리 서브시스템(`mm/memory.c`, `mm/mmap.c`)의 핵심 기제인 **Copy-on-Write (CoW, 쓰기 시점 복사)** 덕분입니다:
1. **가상 메모리 복제와 쓰기 방지 (`dup_mmap`)**:
   - `fork()` 시 커널은 부모의 물리 페이지 프레임 데이터를 복사하지 않고, 가상 메모리 영역(VMA, `vm_area_struct`)과 페이지 테이블 엔트리(PTE, Page Table Entry)만을 복제합니다.
   - 이때 쓰기 가능한 사설 익명 페이지(`VM_WRITE & ~VM_SHARED`)의 PTE에서 **쓰기 권한 비트(`writable`)를 강제로 박탈하여 읽기 전용(Read-Only)으로 변경**합니다 (`pte_wrprotect`).
   - 동시에 공유되는 물리 페이지 프레임(`struct page`)의 참조 카운터(`page_count`)를 1 증가시키고, 단독 소유 플래그(`PageAnonExclusive`)를 해제합니다.
   - 따라서 부모와 자식은 동일한 물리 메모리 프레임을 평화롭게 공유하여 읽기(Read)를 수행합니다.
2. **쓰기 시점 하드웨어 페이지 폴트 (#PF, Page Fault)**:
   - 부모나 자식 프로세스 중 누군가가 해당 페이지에 데이터를 쓰려고(`PAGE_WRITE`) 시도하면, CPU MMU(Memory Management Unit)는 읽기 전용 PTE에 쓰기가 시도되었음을 감지하고 하드웨어 페이지 폴트 인터럽트(`#PF`)를 발생시킵니다.
   - 리눅스 커널의 페이지 폴트 핸들러 `handle_mm_fault()`는 `do_wp_page()`(Write-Protect Page Fault)를 호출하여 CoW를 해결합니다.
3. **`do_wp_page()`의 3대 핵심 분기**:
   - **분기 A: Zero-Page 분리 (`COW_ZERO_PAGE_BREAK`)**: 읽기 전용으로 공유되던 전역 전용 0번 제로 페이지(`ZERO_PAGE`, PFN 0)에 쓰기가 발생한 경우, 새로운 물리 프레임을 할당받아 0으로 초기화한 뒤 쓰기를 적용하고 PTE를 교체합니다.
   - **분기 B: 단독 소유 페이지 재사용 (`COW_REUSE_PAGE_NO_COPY`)**: 다른 프로세스가 이미 CoW를 격파했거나 종료하여 현재 물리 페이지의 참조 카운터가 1(`page_count == 1`)인 경우, **새로운 물리 메모리를 할당하거나 데이터를 복사할 필요가 전혀 없습니다!** 기존 프레임에 쓰기 권한 비트를 다시 켜고(`pte_mkwrite`), `PageAnonExclusive` 플래그를 설정하여 0-알로케이션으로 즉시 쓰기를 완료합니다.
   - **분기 C: 공유 페이지 복제 분리 (`COW_ALLOC_AND_COPY`)**: 다른 프로세스와 여전히 물리 페이지를 공유 중(`page_count > 1`)인 경우, 버디 할당자에서 새 물리 프레임을 할당받고 기존 페이지 데이터를 복사(`copy_user_highpage`)한 뒤 쓰기를 반영합니다. 기존 물리 페이지의 참조 카운터는 1 감소합니다.

여러분은 리눅스 커널 가상 메모리 서브시스템의 코어 커널 엔지니어로서, `mm/memory.c`의 `do_wp_page` 수명 주기와 참조 카운팅, 제로 페이지 분리 및 배타적 재사용 최적화를 완벽히 모의하는 **Linux Kernel CoW Page Fault Engine**을 구현해야 합니다!

---

## 2. 상태 머신 및 연산 규칙

### 2.1 가상 메모리 및 물리 프레임 상태
1. **물리 메모리 관리자 (`PhysicalMemory`)**:
   - 총 `max_physical_frames`개의 물리 페이지 프레임 번호(PFN, Page Frame Number)를 관리합니다.
   - PFN 0은 전역 읽기 전용 익명 페이지인 `ZERO_PAGE`로 예약되며, 참조 카운터는 무한대(해제 불가)입니다.
   - 일반 물리 프레임(PFN $\ge 1$)은 `refcount` (참조 프로세스 수), `anon_exclusive` (단독 소유 여부), `data` (오프셋별 저장 값 딕셔너리)를 갖습니다.
   - 미할당 프레임은 오름차순(가장 작은 번호 우선)으로 재사용됩니다.
2. **프로세스 주소 공간 (`Process`)**:
   - VMA 리스트: `[{"start": vpn_start, "end": vpn_end, "flags": ["READ", "WRITE"]}]`
   - 페이지 테이블: 가상 페이지 번호(VPN, Virtual Page Number) $	o$ `PTE`:
     - `present`: 매핑 존재 여부 (True/False)
     - `pfn`: 매핑된 물리 프레임 번호
     - `writable`: 쓰기 가능 여부 (True/False)
     - `dirty`: 변경 발생 여부 (True/False)

### 2.2 연산 규칙 (`operations`)
1. `PROCESS_CREATE`:
   - 주어진 `pid`로 새 프로세스를 생성합니다. `status: "CREATED"`.
2. `MMAP_ANONYMOUS`:
   - `vpn_start`부터 `vpn_end` 직전까지의 범위에 대해 지정된 `flags`를 갖는 VMA를 등록합니다. Demand Paging에 따라 초기에는 페이지 테이블 매핑이 비어 있습니다. `status: "MAPPED"`.
3. `FORK`:
   - `parent_pid`의 모든 VMA와 매핑된 PTE를 `child_pid`로 복제합니다.
   - 부모의 VMA 중 `"WRITE"` 권한을 가진 영역의 모든 존재하는 PTE에 대해 `writable = False`를 적용(`pte_wrprotect`)합니다.
   - 매핑된 물리 프레임(PFN $
e 0$)의 `refcount`를 $+1$하고, `anon_exclusive = False`로 설정합니다.
   - 자식의 PTE 역시 `writable = False`로 설정하여 복제합니다.
   - `status: "FORK_COMPLETED"`, `wrprotected_pages` 수를 로그에 기록합니다.
4. `PAGE_READ`:
   - 지정된 VPN과 오프셋의 값을 읽습니다.
   - VMA가 없거나 `"READ"` 플래그가 없으면 세그멘테이션 폴트: `status: "SIGSEGV_READ_VIOLATION"`, `sigsegv_violations` $+1$.
   - 매핑되지 않은(`present == False`) 경우: 요구 페이징(Demand Zero-Page)에 의해 PFN 0(`ZERO_PAGE`)에 읽기 전용(`writable = False`)으로 매핑합니다. `total_page_faults` $+1$, `demand_page_faults` $+1$, `status: "DEMAND_ZERO_PAGE_MAP"`, 반환 값은 0.
   - 매핑된 경우: 물리 프레임의 오프셋 값을 읽어 반환합니다. `status: "READ_SUCCESS"`.
5. `PAGE_WRITE`:
   - 지정된 VPN과 오프셋에 `val`을 씁니다.
   - VMA가 없거나 `"WRITE"` 플래그가 없으면 세그멘테이션 폴트: `status: "SIGSEGV_WRITE_VIOLATION"`, `sigsegv_violations` $+1$.
   - **미매핑 상태 (`present == False`)**:
     - 첫 쓰기 요구 페이징: 새 물리 프레임 할당, 오프셋에 쓰기, `writable=True`, `dirty=True`, `status: "DEMAND_PAGE_ALLOC_WRITE"`, `total_page_faults` $+1$, `demand_page_faults` $+1$.
   - **매핑됨 & 쓰기 가능 (`writable == True`)**:
     - Fast Path: 하드웨어 페이지 폴트 없이 물리 프레임에 직접 쓰기, `dirty=True`, `status: "FAST_PATH_WRITE_NO_FAULT"`.
   - **매핑됨 & 쓰기 보호 (`writable == False`) $	o$ COW PAGE FAULT (`do_wp_page`)**:
     - `total_page_faults` $+1$.
     - `old_pfn == 0` (Zero-Page): 새 물리 프레임 할당, 쓰기, PTE 갱신 (`writable=True`, `dirty=True`), `cow_zero_page_breaks` $+1$, `status: "COW_ZERO_PAGE_BREAK"`.
     - `old_pfn`의 `refcount == 1`: 단독 소유 프레임이므로 재사용! 새 할당/복사 없이 기존 프레임에 쓰기, `anon_exclusive=True`, `writable=True`, `dirty=True`, `cow_page_reuses` $+1$, `status: "COW_REUSE_PAGE_NO_COPY"`.
     - `old_pfn`의 `refcount > 1`: 새 물리 프레임 할당, 구 프레임의 데이터를 새 프레임으로 복사 후 오프셋 쓰기, 구 프레임 `refcount` $-1$ (만약 구 프레임의 새 refcount가 1이면 구 프레임 `anon_exclusive=True`), 새 프레임 `anon_exclusive=True`, PTE 갱신, `cow_alloc_copies` $+1$, `status: "COW_ALLOC_AND_COPY"`.
6. `PROCESS_EXIT`:
   - 프로세스가 종료됩니다. 해당 프로세스의 모든 매핑된 물리 프레임(PFN $
e 0$)의 `refcount`를 1씩 감소시킵니다.
   - 만약 감소 후 `refcount == 0`이 되면 해당 물리 프레임을 해제(`free_frame`)하여 재사용 풀로 반환합니다.
   - 만약 감소 후 `refcount == 1`이 되면 남은 소유자의 프레임을 `anon_exclusive = True`로 승격합니다.
   - 프로세스 객체를 소멸시킵니다. `status: "EXIT_RESOURCES_FREED"`.

---

## 3. 입력 형식 (Input Specification)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "system": {
    "max_physical_frames": 16
  },
  "operations": [
    {"step": 1, "op": "PROCESS_CREATE", "pid": 10},
    {"step": 2, "op": "MMAP_ANONYMOUS", "pid": 10, "vpn_start": 0, "vpn_end": 4, "flags": ["READ", "WRITE"]},
    {"step": 3, "op": "PAGE_WRITE", "pid": 10, "vpn": 1, "offset": 0, "val": 100},
    {"step": 4, "op": "FORK", "parent_pid": 10, "child_pid": 11},
    {"step": 5, "op": "PAGE_READ", "pid": 11, "vpn": 1, "offset": 0},
    {"step": 6, "op": "PAGE_WRITE", "pid": 11, "vpn": 1, "offset": 0, "val": 200}
  ]
}
```

---

## 4. 출력 형식 (Output Specification)
표준 출력(stdout)으로 연산 진행 로그, 집계 통계, 최종 활성 물리 프레임 수 및 할당된 PFN 목록을 포함하는 JSON 객체를 한 줄로 출력합니다:
```json
{
  "operations_log": [
    {"step": 1, "op": "PROCESS_CREATE", "pid": 10, "status": "CREATED"},
    {"step": 2, "op": "MMAP_ANONYMOUS", "pid": 10, "vpn_range": [0, 4], "status": "MAPPED"},
    {"step": 3, "op": "PAGE_WRITE", "pid": 10, "vpn": 1, "new_pfn": 1, "status": "DEMAND_PAGE_ALLOC_WRITE"},
    {"step": 4, "op": "FORK", "parent_pid": 10, "child_pid": 11, "wrprotected_pages": 1, "status": "FORK_COMPLETED"},
    {"step": 5, "op": "PAGE_READ", "pid": 11, "vpn": 1, "pfn": 1, "val": 100, "status": "READ_SUCCESS"},
    {"step": 6, "op": "PAGE_WRITE", "pid": 11, "vpn": 1, "old_pfn": 1, "new_pfn": 2, "status": "COW_ALLOC_AND_COPY"}
  ],
  "statistics": {
    "total_page_faults": 2,
    "cow_alloc_copies": 1,
    "cow_page_reuses": 0,
    "cow_zero_page_breaks": 0,
    "demand_page_faults": 1,
    "sigsegv_violations": 0
  },
  "active_physical_pages": 2,
  "allocated_pfns": [1, 2]
}
```
