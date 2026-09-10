# 문제 304: 리눅스 커널 CFS 대역폭 컨트롤러 버스트 및 멀티코어 슬라이스 대여 쓰로틀링 엔진 (Linux Kernel CFS Bandwidth Controller Burst & Multicore Quota Borrowing Engine)

## 문제 설명

쿠버네티스(Kubernetes) 및 컨테이너 런타임(Docker, containerd)에서 CPU 제한(`resources.limits.cpu`)을 설정하면, 리눅스 커널의 **CFS 대역폭 컨트롤러(CFS Bandwidth Controller - `kernel/sched/fair.c`)**가 Cgroup v1/v2의 `cpu.cfs_quota_us` 및 `cpu.cfs_period_us`를 통해 해당 컨테이너의 CPU 점유율을 강제 통제합니다.

전통적인 CFS 대역폭 제어에서는 주기(`period`, 기본 100ms) 동안 컨테이너에 할당된 쿼터(`quota`, 예: 100ms)를 초과하여 CPU를 소비하면, 해당 주기가 끝날 때까지 컨테이너의 모든 스레드가 커널 스케줄러에서 강제 탈락(Dequeue)되어 **CPU 쓰로틀링(Throttling)** 상태에 빠집니다.

그러나 웹 서버나 분산 RPC 서비스는 평소에는 CPU 사용량이 극히 적다가 일시적으로 트래픽 스파이크(Burst)가 인입됩니다. 평소에 쓰지 않고 버려진 쿼터가 많음에도 불구하고 100ms 주기 내의 짧은 스파이크 때문에 불필요하게 쓰로틀링되어 P99 지연시간(Latency)이 튀는 심각한 문제가 발생했습니다.

리눅스 커널 5.14부터 이를 완벽히 해결하기 위해 **CFS 버스트(`cpu.cfs_burst_us`)** 기능이 도입되었습니다:
1. **전역 쿼터 풀(`cfs_b->runtime`)과 코어별 슬라이스 대여(`sched_cfs_bandwidth_slice`)**:
   - 멀티코어 환경에서 락 경합을 줄이기 위해, 각 CPU 코어의 실행 큐(`cfs_rq`)는 전역 풀에서 고정 단위 슬라이스(기본 5ms = 5,000μs)씩 런타임을 대여하여 소비합니다.
2. **버스트 버퍼 축적(`burst_buffer_us`)**:
   - 주기가 종료되는 타이머 인터럽트(`sched_cfs_period_timer`) 시점에 이전 주기에서 다 쓰지 못하고 남은 미사용 쿼터(`total_unused`)는 버려지지 않고 버스트 버퍼에 적립됩니다 (최대 `max_burst_us` 상한선까지 클램핑).
3. **버스트 동적 소비**:
   - 다음 주기가 시작될 때 기본 쿼터에 누적된 버스트 쿼터가 가산되어 즉시 인출 가능한 런타임 풀로 충전됩니다.
   - 이를 통해 일시적 스파이크 시 컨테이너는 기본 쿼터를 초과하여 최대 `quota + max_burst`까지 쓰로틀링 없이 매끄럽게 실행될 수 있습니다.
4. **전역 쿼터 소진 시 즉각 쓰로틀링**:
   - 전역 풀이 완전히 고갈되면 슬라이스를 대여하지 못한 `cfs_rq`는 즉시 쓰로틀링되어 다음 주기 시작 전까지 정지됩니다.

본 문제에서는 리눅스 커널 5.14+ CFS 대역폭 버스트 및 멀티코어 슬라이스 대여 메커니즘을 마이크로초 단위로 시뮬레이션하여, 각 코어의 실행 결과, 쓰로틀링 발생 여부 및 최종 스케줄러 통계를 출력하는 **CFS 대역폭 버스트 엔진**을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 다음과 같은 단일 JSON 객체가 주어집니다:

```json
{
  "period_us": 100000,
  "quota_us": 100000,
  "max_burst_us": 50000,
  "slice_us": 5000,
  "num_cpus": 2,
  "commands": [
    {"op": "RUN", "cpu": 0, "execution_time_us": 40000},
    {"op": "PERIOD_TICK"},
    {"op": "RUN", "cpu": 0, "execution_time_us": 80000},
    {"op": "RUN", "cpu": 1, "execution_time_us": 70000}
  ]
}
```

- `period_us`: 대역폭 평가 주기 (μs, 기본 100,000μs = 100ms).
- `quota_us`: 주기당 기본 허용 쿼터 (μs, 기본 100,000μs).
- `max_burst_us`: 최대 이월 적립 가능한 버스트 상한선 (μs, 0이면 버스트 미사용).
- `slice_us`: 각 CPU 코어가 전역 풀에서 한 번에 대여하는 슬라이스 크기 (기본 5,000μs).
- `num_cpus`: CPU 코어 수 ($1 \le \text{num\_cpus} \le 64$).
- `commands`: 실행할 명령어 리스트:
  - `RUN`: `{"op": "RUN", "cpu": int, "execution_time_us": int}` (해당 코어에서 지정된 마이크로초 동안 태스크 실행).
  - `PERIOD_TICK`: `{"op": "PERIOD_TICK"}` (주기 타이머 만료: 미사용 쿼터 버스트 이월, 쿼터 재충전, 모든 쓰로틀 해제).

---

## 출력 형식

표준 출력(stdout)으로 다음 구조를 갖는 단일 JSON 객체를 한 줄로 출력합니다:

```json
{
  "command_results": [
    {
      "op": "RUN",
      "result": {
        "cpu_id": 0,
        "executed_us": 40000,
        "throttled": false,
        "reason": "OK"
      }
    },
    {
      "op": "PERIOD_TICK",
      "result": {
        "period_count": 1,
        "replenished_runtime_us": 150000,
        "assigned_burst_us": 50000,
        "all_unthrottled": true
      }
    },
    {
      "op": "RUN",
      "result": {
        "cpu_id": 0,
        "executed_us": 80000,
        "throttled": false,
        "reason": "OK"
      }
    },
    {
      "op": "RUN",
      "result": {
        "cpu_id": 1,
        "executed_us": 70000,
        "throttled": false,
        "reason": "OK"
      }
    }
  ],
  "final_stats": {
    "time_us": 100000,
    "period_count": 1,
    "global_runtime_remaining_us": 0,
    "nr_throttled": 0,
    "throttled_time_us": 0,
    "throttled_rq_cpus": []
  }
}
```

---

## 제약 사항

- $1000 \le \text{period\_us} \le 10^6$
- $1000 \le \text{quota\_us} \le 10^7$
- $0 \le \text{max\_burst\_us} \le 10^7$
- $100 \le \text{slice\_us} \le 50000$
- $1 \le \text{num\_cpus} \le 64$
- 메모리 제한: 512 MB
- 실행 시간 제한: 3.0 초
