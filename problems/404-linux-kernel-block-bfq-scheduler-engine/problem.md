# 문제 404: Linux 커널 블록 레이어 BFQ(Budget Fair Queueing) 스토리지 I/O 스케줄러 및 저지연 휴리스틱 엔진

## 문제 설명

현대 운영체제의 블록 I/O 계층(`Block Layer`)은 다양한 성능 특성을 갖는 다중 프로세스(웹 서버, 데이터베이스, 배치 컴파일러, 대화형 GUI 애플리케이션 등)로부터 발생하는 디스크 읽기/쓰기 요청을 중재합니다.

과거 리눅스 커널의 표준 공정 큐잉 스케줄러였던 **CFQ(Completely Fair Queueing)**는 각 프로세스에게 고정된 **시간 슬라이스(Time Slice, 예: 100ms)**를 할당하는 방식을 취했습니다. 그러나 저장 장치가 회전식 자기 디스크(HDD)에서 초고속 플래시 메모리(SATA SSD, NVMe SSD) 및 이종 스토리지로 진화함에 따라, 시간 기반 할당은 심각한 불공정성을 야기했습니다. 디스크 헤드의 탐색 위치, 플래시 메모리의 내부 병렬 처리 상태, 요청 블록 크기 등에 따라 동일한 시간 슬라이스 내에 전송할 수 있는 데이터 섹터(Sector) 양이 수십 배 이상 변동하기 때문입니다.

이를 근본적으로 해결하기 위해 Paolo Valente 연구진에 의해 고안되어 리눅스 커널 4.12에 정식 머지된 **BFQ(Budget Fair Queueing, `block/bfq-*.c`, `CONFIG_IOSCHED_BFQ`)**는 시간 대신 **섹터(Sector) 단위의 "예산(Budget)"**을 서비스 단위로 채택한 혁신적인 I/O 스케줄러입니다.

BFQ는 컴퓨터 네트워크 패킷 스케줄링 이론의 걸작인 **$B-WF^2Q+$ (Budget Worst-case Fair Weighted Fair Queueing)** 알고리즘을 스토리지 디바이스 특성에 맞게 개량하여, 각 큐의 최악 서비스 지연(Worst-case Service Lag)을 엄격히 상한으로 제한하면서도 다음의 핵심 메커니즘을 제공합니다:

1. **B-WF2Q+ 서비스 트리 및 가상 시간(Virtual Time) 회계**:
   - 시스템 전체의 가상 시간 $V(t)$는 활성 큐들의 유효 가중치 합에 비례하여 전진합니다.
   - 각 엔티티 $i$는 가상 시작 시각 $S_i = \max(V, F_i^{\text{prev}})$ 및 가상 완료 시각 $F_i = S_i + \frac{B_i}{W_i^{\text{eff}}}$를 가집니다.
   - 적격성 조건(Eligibility): $S_i \le V$를 만족하는 엔티티 중에서만 후보를 선별합니다.
   - 선택 규칙: 적격 엔티티 중 **가장 작은 가상 완료 시각 $F_i$**를 갖는 큐를 In-Service 큐로 선택합니다.
2. **동적 예산 적응(Adaptive Budgeting)**:
   - 할당된 예산을 모두 소진한 큐(`BUDGET_EXHAUSTED`): 대규모 순차 스트리밍으로 간주하여 처리량 극대화를 위해 예산을 2배로 확장합니다($\min(B_{\max}, 2 \times B_i)$).
   - 예산의 절반 미만을 소비하고 큐가 빈 경우(`EMPTY_NO_IDLE`, `EMPTY_TIMEOUT`): 디바이스 점유를 최소화하기 위해 예산을 축소합니다($\max(B_{\min}, \max(s_{\text{actual}}, \lfloor B_i / 2 \rfloor))$).
3. **저지연 대화형 휴리스틱(Low-Latency Heuristics & Weight-Raising)**:
   - 사용자 입력(GUI, 터미널)과 같이 짧은 요청을 간헐적으로 발행하는 대화형 프로세스는 이전 완료 시점 대비 도착 시점 간격(Think-time)이 임계값 이상일 때 새로운 버스트로 판정됩니다.
   - 대화형 큐는 즉시 **가중치 부스팅(Weight-Raising, $W_i \times \text{wr\_boost\_factor}$)**을 부여받아 초저지연 선점을 누립니다.
   - 단, 버스트 누적 섹터가 한계치(`burst_sectors_threshold`)를 초과하거나 유효 시간이 만료되면 즉시 기본 가중치로 감쇠(Decay)합니다.
