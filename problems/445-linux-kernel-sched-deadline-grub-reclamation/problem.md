# Problem #445: 리눅스 커널 실시간 스케줄러: kernel/sched/deadline.c SCHED_DEADLINE GRUB(Greedy Reclamation of Unused Bandwidth) 유휴 대역폭 탐욕적 회수 및 0-Lag 타이머 엔진

## 🌟 개요 (Executive Summary)
리눅스 커널의 최상위 하드 실시간 스케줄러인 `SCHED_DEADLINE`(`kernel/sched/deadline.c`)은 EDF(Earliest Deadline First)와 CBS(Constant Bandwidth Server) 알고리즘을 기반으로 각 실시간 태스크에게 `(runtime Q_i, deadline D_i, period P_i)` 매개변수를 보장합니다.
그러나 고전적인 순수 CBS 환경에서는 태스크가 최악 실행 시간(WCET)에 대비해 큰 예산을 할당받았으나 실제로는 작업을 조기에 완료(Early Completion)했을 때, 남아있는 유휴 예산이 시스템에 환원되지 못하고 그대로 버려져 CPU 유휴 자원이 심각하게 낭비되는 비효율이 존재했습니다.

리눅스 커널 4.13+에서는 실시간 시스템 이론의 대가 Giuseppe Lipari, Luca Abeni, Juri Lelli에 의해 **GRUB (Greedy Reclamation of Unused Bandwidth)** 알고리즘이 메인라인 커널에 전격 머지되었습니다:
- **활성 대역폭($U_{\text{act}}$)의 실시간 추적**:
  - 현재 CPU 상에서 실행 중이거나 실행 대기 중인 모든 활성 실시간 태스크의 공칭 이용률 합산값 $U_{\text{act}} = \sum_{k \in \text{ACTIVE}} U_k$ (여기서 $U_k = Q_k / P_k$)을 동적으로 계산합니다.
- **탐욕적 예산 차감 스케일링 (Greedy Depletion Scaling)**:
  - 태스크가 물리 CPU에서 $\Delta t$ 시간 동안 실행될 때, 순수 CBS처럼 예산을 $\Delta q = \Delta t$로 1:1 차감하지 않고, 현재 활성 이용률을 반영하여 **감속 차감**합니다:
    $$\Delta q = \max\left(U_i, U_{\text{act}}\right) \times \Delta t$$
  - 예를 들어 CPU 상에 이용률 20%($U_{\text{act}} = 0.2$)인 단 하나의 태스크만 존재한다면, 이 태스크는 $1000\mu s$ 동안 물리 실행되더라도 예산은 단 $200\mu s$만 소모되어 남은 80%의 유휴 CPU 대역폭을 탐욕적으로 회수(Reclaim)하여 초과 실행할 수 있습니다.
- **수학적 마감시간 안전성 증명**:
  - 태스크가 유휴 대역폭을 초과 사용하더라도, 다른 실시간 태스크가 깨어나는 즉시 $U_{\text{act}}$가 증가하여 예산 소모율이 즉각 정상화되므로 **시스템의 어떠한 하드 실시간 마감시간(Hard Deadline)도 결코 위반되지 않음**이 수학적으로 보장됩니다.
- **0-Lag 타이머 (Zero-Lag Timer)와 악의적 대역폭 착취 방어**:
  - 태스크가 작업을 일찍 마치고 블록(`BLOCK_TASK`)되었을 때 즉시 $U_{\text{act}}$에서 제외해 버리면, 빠른 주기 슬립/웨이크업을 통해 $U_{\text{act}}$를 인위적으로 낮춰 대역폭을 비정상 탈취하는 취약점이 발생합니다.
  - 리눅스 커널은 해당 태스크가 소모한 예산과 경과 시간의 지연(Lag)이 0이 되는 절대 시각인 **0-Lag 시각($t_{\text{zero\_lag}} = d_i - q_i / U_i$)**까지 해당 태스크의 이용률을 $U_{\text{act}}$에 유지시키며, 타이머가 만료될 때 비로소 $U_{\text{act}}$를 감소시킵니다.

