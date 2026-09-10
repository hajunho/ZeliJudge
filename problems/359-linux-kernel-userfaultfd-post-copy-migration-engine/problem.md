# Linux Kernel userfaultfd (UFFD) 유저스페이스 페이지 폴트 처리기: 포스트-카피 가상 머신 실시간 마이그레이션 & UFFDIO_COPY / ZEROPAGE / WRITEPROTECT 엔진

## 문제 설명

대규모 클라우드 인프라(AWS EC2, Google Compute Engine, OpenStack)에서 가상 머신(KVM/QEMU 게스트)을 중단 없이 다른 물리 호스트로 이동시키는 실시간 마이그레이션(Live Migration)은 유지보수와 고가용성의 핵심입니다.

그러나 인메모리 데이터베이스(Redis, SAP HANA)와 같은 고빈도 쓰기 워크로드는 네트워크 복사 속도보다 메모리 더티 발생 속도가 훨씬 빨라 기존 **사전 복사(Pre-Copy)** 방식으로는 수렴하지 못하고 마이그레이션이 무한정 지연되는 한계가 있었습니다.

이를 극복하기 위해 도입된 **포스트-카피(Post-Copy)** 마이그레이션은 CPU 레지스터와 최소 상태만 타깃 호스트로 전송한 즉시 게스트 vCPU 실행을 시작합니다. 이때 타깃 호스트의 물리 메모리에 아직 도착하지 않은 페이지에 vCPU가 접근하면 하드웨어 페이지 폴트(`#PF`)가 발생하는데, 리눅스 커널의 **`userfaultfd` (UFFD, `fs/userfaultfd.c`)**가 이를 유저 공간의 마이그레이션 관리 스레드로 트랩(Trap)하여 원격 호스트로부터 온디맨드로 페이지를 스트리밍해옵니다.

```
       [ Destination Host: Guest vCPU ]
                      │
                      ▼ (접근: 미도착 누락 페이지 / 0x70001000)
       [ Linux Kernel Memory Management (#PF) ]
                      │
                      ▼
       [ userfaultfd Kernel Framework (fs/userfaultfd.c) ]
         ├── vCPU 스레드를 wait_queue에 중단(Sleep)
         └── UFFD_EVENT_PAGEFAULT 이벤트를 생성하여 uffd 파일 디스크립터로 전달
                      │
                      ▼ (read(uffd, &msg, sizeof(msg)))
       [ QEMU Migration Manager Daemon (User Space) ]
         ├── 원격 소스 호스트로부터 4KB 페이지 데이터 수신
         └── ioctl(uffd, UFFDIO_COPY, &copy_arg) 호출
                      │
                      ▼
       [ Linux Kernel: UFFDIO_COPY 처리 ]
         ├── 목적지 PTE(Page Table Entry)에 물리 페이지 원자적 설치
         └── wait_queue에 잠들어 있던 vCPU 스레드 즉시 기상(Wakeup)!
```

본 문제는 리눅스 커널의 `userfaultfd` 서브시스템(`fs/userfaultfd.c`, `mm/userfaultfd.c`)의 **누락 페이지 트랩, 대기 큐 직렬화, UFFDIO_COPY, UFFDIO_ZEROPAGE, UFFDIO_WRITEPROTECT 및 UFFDIO_WAKE 상태 머신**을 정밀하게 에뮬레이션하는 엔진을 구현하는 것입니다.

---

## 핵심 엔진 아키텍처 및 요구사항

### 1. VMA 주소 공간 및 페이지 테이블 모델
- 관리되는 VMA는 `start_addr`부터 `start_addr + total_pages * 4096`까지 4KB 페이지 단위로 정렬됩니다.
- 각 페이지는 다음 상태를 유지합니다:
  - `present`: 물리 페이지 매핑 여부 (기본 `false`, 네트워크 도착 시 `true`).
  - `write_protected`: 쓰기 보호 활성화 여부 (`UFFDIO_WRITEPROTECT`).
  - `waiting_threads`: 해당 페이지의 메모리 공급을 기다리며 대기 중인 vCPU 스레드 큐.

### 2. 스레드 메모리 접근 (`THREAD_ACCESS`)
- 등록된 VMA 범위를 벗어난 주소 접근 시 `SEGFAULT_OUT_OF_VMA`, status: `CRASH` 처리.
- **누락 페이지 폴트 (Missing Page Fault)**:
  - `present == false`인 경우 커널은 `UFFD_EVENT_PAGEFAULT` 이벤트를 발생시키고, 해당 스레드를 페이지의 `waiting_threads` 큐에 잠재웁니다(`THREAD_SUSPENDED_IN_WAITQUEUE`).
  - 플래그는 `access_type == "WRITE"`이면 `UFFD_PAGEFAULT_FLAG_WRITE`, 그렇지 않으면 `UFFD_PAGEFAULT_FLAG_READ`.
