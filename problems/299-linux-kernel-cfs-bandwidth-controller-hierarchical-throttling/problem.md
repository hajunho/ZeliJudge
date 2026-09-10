# 리눅스 커널 CFS 대역폭 제어기 및 계층적 쓰로틀링 (Linux Kernel CFS Bandwidth Controller & Hierarchical Throttling)

## 문제 설명

리눅스 커널의 **CFS(Completely Fair Scheduler) 대역폭 제어기(`kernel/sched/fair.c`)**는 cgroup v1/v2 환경에서 컨테이너 및 프로세스 그룹의 최대 CPU 사용량(`cpu.cfs_quota_us`, `cpu.cfs_period_us`, `cpu.max`)을 엄격하게 제한하는 핵심 서브시스템입니다. 쿠버네티스(Kubernetes)의 CPU Limits(`resources.limits.cpu`) 및 도커(Docker)의 `--cpus` 플래그는 모두 이 커널 메커니즘을 기반으로 동작합니다.

멀티코어 시스템에서 전역 락(Global Lock) 경합을 회피하기 위해, CFS 대역폭 제어기는 **전역 런타임 풀(`cfs_b->runtime`)**에서 각 CPU 실행 큐(`cfs_rq`)로 일정 크기의 조각(Slice, 통상 5ms)을 미리 인출하여 사용하는 **2단계 슬라이스 대여(Slice Borrowing) 모델**을 채택하고 있습니다. 할당된 주기가 끝나기 전에 전역 쿼터가 모두 고갈되면 해당 cgroup의 모든 스레드는 실행 큐에서 제거되어 **쓰로틀링(Throttling - `throttle_cfs_rq()`)**되며, 주기 타이머(`cfs_period_us`, 기본 100ms)가 만료되어 쿼터가 보충될 때까지 CPU 스케줄링에서 완전히 배제됩니다.

또한 리눅스 5.14+ 커널부터는 일시적인 트래픽 급증(Traffic Burst) 시 불필요한 레이턴시 급증과 쓰로틀링을 방지하기 위해, 이전 주기의 미사용 쿼터를 이월할 수 있는 **CPU 버스트(`cpu.cfs_burst_us`)** 기능이 추가되었습니다.

본 문제에서는 실제 리눅스 커널 `kernel/sched/fair.c`의 CFS 대역폭 제어기 동작을 충실하게 모델링하여, 다중 CPU 런타임 분배, 계층적 쓰로틀링, 주기 만료 언쓰로틀링, 그리고 CPU 버스트 누적 시뮬레이터를 구현합니다.

---

## 동작 명세

### 1. 설정 매개변수
- `period_us`: 쿼터 갱신 주기 (기본값: 100,000µs = 100ms).
- `quota_us`: 한 주기 동안 그룹 내 모든 CPU가 소모할 수 있는 최대 CPU 시간.
- `slice_us`: 각 CPU 런큐가 전역 풀에서 한 번에 인출해 오는 최소 대여 슬라이스 (기본값: 5,000µs = 5ms).
- `burst_us`: 미사용 쿼터의 최대 누적 허용량 (`cfs_burst_us`, 0이면 버스트 비활성화).
- `num_cpus`: 시스템 가상 CPU 코어 수.
- `parent_quota_us`: (선택적) 상위 부모 cgroup의 쿼터. 지정된 경우 계층적 제약을 적용합니다.

