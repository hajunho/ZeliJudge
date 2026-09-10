# 문제 426: 리눅스 커널 비동기 I/O: io_uring 협력적 작업 실행(Cooperative Task Work) 및 IPI 인터럽트 제거 엔진

## 1. 개요 (Overview)

초고성능 스토리지(NVMe SSD)와 초고속 네트워크(100GbE+) 환경에서 `io_uring`은 백만 단위의 IOPS를 처리하는 현대 리눅스 비동기 I/O의 표준입니다. 그러나 리눅스 커널 5.18 이전의 레거시 `io_uring` 아키텍처는 고부하 환경에서 예상치 못한 CPU 병목 현상에 직면했습니다.

비동기 I/O 요청(디스크 읽기/쓰기, 네트워크 송수신)이 하드웨어 인터럽트 핸들러나 비동기 커널 워커(`io-wq`)에서 완료되면, 커널은 원래 유저스페이스 애플리케이션 스레드의 태스크 컨텍스트에서 **완료 큐 엔트리(CQE)**를 게시하고 리소스를 정리하기 위해 **`task_work`**를 등록합니다.
레거시 방식에서는 이 `task_work`를 즉시 실행시키기 위해 대상 CPU 코어로 **프로세서 간 인터럽트(IPI, Inter-Processor Interrupt)**를 발송하고 스레드 플래그에 `TIF_NOTIFY_SIGNAL`을 설정했습니다.
초당 200만~500만 IOPS가 발생하는 환경에서는 초당 수백만 개의 IPI가 코어 간 인터커넥트를 강타하며 전체 CPU 사이클의 30~40%를 순수 IPI 처리 및 컨텍스트 스위칭 오버헤드로 낭비했습니다.

리눅스 커널 창시자이자 io_uring 설계자인 옌스 악스보(Jens Axboe)는 커널 v5.19 및 v6.0에서 이를 근본적으로 혁신하는 **협력적 작업 실행(`IORING_SETUP_COOP_TASKRUN`)**과 **유저스페이스 작업 알림 플래그(`IORING_SETUP_TASKRUN_FLAG`)**를 도입했습니다.

`COOP_TASKRUN` 모드에서는 커널이 비동기 완료 시 IPI를 일체 발송하지 않습니다 (`ipis_sent = 0`). 대신 완료된 작업은 스레드의 로컬 작업 큐(`pending_task_work`)에 적재되고, 유저와 커널이 공유하는 SQ 링 헤더에 `IORING_SQ_TASKRUN` 플래그를 원자적으로 설정합니다. 애플리케이션은 유저스페이스에서 이 플래그를 감지하거나 `io_uring_enter()`를 호출할 때 지연된 작업들을 단일 배치(Batch)로 일괄 드레인(Drain)하여 CQE를 게시합니다.

본 과제에서는 리눅스 커널 `io_uring/io_uring.c`의 레거시 IPI 방식과 차세대 `COOP_TASKRUN` 협력적 실행 엔진을 시뮬레이션하고, IPI 폭풍 제거, 작업 큐잉, 태스크런 플래그 제어 및 배치 드레인 파이프라인을 완벽히 모델링합니다.

---

## 2. 시스템 아키텍처 및 IPI 제거 비교 (System Topology)

```
[Legacy io_uring Task Work: IPI Storm]
 Async Worker Core                         User Thread Core
 ─────────────────                         ────────────────
 Async IO Done!
       │
       ├─► task_work_add()
       │
       ▼ (Send Hardware IPI / TIF_NOTIFY_SIGNAL)
 ═════════════════════════════════════════════════► [CPU Interrupted!]
 (Millions of IPIs per sec -> 40% CPU Burn)        Context Switch & Execute
                                                    Post CQE immediately

-------------------------------------------------------------------------------

[Cooperative io_uring Task Work (IORING_SETUP_COOP_TASKRUN)]
 Async Worker Core                         User Thread Core
 ─────────────────                         ────────────────
 Async IO Done!
       │
       ├─► Queue to local_work_list (NO IPI!)
       │   Set IORING_SQ_TASKRUN flag in shared ring
       │                                           User App loops in userspace
       │                                           (Zero Syscall / Zero IPI)
       │                                                 │
       │                                                 ▼ Checks Flag or Enters
       │                                           io_uring_enter(GETEVENTS)
       │                                                 │
       └─────────────────────────────────────────────────┴─► [Batch Drain & Post CQEs]
                                                             (Zero Inter-Core IPIs!)
```

---

## 3. 세부 동작 명세 (Operational Specifications)

### 3.1 엔진 구성 매개변수 (`config`)
- `mode`: `"COOP"` (기본값) 또는 `"LEGACY"`.
- `flags`: 지원 플래그 목록 (예: `["IORING_SETUP_COOP_TASKRUN", "IORING_SETUP_TASKRUN_FLAG"]`).
- `cq_entries`: 완료 큐(CQ) 링 버퍼 크기 (기본값 `16`).

### 3.2 이벤트 처리 규칙

1. **`SUBMIT_ASYNC_REQ` (`time`, `req_id`, `op`, `data_len`)**:
   - 신규 비동기 I/O 요청을 제출합니다.
   - `total_requests`를 1 증가시키고 `event_logs`에 `REQ_SUBMITTED`를 기록합니다.