본 문제에서는 리눅스 커널 `kernel/sched/deadline.c`의 SCHED_DEADLINE GRUB 대역폭 동적 회수, 예산 스케일링 차감, 0-Lag 타이머 수명주기 엔진을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
        [ ENQUEUE_TASK(task_id, Q_i, D_i, P_i) ]
                         │
        Calculate nominal utilization U_i = Q_i / P_i
        U_act += U_i
        cur_budget = Q_i, cur_deadline = now + D_i
                         │
                         ▼
        [ STEP_RUN(task_id, elapsed_us) ]
                         │
           Is grub_enabled == True?
          ┌──────────────┴──────────────┐
         Yes                            No (Standard CBS)
          │                             │
          ▼                             ▼
   scale = max(U_i, U_act)              dq = elapsed_us
   dq = round(scale * elapsed_us)       reclaimed = 0
   reclaimed = elapsed_us - dq
          │                             │
          └──────────────┬──────────────┘
                         ▼
          cur_budget -= dq
          total_budget_consumed += dq
          reclaimed_bandwidth += reclaimed
                         │
                         ▼
        [ BLOCK_TASK(task_id) / Early Finish ]
                         │
        Compute Zero-Lag Expiration:
        t_zero_lag = cur_deadline - round(cur_budget / U_i)
        State = INACTIVE_TIMER (Holds U_i in U_act!)
                         │
                         ▼
        [ TIMER_TICK(now) / now >= t_zero_lag ]
                         │
        Zero-Lag Timer Fires!
        U_act = max(0.0, U_act - U_i)
        State = INACTIVE_IDLE
```

---

## ⚙️ I/O 데이터 규격 (Input/Output Specifications)

### 1. 입력 JSON 구조
```json
{
  "config": {
    "u_max": 0.95,
    "grub_enabled": true
  },
  "trace": [
    {"op": "ENQUEUE_TASK", "task_id": "T1", "runtime": 2000, "deadline": 10000, "period": 10000, "timestamp": 0},
    {"op": "STEP_RUN", "task_id": "T1", "elapsed_us": 1000, "timestamp": 1000},
    {"op": "BLOCK_TASK", "task_id": "T1", "timestamp": 1000},
    {"op": "TIMER_TICK", "timestamp": 1500},
    {"op": "GET_STATS"}
  ]
}
```

### 2. 필드 정의
- `config`:
  - `u_max` (float, default=0.95): 스케줄링 허용 최대 실시간 대역폭.
  - `grub_enabled` (bool, default=true): GRUB 대역폭 탐욕적 회수 활성화 여부.
- `trace` 명령어:
  1. `ENQUEUE_TASK`:
     - `task_id` (str): 실시간 태스크 식별자.
     - `runtime` (int): 할당 예산 $Q_i$ ($\mu s$).
     - `deadline` (int): 상대 마감시간 $D_i$ ($\mu s$).
     - `period` (int): 반복 주기 $P_i$ ($\mu s$).
     - `timestamp` (int): 진입 시각.
  2. `STEP_RUN`:
     - `task_id` (str): 실행할 태스크 식별자.
     - `elapsed_us` (int): 물리 실행 시간 ($\mu s$).
     - `timestamp` (int): 완료 시각.
  3. `BLOCK_TASK`:
     - `task_id` (str): 조기 완료 후 블록할 태스크 식별자. 0-Lag 시각 산출.
  4. `TIMER_TICK`:
     - `timestamp` (int): 시간 경과 확인 및 0-Lag 타이머 만료 트리거.
  5. `GET_STATS`:
     - 현재 $U_{\text{act}}$, 총 실행 시간, 소모 예산, 회수 대역폭 통계 조회.

### 3. 출력 JSON 구조
```json
{
  "events": [
    {
      "op": "ENQUEUE_TASK",
      "task_id": "T1",
      "util": 0.2,
      "cur_budget": 2000,
      "cur_deadline": 10000,
      "u_act": 0.2,
      "status": "TASK_ENQUEUED"
    },
    {
      "op": "STEP_RUN",
      "task_id": "T1",
      "elapsed_us": 1000,
      "budget_consumed": 200,
      "remaining_budget": 1800,
      "u_act": 0.2,
      "reclaimed_us": 800,
      "status": "STEP_COMPLETED"
    },
    ...
  ],
  "summary": {
    "grub_enabled": true,
    "u_act": 0.0,
    "total_exec_time_us": 1000,
    "total_budget_consumed_us": 200,
    "reclaimed_bandwidth_us": 800,
    "zero_lag_firings": 1
  }
}
```
