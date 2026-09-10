# 문제 423: 리눅스 커널 실시간 동시성 및 잠금: rt_mutex 우선순위 상속(Priority Inheritance) 및 전이적 체인 데드락 탐지 엔진

## 1. 개요 (Overview)

실시간 운영체제(RTOS) 및 리눅스 실시간 커널 패치셋(**PREEMPT_RT**)에서 가장 치명적인 동시성 장애 중 하나는 **우선순위 역전(Priority Inversion)** 현상입니다. 우선순위 역전이란 저우선순위 태스크(Low Priority Task)가 공유 자원(Mutex)을 점유하고 있을 때, 고우선순위 태스크(High Priority Task)가 해당 자원을 요청하여 블록된 상태에서, 둘 사이의 중간 우선순위 태스크들(Medium Priority Tasks)이 CPU를 지속적으로 선점(Preemption)함으로써 최상위 실시간 태스크가 기아(Starvation) 상태에 빠지는 현상입니다. 1997년 NASA의 화성 패스파인더(Mars Pathfinder) 탐사 로버가 화성 표면에서 겪은 시스템 무한 재부팅 사고가 바로 이 우선순위 역전 현상에서 기인했습니다.

리눅스 커널은 이를 해결하기 위해 **우선순위 상속 뮤텍스(`rt_mutex` / `kernel/locking/rtmutex.c`, `CONFIG_RT_MUTEXES`)** 메커니즘을 핵심 기반으로 내장하고 있습니다. `rt_mutex`는 고우선순위 태스크가 락을 획득하려다 블록될 경우, 해당 락을 보유한 소유자 태스크에게 일시적으로 고우선순위를 대여(Inheritance)하여 중간 태스크들의 선점을 막고 임계 영역(Critical Section)을 신속히 빠져나오도록 강제합니다.

나아가 태스크들이 여러 개의 락을 중첩하여 소유하고 대기하는 다단계 종속 환경에서는 우선순위 부스팅이 연쇄적으로 전파되는 **전이적 체인(Transitive PI Chain)** 전파 알고리즘(`rt_mutex_adjust_prio_chain`)과, 대기자 그래프 상에서 순환 의존이 발생하는지 사전에 추적하는 **데드락 탐지(Deadlock Detection)** 로직이 필수적입니다.

본 과제에서는 리눅스 커널 `kernel/locking/rtmutex.c`의 핵심 메커니즘인 우선순위 상속, 다중 대기자 정렬, 전이적 PI 전파, 락 해제 시 우선순위 반환(Deboost), 그리고 대기 그래프 순환을 포착하는 데드락 방어 엔진을 시뮬레이터로 완벽히 구현합니다.

---

## 2. 시스템 아키텍처 및 우선순위 역전 해결 흐름

```
[Unbounded Priority Inversion (No PI)]
  T_high (Prio 10)  : ───[Block on M1]─────────────────────────────► [Starved!]
  T_med  (Prio 50)  :          └─────────[Preempts T_low]──────────► [Runs forever]
  T_low  (Prio 90)  : ──[Lock M1]───────(Preempted by T_med)───────► [Blocked]

-------------------------------------------------------------------------------

[Priority Inheritance with rt_mutex]
  T_high (Prio 10)  : ───[Block on M1]───────────────────► [Acquire M1 & Run]
                             │ (PI Boost: 90 -> 10)               ▲
                             ▼                                    │ Lock Handoff
  T_low  (Prio 90)  : ──[Lock M1]──[Boosted Prio 10 runs]──[Unlock M1 (Deboost: 10 -> 90)]
  T_med  (Prio 50)  :             (Cannot Preempt T_low!)

-------------------------------------------------------------------------------

[Transitive PI Chain & Deadlock Graph]
       T_vip (Prio 10)
             │ blocks on M3
             ▼
       T3 (Prio 40)  ──► Boosted to 10
             │ blocks on M2
             ▼
       T2 (Prio 60)  ──► Boosted to 10
             │ blocks on M1
             ▼
       T1 (Prio 80)  ──► Boosted to 10
             │
             └─ (If T1 tries to lock M3 -> CYCLE DETECTED! Returns -EDEADLK)
```

