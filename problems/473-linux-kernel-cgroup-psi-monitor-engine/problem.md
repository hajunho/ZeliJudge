# 리눅스 커널 Cgroup v2 PSI(Pressure Stall Information) 윈도우 모니터 및 OOM 스톨 엔진

## 1. 개요 및 배경

전통적인 리눅스 시스템 모니터링 지표(CPU 로드 애버리지, 가용 메모리 바이트 수, 디스크 I/O IOPS)는 시스템이 **실제로 멈추고 있는지(Thrashing)** 아니면 자원을 최대 한도로 유용하게 쓰고 있는지 구분하지 못합니다.
예를 들어, 메모리 사용률이 99%라도 페이지 캐시가 원활히 작동하면 시스템은 빠르지만, 가용 메모리가 20% 남아있어도 심각한 메모리 단편화나 직접 회수(Direct Reclaim)로 인해 모든 프로세스가 동결될 수 있습니다.

이 문제를 해결하기 위해 Facebook(Meta)이 주도하고 리눅스 4.20 커널에 병합된 핵심 하부 시스템이 바로 **PSI(Pressure Stall Information, `kernel/sched/psi.c`)**입니다.
PSI는 시스템 또는 Cgroup 내 태스크들이 CPU, 메모리, I/O 자원을 기다리느라 CPU 사이클을 낭비하는 시간 비율을 정량적으로 계측합니다.

PSI의 핵심 분류 및 아키텍처:
1. **스톨 상태의 이원화 (`SOME` vs `FULL`)**:
   - `SOME`: 하나 이상의 태스크가 해당 자원(메모리 페이지 회수, 디스크 I/O 대기 등)으로 인해 지연되고 있으나, 다른 CPU 코어는 여전히 유용한 작업을 수행 중인 상태.
   - `FULL`: 해당 Cgroup(또는 시스템)의 **모든 활성 태스크가 동시에 100% 동결**되어 CPU 생산성이 완전히 제로(0)가 된 치명적 스톨 상태. (단, CPU 압박은 `SOME`만 존재하며 `FULL`은 수학적으로 존재하지 않음).
2. **슬라이딩 윈도우 트리거 (`epoll` 이벤트 통지)**:
   - 유저 공간 OOM 데몬(`systemd-oomd`, Android `lmkd`, Meta `oomd`)은 커널의 `/proc/pressure/...` 또는 `cgroup.pressure` 파일에 특정 임계값(`threshold_us`)과 슬라이딩 감시 윈도우(`window_us`)를 등록합니다.
   - 윈도우 내 누적 스톨 시간이 임계치를 초과하는 즉시 커널은 `epoll`(`POLLPRI`) 이벤트를 발생시켜 데몬을 깨웁니다.
3. **선제적 OOM Killer 및 자원 복구**:
   - 커널 커널 공간의 패닉성 OOM Killer가 시스템 전체를 동결시키기 전에, 유저 공간 데몬이 PSI 경보를 받아 가장 메모리를 많이 낭비하는 악성 태스크만 핀포인트로 사살(`OOM_KILL_ACTION`)하여 무중단 서비스를 유지합니다.

본 과제에서는 리눅스 커널 `kernel/sched/psi.c` 및 Cgroup v2 계층형 압박 전파, 슬라이딩 윈도우 스톨 적산, 쿨다운 제어, 선제적 OOM 트리거 엔진을 정밀 시뮬레이션합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------------+
|                                Userspace OOM Daemon                                     |
|   1. Register PSI Trigger: cgroup="cg_web", type="full", thresh=50ms, win=200ms         |
|   2. epoll_wait() on /sys/fs/cgroup/cg_web/memory.pressure                              |
+-----------------------------------------------------------------------------------------+
                                         ^
                                         | POLLPRI Notification (Trigger Fired!)
                                         v
