# 문제 452: 리눅스 커널 동시성 — rwsem (Reader-Writer Semaphore) 낙관적 스피닝, 락 스틸링 및 핸드오프 기아 방지 엔진 (`kernel/locking/rwsem.c`)

## 1. 개요 및 배경

리눅스 커널에서 **`rw_semaphore` (Reader-Writer Semaphore / `kernel/locking/rwsem.c`)**는 프로세스의 가상 주소 공간 전체를 관장하는 `mmap_lock` (구 `mmap_sem`), 파일시스템 슈퍼블록, VFS 마운트 테이블 등 시스템 전반의 핵심 공유 자료구조를 보호하는 가장 중요한 동기화 프리미티브입니다.

### 1) 전통적인 수면 세마포어(Sleeping Semaphore)의 지연 병목
- 과거의 단순 세마포어는 락을 즉시 획득하지 못하면 즉각 태스크를 `TASK_UNINTERRUPTIBLE` 수면 상태로 전환하고 스케줄러를 호출했습니다.
- 문맥 교환(Context Switch)에는 통상 2,000ns ~ 5,000ns의 지연이 수반되므로, 임계 구역이 매우 짧은 경우 불필요한 수면과 깨우기 오버헤드로 인해 멀티코어 서버의 확장성이 극심하게 붕괴되었습니다.

```
[rwsem 고성능 하이브리드 잠금 및 기아 방지 아키텍처]:
Lock Request ──> [Atomic Fast Path] (1 Cycle 획득 성공 시 즉각 진입)
                        │ (실패 시)
                        ▼
                 [Optimistic Spinning] (OSQ 락 기반 소유자 실행 감시 스핀)
                        │
             ┌──────────┴──────────┐
      (락 해제 포착)          (타임아웃/소유자 수면)
             │                     │
             ▼                     ▼
     [Lock Stealing]        [Wait Queue Enqueue] (FIFO 대기열 진입)
     (락 가로채기 성공)            │
                            (장기 대기 발생 시)
                                   │
                                   ▼
                            [HANDOFF Mode Activated!]
                            (신규 스피너 락 가로채기 100% 원천 차단)
                                   │
                            [Direct Handoff & Reader Wakeup Batching]
```

리눅스 커널은 이를 해결하기 위해 `kernel/locking/rwsem.c`에 다음과 같은 정교한 기법들을 결합하였습니다:
1. **원자적 패스트패스 (Atomic Fast Path)**: 경합이 없을 때 1개의 CPU 원자적 연산으로 무지연 획득.
2. **낙관적 스피닝 (Optimistic Spinning & Lock Stealing)**: 락 소유자가 다른 CPU에서 실행 중일 때 잠들지 않고 짧게 스핀하며, 소유자가 락을 놓는 순간 대기 큐를 우회하여 락을 즉시 가로챕니다.
3. **핸드오프 기아 방지 메커니즘 (`RWSEM_FLAG_HANDOFF`)**: 무분별한 락 가로채기로 인해 대기열의 헤드 태스크가 굶어 죽는(Starvation) 현상을 방지하기 위해, 임계 대기 시간 초과 시 `HANDOFF` 플래그를 세워 신규 스피너의 진입을 영구 차단하고 헤드 대기자에게 강제 양도합니다.
4. **리더 깨우기 일괄 처리 (Reader Wakeup Batching)**: 쓰기 잠금이 해제될 때 대기열 전두의 연속된 모든 읽기 대기자들을 단일 배치로 일괄 기상시켜 병렬 처리량을 극대화합니다.

---

## 2. 핵심 메커니즘 및 상세 스펙

본 문제에서는 리눅스 커널 `kernel/locking/rwsem.c`의 다중 상태 머신을 모델링하는 엔진을 구현합니다.

### 1) 설정 파라미터 (`config`)
- `handoff_threshold_us`: 대기열 헤드가 대기한 지 이 시간을 초과하면 핸드오프 모드가 강제 활성화되는 임계 시간 (기본 1000 µs).

### 2) 읽기 잠금 획득 (`DOWN_READ`)
- `thread_id`, `time_us`
- **패스트패스 조건**:
  - `not writer_locked` AND `not handoff_active` AND 대기 큐가 비어있거나 대기 큐의 헤드가 `READ`인 경우.
  - `readers += 1`, `fast_read_hits += 1`.
  - 반환: `{"status": "ACQUIRED_READ_FAST", "thread_id": thread_id, "readers": readers}`.
- **슬로우패스 (대기열 적재)**:
  - 대기 큐(`wait_list`) 끝에 `{"thread_id": thread_id, "type": "READ", "wait_start": time_us}` 추가.
  - 반환: `{"status": "WAITING_READ", "thread_id": thread_id, "wait_pos": pos}`.

### 3) 쓰기 잠금 획득 (`DOWN_WRITE`)
- `thread_id`, `time_us`
- **패스트패스 조건**:
  - `readers == 0` AND `not writer_locked` AND `not handoff_active` AND 대기 큐가 완전히 비어있는 경우.
  - `writer_locked = true`, `owner = thread_id`, `fast_write_hits += 1`.
  - 반환: `{"status": "ACQUIRED_WRITE_FAST", "thread_id": thread_id}`.
