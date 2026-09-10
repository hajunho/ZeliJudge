# 문제 427: 리눅스 커널 동시성 및 잠금: qrwlock(Queued Read-Write Lock) 쓰기 기아 방지 및 공정성 엔진

## 1. 개요 (Overview)

대규모 멀티코어 및 멀티소켓 NUMA 서버 환경에서 공유 커널 자료구조(VFS 디렉터리 캐시, 프로세스 태스크 리스트, 네트워크 라우팅 테이블)는 읽기 요청의 빈도가 쓰기 요청에 비해 압도적으로 높습니다.
과거 리눅스 커널에서 사용되던 전통적인 읽기-쓰기 스핀락(`rwlock_t`)은 심각한 **쓰기 기아(Writer Starvation)** 문제와 **캐시라인 바운싱(Cacheline Bouncing)** 병목을 안고 있었습니다:
1. **쓰기 기아**: 읽기 스레드들이 락을 쥐고 있는 동안 새로운 읽기 스레드들이 끊임없이 유입되면, 활성 리더 카운트(`reader_count`)가 영원히 0으로 떨어지지 않아 대기 중인 쓰기 스레드(Writer)가 무한정 굶주리는(Starvation) 현상이 발생합니다.
2. **캐시라인 경합**: 수십~수백 개의 CPU 코어가 단일 32비트 락 워드에 대해 `atomic_inc`와 `atomic_dec`를 반복 실행하면서 CPU 버스 인터커넥트(MESI/MOESI 캐시 일관성 프로토콜)가 포화되어 시스템 처리량이 급감했습니다.

이를 해결하기 위해 피터 제일스트라(Peter Zijlstra)와 와이먼 롱(Waiman Long)은 **큐 기반 읽기-쓰기 락(`qrwlock` / `kernel/locking/qrwlock.c`, `include/asm-generic/qrwlock.h`)**을 개발하여 메인라인 커널에 도입하였습니다.

`qrwlock`은 32비트 원자적 정수 하나를 다음과 같은 정밀한 비트 필드로 분할 관리합니다:
- **`_QW_LOCKED` (Bit 0, `0x01`)**: 현재 쓰기 스레드가 락을 독점 소유 중임을 표시.
- **`_QW_WAITING` (Bit 8, `0x100`)**: 쓰기 스레드가 진입하여 대기 중임을 알리는 **쓰기 배리어(Writer Barrier)** 비트.
- **`_QR_BIAS` (Bits 9..31)**: 활성 읽기 스레드의 참조 카운터 (`reader_count = cnts >> 9`).

쓰기 스레드가 진입하면 즉시 `_QW_WAITING` 비트를 세팅하여 **이후 새로 도착하는 모든 읽기 스레드의 패스트패스 진입을 원천 차단**합니다. 기존에 남아 있던 읽기 스레드들이 작업을 마치고 카운트가 0이 되는 순간, 대기 중이던 쓰기 스레드가 락을 즉각 가로채어 임계 영역에 진입합니다. 또한 둘 이상의 쓰기 스레드가 경합할 경우 로컬 캐시라인에서 스핀하는 **MCS 대기 큐(MCS Queue)**로 흡수하여 캐시라인 바운싱을 제거합니다.

본 과제에서는 리눅스 커널 `kernel/locking/qrwlock.c`의 핵심 메커니즘인 읽기 패스트패스, 쓰기 배리어 설정, 쓰기 기아 방지, MCS 큐잉, 쓰기-읽기 핸드오프 및 대기 리더 배치 기상을 시뮬레이션하는 엔진을 구현합니다.

---

## 2. 시스템 아키텍처 및 32비트 락 워드 구조

```
[qrwlock 32-bit Atomic Lock Word Layout]
 31                                9   8               1   0
+------------------------------------+---+---------------+---+
|        Reader Count (BIAS)         | W |   Reserved    | L |
+------------------------------------+---+---------------+---+
                                       │                   │
                                       │                   └─► _QW_LOCKED (0x01)
                                       └─────────────────────► _QW_WAITING (0x100)

-------------------------------------------------------------------------------

[Writer Starvation Prevention Pipeline]
1. Readers R1, R2 holding lock:
   [Readers = 2, W = 0, L = 0] ──► Readers execute in parallel!

2. Writer W1 arrives:
   Atomically sets _QW_WAITING:
   [Readers = 2, W = 1, L = 0] ──► WRITE BARRIER ACTIVE!

3. New Readers R3, R4 arrive:
   Seeing W == 1 ──► BLOCKED! Enters Reader Wait Queue. (No Writer Starvation!)

4. R1, R2 finish (Reader count -> 0):
   [Readers = 0, W = 0, L = 1] ──► W1 ACQUIRES LOCK IMMEDIATELY!

5. W1 unlocks:
   Wakes up R3, R4 simultaneously in batch!
```

