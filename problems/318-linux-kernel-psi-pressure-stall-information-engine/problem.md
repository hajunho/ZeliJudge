# 리눅스 커널 PSI(Pressure Stall Information) 스톨 모니터 및 슬라이딩 윈도우 트리거 엔진 (Linux Kernel PSI Engine)

## 문제 설명

리눅스 커널 4.20부터 도입된 **PSI(Pressure Stall Information, `kernel/sched/psi.c`)**는 시스템 관리자와 컨테이너 오케스트레이터(Kubernetes, Android LMK, Meta oomd)가 CPU, 메모리, I/O 자원의 고갈로 인한 작업 지연(Stall)을 정밀하게 계측하고 조기 경보를 수신할 수 있도록 만든 혁신적인 커널 서브시스템입니다.

과거의 전통적인 지표인 `loadavg`는 실행 대기(Runnable) 작업과 디스크 I/O 대기(Uninterruptible Sleep) 작업을 명확히 분리하지 못했고, 특히 메모리 직접 회수(Direct Reclaim)나 스왑 인(Swap-in)으로 인해 프로세스가 겪는 지연을 전혀 측정하지 못했습니다.

PSI는 리소스별로 2가지 뚜렷한 압력 수준을 정의합니다:
1. **`some`**: 해당 리소스의 결핍으로 인해 **적어도 하나 이상의 태스크가 대기(Stall)**하고 있는 시간의 비율. 이때 다른 CPU 코어는 여전히 생산적인 작업을 수행할 수 있습니다.
2. **`full`**: **모든 비-아이들(Non-idle) 활성 태스크가 동시에 해당 리소스 대기로 인해 멈춰버린** 시간의 비율. 이 상태에서는 어떠한 유의미한 CPU 연산도 진행되지 못하는 **완전한 기아/쓰레싱(Thrashing)**이 발생합니다. *(단, CPU 리소스는 항상 누군가 실행 중일 때 대기가 발생하므로 `full`이 정의되지 않으며 항상 0입니다.)*

```
+---------------------------------------------------------------------------------+
|                   Linux Kernel PSI Architecture (kernel/sched/psi.c)            |
+---------------------------------------------------------------------------------+
| Non-Idle Active Tasks: [Task 1: RUNNING], [Task 2: STALLED_MEM]                 |
+---------------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |  Pressure State Classifier                                                |
   |  - any(task == STALLED_MEM)  --> some = True                              |
   |  - all(task == STALLED_MEM)  --> full = False                             |
   +---------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |  Exponential Moving Average (10s, 60s, 300s Horizons)                     |
   |  avg = avg * exp(-dt/tau) + (stall_time/dt * 100) * (1 - exp(-dt/tau))    |
   +---------------------------------------------------------------------------+
                                         |
                                         v
   +---------------------------------------------------------------------------+
   |  Userspace Triggers (/proc/pressure/* or Cgroup v2 *.pressure)            |
   |  "some 150000 1000000" (Window: 1s, Threshold: 150ms)                      |
   |  - Sliding Window Overlap Accumulator                                     |
   |  - sum_stall >= threshold --> TRIGGER_FIRED (Wakeup poll/epoll)           |
   |  - Cooldown: Rate-limit notification once per window                      |
   +---------------------------------------------------------------------------+
```

### 1. 알고리즘 및 상태 전이 명세

#### 1.1 압력 상태 판정
시간 간격 $\Delta t$ 동안 활성 태스크 목록을 검사합니다:
- **`some`**: `stalled_count > 0`
- **`full`**: `total_active > 0` and `stalled_count == total_active` (단, `cpu` 리소스는 `full = False`)

#### 1.2 지수 이동 평균(EMA) 업데이트
10초, 60초, 300초의 시정수 $	au$에 대해:
$$	ext{factor} = \exp(-\Delta t / 	au)$$
$$	ext{avg} \leftarrow 	ext{round}\left(	ext{old\_avg} 	imes 	ext{factor} + \left(rac{	ext{stall\_us}}{\Delta t} 	imes 100ight) 	imes (1 - 	ext{factor}), 2ight)$$

#### 1.3 슬라이딩 윈도우 트리거 감시 (`REGISTER_TRIGGER`)
사용자 공간 데몬은 `threshold_us`와 `window_us`를 지정하여 비동기 감시를 등록합니다:
- 현재 시각 $t_{	ext{end}}$ 기준으로 $[t_{	ext{end}} - 	ext{window\_us}, t_{	ext{end}}]$ 윈도우 내에 포함된 스톨 시간의 합산 $\sum 	ext{stall}$을 계산합니다.
- $\sum 	ext{stall} \ge 	ext{threshold\_us}$ 이고, 마지막 알림 시점으로부터 `window_us` 이상 경과한 경우 `TRIGGER_FIRED`를 발생시키고 쿨다운을 갱신합니다.

---

## 입력 및 출력 형식

### 입력 형식 (JSON)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {},
  "operations": [
    {"op": "REGISTER_TASK", "pid": 1},
    {"op": "REGISTER_TRIGGER", "trigger_id": "mem_some_50ms", "resource": "memory", "type": "some", "threshold_us": 50000, "window_us": 1000000},
    {"op": "SET_TASK_STATE", "pid": 1, "state": "STALLED_MEMORY"},
    {"op": "STEP_TIME", "delta_us": 60000}
  ]
}
```

### 출력 형식 (JSON)
표준 출력(stdout)으로 공백 없는 단일 행 압축 JSON을 출력합니다:
```json
{
  "stats": {
    "time_steps": 1,
    "triggers_fired": 1,
    "total_some_stalls_us": {"cpu": 0, "memory": 60000, "io": 0},
    "total_full_stalls_us": {"cpu": 0, "memory": 60000, "io": 0}
  },
  "current_time_us": 60000,
  "pressure": {
    "memory": {
      "some": {"avg10": 0.6, "avg60": 0.1, "avg300": 0.02, "total_us": 60000},
      "full": {"avg10": 0.6, "avg60": 0.1, "avg300": 0.02, "total_us": 60000}
    }
  },
  "history": [...],
  "event_log": [...]
}
```