---

## 3. 세부 동작 명세 (Operational Specifications)

### 3.1 우선순위 체계 (Priority System)
- 리눅스 커널 규칙에 따라, 우선순위 수치가 **작을수록 더 높은 우선순위**를 의미합니다 (예: 우선순위 `10`은 우선순위 `80`보다 높음).
- 각 태스크는 기본 우선순위(`normal_prio`)와 유효 우선순위(`effective_prio`)를 갖습니다:
  $$P_{\text{eff}}(T) = \min \left( P_{\text{normal}}(T), \min_{m \in \text{Held}(T)} \left( \min_{w \in \text{Waiters}(m)} P_{\text{eff}}(w) \right) \right)$$

### 3.2 이벤트 명세

1. **`CREATE_TASK` (`time`, `task_id`, `prio`)**:
   - 신규 태스크를 생성합니다. 초기 상태: `normal_prio = prio`, `effective_prio = prio`, `held_locks = []`, `blocked_on = None`.
   - `event_logs`에 `TASK_CREATED`를 기록합니다.

2. **`LOCK` (`time`, `task_id`, `mutex_id`)**:
   - 뮤텍스가 비어있는 경우 (`owner is None`):
     - `task_id`가 락을 즉시 획득합니다 (Fast-Path). `held_locks`에 추가.
     - `event_logs`에 `LOCK_ACQUIRED_FASTPATH`를 기록합니다.
   - 뮤텍스를 이미 본인이 소유한 경우: 즉시 성공 처리.
   - 뮤텍스를 다른 태스크가 소유하고 있는 경우:
     - **데드락 검증 (`_check_deadlock`)**:
       현재 뮤텍스 소유자로부터 시작하여 `blocked_on` 체인을 따라 탐색합니다. 탐색 도중 `task_id`에 도달하면 대기 그래프의 순환(Cycle)이 형성되므로 **데드락**으로 판정합니다.
       - 데드락 발생 시: `deadlocks_prevented` 카운트를 1 증가시키고, `event_logs`에 `DEADLOCK_DETECTED`를 기록하며, 태스크는 블록되지 않고 함수를 종료합니다.
     - 데드락이 없는 경우:
       - `task_id`의 `blocked_on`을 `mutex_id`로 설정하고, 해당 뮤텍스의 `waiters` 큐에 추가합니다.
       - `event_logs`에 `LOCK_BLOCKED`를 기록합니다.
       - **전이적 PI 체인 전파 (`_propagate_chain`)**:
         뮤텍스 소유자부터 시작하여 대기 체인을 순회하며 유효 우선순위를 재계산합니다. 우선순위가 변경(상속)되면 `pi_boost_count`를 증가시키고 `pi_logs`에 `PI_BOOST` 로그를 기록하며, 해당 소유자가 또 다른 락에 블록되어 있다면 다음 소유자로 전파를 지속합니다.

3. **`UNLOCK` (`time`, `task_id`, `mutex_id`)**:
   - `task_id`가 해당 뮤텍스의 소유자가 아니면 무시합니다.
   - `task_id`의 `held_locks`에서 해당 뮤텍스를 제거합니다.
   - `event_logs`에 `LOCK_RELEASED`를 기록합니다.
   - 대기자(`waiters`)가 존재하는 경우:
     - 대기자 중 유효 우선순위가 가장 높은(수치가 가장 작은) 대기자를 선택합니다 (동일 순위 시 먼저 도착한 순서).
     - 선택된 대기자(`top_waiter`)는 대기 큐에서 제거되고, `blocked_on = None`, `held_locks`에 뮤텍스가 추가되며 새 소유자가 됩니다.
     - `event_logs`에 `LOCK_HANDOFF`를 기록하고, `top_waiter`의 유효 우선순위를 갱신합니다.
   - 대기자가 없으면 `mutex.owner = None`으로 설정합니다.
   - 락을 해제한 이전 소유자(`task_id`)의 유효 우선순위를 재계산합니다:
     - 여전히 다른 락을 보유하고 있고 그 락에 대기자가 있다면 해당 대기자들의 최고 우선순위와 자신의 `normal_prio` 중 최솟값을 취합니다.
     - 우선순위가 낮아지면(수치가 커지면) `pi_deboost_count`를 증가시키고 `pi_logs`에 `PI_DEBOOST`를 기록합니다.

