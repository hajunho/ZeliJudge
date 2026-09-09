# Linux io_uring 비동기 I/O 링 버퍼(SQE/CQE), 시스템 콜 제로-카피와 Polled I/O 커널 스레드

## 1. 개요: 리눅스 I/O 인터페이스의 진화와 시스템 콜 오버헤드의 벽

수십 년간 리눅스 고성능 서버(Nginx, Redis, Netty 등)의 비동기 I/O는 `epoll` 이벤트 루프를 중심으로 구축되었습니다.
하지만 NVMe SSD가 등장하여 초당 수백만 IOPS(Input/Output Operations Per Second)와 마이크로초($\mu\text{s}$) 단위의 하드웨어 응답 속도를 제공하게 되면서, **소프트웨어 계층의 시스템 콜 오버헤드**가 가장 심각한 병목으로 대두되었습니다:

1. **동기식 I/O (`read()`, `write()`, `preadv()`)**:
   - I/O를 요청할 때마다 유저스페이스 $\leftrightarrow$ 커널스페이스 간 컨텍스트 스위칭(Context Switching), CPU 모드 전환(Syscall Trap, `sysenter`/`syscall`), 페이지 테이블 격리(KPTI) 비용이 발생합니다 (I/O당 약 $1.0 \sim 1.5\,\mu\text{s}$).
   - 100만 IOPS 환경에서 시스템 콜 오버헤드만으로 CPU 코어 여러 개가 100% 포화됩니다.
2. **기존 리눅스 AIO (`io_submit()`, `io_getevents()`)의 결함**:
   - `O_DIRECT` 플래그를 지정한 특정 블록 디바이스 파일에서만 비동기로 동작합니다.
   - 버퍼링된 I/O(일반 파일), 네트워크 소켓, 파이프에서는 블로킹(Blocking)되어 사실상 무용지물이었습니다.
3. **Linux 5.1의 혁명: io_uring (Jens Axboe, 2019)**:
   - 커널과 유저스페이스가 **원형 링 버퍼(Ring Buffer) 메모리를 직접 공유**하여, 어떤 파일/소켓이든 완전한 비동기로 처리합니다.
   - 배치 제출을 통해 시스템 콜 횟수를 극적으로 줄이거나, **커널 폴링 스레드(`IORING_SETUP_SQPOLL`)를 통해 시스템 콜을 단 1회도 호출하지 않는 완전한 제로-시스템콜(Zero-Syscall) I/O**를 실현했습니다.

---

## 2. io_uring 핵심 아키텍처: 2개의 공유 링 버퍼

io_uring은 유저 공간과 커널 공간 사이에 위치한 2개의 잠금 없는(Lock-Free) 원형 링 버퍼로 동작합니다:

```
[유저스페이스 애플리케이션]                                          [리눅스 커널]
           │                                                               │
           │ 1. SQE 작성 (mmap 공유 메모리)                                  │
           ▼                                                               │
┌──────────────────────────────────────┐                                   │
│  제출 큐: SQ (Submission Queue)      │ ─── 2. io_uring_enter() 시스템 콜 ───►│ (또는 SQPOLL 커널 스레드가
│  - sq_head (커널이 소비 전진)        │     (또는 SQPOLL 시 0 Syscall!)   │   sq_tail 변경을 폴링 감지)
│  - sq_tail (유저가 제출 전진)        │                                   │
└──────────────────────────────────────┘                                   │
                                                                           │
                                                                           ▼ 3. 하드웨어 비동기 I/O
                                                                           [NVMe SSD / 드라이버]
                                                                           │
                                                                           ▼ 4. 인터럽트 / 완료 처리
┌──────────────────────────────────────┐                                   │
│  완료 큐: CQ (Completion Queue)      │◄── 5. CQE 기록 및 cq_tail 전진 ───┘
│  - cq_head (유저가 결과 읽고 전진)   │
│  - cq_tail (커널이 완료 쓰고 전진)   │
└──────────────────────────────────────┘
           ▲
           │ 6. mmap 메모리에서 CQE 즉각 확인 (0 Syscall)
[유저스페이스 애플리케이션]
```

### 2.1 제출 큐: Submission Queue (SQ)
- 유저 애플리케이션이 수행할 I/O 요청을 담는 **SQE(Submission Queue Entry)**의 링 버퍼입니다.
- 구조체 크기는 64바이트이며, 파일 디스크립터(`fd`), 오프셋(`off`), 버퍼 주소(`addr`), 읽기/쓰기 바이트 수(`len`), 작업 코드(`opcode`, 예: `IORING_OP_READV`, `IORING_OP_WRITEV`) 등을 포함합니다.
- 유저는 `sq_tail` 위치에 SQE를 쓰고 메모리 배리어(`smp_store_release`)로 `sq_tail`을 전진시킵니다.

