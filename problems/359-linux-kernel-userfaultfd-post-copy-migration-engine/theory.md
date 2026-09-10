# Linux Kernel userfaultfd (UFFD)와 포스트-카피 라이브 마이그레이션 이론

## 1. 가상 머신 실시간 마이그레이션의 진화: Pre-Copy vs Post-Copy

가상 머신(KVM/QEMU)의 무중단 실시간 마이그레이션은 클라우드 인프라 유지보수의 핵심 기술입니다:

### 1.1 사전 복사 (Pre-Copy Migration)
1. 게스트 vCPU가 소스 호스트에서 계속 실행되는 동안 전체 메모리를 타깃 호스트로 반복 복사합니다.
2. 각 라운드마다 게스트가 수정한 **더티 페이지(Dirty Pages)**를 추적(Dirty Logging)하여 재전송합니다.
3. **한계점 (The Thrashing Problem)**:
   - 메모리 쓰기 빈도가 높은 데이터베이스(Redis, MySQL, SAP HANA)는 네트워크 대역폭보다 메모리 갱신 속도가 빨라 영원히 수렴하지 못하고 마이그레이션이 실패하거나 다운타임이 수 분 이상 치솟습니다.

### 1.2 사후 복사 (Post-Copy Migration)
1. 소스 호스트에서 vCPU를 일시 정지하고, CPU 레지스터와 디바이스 상태만 타깃으로 전송한 즉시 타깃 호스트에서 vCPU를 재개합니다 (다운타임 < 10ms).
2. 타깃 호스트의 물리 메모리는 아직 비어 있는 상태입니다.
3. 게스트가 메모리에 접근할 때 아직 전송되지 않은 페이지라면 하드웨어 페이지 폴트(`#PF`)가 발생하며, 이를 **`userfaultfd`**를 통해 가로채 원격 소스 호스트로부터 온디맨드로 실시간 페이징(Demand Paging)합니다.

---

## 2. userfaultfd 커널 아키텍처 (`fs/userfaultfd.c`)

전통적인 리눅스 커널에서 유효하지 않은 가상 메모리 접근은 `SIGSEGV` 시그널로 프로세스를 종료시켰습니다.
Andrea Arcangeli에 의해 도입된 `userfaultfd` 시스템 콜은 유저 공간 프로세스가 특정 VMA 영역의 페이지 폴트를 독점적으로 수신하고 처리할 수 있도록 개방했습니다:

```c
int uffd = syscall(__NR_userfaultfd, O_CLOEXEC | O_NONBLOCK);
```

### 2.1 등록 모드 (Registration Modes)
- `UFFDIO_REGISTER_MODE_MISSING`: 매핑되지 않은 누락 페이지 접근을 감지 (Post-Copy 마이그레이션의 핵심).
- `UFFDIO_REGISTER_MODE_WP`: 쓰기 보호된 페이지에 대한 쓰기 시도를 감지 (Copy-on-Write 및 유저스페이스 더티 트래킹).
- `UFFDIO_REGISTER_MODE_MINOR`: shmem/hugetlbfs 파일 백업 메모리 영역의 매핑 제어.

### 2.2 커널 대기 큐 (Wait Queue) 메커니즘
1. 게스트 vCPU 스레드가 미할당 페이지 주소 $A$에 접근하면 MMU가 `#PF` 예외를 발생시킵니다.
2. 아키텍처 독립적 폴트 핸들러 `handle_mm_fault()` $ightarrow$ `handle_userfault()`로 진입합니다.
3. 커널은 `struct uffd_msg` 구조체에 폴트 발생 주소, vCPU 스레드 ID, 읽기/쓰기 플래그를 채우고 UFFD 이벤트 큐에 인큐합니다.
4. 폴트를 일으킨 vCPU 스레드는 커널 대기 큐(`wait_queue_head_t`)에 `TASK_KILLABLE` 상태로 블록(Sleep)됩니다.

---

## 3. UFFD ioctl 제어 명령어와 원자적 PTE 조작

유저 공간의 마이그레이션 데몬은 `poll()` 또는 `epoll()`을 통해 UFFD 파일 디스크립터에서 폴트 이벤트를 읽은 후 다음 ioctl 명령으로 해결합니다:

```c
/* 1. UFFDIO_COPY: 원격에서 수신한 메모리 데이터를 대상 주소에 원자적으로 설치 */
struct uffdio_copy copy_arg = {
    .dst = fault_addr,
    .src = (unsigned long)network_buffer,
    .len = PAGE_SIZE,
    .mode = 0 // or UFFDIO_COPY_MODE_DONTWAKE
};
ioctl(uffd, UFFDIO_COPY, &copy_arg);
```

- **PTE 원자적 설치 (`mm/userfaultfd.c`)**:
  - `mmap_read_lock()`을 획득하고, 슬랩에서 새로운 `struct page`를 할당한 뒤 유저 공간 버퍼를 복사합니다.
  - 페이지 테이블 락(`pte_lockptr`) 하에서 대상 PTE에 물리 PFN을 원자적으로 바인딩하고 캐시/TLB를 플러시합니다.
  - `wake_up()`을 호출하여 대기 큐에 잠들어 있던 vCPU 스레드를 즉시 기상시킵니다. vCPU는 자신이 잠들었던 사실조차 모른 채 하드웨어 인스트럭션을 원활히 재실행합니다.

- **`UFFDIO_ZEROPAGE`**:
  - 데이터 전송 없이 커널의 전역 `ZERO_PAGE`를 직접 매핑하여 물리 메모리 할당 및 네트워크 I/O 오버헤드를 0으로 절감합니다.

- **`UFFDIO_WRITEPROTECT`**:
  - PTE의 `_PAGE_RW` 비트를 제거하여 페이지를 쓰기 보호 상태로 변경하거나 해제합니다. 스냅샷 생성 및 증분 백업에 활용됩니다.

---

## 4. 포스트-카피의 위험성과 고가용성 설계

- **단점 및 위험성 (The Catastrophic Failure Mode)**:
  - 사전 복사(Pre-copy) 도중 네트워크가 끊어지면 소스 호스트의 원본 VM이 온전히 남아 있으므로 마이그레이션을 취소하고 계속 서비스할 수 있습니다.
  - 그러나 사후 복사(Post-copy) 도중 네트워크 파티션이 발생하면, 메모리의 일부는 소스에 있고 일부는 타깃에 분산되어 있어 **가상 머신 전체가 복구 불가능한 메모리 손상(Kernel Panic / Data Corruption)**에 직면합니다.
- **실무 대응책**:
  - 100Gbps 전용 이중화 네트워크 본딩(LACP).
  - 사전 복사로 80~90%의 비활성 페이지를 미리 전송한 뒤 남은 10%에 대해서만 포스트-카피로 전환하는 **하이브리드 마이그레이션(Hybrid Pre-copy + Post-copy)** 기법 채택.

---

## 5. 최신 컨테이너 및 CXL 메모리 풀링에의 응용

1. **CRIU (Checkpoint/Restore In Userspace)**:
   - 컨테이너(Docker, Podman)를 원격 노드로 즉시 순간이동시키고, 대용량 힙 메모리는 UFFD를 통해 백그라운드로 지연 로딩(Lazy Restore)합니다.
2. **CXL 원격 디스애그리게이트 메모리 (CXL Disaggregated Memory)**:
   - CXL 패브릭으로 연결된 원격 공유 메모리 풀을 로컬 가상 주소 공간으로 노출하고, UFFD를 이용하여 캐시 미스 시 온디맨드로 페이지를 스왑인하는 차세대 분산 메모리 아키텍처에 핵심적으로 활용됩니다.
