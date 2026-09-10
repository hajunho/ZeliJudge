# 402: 리눅스 커널 메모리 관리 — userfaultfd 포스트 카피(Post-Copy) 실시간 마이그레이션 및 사용자 공간 온디맨드 페이징 엔진

## 1. 개요 (Overview)

클라우드 데이터센터에서 대규모 엔터프라이즈 가상 머신(VM)을 실시간으로 이전할 때, 소스 호스트에서 대상 호스트로 메모리를 먼저 전송하는 **프리 카피(Pre-Copy)** 방식은 쓰기 빈도가 극도로 높은 워크로드(대규모 트랜잭션 DB, 인메모리 캐시 등)에서 수렴(Convergence)하지 못하고 마이그레이션이 무한정 지연되는 치명적인 문제가 발생합니다.

이 수렴성 한계를 극복하기 위한 해법이 바로 **포스트 카피(Post-Copy Live Migration)** 입니다:
- VM의 CPU 레지스터 상태만 복사한 후, 대상(Target) 호스트에서 게스트 VM의 실행을 **즉시 재개**합니다.
- 대상 호스트에서 vCPU가 아직 네트워크를 통해 도착하지 않은 미전송 메모리 페이지에 접근하면 하드웨어 페이지 폴트(`#PF`)가 발생합니다.
- 전통적으로 페이지 폴트는 커널 내부에서만 처리할 수 있어 프로세스가 중단되거나 `SIGBUS` 크래시가 발생하지만, **userfaultfd (`fs/userfaultfd.c`)** 서브시스템은 커널이 이 페이지 폴트를 가로채(Trap) 사용자 공간(QEMU 등)의 마이그레이션 데몬에 전달할 수 있게 해줍니다.

사용자 공간 데몬은 소스 호스트로부터 네트워크로 해당 누락 페이지를 긴급 요청하여 수신한 뒤, **`ioctl(uffd, UFFDIO_COPY)`** 시스템 콜을 호출하여 커널에 페이지를 주입(Inject)하고 대기 중이던 vCPU를 즉시 깨워(Wakeup) 실행을 지속시킵니다.
나아가 **`UFFDIO_WRITEPROTECT`** 기능을 통해 사용자 공간에서 쓰기 보호 및 CoW(Copy-on-Write) 트래킹을 무잠금으로 수행할 수 있습니다.

본 문제에서는 리눅스 커널 `userfaultfd`의 누락 페이지 폴트 가로채기, 스레드 대기 큐 관리, `UFFDIO_COPY`를 통한 메모리 주입 및 스레드 일괄 기상, `UFFDIO_ZEROPAGE` 매핑, `UFFDIO_WRITEPROTECT` 쓰기 보호 트랩 및 해제 엔진을 설계 및 구현합니다.

---

## 2. userfaultfd 포스트 카피 아키텍처 다이어그램

```
+========================================================================================+
|                        Target Host Linux Kernel (handle_mm_fault)                      |
|                                                                                        |
|  [Guest vCPU Thread]                                                                   |
|  - Reads 0x10000 -> Page is MISSING!                                                  |
|  - Page Fault (#PF) trapped by userfaultfd handler                                     |
|  - vCPU suspended & appended to page.waiting_threads                                   |
|                          ||                                                            |
|                          || (Sends UFFD_EVENT_PAGEFAULT message)                       |
|                          VV                                                            |
+========================================================================================+
|                     Target User-Space Hypervisor (QEMU / userfaultfd)                  |
|                                                                                        |
|  1. poll(uffd) returns POLLIN -> Read faulting address (0x10000)                       |
|  2. Send high-priority TCP request to Source Host: "Need Page 0x10000 NOW!"            |
|  3. Receive 4KB page data over network stream                                          |
|  4. Execute ioctl(uffd, UFFDIO_COPY, dst=0x10000, data, wake=true)                     |
+========================================================================================+
                          ||                                                            |
                          || (Injects page & executes wake_up)                          |
                          VV                                                            |
+========================================================================================+
|  Kernel maps page as PRESENT -> Wakes up all threads waiting on 0x10000!               |
|  Guest vCPU resumes execution at zero-latency DRAM speed!                              |
+========================================================================================+
```

---

## 3. 핵심 수리 및 알고리즘 규칙

### 3.1 페이지 슬롯 상태 머신
각 4KB 페이지는 다음 3가지 상태를 가집니다:
- `MISSING`: 대상 호스트에 아직 도착하지 않은 상태. 접근 시 유저폴트 발생.
- `PRESENT`: 데이터가 수신되어 물리 메모리에 매핑된 정상 상태.
- `WP` (Write-Protected): 사용자 공간에 의해 쓰기 보호된 상태. 읽기는 허용되나 쓰기 시 유저폴트 발생.

### 3.2 페이지 폴트 트랩 (`FAULT`)
- 접근 주소가 등록 범위 밖이면 `SIGSEGV_OUT_OF_BOUNDS` 반환.
- `page.state == "MISSING"`:
  - `page_faults_missing` 카운터 증가.
  - `fault_queue`에 기록 및 `page.waiting_threads`에 해당 스레드 등록.
  - `TRAPPED_USERFAULT_MISSING` 반환.
- `page.state == "WP"` AND `access_type == "WRITE"`:
  - `page_faults_wp` 카운터 증가.
  - `fault_queue`에 기록 및 `page.waiting_threads`에 스레드 등록.
  - `TRAPPED_USERFAULT_WP` 반환.
- 그 외(정상 읽기/쓰기): `SUCCESS_RESOLVED` 반환.

### 3.3 사용자 공간 주입 프리미티브
1. `UFFDIO_COPY`:
   - 목적지 주소에 4KB 데이터를 기록하고 상태를 `PRESENT`로 전이.
   - `wake_threads == True`이면 해당 페이지에 대기 중이던 모든 스레드를 기상(`threads_resolved += len(woken)`)시키고 `fault_queue`에서 제거.
2. `UFFDIO_ZEROPAGE`:
   - `00`으로 채워진 4096바이트 제로 페이지를 매핑하고 대기 스레드 기상.
3. `UFFDIO_WRITEPROTECT`:
   - `enable_wp == True`: 상태를 `WP`로 변경.
   - `enable_wp == False`: 상태를 `PRESENT`로 환원하고 쓰기 대기 중이던 스레드들을 기상.

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
```json
{
  "config": {
    "start_addr": 65536,
    "nr_pages": 4
  },
  "operations": [
    {"action": "FAULT", "thread_id": "vCPU_0", "addr": 65536, "type": "READ"},
    {"action": "UFFDIO_COPY", "dst_addr": 65536, "data_hex": "AABBCCDD"},
    {"action": "FAULT", "thread_id": "vCPU_0", "addr": 65536, "type": "READ"}
  ]
}
```

### 4.2 출력 형식 (Output Format)
```json
{
  "stats": {
    "page_faults_missing": 1,
    "page_faults_wp": 0,
    "uffdio_copy_ops": 1,
    "uffdio_zeropage_ops": 0,
    "uffdio_wp_ops": 0,
    "threads_resolved": 1
  },
  "pending_faults_count": 0,
  "pending_faults": [],
  "pages_state": {
    "0x00010000": {
      "state": "PRESENT",
      "has_data": true,
      "waiting_threads": []
    }
  }
}
```