4. **예측적 유휴 대기(Anticipatory Device Idling)**:
   - 인터랙티브 큐가 요청을 모두 처리하고 비었을 때(`pending == 0`), 즉시 백그라운드 배치 큐로 스위칭하면 디스크 헤드 시크가 발생하거나 인터랙티브 지연이 폭증합니다.
   - BFQ는 디바이스를 최대 `slice_idle` ms 동안 유휴 상태로 대기시킵니다. 대기 시간 내에 후속 요청이 도착하면 스위칭 오버헤드 없이 즉시 처리하며, 만료 시(`EMPTY_TIMEOUT`) 다음 큐로 전환합니다.

여러분의 임무는 리눅스 커널의 BFQ 스토리지 I/O 스케줄러의 코어 아키텍처 및 B-WF2Q+ 스케줄링 엔진을 정밀하게 시뮬레이션하는 시스템을 구현하는 것입니다.

---

## 시스템 아키텍처 다이어그램

```
+========================================================================================+
|                             BFQ Storage I/O Scheduler Architecture                     |
+========================================================================================+

    [ Application Layer ]
         |           |             |
     (Web API)    (DB WAL)    (Batch Backup)
         |           |             |
         v           v             v
+----------------------------------------------------------------------------------------+
|  BFQ Queue Manager & Classifier (block/bfq-iosched.c)                                   |
|   - Queue Tracking: qid, base_weight, dynamic budget B_i, think_time                   |
|   - Low-Latency Heuristic: Detect interactive burst -> Apply Weight-Raising (10x)      |
+----------------------------------------------------------------------------------------+
                               |
                               v
+----------------------------------------------------------------------------------------+
|  B-WF2Q+ Service Tree (block/bfq-wf2q.c)                                               |
|                                                                                        |
|   System Virtual Time: V(t)  <--- Monotonically increases by (sectors / sum(W_active))|
|                                                                                        |
|   Active Entities Pool:                                                                |
|     Queue A:  S_A = max(V, F_prev) ---------> F_A = S_A + B_A / W_A                    |
|     Queue B:  S_B = max(V, F_prev) ---------> F_B = S_B + B_B / W_B                    |
|                                                                                        |
|   Eligibility Filter:  S_i <= V                                                        |
|   Selection Policy:    min(F_i) among eligible queues (tie-break: lexicographical qid) |
+----------------------------------------------------------------------------------------+
                               | Select In-Service Queue
                               v
+----------------------------------------------------------------------------------------+
|  In-Service Queue Execution Loop                                                       |
|                                                                                        |
|   +--------------------------------------------------------------------------------+   |
|   | Dispatch Request -> Device Busy (overhead + ceil(sectors / speed))             |   |
|   +--------------------------------------------------------------------------------+   |
|                               |                                                        |
|                       Request Completed                                                |
|                               |                                                        |
|        [ Budget Exhausted? ] ---> YES ---> Expire: BUDGET_EXHAUSTED (Budget x 2)       |
|                 | NO                                                                   |
|        [ Queue Empty? ]                                                                |
|                 | YES                                                                  |
|         Is Interactive & Idling Enabled?                                               |
|            /            \                                                              |
|          YES             NO                                                            |
|          /                 \                                                           |
|    Enter Anticipatory       Expire: EMPTY_NO_IDLE                                      |
|    Idle (slice_idle ms)     (Downscale Budget)                                         |
|       /          \                                                                     |
|  Arrival      Timeout                                                                  |
|  Caught!      Fired!                                                                   |
|     |            |                                                                     |
|  Resume      Expire: EMPTY_TIMEOUT                                                     |
|  Dispatch    (Downscale Budget)                                                        |
+----------------------------------------------------------------------------------------+
                               |
                               v
+----------------------------------------------------------------------------------------+
|  Underlying Storage Controller / Device (e.g. NVMe / SATA Flash / Mechanical Disk)      |
+----------------------------------------------------------------------------------------+
```

---

## 입출력 형식 및 명세

### 입력 JSON 구조

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 전달됩니다:

```json
{
  "config": {
    "default_budget": 128,
    "max_budget": 512,
    "min_budget": 32,
    "slice_idle": 6,
    "enable_idling": true,
    "device_speed_sectors_per_ms": 10,
    "switch_overhead_ms": 1,
    "enable_low_latency": true,
    "think_time_threshold": 16,
    "burst_sectors_threshold": 128,
    "wr_boost_factor": 10,
    "wr_duration_ms": 150
  },
  "queues": [
    {"qid": "reader_a", "weight": 100},
    {"qid": "reader_b", "weight": 100}
  ],
  "requests": [
    {"req_id": "r1", "qid": "reader_a", "arrival_time": 0, "sectors": 64},
    {"req_id": "r2", "qid": "reader_b", "arrival_time": 5, "sectors": 64}
  ]
}
```

