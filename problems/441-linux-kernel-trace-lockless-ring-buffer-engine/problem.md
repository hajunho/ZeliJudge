# Problem #441: 리눅스 커널 추적 계층: kernel/trace/ring_buffer.c Ftrace 락리스 멀티-컨텍스트(NMI·IRQ·Task) 링 버퍼 및 2단계 예약·커밋 엔진

## 🌟 개요 (Executive Summary)
리눅스 커널의 핵심 동적 추적 프레임워크인 Ftrace(`kernel/trace/ring_buffer.c`, `kernel/trace/trace.c`)는 시스템의 모든 함수 호출(Function Tracer), 스케줄러 전환, 인터럽트 핸들러, 하드웨어 NMI(Non-Maskable Interrupt) 이벤트를 나노초(ns) 단위로 실시간 기록합니다.
그러나 커널 공간에서의 이벤트 로깅은 극도로 치명적인 동시성 딜레마를 안고 있습니다:
1. **중첩 실행과 데드락 위험**: 일반 프로세스(Task)가 trace 이벤트를 기록하는 도중 하드웨어 인터럽트(HardIRQ)가 발생하여 CPU를 선점하고, 인터럽트 핸들러가 실행되는 도중 다시 NMI 워치독이 침입할 수 있습니다.
2. **동기화 원시(Lock) 사용 불가**: 만약 링 버퍼 보호를 위해 일반적인 스핀락(`spin_lock()`)이나 뮤텍스를 사용한다면, 태스크가 락을 획득한 상태에서 발생한 인터럽트나 NMI가 동일 락을 획득하려 시도하는 순간 영구적인 **재진입 데드락(Reentrancy Deadlock / Self-Deadlock)**에 빠져 시스템 전체가 즉각 정지합니다.

Ftrace 메인테이너 Steven Rostedt는 이를 해결하기 위해 **고성능 락리스 원형 링 버퍼 (`kernel/trace/ring_buffer.c`)**를 설계하였습니다:
- **4단계 실행 컨텍스트 계층 구조**: 각 CPU 코어는 `TASK (0) < SOFTIRQ (1) < HARDIRQ (2) < NMI (3)`의 엄격한 선점 우선순위를 준수하며, 상위 컨텍스트만이 하위 컨텍스트를 중첩 선점할 수 있습니다. 동일 또는 역방향 중첩은 방어됩니다.
- **원자적 2단계 예약-커밋 프로토콜 (2-Phase Reserve & Commit)**:
  - **예약 (`ring_buffer_lock_reserve`)**: 원자적 포인터 가산(`cmpxchg`)을 통해 `write` 오프셋을 즉각 확보하여 이벤트 슬롯을 할당받습니다. 락을 전혀 획득하지 않으므로 NMI 컨텍스트에서도 안전합니다.
  - **커밋 (`ring_buffer_unlock_commit`)**: 데이터 기록이 완료되면 `commit` 오프셋을 전진시켜 사용자 영역 리더(`trace_pipe`)가 읽을 수 있도록 원자적으로 공개합니다.
- **원형 페이지 체인과 2대 버퍼 정책**:
  - 각 CPU는 4KB 메모리 페이지(`struct buffer_data_page`)들의 이중 연결 원형 리스트를 가집니다.
  - **덮어쓰기 모드 (Overwrite Mode / 기본값)**: 링 버퍼가 가득 차면 오래된 데이터를 담고 있는 헤드 페이지(`head_page`)를 앞으로 밀어내며 최신 이벤트를 계속 기록합니다. 손실된 이벤트 수(`overwritten_events`)를 정밀 추적합니다.
  - **폐기 모드 (Discard / Produce-or-Drop Mode)**: 초기 부팅 트레이스나 특정 재현 시나리오를 위해 링 버퍼가 가득 차면 신규 이벤트를 기록하지 않고 즉각 버려(`dropped_events++`) 기존 로그의 원본성을 사수합니다.
- **사용자 영역 무손실 드레인 (`CONSUME_PAGE`)**: 리더 프로세스가 `trace_pipe`를 통해 완료된 헤드 페이지를 읽으면 해당 페이지를 즉각 초기화하여 링 버퍼의 가용 용량으로 회수합니다.

