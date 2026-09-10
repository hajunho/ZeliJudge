# [OS/커널/스케줄러] 리눅스 6.6 EEVDF(Earliest Eligible Virtual Deadline First) 스케줄러: 가상 시간(Virtual Time), 래그(Lag), 적격성(Eligibility), 가상 데드라인(Virtual Deadline) 기반 지연시간·처리량 보장 엔진

## 문제 설명

리눅스 커널 2.6.23(2007년)부터 무려 16년간 리눅스 표준 프로세스 스케줄러의 자리를 지켜온 **CFS(Completely Fair Scheduler)**가 리눅스 6.6에서 전격 폐기되고, 피터 질스트라(Peter Zijlstra)와 잉고 몰나르(Ingo Molnar)에 의해 **EEVDF(Earliest Eligible Virtual Deadline First)** 스케줄러로 전면 교체되었습니다.

기존 CFS는 가상 실행 시간(`vruntime`)의 최소값(`min_vruntime`)을 추종하여 장기적인 CPU 대역폭 공평성(Fairness)을 달성하는 데는 뛰어났으나, **지연시간 민감 작업(Latency-sensitive Tasks)**과 **처리량 중심 배치 작업(Throughput-oriented Batch Tasks)** 간의 상충 관계를 수학적으로 해결하지 못했습니다:
- CFS는 오디오(PipeWire/JACK), 실시간 UI 렌더링, 네트워크 패킷 인터럽트 등 짧고 긴급한 작업을 배려하기 위해 `latency_target`, 휴리스틱 프리엠션(`granularity`), 슬리퍼 보너스(`sched_latency`) 등 온갖 경험적 편법(Heuristics)을 누더기처럼 덧대었습니다.
- 이로 인해 I/O 대기 후 깨어난 작업이 다른 작업의 CPU를 부당하게 빼앗는 '슬리퍼 도둑질(Sleeper Latency Thievery)'이나, 반대로 게임 및 오디오 환경에서 0.1초 단위의 간헐적 버벅임(Stuttering/Jitter)이 끊이지 않았습니다.

피터 훈(Peter Hoon, 1995)의 대기열 이론에 기반한 **EEVDF**는 이 문제를 공평성과 지연시간의 두 축으로 분리하여 수학적으로 완벽하게 정립했습니다:
1. **가상 시간(Virtual Time, $V$)과 래그(Lag)**:
   - 런큐 전체의 가중치 합을 $\sum w_i$라 할 때, 런큐 가상 시간 $V$는 $\Delta V = \Delta t \cdot \frac{1024}{\sum w_i}$로 단조 증가합니다.
   - 각 작업의 누적 가상 실행 시간은 $vruntime_i \mathrel{+}= \Delta t_i \cdot \frac{1024}{w_i}$로 갱신됩니다.
   - **래그(Lag)**: 작업 $i$가 이론상 공평하게 받아야 할 시간과 실제 받은 시간의 차이:
     $$lag_i = V - vruntime_i$$
     - $lag_i > 0$: 공평한 몫보다 적게 실행된 불리한 작업 (서비스 지체).
     - $lag_i < 0$: 공평한 몫보다 많이 실행된 유리한 작업 (초과 수혜).
2. **적격성 조건 (Eligibility Condition)**:
   - 작업 $i$는 **자신의 래그가 0 이상일 때만($lag_i \ge 0 \iff vruntime_i \le V$) 실행 적격(Eligible)**으로 판정됩니다.
   - 이미 CPU를 초과 사용한 작업($lag_i < 0$)은 자격을 박탈당해 래그 트리(Lag Tree)에 묶이며, $V$가 $vruntime_i$까지 따라잡을 때까지 스케줄링 후보에서 배제됩니다.
3. **가상 데드라인 (Virtual Deadline, $d_i$)과 선택 공리**:
   - 각 작업은 자신의 목적에 따라 요청 타임슬라이스(Latency Slice, $q_i$)를 가집니다 (예: 오디오 $1\text{ms}$, 일반 웹 $4\text{ms}$, 배치 $8\text{ms}$).
   - 가상 데드라인 $d_i = vruntime_i + q_i \cdot \frac{1024}{w_i}$.
   - **EEVDF 스케줄러는 실행 적격($lag_i \ge 0$)인 작업들 중 가상 데드라인이 가장 빠른 작업($\min d_i$)을 다음 실행 작업으로 선출합니다.**
