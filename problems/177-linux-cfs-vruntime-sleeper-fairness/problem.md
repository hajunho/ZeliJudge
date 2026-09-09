# Problem 177: Linux CFS 스케줄러 vruntime, Nice 가중치 스케줄링과 슬리퍼 기아(Sleeper Starvation) 방어

## 문제 설명

대규모 멀티미디어 스트리밍 서버 클러스터를 운영하던 플랫폼 엔지니어링 팀은 기이한 성능 저하 장애를 겪었습니다.
음악 스트리밍 데몬(`audio`)과 배치 컴파일/머신러닝 전처리 워커(`worker`)가 동일한 서버 코어에서 실행되던 중,
주기적으로 50ms 동안 잠들어 있다가 깨어나는 `audio` 스레드가 발생할 때마다 **`worker` 스레드가 50ms 이상 아무런 CPU도 할당받지 못하고 완전히 멈추는 극심한 지연 시간(Latency Spike) 참사**가 발생한 것입니다.

조사 결과, 운영체제 스케줄러가 **Linux CFS(Completely Fair Scheduler)**의 핵심 안정화 메커니즘인 **Sleeper Fairness (`FAIR_SLEEPERS`)**를 적용하지 않고, 오랜 시간 잠들어 있던 태스크의 과거 `vruntime`을 그대로 인정하면서 발생한 **슬리퍼 CPU 독점 기아(Sleeper Starvation of others)** 현상으로 밝혀졌습니다.

당신은 Linux CFS 스케줄러의 $vruntime$ 진행, Nice 가중치 매핑, 단조 증가 `min_vruntime` 추적, 그리고 **슬리퍼 기아 방어 클램핑 알고리즘**을 정밀하게 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 핵심 스케줄링 규칙

### 1. Nice 값과 가중치 매핑 (`NICE_TO_WEIGHT`)
Nice 값(-20 ~ 19)은 리눅스 커널 표준 40단계 가중치 테이블에 매핑됩니다:
- `nice = 0` $\to$ `weight = 1024`
- `nice = -5` $\to$ `weight = 3121`
- `nice = 5` $\to$ `weight = 335`
- `nice = -20` $\to$ `weight = 88761`, `nice = 19` $\to$ `weight = 15`

### 2. 가상 실행 시간(vruntime) 증가
태스크가 1ms (1 tick) 동안 실행될 때 $vruntime$은 다음과 같이 증가합니다:
$$\Delta vruntime = 1.0 \times \frac{1024.0}{\text{weight}}$$

### 3. 디스패치 및 선점 (Dispatching)
매 틱마다 `RUNNABLE` 및 `RUNNING` 상태인 태스크들 중 **$vruntime$이 가장 작은 태스크**가 실행됩니다.
- $vruntime$이 동일할 경우(부동소수점 오차 방지를 위해 소수점 6자리 반올림 기준), `task_id`의 사전순(오름차순)으로 타이브레이킹합니다.
- 선택된 태스크는 1ms 동안 `RUNNING` 상태가 되며, 나머지 태스크는 `RUNNABLE` 상태로 대기합니다.
- 대기 중인 모든 `RUNNABLE` 태스크는 대기 시간(`current_wait_time`)이 1ms씩 누적되며, 각 태스크의 최대 연속 대기 시간(`max_wait_latency_ms`)을 갱신합니다.

### 4. `min_vruntime` 단조 증가 추적
`min_vruntime`은 현재 활성 상태인 모든 실행 가능(`RUNNABLE`, `RUNNING`) 태스크들의 $vruntime$ 최솟값을 추적하며, 절대 감소하지 않습니다:
$$\text{min\_vruntime} \leftarrow \max(\text{min\_vruntime}, \min_{t \in \text{active}} t.vruntime)$$
- 신규 태스크(`create_task`)가 생성되면 `task.vruntime = min_vruntime`으로 초기화됩니다.

### 5. 슬리퍼 기아 방어 (`wake_up` 시점의 Sleeper Fairness)
잠들어 있던 태스크(`SLEEPING`)가 깨어날 때:
- `enable_sleeper_fairness == True`인 경우:
  $$\text{thresh} = \frac{\text{sched\_latency\_ms}}{2.0}$$
  $$\text{task.vruntime} = \max(\text{task.vruntime}, \text{min\_vruntime} - \text{thresh})$$
  잠들어 있는 동안 뒤처졌던 $vruntime$을 현재 기준 시계에서 최대 `thresh` ms만큼만 앞서도록 상한선 클램핑합니다.
- `enable_sleeper_fairness == False`인 경우:
  $vruntime$을 전혀 보정하지 않고 과거의 낮은 값을 그대로 유지합니다. 이로 인해 깨어난 태스크가 다른 태스크를 굶기며 CPU를 장시간 독점하게 됩니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "sched_latency_ms": 6.0,
    "min_granularity_ms": 1.0,
    "enable_sleeper_fairness": true
  },
  "total_ticks": 120,
  "events": [
    {"tick": 0, "type": "create_task", "task_id": "worker", "nice": 0},
    {"tick": 0, "type": "create_task", "task_id": "audio", "nice": 0},
    {"tick": 10, "type": "sleep", "task_id": "audio", "duration": 50}
  ]
}
```

- `config.sched_latency_ms`: 스케줄링 레이턴시 목표값 (기본 6.0)
- `config.enable_sleeper_fairness`: 슬리퍼 공정성 클램핑 활성화 여부 (`true` 또는 `false`)
- `total_ticks`: 총 시뮬레이션 틱 수 (1 tick = 1 ms)
- `events`: 틱별 발생 이벤트 배열 (`create_task`, `sleep`, `wake`)

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "verdict": "INTERACTIVE_SLEEPER_FAIR_RESPONSE",
  "min_vruntime": 83.0,
  "max_wait_latency_ms": 4.0,
  "tasks": {
    "audio": {
      "nice": 0,
      "weight": 1024,
      "total_exec_time_ms": 37.0,
      "final_vruntime": 84.0,
      "max_wait_latency_ms": 1.0
    },
    "worker": {
      "nice": 0,
      "weight": 1024,
      "total_exec_time_ms": 83.0,
      "final_vruntime": 83.0,
      "max_wait_latency_ms": 4.0
    }
  }
}
```

### 판정(Verdict) 기준
1. `CATASTROPHIC_SLEEPER_CPU_MONOPOLY`:
   - `enable_sleeper_fairness == false`이고, 런큐 내 태스크의 `max_wait_latency_ms >= 20.0`인 경우 (슬리퍼가 깨어나 다른 태스크를 20ms 이상 굶겨 죽임).
2. `INTERACTIVE_SLEEPER_FAIR_RESPONSE`:
   - `enable_sleeper_fairness == true`이고, 하나 이상의 태스크가 `sleep` 후 깨어난 이력이 있는 경우 (인터랙티브 응답성을 유지하면서 기아 방지 성공).
3. `COMPLETELY_FAIR_WEIGHTED_SHARING`:
   - 그 외의 경우 (슬립 이벤트 없이 가중치에 따라 공정하게 시분할 실행).