---

## 3. 세부 동작 명세 (Operational Specifications)

### 3.1 락 내부 상태 (`QRWLock`)
각 락 인스턴스는 다음 상태를 유지합니다:
- `writer_locked`: 쓰기 락 점유 플래그 (`True`/`False`).
- `writer_waiting`: 첫 번째 대기 쓰기 스레드가 설정한 배리어 플래그 (`True`/`False`).
- `reader_count`: 현재 임계 영역에서 실행 중인 활성 읽기 스레드 수.
- `active_readers`: 활성 읽기 스레드 ID 집합 (`set`).
- `active_writer`: 현재 락을 소유한 쓰기 스레드 ID (`None` 또는 문자열).
- `waiting_writer`: `writer_waiting` 배리어를 설정하고 리더 퇴출을 대기 중인 쓰기 스레드 ID.
- `writer_queue`: 배리어 설정자 뒤에 줄을 선 후속 쓰기 스레드 목록 (MCS Queue, 선입선출).
- `reader_queue`: 쓰기 배리어 또는 쓰기 락으로 인해 차단된 대기 읽기 스레드 목록.

### 3.2 이벤트 처리 규칙

1. **`READ_LOCK` (`time`, `lock_id`, `task_id`)**:
   - **패스트패스 조건**: `not writer_locked and not writer_waiting and waiting_writer is None`.
     - 조건 충족 시: `reader_count += 1`, `active_readers.add(task_id)`, `read_fastpath_count += 1`.
     - `event_logs`에 `READ_LOCK_FASTPATH`를 기록합니다.
   - **블록 조건 (슬로우패스)**:
     - 쓰기 스레드가 락을 쥐고 있거나, 쓰기 배리어(`writer_waiting`)가 켜져 있는 경우.
     - `reader_queue`에 `task_id`를 삽입하고 `read_blocked_count += 1`.
     - `event_logs`에 `READ_LOCK_BLOCKED`를 기록합니다.

2. **`READ_UNLOCK` (`time`, `lock_id`, `task_id`)**:
   - `task_id`가 `active_readers`에 속해 있지 않으면 무시합니다.
   - `active_readers`에서 제거하고 `reader_count -= 1`.
   - `event_logs`에 `READ_UNLOCK_SUCCESS`를 기록합니다.
   - **쓰기 스레드 핸드오프 검사**:
     - `reader_count == 0`에 도달하고 `waiting_writer`가 대기 중인 경우:
       - 대기 쓰기 스레드(`waiting_writer`)가 즉시 락을 획득합니다!
       - `writer_locked = True`, `writer_waiting = False`, `active_writer = waiting_writer`, `waiting_writer = None`.
       - `writer_starvations_prevented`를 1 증가시킵니다.
       - `lock_logs`에 `WRITER_HANDOFF_FROM_READERS`, `event_logs`에 `WRITER_ACQUIRED_AFTER_READERS_DRAIN`을 기록합니다.

3. **`WRITE_LOCK` (`time`, `lock_id`, `task_id`)**:
   - **패스트패스 조건**: `not writer_locked and not writer_waiting and reader_count == 0 and waiting_writer is None`.
     - 즉시 독점 획득: `writer_locked = True`, `active_writer = task_id`, `write_fastpath_count += 1`.
     - `event_logs`에 `WRITE_LOCK_FASTPATH`를 기록합니다.
   - **경합 발생 (슬로우패스)**:
     - 아직 대기 쓰기 스레드가 없는 경우 (`not writer_waiting and waiting_writer is None`):
       - `task_id`가 첫 번째 대기자가 되어 쓰기 배리어를 설정합니다: `writer_waiting = True`, `waiting_writer = task_id`.
       - `write_barriers_set`을 1 증가시킵니다.
       - `lock_logs`에 `WRITE_BARRIER_SET`, `event_logs`에 `WRITE_LOCK_WAITING_SET_BARRIER`를 기록합니다.
     - 이미 대기 쓰기 스레드가 존재하는 경우:
       - 후속 쓰기 스레드는 MCS 대기 큐(`writer_queue`)에 삽입됩니다.
       - `event_logs`에 `WRITE_LOCK_QUEUED_MCS`를 기록합니다.