- **슬로우패스**:
  - 대기 큐 끝에 `{"thread_id": thread_id, "type": "WRITE", "wait_start": time_us}` 추가.
  - 반환: `{"status": "WAITING_WRITE", "thread_id": thread_id, "wait_pos": pos}`.

### 4) 낙관적 스핀 락 가로채기 (`TRY_SPIN_ACQUIRE`)
- `thread_id`, `time_us`
- 대기 큐에 들어가지 않고 외부에서 스핀하던 쓰기 스레드가 락 획득을 시도하는 연산.
- 락이 비어있는 경우 (`readers == 0` AND `not writer_locked`):
  - **만약 `handoff_active == true`라면**:
    대기열 헤드의 기아 방지를 위해 스핀 가로채기를 엄격히 거절!
    반환: `{"status": "SPIN_STEAL_REJECTED_HANDOFF", "thread_id": thread_id}`.
  - **`handoff_active == false`인 경우**:
    가로채기 성공! `writer_locked = true`, `owner = thread_id`, `spin_steals += 1`.
    반환: `{"status": "SPIN_STEAL_SUCCESS", "thread_id": thread_id}`.
- 락이 점유 중인 경우:
  - 반환: `{"status": "SPIN_STEAL_FAILED_BUSY", "thread_id": thread_id}`.

### 5) 읽기 잠금 해제 (`UP_READ`)
- `thread_id`, `time_us`
- `readers <= 0`인 경우: 언더플로우 에러 `{"status": "ERROR_UNDERFLOW", "thread_id": thread_id}`.
- `readers -= 1`.
- 만약 `readers == 0`이고 대기 큐의 헤드가 `WRITE`라면:
  - 헤드 쓰기 대기자를 팝하고 락을 직접 인계: `writer_locked = true`, `owner = head.thread_id`.
  - 반환: `{"status": "READ_RELEASED", "thread_id": thread_id, "readers": 0, "woken_writer": head.thread_id}`.
- 그 외의 경우:
  - 반환: `{"status": "READ_RELEASED", "thread_id": thread_id, "readers": readers, "woken_writer": null}`.

### 6) 쓰기 잠금 해제 (`UP_WRITE`)
- `thread_id`, `time_us`
- `not writer_locked`인 경우: 에러 `{"status": "ERROR_NOT_LOCKED", "thread_id": thread_id}`.
- `writer_locked = false`, `owner = null`.
- 대기 큐가 비어있지 않은 경우:
  - 헤드가 `WRITE`:
    - 헤드 쓰기 대기자에게 직접 핸드오프: `writer_locked = true`, `owner = head.thread_id`.
    - 반환: `{"status": "WRITE_RELEASED", "thread_id": thread_id, "woken_type": "WRITE", "woken": [head.thread_id], "readers": 0}`.
  - 헤드가 `READ`:
    - **리더 일괄 깨우기 (Reader Wakeup Batching)**!
    - 대기 큐 전두에 위치한 **모든 연속된 `READ` 대기자들을 한꺼번에 팝**하여 락을 부여 (`readers += len(batch)`).
    - `batched_reader_wakes += len(batch)`.
    - 반환: `{"status": "WRITE_RELEASED", "thread_id": thread_id, "woken_type": "READ_BATCH", "woken": [...], "readers": readers}`.
- 대기 큐가 빈 경우:
  - 반환: `{"status": "WRITE_RELEASED", "thread_id": thread_id, "woken_type": "NONE", "woken": [], "readers": 0}`.

### 7) 대기 시간 갱신 및 핸드오프 감시 (`UPDATE_WAITERS_TIME`)
- `time_us`: 현재 시각.
- 대기 큐 헤드의 대기 시간이 `handoff_threshold_us` 이상이면 `handoff_active = true` 설정.
- 반환: `{"status": "HANDOFF_ACTIVATED", "head_thread": head, "wait_duration_us": duration}` 또는 `{"status": "WAITING_NORMAL", "handoff_active": bool}`.

### 8) 통계 조회 (`QUERY_STATS`)
- `readers`, `writer_locked`, `owner`, `waiters_count`, `handoff_active`, `fast_read_hits`, `fast_write_hits`, `spin_steals`, `batched_reader_wakes`를 반환합니다.

---

## 3. 입력 및 출력 형식

### 입력 포맷 (표준 입력 JSON)
```json
{
  "config": {
    "handoff_threshold_us": 1000
  },
  "operations": [
    {"op": "DOWN_WRITE", "thread_id": "W1", "time_us": 100},
    {"op": "DOWN_READ", "thread_id": "R1", "time_us": 110},
    {"op": "DOWN_READ", "thread_id": "R2", "time_us": 120},
    {"op": "UP_WRITE", "thread_id": "W1", "time_us": 200},
    {"op": "QUERY_STATS"}
  ]
}
```

### 출력 포맷 (표준 출력 단일 라인 JSON)
```json
{"results":[...]}
```
모든 키와 값은 공백 없는 압축 JSON(`separators=(',', ':')`) 형식으로 출력합니다.