### 2.2 완료 큐: Completion Queue (CQ)
- 커널이 I/O를 마친 후 결과를 유저에게 전달하는 **CQE(Completion Queue Entry)**의 링 버퍼입니다.
- 구조체 크기는 16바이트이며, 유저가 전달했던 식별자(`user_data`), 결과 코드(성공 시 읽은 바이트 수, 실패 시 음수 에러 코드 `res`), 플래그(`flags`)를 포함합니다.
- 커널이 `cq_tail`을 전진시키면, 유저는 시스템 콜 없이 `cq_head`를 확인하여 결과를 수확하고 `cq_head`를 전진시킵니다 (`io_uring_cq_advance`).

---

## 3. 3대 실행 모드와 성능 특성

### 3.1 인터럽트 주도 배치 모드 (Batched io_uring)
- 유저스페이스가 메모리에 여러 개의 SQE(예: 16개, 64개)를 연속으로 채워 넣습니다.
- 단 한 번의 **`io_uring_enter(fd, to_submit, min_complete, flags)`** 시스템 콜을 호출하여 수십 개의 I/O를 일괄 제출합니다.
- 기존 동기식 I/O 대비 시스템 콜 횟수가 배치 크기만큼 반비례하여 감소합니다 ($N$회 $\to 1$회).

### 3.2 커널 폴링 스레드 모드 (`IORING_SETUP_SQPOLL`)
- `io_uring_setup()` 호출 시 `IORING_SETUP_SQPOLL` 플래그를 지정하면, 커널 내부에 전용 커널 스레드(`io_uring-sq`)가 생성됩니다.
- 이 커널 스레드는 SQ 링의 `sq_tail` 포인터를 무한 루프로 폴링 감시합니다.
- **유저는 메모리에 SQE를 쓰고 tail만 전진시키면, 커널 스레드가 즉시 이를 감지하여 I/O를 디스패치**합니다.
- **결과**: I/O 제출에 소요되는 시스템 콜 횟수가 **완벽한 0회(Zero-Syscall)**가 됩니다! CPU 모드 전환이 0이 되어 지연시간이 하드웨어 한계선까지 단축됩니다.

### 3.3 고정 버퍼 사전 등록 (`IORING_REGISTER_BUFFERS`)
- 일반적인 I/O는 커널이 유저 가상 메모리 버퍼를 물리 메모리에 락(Pin)하고 페이지 테이블을 순회하는 오버헤드가 발생합니다.
- 유저가 버퍼를 미리 `io_uring_register()`로 커널에 등록해 두면, I/O 발생 시마다 일어나는 페이지 고정/해제 비용을 영구히 생략할 수 있습니다.

---

## 4. 완료 큐(CQ) 오버플로우와 역압(Backpressure)

io_uring에서 링 버퍼 크기(`queue_depth`)는 유한합니다.
- 유저 애플리케이션이 빠른 속도로 SQE를 계속 제출하면서, 완료된 CQE를 제때 회수(`drain_cqe_count` 또는 `cq_head` 전진)하지 않으면 완료 큐가 가득 차게 됩니다 (`cq_tail - cq_head >= queue_depth`).
- 과거 커널에서는 새로운 완료 이벤트가 조용히 유실(Drop)되는 치명적 참사가 발생했습니다.
- 현대 커널은 `IORING_FEAT_NODROP` 기능을 통해 백로그 리스트를 관리하거나 오버플로우 플래그(`IORING_CQ_OVERFLOW`)를 세팅하여 유저에게 역압을 통보합니다.

---

## 5. 실무 지표 비교: 전통 Epoll vs io_uring

| 성능 및 아키텍처 지표 | 전통 Epoll + pread | io_uring Batched | io_uring SQPOLL |
| :--- | :--- | :--- | :--- |
| **I/O당 시스템 콜 수** | 정확히 **1회** ($N$개 I/O $\to N$회 Syscall) | **$1/B$회** ($B$개 배치당 1회) | **완벽한 0회 (Zero-Syscall)** |
| **CPU 컨텍스트 스위칭** | 매 I/O마다 유저/커널 왕복 | 배치당 1회 | **0회 (순수 메모리 쓰기)** |
| **NVMe 랜덤 읽기 IOPS** | ~400K ~ 600K IOPS (Syscall 병목) | ~1.2M IOPS | **~2.5M+ IOPS (하드웨어 한계선)** |
| **평균 단건 지연시간** | 하드웨어 시간 + $1.5\,\mu\text{s}$ (Syscall Trap) | 하드웨어 시간 + $\approx 0.1\,\mu\text{s}$ | **하드웨어 원본 지연시간 달성** |
