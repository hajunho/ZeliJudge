# 리눅스 커널 SCHED_DEADLINE 실시간 스케줄러 및 CBS 대역폭 서버 엔진 (Linux Kernel SCHED_DEADLINE Real-Time EDF & CBS Bandwidth Server Engine - kernel/sched/deadline.c)

## 문제 설명

리눅스 커널의 **`SCHED_DEADLINE`(`kernel/sched/deadline.c`)**은 리눅스 커널 3.14에 공식 도입된 최고 우선순위의 실시간 스케줄링 클래스(`dl_sched_class`)입니다. 기존 실시간 스케줄러인 `SCHED_FIFO` 및 `SCHED_RR`이 고정 우선순위(Static Priority, 1~99)에 의존하여 우선순위 역전이나 버그성 무한 루프 시 시스템 전체를 완전히 먹통(CPU Starvation)으로 만드는 치명적 결함을 완벽히 해결하였습니다.

`SCHED_DEADLINE`은 두 가지 핵심 컴퓨터 과학 이론을 결합하여 구현되었습니다:
1. **EDF (Earliest Deadline First)**: 준비 큐(`dl_rq`)에 존재하는 태스크 중 절대 마감시간($d_i$)이 가장 빠른 태스크를 먼저 실행하여 단일 코어에서 이론적으로 100% 대역폭까지 마감시간 위반 없는 최적(Optimal) 스케줄링을 보장합니다.
2. **CBS (Constant Bandwidth Server)**: 각 태스크에 할당된 런타임 예산($Q_i$)과 주기($P_i$)를 강제합니다. 태스크가 할당된 예산을 모두 소진하면 즉시 쓰로틀링(`THROTTLED`)되어 다음 주기 마감시간까지 CPU 점유를 박탈당하므로, 오작동하는 실시간 태스크가 있더라도 시스템 내 다른 태스크나 커널이 고사하지 않습니다.

```
                  Linux Scheduling Class Hierarchy
   +-------------------------------------------------------------+
   | stop_sched_class      (Migration & Hotplug Kernel Threads)  |
   +-------------------------------------------------------------+
                                  |
                                  v
   +=============================================================+
   | dl_sched_class        (SCHED_DEADLINE: EDF + CBS Server)    | <= [THIS PROBLEM]
   +=============================================================+
                                  |
                                  v
   +-------------------------------------------------------------+
   | rt_sched_class        (SCHED_FIFO / SCHED_RR: Priorities)   |
   +-------------------------------------------------------------+
                                  |
                                  v
   +-------------------------------------------------------------+
   | fair_sched_class      (CFS / EEVDF: Virtual Time Scheduling)|
   +-------------------------------------------------------------+
                                  |
                                  v
   +-------------------------------------------------------------+
   | idle_sched_class      (CPU Idle Thread)                     |
   +-------------------------------------------------------------+
```

본 문제에서는 실제 리눅스 커널 `kernel/sched/deadline.c`의 **글로벌 인가 제어(Admission Control: $\sum U_i \le U_{max}$)**, **EDF 레드-블랙 트리 절대 마감시간 우선 스케줄링**, **CBS 예산 소진에 따른 타이머 기반 쓰로틀링/보충(Throttling & Replenishment)**, 및 **수면 복귀 시 마감시간 연기 판정(CBS Wake-up Rule)**을 충실히 모델링한 시뮬레이션 엔진을 구현합니다.

---

## 핵심 메커니즘 및 수리 모델

### 1. 태스크 파라미터 및 인가 제어 (Admission Control)
각 태스크 $T_i$는 3대 파라미터 `(runtime_ms, deadline_ms, period_ms)`로 정의되며, CPU 대역폭 이용률(Utilization)은 다음과 같습니다:

$$U_i = 	ext{round}\left(rac{	ext{runtime\_ms}}{	ext{period\_ms}}, 4ight)$$

- 전체 등록된 실시간 태스크들의 총 대역폭 $U_{total} = \sum U_i$가 시스템 설정 `max_bandwidth` (기본 $0.95$, 즉 95%)를 초과할 경우 커널은 에러코드 `-EBUSY`와 함께 태스크 등록을 거부(`REJECTED`)합니다. 이를 통해 비-실시간 태스크(CFS/EEVDF)를 위한 5% 이상의 CPU 대역폭이 상시 보장됩니다.