본 문제에서는 리눅스 커널 `kernel/trace/ring_buffer.c`의 4대 컨텍스트 중첩 관리, 락리스 페이지 롤오버, Overwrite/Discard 모드 분기 및 2단계 예약-커밋 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
        [ Tracing Event on CPU Core k ]
                      │
   Validate Context Nesting:
   Active Stack: [TASK] -> Interrupt by [HARDIRQ]? (Valid)
   Active Stack: [HARDIRQ] -> Interrupt by [SOFTIRQ]? (Invalid Violation!)
                      │
                      ▼
        [ ring_buffer_lock_reserve() ]
                      │
   Fits in tail_page (tail.write + len <= capacity)?
              ┌───────┴───────┐
             Yes              No
              │               │
              │               ▼
              │      [ Check next_page in Circular Ring ]
              │      Is next_page == head_page? (Buffer Full)
              │         ┌───────────┴───────────┐
              │      Yes (Full)                 No (Free Page)
              │         │                             │
              │         ├─ overwrite_mode == True?    │
              │         │  Advance head_page          │
              │         │  overwritten_events++       │
              │         │  tail_page = next_page      │
              │         │                             │
              │         └─ overwrite_mode == False?   │
              │            dropped_events++           │
              │            return DROPPED             │
              ▼                                       ▼
    [ Reserve Event Slot ]                 [ Page Rollover ]
    tail.write += len                      tail_page = next_page
    status = RESERVED                      status = RESERVED_ROLLED
                      │
                      ▼
           (Write event payload into slot)
                      │
                      ▼
        [ ring_buffer_unlock_commit() ]
    tail.commit += len, entries_count++
    Exit context stack
    status = COMMITTED_SUCCESS
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "num_cpus": 2,
    "page_size": 4096,
    "pages_per_cpu": 4,
    "overwrite_mode": true
  },
  "trace": [
    {"op": "RESERVE_EVENT", "event_id": "EV_1", "cpu_id": 0, "context": "TASK", "length": 64},
    {"op": "COMMIT_EVENT", "event_id": "EV_1"},
    {"op": "CONSUME_PAGE", "cpu_id": 0},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `num_cpus` (int, default=2): 시스템 논리 CPU 수.
  - `page_size` (int, default=4096): 링 버퍼 페이지 크기 (바이트). 유효 용량은 `page_size - 16`.
  - `pages_per_cpu` (int, default=4): 코어당 순환 링을 구성하는 페이지 수.
  - `overwrite_mode` (bool, default=true): 버퍼 포화 시 오래된 페이지 덮어쓰기 여부 (False 시 신규 이벤트 폐기).
- `trace` 명령어:
  1. `RESERVE_EVENT`:
     - `event_id` (str): 이벤트 식별자.
     - `cpu_id` (int): 이벤트를 발생시킨 CPU 코어 ID.
     - `context` (str): `"TASK"`, `"SOFTIRQ"`, `"HARDIRQ"`, `"NMI"` 중 하나.
     - `length` (int): 이벤트 크기 (바이트).
  2. `COMMIT_EVENT`:
     - `event_id` (str): 예약 완료된 이벤트를 링 버퍼에 최종 커밋.
  3. `CONSUME_PAGE`:
     - `cpu_id` (int): 사용자 영역 리더가 해당 코어의 `head_page`를 읽고 비움.
  4. `GET_STATS`:
     - 코어별 커밋, 덮어쓰기, 폐기 통계 및 헤드/테일 인덱스 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "RESERVE_EVENT",
      "event_id": "EV_1",
      "cpu_id": 0,
      "page_idx": 0,
      "offset": 0,
      "length": 64,
      "status": "RESERVED_CURRENT_PAGE",
      "nesting_depth": 1
    },
    ...
  ],
  "summary": {
    "total_committed_events": 1,
    "total_committed_bytes": 64,
    "total_overwritten_events": 0,
    "total_dropped_events": 0,
    "remaining_reservations": 0
  }
}
```
