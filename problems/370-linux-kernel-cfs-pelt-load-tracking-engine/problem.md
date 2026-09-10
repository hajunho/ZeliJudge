# Linux Kernel CFS PELT (Per-Entity Load Tracking): 32ms 반감기 지수 감쇠, CPU 가동률(util_avg) 대 부하(load_avg) 분리 및 Schedutil 주파수 제어 엔진

## 문제 설명

리눅스 커널의 **완전 공정 스케줄러(CFS) PELT(Per-Entity Load Tracking / `kernel/sched/pelt.c`, `kernel/sched/pelt.h`)**는 멀티코어 시스템에서 각 프로세스(스레드)와 CPU 실행 큐(`cfs_rq`)가 실제로 소모하는 연산 자원의 크기를 추적하는 핵심 부하 추적 서브시스템입니다.

과거 리눅스는 단순히 실행 대기 중인 스레드의 개수나 수면 평균 시간을 측정하는 조잡한 방식을 사용했으나, 이로 인해 순간적인 스파이크와 이력 현상(Hysteresis)이 발생하여 CPU 전력 거버너(`schedutil`)가 클록 주파수를 엉뚱하게 조절하거나 부하 분산기(Load Balancer)가 비효율적인 스레드 이주(Migration)를 반복하는 심각한 문제가 있었습니다.

PELT는 시간을 1024 $\mu	ext{s}$ (1 ms) 단위의 주기로 분할하고, 32개 주기(약 32ms)를 **반감기(Half-Life)**로 삼는 정교한 기하급수적 이동 평균(EMA: Exponential Moving Average)을 도입하여 이 문제를 완벽히 해결했습니다:

```
          [ 연속 시간 타임라인 (1024 us = 1 Period 단위 분할) ]
---+-------------+-------------+-------------+-------------+--->
   |  Period 0   |  Period 1   |  Period 2   |     ...     |
---+-------------+-------------+-------------+-------------+--->
   <------------- 32개 주기 (약 32,768 us = 32ms) ------------->
             (과거의 모든 기여도가 정확히 1/2로 감쇠!)

                   [ 3대 핵심 추적 시그널 분리 ]
  1. util_avg (가동률): 순수 CPU 점유 시간 (Weight와 무관, 0 ~ 1024)
     -> schedutil 거버너가 CPU 클록 주파수(DVFS)를 결정하는 기준!
  2. load_avg (부하): (실행 시간 + 대기 시간) * 스레드 우선순위 가중치(Weight)
     -> CFS 로드 밸런서가 코어 간 부하 균형을 맞출 때 사용!
  3. runnable_avg (실행 가능률): 큐 대기 시간 + 실행 시간 (Weight 무관)
     -> 코어 과포화(Over-utilized) 여부 판정!
```

### 핵심 수리 모델 및 알고리즘

1. **시간 지수 감쇠 (Geometric Decay)**:
   - 감쇠 인자 $y = 0.5^{1/32} pprox 0.97857206$.
   - 무한 등비급수 최대 누적합:
     $$	ext{MAX\_SUM} = \sum_{i=0}^{\infty} 1024 	imes y^i = rac{1024}{1 - y} pprox 47742$$
   - 경과 시간 $\Delta t$ 동안 경과한 전체 주기 수 $k = \lfloor \Delta t / 1024 floor$, 나머지 시간 $r = \Delta t \pmod{1024}$.
   - 기존 누적값은 $y^k$만큼 감쇠하며, 새로운 활동 시간은 등비급수 합으로 누적됩니다.

2. **상태별 시그널 누적 규칙**:
   - `RUNNING`: CPU를 점유하여 실제 실행 중인 상태 $	o$ `util_sum`, `load_sum`, `runnable_sum` 모두 누적.
   - `RUNNABLE`: 실행 큐에서 대기 중인 상태 $	o$ `load_sum`, `runnable_sum`만 누적, `util_sum`은 멈추고 감쇠만 진행.
   - `SLEEPING`: I/O 대기나 락 대기로 잠든 상태 $	o$ 아무것도 누적되지 않으며 모든 합이 시간 경과에 따라 지수 감쇠.

3. **정규화 평균값 산출 (0 ~ 1024 스케일)**:
   - $	ext{util\_avg} = \min\left(1024.0, 	ext{round}\left(rac{	ext{util\_sum}}{	ext{MAX\_SUM}} 	imes 1024.0, 2ight)ight)$
   - $	ext{load\_avg} = 	ext{round}\left(rac{	ext{load\_sum}}{	ext{MAX\_SUM}} 	imes rac{	ext{weight}}{1024.0} 	imes 1024.0, 2ight)$
   - $	ext{runnable\_avg} = \min\left(1024.0, 	ext{round}\left(rac{	ext{runnable\_sum}}{	ext{MAX\_SUM}} 	imes 1024.0, 2ight)ight)$

4. **Schedutil 주파수 조절기 목표 용량 계산**:
   - 각 CPU의 전체 가동률 합에 $1.25$배(25% 헤드룸 마진)를 곱하여 클록 주파수 목표치(`schedutil_target_cap`)를 산출합니다:
     $$	ext{schedutil\_target\_cap} = \min(1024.0, 	ext{round}(	ext{total\_util\_avg} 	imes 1.25, 2))$$

5. **태스크 마이그레이션 (Core Migration)**:
   - 태스크가 다른 CPU 코어로 이동하면, 해당 태스크의 `util_avg`와 `load_avg`가 이전 CPU에서 차감되고 목표 CPU에 즉시 합산됩니다.

본 문제에서는 이 리눅스 커널 PELT 지수 감쇠 수학 모델과 Per-CPU 및 태스크별 집계 엔진을 충실히 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "num_cpus": 2,
  "operations": [
    {"time": 0, "op": "CREATE_TASK", "task_id": "worker-1", "weight": 1024, "cpu": 0},
    {"time": 0, "op": "SET_STATE", "task_id": "worker-1", "new_state": "RUNNING"},
    {"time": 32768, "op": "ADVANCE_TIME"},
    {"time": 65536, "op": "ADVANCE_TIME"},
    {"time": 65536, "op": "SET_STATE", "task_id": "worker-1", "new_state": "SLEEPING"},
    {"time": 98304, "op": "ADVANCE_TIME"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 객체를 공백 없이 출력합니다:

```json
{
  "num_cpus": 2,
  "final_time_us": 98304,
  "cpu_aggregates": {
    "cpu_0": {
      "task_count": 1,
      "total_util_avg": 384.37,
      "total_load_avg": 384.37,
      "schedutil_target_cap": 480.46
    },
    "cpu_1": {
      "task_count": 0,
      "total_util_avg": 0.0,
      "total_load_avg": 0.0,
      "schedutil_target_cap": 0.0
    }
  },
  "task_summaries": {
    "worker-1": {
      "cpu": 0,
      "state": "SLEEPING",
      "weight": 1024,
      "util_avg": 384.37,
      "load_avg": 384.37,
      "runnable_avg": 384.37
    }
  },
  "stats": {
    "task_creations": 1,
    "state_transitions": 2,
    "migrations": 0,
    "schedutil_freq_updates": 0
  },
  "op_log": [
    {
      "time": 0,
      "op": "CREATE_TASK",
      "task_id": "worker-1",
      "cpu": 0,
      "weight": 1024
    }
  ]
}
```