### 2. 주기 타이머 및 쿼터 보충 (`_on_period_expire`)
- 시간이 경과하여 `period_us` 경계(`100ms, 200ms, ...`)를 지날 때마다 주기 타이머가 발화합니다:
  1. **버스트 누적 (`burst_buffer`)**:
     - `max_burst_us > 0`이고 현재 주기에 남은 런타임(`runtime_remaining > 0`)이 있다면:
       $$	ext{burst\_buffer} = \min(	ext{max\_burst\_us}, 	ext{burst\_buffer} + 	ext{runtime\_remaining})$$
     - 만약 런타임이 고갈되었거나 0 이하이면 `burst_buffer = 0`으로 초기화됩니다.
  2. **쿼터 재충전**:
     $$	ext{runtime\_remaining} = 	ext{quota\_us} + 	ext{burst\_buffer}$$
     (부모 쿼터가 존재할 경우 부모의 런타임도 `parent_quota_us`로 리셋)
  3. **언쓰로틀링(Unthrottle)**:
     - 쓰로틀 상태였던 모든 CPU 런큐의 `throttled` 플래그를 해제(`False`)하고 정상 실행 상태로 복구합니다.

### 3. 작업 실행 (`RUN_TASK`)
- 특정 CPU에서 `duration_us`만큼의 CPU 연산 작업을 요청합니다:
  1. 이미 해당 CPU가 `throttled == True`인 상태라면 작업을 전혀 실행하지 못하고 즉시 `THROTTLED` 상태로 반환되며, 요청 시간 전체가 `throttled_time_us` 통계에 합산됩니다.
  2. CPU 로컬 슬라이스(`cpu["slice"]`)가 남아 있다면 먼저 차감하여 실행합니다.
  3. 로컬 슬라이스가 부족하면 전역 런타임 풀에서 `claim = min(slice_us, runtime_remaining)`만큼 인출하여 슬라이스를 보충합니다. (부모 쿼터가 존재하면 부모 풀에서도 동시 차감)
  4. 만약 전역 런타임(또는 부모 런타임)이 0 이하로 고갈되어 더 이상 슬라이스를 빌려올 수 없다면:
     - 해당 CPU는 즉시 **쓰로틀링(`throttled = True`)** 처리됩니다.
     - `nr_throttled += 1` 증가, 미실행 잔여 시간이 `throttled_time_us`에 누적됩니다.
     - 작업은 `PARTIALLY_THROTTLED` 상태로 반환됩니다.
  5. 버스트 풀(`runtime_remaining > quota_us`)에서 런타임이 인출된 경우 `burst_used_us` 통계에 합산합니다.

---

## 입력 형식

JSON 형식으로 표준 입력에 전달됩니다.

```json
{
  "config": {
    "period_us": 100000,
    "quota_us": 50000,
    "burst_us": 30000,
    "slice_us": 5000,
    "num_cpus": 2
  },
  "actions": [
    {"type": "RUN_TASK", "time_us": 10000, "cpu_id": 0, "duration_us": 20000},
    {"type": "ADVANCE_TIME", "time_us": 100000},
    {"type": "RUN_TASK", "time_us": 110000, "cpu_id": 0, "duration_us": 70000}
  ]
}
```

---

## 출력 형식

```json
{
  "history": [
    {
      "time_us": 10000,
      "event": "TASK_EXEC",
      "cpu_id": 0,
      "requested_us": 20000,
      "executed_us": 20000,
      "status": "COMPLETED"
    },
    {
      "time_us": 100000,
      "event": "PERIOD_EXPIRED_REFILL",
      "period": 1,
      "refilled_runtime": 80000,
      "burst_buffer": 30000,
      "unthrottled_cpus": []
    },
    {
      "time_us": 110000,
      "event": "TASK_EXEC",
      "cpu_id": 0,
      "requested_us": 70000,
      "executed_us": 70000,
      "status": "COMPLETED"
    }
  ],
  "stats": {
    "periods": 1,
    "nr_throttled": 0,
    "throttled_time_us": 0,
    "total_runtime_consumed": 90000,
    "burst_used_us": 30000
  },
  "final_state": {
    "current_time_us": 110000,
    "periods_elapsed": 1,
    "runtime_remaining_us": 10000,
    "burst_buffer_us": 30000,
    "cpus": {
      "0": {"slice_us": 0, "throttled": false, "total_executed_us": 90000},
      "1": {"slice_us": 0, "throttled": false, "total_executed_us": 0}
    }
  }
}
```