#### 설정 파라미터 필드 명세:
- `default_budget` (int): 큐 생성 시 초기 할당 예산 (섹터 단위).
- `max_budget` (int): 큐 예산 확장 시 최대 상한 (섹터 단위).
- `min_budget` (int): 큐 예산 축소 시 최소 하한 (섹터 단위).
- `slice_idle` (int): 예측 유휴 대기 시간 제한 (ms).
- `enable_idling` (bool): 디바이스 예측 유휴 활성화 여부.
- `device_speed_sectors_per_ms` (int): 스토리지 디바이스의 전송 속도 (섹터/ms).
- `switch_overhead_ms` (int): 다른 큐로 디스패치 전환 시 발생하는 헤드 탐색/컨텍스트 스위칭 오버헤드 (ms).
- `enable_low_latency` (bool): 저지연 가중치 부스팅 활성화 여부.
- `think_time_threshold` (int): 새로운 대화형 버스트로 간주하기 위한 최소 씽크 타임 (ms).
- `burst_sectors_threshold` (int): 가중치 부스팅이 유지되는 최대 누적 버스트 섹터 수.
- `wr_boost_factor` (int): 가중치 부스팅 시 기본 가중치에 곱해지는 배수 (최대 1000 클램핑).
- `wr_duration_ms` (int): 가중치 부스팅 유지 최대 시간 (ms).

---

### 출력 JSON 구조

표준 출력(`sys.stdout`)으로 공백 없이 압축된 단일 JSON 문자열을 출력합니다:

```json
{
  "summary": {
    "total_simulation_time": 45,
    "total_dispatched_requests": 6,
    "total_sectors_served": 384,
    "total_idle_time": 0,
    "total_switch_overhead_time": 2
  },
  "queue_metrics": {
    "reader_a": {
      "base_weight": 100,
      "final_budget": 256,
      "dispatched_count": 3,
      "total_sectors": 192,
      "avg_wait_time_ms": 8.0,
      "avg_service_time_ms": 7.0,
      "weight_raising_count": 0
    },
    "reader_b": {
      "base_weight": 100,
      "final_budget": 256,
      "dispatched_count": 3,
      "total_sectors": 192,
      "avg_wait_time_ms": 14.67,
      "avg_service_time_ms": 7.0,
      "weight_raising_count": 0
    }
  },
  "expirations": [
    {
      "time": 14,
      "qid": "reader_a",
      "reason": "BUDGET_EXHAUSTED",
      "consumed": 128,
      "new_budget": 256,
      "vstart": 1.28,
      "vfinish": 3.84
    }
  ],
  "dispatch_order": ["a1", "a2", "b1", "b2", "a3", "b3"]
}
```

---

## 핵심 스케줄링 수학 및 시뮬레이션 규칙

1. **이벤트 우선순위 (동일 시각 타임스탬프 발생 시)**:
   - Priority 0: `COMPLETION` (디바이스 완료 처리)
   - Priority 1: `ARRIVAL` (워크로드 신규 요청 도착)
   - Priority 2: `IDLE_TIMEOUT` (예측적 유휴 만료 처리)
2. **가상 시간 전진 ($V$)**:
   - 디바이스에서 요청 완료 시:
     $$\Delta V = \frac{\text{sectors}}{\sum_{q \in \text{active}} W_q^{\text{eff}}}$$
   - 모든 활성 큐가 $S_i > V$인 경우 (진행 불능 방지):
     $$V = \max(V, \min_{q \in \text{active}} S_q)$$
3. **요청 처리 소요 시간 ($\Delta t$)**:
   $$\text{overhead} = \begin{cases} \text{switch\_overhead\_ms}, & \text{이전 처리 큐와 다른 큐로 전환 시} \\ 0, & \text{동일 큐 연속 처리 시 또는 첫 디스패치 시} \end{cases}$$
   $$\text{transfer\_time} = \lceil \frac{\text{sectors}}{\text{device\_speed\_sectors\_per\_ms}} \rceil$$
   $$\Delta t = \text{overhead} + \text{transfer\_time}$$
4. **대화형 판정 및 가중치 부스팅**:
   - 큐의 첫 요청 도착 시 또는 `(arrival_time - last_completion_time) >= think_time_threshold`일 때:
     - 새 부스팅 시작: $W_i^{\text{eff}} = \min(1000, W_i \times \text{wr\_boost\_factor})$, 만료 시각 $t_{\text{expire}} = t_{\text{arrival}} + \text{wr\_duration\_ms}$, 누적 섹터 카운터 0 초기화.
   - 요청 완료 시 `cumulative_sectors_in_burst >= burst_sectors_threshold`이거나 `current_time >= wr_until`이면 즉시 부스팅 소멸 ($W_i^{\text{eff}} = W_i$).