4. **`WRITE_UNLOCK` (`time`, `lock_id`, `task_id`)**:
   - `task_id`가 `active_writer`가 아니면 무시합니다.
   - 락 해제: `writer_locked = False`, `active_writer = None`.
   - `event_logs`에 `WRITE_UNLOCK_SUCCESS`를 기록합니다.
   - **우선순위 인계(Handoff) 정책**:
     1. `writer_queue`에 대기 중인 쓰기 스레드가 있는 경우:
        - 맨 앞의 쓰기 스레드를 꺼내어 즉시 `active_writer`로 승격시킵니다 (`writer_locked = True`).
        - `lock_logs`에 `WRITER_HANDOFF_MCS`, `event_logs`에 `WRITER_ACQUIRED_FROM_MCS`를 기록합니다.
     2. 대기 쓰기 스레드는 없고 `reader_queue`에 대기 중인 읽기 스레드가 있는 경우:
        - 대기 중인 모든 읽기 스레드를 일괄 기상(Batch Unblock)시킵니다.
        - `reader_queue`의 모든 항목을 `active_readers`로 이동하고 `reader_count`를 가산합니다.
        - `lock_logs`에 `READERS_BATCH_UNBLOCKED`, `event_logs`에 `READERS_WOKEN_UP`을 기록합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 입력 형식 (Standard Input, JSON)
```json
{
  "config": {},
  "trace": [
    {"time": 10, "type": "READ_LOCK", "lock_id": "rw1", "task_id": "r1"},
    {"time": 20, "type": "READ_LOCK", "lock_id": "rw1", "task_id": "r2"},
    {"time": 30, "type": "WRITE_LOCK", "lock_id": "rw1", "task_id": "w1"},
    {"time": 40, "type": "READ_LOCK", "lock_id": "rw1", "task_id": "r3"},
    {"time": 50, "type": "READ_LOCK", "lock_id": "rw1", "task_id": "r4"},
    {"time": 60, "type": "READ_UNLOCK", "lock_id": "rw1", "task_id": "r1"},
    {"time": 70, "type": "READ_UNLOCK", "lock_id": "rw1", "task_id": "r2"},
    {"time": 80, "type": "WRITE_UNLOCK", "lock_id": "rw1", "task_id": "w1"},
    {"time": 90, "type": "READ_UNLOCK", "lock_id": "rw1", "task_id": "r3"},
    {"time": 100, "type": "READ_UNLOCK", "lock_id": "rw1", "task_id": "r4"}
  ]
}
```

### 출력 형식 (Standard Output, Compact JSON)
공백 없는 단일 라인 JSON 문자열(`separators=(',', ':')`)로 출력합니다:
```json
{"summary":{"read_fastpath_count":2,"read_blocked_count":2,"write_fastpath_count":0,"write_barriers_set":1,"writer_starvations_prevented":1,"total_locks":1},"locks":{"rw1":{"writer_locked":false,"writer_waiting":false,"reader_count":0,"active_readers":[],"active_writer":null,"waiting_writer":null,"queued_writers":[],"queued_readers":[]}},"lock_logs":[{"time":30,"action":"WRITE_BARRIER_SET","lock_id":"rw1","waiting_writer":"w1","active_readers":2},{"time":70,"action":"WRITER_HANDOFF_FROM_READERS","lock_id":"rw1","writer_id":"w1"},{"time":80,"action":"READERS_BATCH_UNBLOCKED","lock_id":"rw1","count":2}],"event_logs":[{"time":10,"event":"READ_LOCK_FASTPATH","lock_id":"rw1","task_id":"r1","reader_count":1},{"time":20,"event":"READ_LOCK_FASTPATH","lock_id":"rw1","task_id":"r2","reader_count":2},{"time":30,"event":"WRITE_LOCK_WAITING_SET_BARRIER","lock_id":"rw1","task_id":"w1"},{"time":40,"event":"READ_LOCK_BLOCKED","lock_id":"rw1","task_id":"r3","reason":"WRITER_PENDING_OR_LOCKED"},{"time":50,"event":"READ_LOCK_BLOCKED","lock_id":"rw1","task_id":"r4","reason":"WRITER_PENDING_OR_LOCKED"},{"time":60,"event":"READ_UNLOCK_SUCCESS","lock_id":"rw1","task_id":"r1","remaining_readers":1},{"time":70,"event":"READ_UNLOCK_SUCCESS","lock_id":"rw1","task_id":"r2","remaining_readers":0},{"time":70,"event":"WRITER_ACQUIRED_AFTER_READERS_DRAIN","lock_id":"rw1","writer_id":"w1"},{"time":80,"event":"WRITE_UNLOCK_SUCCESS","lock_id":"rw1","task_id":"w1"},{"time":80,"event":"READERS_WOKEN_UP","lock_id":"rw1","count":2},{"time":90,"event":"READ_UNLOCK_SUCCESS","lock_id":"rw1","task_id":"r3","remaining_readers":1},{"time":100,"event":"READ_UNLOCK_SUCCESS","lock_id":"rw1","task_id":"r4","remaining_readers":0}]}
```