- **쓰기 보호 폴트 (Write-Protect Fault)**:
  - `present == true`이지만 `write_protected == true`이고 `access_type == "WRITE"`인 경우 `UFFD_EVENT_PAGEFAULT_WP`, status: `WRITE_PROTECT_TRAPPED`로 스레드를 정지시킵니다.
- **정상 히트 (Hardware Fast Access)**:
  - 페이지가 존재하고 쓰기 제약이 없으면 즉시 접근 허용(`HARDWARE_FAST_ACCESS`, status: `IMMEDIATE_HIT`).

### 3. 유저스페이스 UFFD 제어 명령 (`ioctl`)
1. **`UFFDIO_COPY`**:
   - 4KB 페이지 데이터를 PTE에 원자적으로 설치(`present = true`).
   - `dont_wake == false`인 경우 해당 페이지의 `waiting_threads`에 대기 중이던 모든 vCPU 스레드를 깨워 실행을 재개시킵니다.
2. **`UFFDIO_ZEROPAGE`**:
   - 네트워크 페이로드 없이 0으로 채워진 페이지를 즉시 매핑하고, 대기 중인 스레드를 기상시킵니다.
3. **`UFFDIO_WRITEPROTECT`**:
   - 해당 페이지의 `write_protected` 플래그를 토글(`enable_wp`)하여 유저 공간 더티 페이지 추적을 활성화/비활성화합니다.
4. **`UFFDIO_WAKE`**:
   - 명시적으로 지정된 페이지에서 대기 중인 모든 스레드를 강제로 기상시킵니다.

---

## 입력 형식

JSON 문자열이 표준 입력(`stdin`)으로 주어집니다:

```json
{
  "vm_config": {
    "start_addr": 1879048192,
    "total_pages": 4
  },
  "initial_present_pages": [
    {"addr": 1879048192, "data": "BOOT_CODE"}
  ],
  "events": [
    {"type": "THREAD_ACCESS", "thread_id": "vCPU-0", "addr": 1879048192, "access_type": "READ"},
    {"type": "THREAD_ACCESS", "thread_id": "vCPU-1", "addr": 1879052288, "access_type": "READ"},
    {"type": "UFFDIO_COPY", "addr": 1879052288, "data": "NET_CHUNK_1", "dont_wake": false}
  ]
}
```

---

## 출력 형식

처리된 이벤트 로그와 UFFD 마이그레이션 메트릭을 JSON 형태로 표준 출력(`stdout`)에 공백 없이 출력합니다:

```json
{
  "engine": "linux_kernel_userfaultfd_postcopy",
  "metrics": {
    "total_pages_in_vma": 4,
    "present_pages": 2,
    "completion_pct": 50.0,
    "trapped_missing_faults": 1,
    "write_protect_faults": 0,
    "uffdio_copies": 1,
    "uffdio_zeropages": 0,
    "threads_woken": 1,
    "currently_stalled_threads": 0
  },
  "verdict": "UFFD_MISSING_PAGE_RESOLVED",
  "event_log": [
    {
      "event": "HARDWARE_FAST_ACCESS",
      "thread_id": "vCPU-0",
      "addr": "0x70000000",
      "status": "IMMEDIATE_HIT"
    },
    {
      "event": "UFFD_EVENT_PAGEFAULT",
      "flag": "UFFD_PAGEFAULT_FLAG_READ",
      "thread_id": "vCPU-1",
      "fault_page": "0x70001000",
      "status": "THREAD_SUSPENDED_IN_WAITQUEUE"
    },
    {
      "event": "UFFDIO_COPY_APPLIED",
      "page": "0x70001000",
      "status": "PTE_ATOMICALLY_INSTALLED",
      "threads_woken": ["vCPU-1"]
    }
  ]
}
```

---

## 판정 규칙 (`verdict`)

1. 모든 VMA 페이지가 로드되고(`completion_pct == 100.0`) 대기 중인 스레드가 0개인 경우:
   `"POST_COPY_MIGRATION_CONVERGED"`
2. 페이지 폴트가 트랩되었으나 모두 정상 해결되어 대기 스레드가 없는 경우:
   `"UFFD_MISSING_PAGE_RESOLVED"`
3. 대기 큐에 멈춰 있는 스레드가 남아 있는 경우:
   `"UFFD_FAULT_STALL"`