4. **슬리퍼 래그 감쇠 (Lag Decay on Sleep)**:
   - 작업이 수면(Sleep)에 들어갈 때 누적된 래그는 방치되지 않고 지수 감쇠($lag \cdot e^{-\Delta t / \tau}$)되어, 장시간 대기한 작업이 깨어나 폭발적인 CPU 독점을 일으키지 않도록 방어합니다.

리눅스 커널 시스템 엔지니어링 팀의 일원이 되어, 프로세스들의 Nice 레벨(가중치 $w_i$), 요청 슬라이스 크기($q_i$), 작업량 및 수면 주기를 입력받아 EEVDF 상태 전이, 가상 시간 추적, 적격성 판정, 데드라인 기반 선점 및 래그 감쇠를 정밀하게 시뮬레이션하는 **리눅스 6.6 EEVDF 커널 스케줄러 전산 엔진**을 구현하십시오.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "config": {
    "total_duration_ms": 30.0,
    "tick_ms": 0.5,
    "lag_decay_tau_ms": 10.0
  },
  "tasks": [
    {
      "id": "interactive_ui",
      "nice": 0,
      "slice_ms": 1.0,
      "total_work_ms": 100.0,
      "arrival_time_ms": 0.0,
      "sleep_intervals": []
    },
    {
      "id": "batch_worker",
      "nice": 0,
      "slice_ms": 8.0,
      "total_work_ms": 100.0,
      "arrival_time_ms": 0.0,
      "sleep_intervals": []
    }
  ]
}
```

- `config`:
  - `total_duration_ms` (Float): 전체 시뮬레이션 시간 (ms)
  - `tick_ms` (Float): 스케줄러 틱 단위 (ms)
  - `lag_decay_tau_ms` (Float): 슬리퍼 래그 지수 감쇠 시상수 $\tau$ (ms)
- `tasks`: 작업 목록
  - `id` (String): 작업 고유 식별자
  - `nice` (Integer): Nice 우선순위 (-20 ~ 19, 기본 0)
  - `slice_ms` (Float): EEVDF 요청 레이턴시 슬라이스 $q_i$ (ms)
  - `total_work_ms` (Float): 작업이 필요로 하는 총 CPU 연산량 (ms)
  - `arrival_time_ms` (Float): 작업이 런큐에 도착하는 시점 (ms)
  - `sleep_intervals` (Array of Object): 수면 구간 목록 (`[{"start_ms": 2.0, "end_ms": 8.0}]`)

---

## 출력 형식

표준 출력(stdout)으로 시뮬레이션 요약 및 작업별 스케줄링 통계가 담긴 JSON 객체를 한 줄(Single-line)로 출력합니다.

```json
{
  "simulation_summary": {
    "total_duration_ms": 30.0,
    "final_virtual_time": 15.0,
    "total_tasks": 2,
    "completed_tasks": 0
  },
  "tasks": [
    {
      "task_id": "batch_worker",
      "nice": 0,
      "weight": 1024,
      "slice_ms": 8.0,
      "runtime_ms": 15.0,
      "cpu_share_percent": 50.0,
      "vruntime": 15.0,
      "deadline": 23.0,
      "final_lag": 0.0,
      "context_switches": 15,
      "preemptions_caused": 14,
      "state": "RUNNABLE"
    },
    {
      "task_id": "interactive_ui",
      "nice": 0,
      "weight": 1024,
      "slice_ms": 1.0,
      "runtime_ms": 15.0,
      "cpu_share_percent": 50.0,
      "vruntime": 15.0,
      "deadline": 16.0,
      "final_lag": 0.0,
      "context_switches": 16,
      "preemptions_caused": 15,
      "state": "RUNNING"
    }
  ],
  "timeline_sample": [ ... ]
}
```