4. **`CHANGE_PRIO` (`time`, `task_id`, `new_prio`)**:
   - 리눅스 `sched_setscheduler()` 시스템 콜을 모사합니다.
   - `task_id`의 `normal_prio`를 `new_prio`로 변경합니다.
   - `event_logs`에 `PRIO_CHANGED`를 기록합니다.
   - 해당 태스크 및 해당 태스크가 블록되어 있는 전이적 체인의 유효 우선순위를 재계산하고 전파합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 입력 형식 (Standard Input, JSON)
```json
{
  "config": {},
  "trace": [
    {"time": 10, "type": "CREATE_TASK", "task_id": "T_low", "prio": 90},
    {"time": 20, "type": "CREATE_TASK", "task_id": "T_med", "prio": 50},
    {"time": 30, "type": "CREATE_TASK", "task_id": "T_high", "prio": 10},
    {"time": 40, "type": "LOCK", "task_id": "T_low", "mutex_id": "M_bus"},
    {"time": 50, "type": "LOCK", "task_id": "T_high", "mutex_id": "M_bus"},
    {"time": 60, "type": "UNLOCK", "task_id": "T_low", "mutex_id": "M_bus"},
    {"time": 70, "type": "UNLOCK", "task_id": "T_high", "mutex_id": "M_bus"}
  ]
}
```

### 출력 형식 (Standard Output, Compact JSON)
공백 없는 단일 라인 JSON 문자열(`separators=(',', ':')`)로 출력합니다:
```json
{"summary":{"pi_boost_count":1,"pi_deboost_count":1,"deadlocks_prevented":0,"total_tasks":3,"total_mutexes":1},"tasks":{"T_high":{"normal_prio":10,"effective_prio":10,"held_locks":[],"blocked_on":null},"T_low":{"normal_prio":90,"effective_prio":90,"held_locks":[],"blocked_on":null},"T_med":{"normal_prio":50,"effective_prio":50,"held_locks":[],"blocked_on":null}},"mutexes":{"M_bus":{"owner":null,"waiter_count":0,"waiters":[]}},"pi_logs":[{"time":50,"action":"PI_BOOST","task_id":"T_low","old_prio":90,"new_prio":10},{"time":60,"action":"PI_DEBOOST","task_id":"T_low","old_prio":10,"new_prio":90}],"event_logs":[{"time":10,"event":"TASK_CREATED","task_id":"T_low","prio":90},{"time":20,"event":"TASK_CREATED","task_id":"T_med","prio":50},{"time":30,"event":"TASK_CREATED","task_id":"T_high","prio":10},{"time":40,"event":"LOCK_ACQUIRED_FASTPATH","task_id":"T_low","mutex_id":"M_bus"},{"time":50,"event":"LOCK_BLOCKED","task_id":"T_high","mutex_id":"M_bus","owner":"T_low"},{"time":60,"event":"LOCK_RELEASED","task_id":"T_low","mutex_id":"M_bus"},{"time":60,"event":"LOCK_HANDOFF","mutex_id":"M_bus","from_task":"T_low","to_task":"T_high"},{"time":70,"event":"LOCK_RELEASED","task_id":"T_high","mutex_id":"M_bus"}]}
```