+-----------------------------------------------------------------------------------------+
|                                Linux Kernel (kernel/sched/psi.c)                        |
|                                                                                         |
|   [ Cgroup v2 Unified Hierarchy ]                                                       |
|   root                                                                                  |
|    └── cg_web                                                                           |
|         ├── Task 1: MEMSTALL (Direct Reclaim)                                           |
|         └── Task 2: MEMSTALL (Swap Page-In)                                             |
|                                                                                         |
|   [ Instant Stall Evaluation at Time t ]                                                |
|   - Active tasks in cg_web: 2                                                           |
|   - Tasks in MEMSTALL: 2 (100%!)                                                        |
|   => cg_web memory: { SOME: true, FULL: true }                                          |
|                                                                                         |
|   [ Sliding Window Monitor (win = 200ms) ]                                              |
|   - Accumulated full stall in [t - 200ms, t]: 60ms >= 50ms (Threshold Exceeded!)        |
|   - Cooldown checked (t - last_fired >= cooldown) => FIRE TRIGGER!                      |
+-----------------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------------+
|                          Action: OOM_KILL_ACTION                                        |
|   Terminate offending leaker task -> 100% Full Stall instantly resolved to Normal!       |
+-----------------------------------------------------------------------------------------+
```

---

## 3. 핵심 규칙 및 상태 전이 사양

### 3.1 Cgroup 계층 및 태스크 상태
- 태스크 상태:
  - `"RUNNING"`: 정상 CPU 실행 중.
  - `"MEMSTALL"`: 메모리 회수/스왑 대기 중 (메모리 스톨 기여).
  - `"IOWAIT"`: 디스크 블록 I/O 완료 대기 중 (I/O 스톨 기여).
  - `"CPU_QUEUED"`: 런큐 대기 중 (CPU `SOME` 스톨 기여).
  - `"SLEEPING"`: 자발적 수면 (비활성, 스톨 모수에 포함되지 않음).
  - `"TERMINATED"`: 종료됨 (비활성).
- 계층형 전파:
  - 자식 Cgroup에 속한 태스크는 부모 Cgroup(예: `root`)의 태스크 집합에도 자동으로 포함됨.

### 3.2 순간 스톨(Instant Stall) 판정 규칙
Cgroup 내 활성 태스크($N = 	ext{count of active tasks}$)에 대해:
- $N == 0$: 모든 스톨은 `false`.
- **Memory**:
  - `some`: `MEMSTALL` 상태인 태스크 수가 1개 이상이면 `true`.
  - `full`: 활성 태스크 100%($	ext{count} == N$)가 `MEMSTALL`이면 `true`.
- **I/O**:
  - `some`: `IOWAIT` 상태인 태스크 수가 1개 이상이면 `true`.
  - `full`: 활성 태스크 100%($	ext{count} == N$)가 `IOWAIT`이면 `true`.
- **CPU**:
  - `some`: `CPU_QUEUED` 상태인 태스크 수가 1개 이상이면 `true`.
  - `full`: 항상 `false` (리눅스 커널 공식 명세: CPU 압박은 `full`이 존재하지 않음).

### 3.3 시간 진행 및 윈도우 스톨 적산 (`ADVANCE_TIME`)
- `delta_us`: 시뮬레이션 시간을 `delta_us`만큼 전진.
- 해당 시간 구간 동안 각 Cgroup별 순간 스톨 상태를 기록.
- 등록된 각 트리거에 대해 현재 시각 $t_{end}$ 기준 $[t_{end} - 	ext{window\_us}, t_{end}]$ 윈도우 내부의 총 스톨 시간 적산.
- 적산 스톨 $\ge 	ext{threshold\_us}$이고 쿨다운($(t_{end} - 	ext{last\_fired}) \ge 	ext{cooldown\_us}$)이 충족되면 트리거 이벤트 발생.

### 3.4 쿼리 및 OOM 액션
- `QUERY_PSI`: 누적된 `total_some_us`, `total_full_us` 및 현재 시점의 `current_stall` 조회.
- `OOM_KILL_ACTION`: 특정 태스크를 사살(`TERMINATED`)하여 스톨 원인 제거.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {},
  "operations": [
    {"type": "CREATE_CGROUP", "name": "cg_web", "parent": "root"},
    {"type": "REGISTER_TRIGGER", "trigger_id": "trig_mem_1", "cgroup": "cg_web", "resource": "memory", "stall_type": "some", "threshold_us": 50000, "window_us": 200000},
    {"type": "TASK_STATE_TRANSITION", "task_id": "t1", "cgroup": "cg_web", "state": "MEMSTALL"},
    {"type": "ADVANCE_TIME", "delta_us": 60000},
    {"type": "QUERY_PSI", "cgroup": "cg_web", "resource": "memory"}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "CREATE_CGROUP",
      "name": "cg_web",
      "parent": "root",
      "status": "CREATED"
    },
    {
      "op_index": 1,
      "type": "REGISTER_TRIGGER",
      "trigger_id": "trig_mem_1",
      "cgroup": "cg_web",
      "status": "REGISTERED"
    },
    {
      "op_index": 2,
      "type": "TASK_STATE_TRANSITION",
      "task_id": "t1",
      "cgroup": "cg_web",
      "state": "MEMSTALL"
    },
    {
      "op_index": 3,
      "type": "ADVANCE_TIME",
      "delta_us": 60000,
      "current_time_us": 60000,
      "triggers_fired": [
        {
          "trigger_id": "trig_mem_1",
          "cgroup": "cg_web",
          "resource": "memory",
          "stall_type": "some",
          "timestamp_us": 60000,
          "window_stall_us": 60000,
          "threshold_us": 50000,
          "window_us": 200000
        }
      ]
    },
    {
      "op_index": 4,
      "type": "QUERY_PSI",
      "cgroup": "cg_web",
      "resource": "memory",
      "total_some_us": 60000,
      "total_full_us": 60000,
      "current_stall": {
        "some": true,
        "full": true
      }
    }
  ],
  "trigger_events": [
    {
      "trigger_id": "trig_mem_1",
      "cgroup": "cg_web",
      "resource": "memory",
      "stall_type": "some",
      "timestamp_us": 60000,
      "window_stall_us": 60000,
      "threshold_us": 50000,
      "window_us": 200000
    }
  ],
  "summary": {
    "total_operations": 5,
    "total_time_us": 60000,
    "stats": {
      "total_trigger_firings": 1,
      "total_state_transitions": 1,
      "total_time_advanced_us": 60000,
      "oom_actions": 0
    }
  }
}
```
