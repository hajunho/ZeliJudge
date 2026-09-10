# 문제 309: 리눅스 커널 io_uring(fs/io_uring.c) SQPOLL 제로 시스콜 링 버퍼 및 비동기 I/O 체인 엔진 (Linux Kernel io_uring Engine)

## 문제 배경
리눅스 서버에서 고성능 NVMe SSD(초당 수백만 IOPS)와 초고속 네트워크를 다룰 때, 가장 치명적인 성능 병목은 I/O 요청마다 발생하는 **시스템 콜 컨텍스트 스위칭(System Call Overhead)**입니다. 기존의 동기식 I/O(`read`/`write`)는 물론, 리눅스 구형 비동기 I/O인 `libaio`조차도 `io_submit()`과 `io_getevents()` 시스템 콜을 호출할 때마다 CPU 모드 전환(Ring 3 $\to$ Ring 0)과 스펙터/멜트다운(Spectre/Meltdown) 방어 비용으로 인해 초당 수만 건 이상의 시스템 콜을 감당하지 못했습니다.

리눅스 커널 5.1에서 젠스 악스보(Jens Axboe)가 설계한 **`io_uring`(`fs/io_uring.c`)**은 유저 공간과 커널 공간이 **공유 메모리 링 버퍼(Shared Memory Ring Buffer)**를 통해 직접 통신하는 혁신적인 구조로 I/O 아키텍처를 완전히 재정의했습니다:
1. **제출 큐 (Submission Queue, SQ)**: 유저 공간이 락 없이 `sqe`(Submission Queue Entry)를 tail에 기록.
2. **완료 큐 (Completion Queue, CQ)**: 커널이 I/O 완료 결과 `cqe`(Completion Queue Event)를 tail에 기록하고 유저 공간이 head에서 수거.
3. **SQPOLL (Submission Queue Polling, `IORING_SETUP_SQPOLL`)**:
   - 커널 내부에서 전용 커널 스레드(`io_uring-sq`)가 상주하며 SQ 링 버퍼를 실시간 폴링합니다.
   - 유저 공간은 시스템 콜(`io_uring_enter`)을 **단 한 번도 호출하지 않고(Zero-Syscall)** 메모리에 SQE를 쓰기만 하면 커널이 즉시 이를 소비하여 하드웨어 NVMe 컨트롤러로 디스패치합니다!
4. **I/O 링크 체인 (`IOSQE_IO_LINK`)**:
   - Write $\to$ Fsync $\to$ Read 처럼 인과 관계가 있는 여러 비동기 I/O 작업을 하나의 원자적 체인으로 엮어 실행하며, 앞선 작업 실패 시 후속 작업들을 `-ECANCELED (-125)`로 즉시 연쇄 취소합니다.

본 문제에서는 리눅스 커널 `fs/io_uring.c`의 공유 링 버퍼 포인터 동기화, SQPOLL 커널 스레드의 유휴 슬립 및 웜업(`IORING_ENTER_SQ_WAKEUP`), I/O 링크 체인 실행 및 장애 전파를 시뮬레이션하는 **io_uring 비동기 I/O 엔진**을 구현해야 합니다.

---

## 시스템 동작 규칙 및 엔진 명세

### 1. 링 버퍼 구조 및 SQPOLL 동작 모드
- **SQ 링 & CQ 링**: 유저 공간과 커널이 공유하는 원형 큐 포인터(`sq_head`, `sq_tail`, `cq_head`, `cq_tail`)를 관리합니다.
- **`sqpoll_enabled == True` (SQPOLL 모드)**:
  - SQPOLL 커널 스레드가 깨어 있는 동안에는 `SUBMIT_SQE`가 발생하자마자 시스템 콜 없이 즉시 커널이 SQE를 소비하여 I/O를 수행하고 CQE를 포스팅합니다 (`zero_syscall_rate = 1.0`).
  - **유휴 타임아웃 슬립**: 마지막 SQE 등록 후 `sq_thread_idle_ms` 이상의 시간이 경과하고 SQ 링이 비어 있다면, SQPOLL 스레드는 수면(Sleep) 상태로 진입합니다.
  - 수면 중에 들어온 SQE는 즉시 처리되지 못하고 대기하며, 유저 공간이 `"ENTER_SYSCALL"` (`flags: ["IORING_ENTER_SQ_WAKEUP"]`)을 호출해야만 스레드가 깨어나 밀린 SQE를 일괄 처리합니다.
- **`sqpoll_enabled == False` (표준 모드)**:
  - SQE는 SQ 링에 펜딩 상태로 누적되며, 유저 공간이 `"ENTER_SYSCALL"`을 명시적으로 호출할 때만 커널이 일괄 처리합니다.

### 2. 지원 I/O 명령어 (`opcode`)
- **`NOP`**: 결과 `res = 0`.
- **`READ`**: `fd`가 없으면 `-EBADF (-9)`. 오프셋이 파일 크기 이상이면 `res = 0` (EOF). 정상 범위면 `res = min(len, file_size - offset)`.
- **`WRITE`**: `fd`가 없으면 `-EBADF (-9)`. 정상 쓰기 시 파일 크기 갱신 및 `res = len`.
- **`FSYNC`**: `fd`가 없으면 `-EBADF (-9)`, 정상이면 `res = 0`.

### 3. I/O 링크 체인 (`IOSQE_IO_LINK`)
- SQE 플래그에 `IOSQE_IO_LINK`가 설정되어 있으면, 다음 SQE와 순차적 실행 의존성을 맺습니다.
- 만약 선행 SQE가 음수 에러(`res < 0`)로 실패하면:
  - 뒤이어 링크된 모든 후속 SQE는 실행되지 않고 즉시 결과 `res = -125 (-ECANCELED)`로 취소 CQE가 포스팅됩니다.

### 4. CQE 드레인 (`DRAIN_CQE`)
- 유저 애플리케이션이 CQ 링에서 최대 `max_events`개의 CQE를 수거(`cq_head` 전진)합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "sq_entries": 8,
    "cq_entries": 16,
    "sqpoll_enabled": true,
    "sq_thread_idle_ms": 100
  },
  "files": {
    "3": {"size": 4096}
  },
  "operations": [
    {
      "op_id": 1,
      "timestamp_ms": 10,
      "type": "SUBMIT_SQE",
      "opcode": "READ",
      "fd": 3,
      "offset": 0,
      "len": 1024,
      "flags": [],
      "user_data": 1001
    },
    {
      "op_id": 2,
      "timestamp_ms": 20,
      "type": "DRAIN_CQE",
      "max_events": 10
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 단일 행으로 출력합니다:

```json
{
  "summary": {
    "sqpoll_enabled": true,
    "total_sqes_submitted": 1,
    "total_cqes_posted": 1,
    "total_syscall_enters": 0,
    "zero_syscall_rate": 1.0,
    "final_sq_ring_empty": true,
    "final_cq_ring_pending": 0
  },
  "drained_batches": [
    {
      "op_id": 2,
      "count": 1,
      "cqes": [
        {
          "user_data": 1001,
          "res": 1024,
          "flags": 0
        }
      ]
    }
  ]
}
```

---

## 제약 사항
- `1 <= len(operations) <= 2,000`
- `sq_entries`와 `cq_entries`는 2의 거듭제곱 (4, 8, 16, 32, 64)
- `zero_syscall_rate`는 소수점 넷째 자리까지 반올림합니다.