2. **`COMPLETE_ASYNC_REQ` (`time`, `req_id`, `result`)**:
   - 하드웨어/워커 스레드에서 I/O 완료가 발생한 시점을 모사합니다.
   - **`mode == "LEGACY"` 인 경우**:
     - 즉각적인 IPI 인터럽트를 발송합니다 (`ipis_sent += 1`).
     - 유저 스레드를 즉시 인터럽트하여 `task_work`를 실행합니다 (`task_work_runs += 1`).
     - `cqes`에 `{"req_id": req_id, "res": result}`를 즉시 추가하고 `cqes_generated += 1`.
     - `task_work_logs`에 `LEGACY_IPI_TASK_WORK`, `event_logs`에 `IPI_INTERRUPT_TRIGGERED`를 기록합니다.
   - **`mode == "COOP"` 인 경우**:
     - **IPI를 일체 발송하지 않습니다** (`ipis_sent` 증가 없음).
     - 완료 항목을 `pending_task_work` 큐에 지연 보관합니다.
     - `flags`에 `"IORING_SETUP_TASKRUN_FLAG"`가 포함되어 있다면 `sq_taskrun_flag = True`로 설정합니다.
     - `task_work_logs`에 `COOP_WORK_QUEUED`, `event_logs`에 `COOP_WORK_QUEUED_NO_IPI`를 기록합니다.

3. **`ENTER_WAIT` (`time`, `min_complete`)**:
   - 애플리케이션이 완료 대기를 위해 `io_uring_enter()`를 호출한 시점을 모사합니다.
   - **`mode == "COOP"` 인 경우**:
     - 대기 중인 `pending_task_work`가 있다면:
       - `batch_flushes += 1`, `task_work_runs += 1`.
       - 지연된 모든 작업을 일괄 추출(Batch Drain)하여 `cqes`에 게시하고 `cqes_generated`를 증가시킵니다.
       - 작업이 모두 비워졌으므로 `sq_taskrun_flag = False`로 리셋합니다.
       - `task_work_logs`에 `COOP_BATCH_DRAINED`, `event_logs`에 `COOP_TASK_WORK_DRAINED`를 기록합니다.

4. **`USER_PEEK_CQE` (`time`)**:
   - 애플리케이션이 커널 진입 없이 유저스페이스 메모리 맵(Shared CQ Ring)을 피킹(Peek)하는 동작을 모사합니다.
   - 현재 가용한 `cqes_available = len(self.cqes)`와 `sq_taskrun_flag` 상태를 조회합니다.
   - `event_logs`에 `USER_PEEK_CQE`를 기록합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 입력 형식 (Standard Input, JSON)
```json
{
  "config": {
    "mode": "COOP",
    "flags": ["IORING_SETUP_COOP_TASKRUN", "IORING_SETUP_TASKRUN_FLAG"],
    "cq_entries": 32
  },
  "trace": [
    {"time": 10, "type": "SUBMIT_ASYNC_REQ", "req_id": "r1", "op": "READ", "data_len": 4096},
    {"time": 20, "type": "SUBMIT_ASYNC_REQ", "req_id": "r2", "op": "READ", "data_len": 8192},
    {"time": 30, "type": "SUBMIT_ASYNC_REQ", "req_id": "r3", "op": "WRITE", "data_len": 16384},
    {"time": 40, "type": "COMPLETE_ASYNC_REQ", "req_id": "r1", "result": 4096},
    {"time": 50, "type": "COMPLETE_ASYNC_REQ", "req_id": "r2", "result": 8192},
    {"time": 60, "type": "COMPLETE_ASYNC_REQ", "req_id": "r3", "result": 16384},
    {"time": 70, "type": "ENTER_WAIT", "min_complete": 1},
    {"time": 80, "type": "USER_PEEK_CQE"}
  ]
}
```

### 출력 형식 (Standard Output, Compact JSON)
공백 없는 단일 라인 JSON 문자열(`separators=(',', ':')`)로 출력합니다:
```json
{"summary":{"mode":"COOP","total_requests":3,"ipis_sent":0,"task_work_runs":1,"cqes_generated":3,"batch_flushes":1,"pending_task_work":0,"sq_taskrun_flag":false},"cqes":[{"req_id":"r1","res":4096},{"req_id":"r2","res":8192},{"req_id":"r3","res":16384}],"task_work_logs":[{"time":40,"action":"COOP_WORK_QUEUED","req_id":"r1","ipi_sent":false,"sq_taskrun_flag":true},{"time":50,"action":"COOP_WORK_QUEUED","req_id":"r2","ipi_sent":false,"sq_taskrun_flag":true},{"time":60,"action":"COOP_WORK_QUEUED","req_id":"r3","ipi_sent":false,"sq_taskrun_flag":true},{"time":70,"action":"COOP_BATCH_DRAINED","items_drained":3}],"event_logs":[{"time":10,"event":"REQ_SUBMITTED","req_id":"r1","op":"READ","len":4096},{"time":20,"event":"REQ_SUBMITTED","req_id":"r2","op":"READ","len":8192},{"time":30,"event":"REQ_SUBMITTED","req_id":"r3","op":"WRITE","len":16384},{"time":40,"event":"COOP_WORK_QUEUED_NO_IPI","req_id":"r1"},{"time":50,"event":"COOP_WORK_QUEUED_NO_IPI","req_id":"r2"},{"time":60,"event":"COOP_WORK_QUEUED_NO_IPI","req_id":"r3"},{"time":70,"event":"COOP_TASK_WORK_DRAINED","count":3},{"time":80,"event":"USER_PEEK_CQE","cqes_available":3,"sq_taskrun_flag":false}]}
```