### 2. EDF 스케줄링 및 컨텍스트 스위칭
- 상태가 `READY` 또는 `RUNNING`이고 남은 예산 $q_i > 0$인 태스크 중 **가장 이른 절대 마감시간($d_i$)**을 가진 태스크가 CPU를 점유합니다.
- 시간 경과($\Delta t$)에 따라 실행 중인 태스크의 남은 예산이 차감됩니다:
  $$q_i \leftarrow \max(0.0, q_i - \Delta t)$$

### 3. CBS 쓰로틀링 및 예산 보충 (Throttling & Replenishment)
- 실행 중인 태스크의 예산이 $0$에 도달하면($q_i \le 0$), 태스크는 즉시 `THROTTLED` 상태로 전이되어 런큐에서 제거됩니다.
- 현재 가상 시간 $t$가 해당 태스크의 절대 마감시간 $d_i$에 도달하는 순간:
  - 예산 보충: $q_i = Q_i$ (원래 할당량으로 리셋)
  - 마감시간 갱신: $d_i = 	ext{round}(d_i + P_i, 4)$
  - 상태 전이: `status = "READY"`로 복귀하여 다시 EDF 스케줄링 풀에 진입합니다.

### 4. CBS 수면 및 기상 규칙 (Wake-up Rule)
실시간 태스크가 I/O 대기나 타이머 슬립 후 기상(`TASK_WAKEUP`)할 때, 커널은 과거에 남겨둔 예산과 마감시간을 악용하여 다른 태스크를 기아 상태로 몰아넣지 못하도록 다음 검사를 수행합니다:

$$	ext{check\_time} = t + \left(rac{q_i}{Q_i}ight) 	imes D_i$$

- **유지 규칙 (`PRESERVED`)**: $	ext{check\_time} < d_i$라면 짧은 수면을 취한 것으로 간주하여 기존 남은 예산 $q_i$와 마감시간 $d_i$를 그대로 유지합니다.
- **보충 및 연기 규칙 (`REPLENISHED`)**: $	ext{check\_time} \ge d_i$라면 태스크가 너무 오래 잠들어 마감시간을 지났거나 예산 대비 시간이 초과된 것으로 판단, 예산을 $q_i = Q_i$로 완전 보충하고 마감시간을 현재 시간 기준으로 $d_i = 	ext{round}(t + D_i, 4)$로 연기합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "max_bandwidth": 0.95,
    "initial_time_ms": 0.0
  },
  "operations": [
    {"op": "REGISTER_TASK", "task_id": "video_task", "runtime_ms": 10.0, "deadline_ms": 30.0, "period_ms": 30.0},
    {"op": "REGISTER_TASK", "task_id": "audio_task", "runtime_ms": 5.0, "deadline_ms": 20.0, "period_ms": 20.0},
    {"op": "STEP_TIME", "duration_ms": 15.0},
    {"op": "TASK_SLEEP", "task_id": "video_task"},
    {"op": "STEP_TIME", "duration_ms": 5.0},
    {"op": "TASK_WAKEUP", "task_id": "video_task"},
    {"op": "GET_STATE"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과와 최종 누적 통계를 담은 JSON을 출력합니다:

```json
{
  "results": [
    {
      "op": "REGISTER_TASK",
      "task_id": "video_task",
      "status": "ADMITTED",
      "utilization": 0.3333,
      "total_bandwidth": 0.3333,
      "abs_deadline": 30.0,
      "budget": 10.0
    }
  ],
  "final_summary": {
    "current_time": 30.0,
    "running_task": null,
    "total_bandwidth": 0.5833,
    "tasks": {
      "video_task": {
        "status": "READY",
        "budget": 10.0,
        "abs_deadline": 60.0,
        "utilization": 0.3333
      }
    },
    "stats": {
      "admitted_tasks": 2,
      "rejected_tasks": 0,
      "context_switches": 3,
      "throttling_events": 2,
      "replenish_events": 2,
      "deadline_misses": 0
    },
    "event_count": 6
  }
}
```
