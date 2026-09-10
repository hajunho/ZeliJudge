# #374 - 리눅스 커널 블록 레이어 BFQ (Budget Fair Queueing) 스토리지 I/O 스케줄러 엔진

## 📖 문제 배경과 시스템 아키텍처

> *"전통적인 CFQ(Completely Fair Queueing) 스케줄러는 프로세스마다 고정된 시간 슬라이스(Time Slice)를 할당했습니다. 그러나 저장장치의 대역폭이 비선형적으로 요동치고 섹터 위치에 따라 처리 속도가 달라지는 환경에서, 시간 기반 할당은 심각한 대역폭 낭비와 대화형 응용 프로그램의 프리징을 초래했습니다. BFQ(Budget Fair Queueing, `block/bfq-iosched.c`)는 시간 대신 섹터/바이트 단위의 '버짓(Budget)'을 공정 분배의 기본 단위로 삼아, 대화형 태스크의 초저지연과 스토리지 최대 처리량을 완벽하게 양립시킵니다."*  
> — **Paolo Valente, Linux Kernel BFQ I/O Scheduler Architect**

리눅스 블록 서브시스템의 **BFQ (Budget Fair Queueing / `block/bfq-iosched.c`)**는 데스크톱, 서버 및 임베디드 기기에서 백그라운드 대용량 파일 복사, 토렌트 다운로드, 데이터베이스 덤프 등이 도는 도중에도 웹 브라우징, 동영상 재생, 터미널 반응성과 같은 대화형(Interactive) 태스크가 멈추지 않고 즉각 반응할 수 있도록 보장하는 비례 분배(Proportional-Share) I/O 스케줄러입니다.

BFQ는 컴퓨터 과학의 고전인 **$B^2\text{WF}^2\text{Q}+$ (Budget-based Worst-case Fair Weighted Fair Queueing)** 알고리즘을 스토리지 디바이스에 맞추어 구현한 것으로, 핵심 원리는 다음과 같습니다:

```
+-------------------------------------------------------------------------------+
|                      리눅스 커널 BFQ I/O 스케줄러 아키텍처                     |
+-------------------------------------------------------------------------------+
  [Applications / Cgroups]
     │
     ├───► Queue A (Bulk Throughput, Weight W=100, Budget B=64 sectors)
     ├───► Queue B (Interactive GUI,  Weight W=100 -> Eff_W=200, Budget B=32)
     └───► Queue C (Database Log,     Weight W=200, Budget B=128 sectors)
             │
             ▼
  [BFQ Scheduler Engine]
     │
     ├───► 1. 가상 시간 (Virtual Time, V(t)) 동기화
     │        V(t) = V(t) + \Delta \text{sectors} / W_{\text{eff}}
     │
     ├───► 2. 가상 종료 시각 (Virtual Finish Time, F_k) 산출
     │        F_k = S_k + \frac{B_k}{W_{k, \text{eff}}}
     │
     ├───► 3. 대화형 큐 선점(Preemption) & 가중치 부스트
     │        - 대화형 큐 도착 시 대용량 백그라운드 큐 즉각 선점
     │
     ├───► 4. 버짓(Budget) 소진 감시
     │        - 할당된 섹터 버짓(B_k) 소진 시 즉시 다음 큐로 공정 전환
     ▼
  [Storage Device Dispatch Queue & Hardware Execution]
```

### BFQ 핵심 메커니즘
1. **버짓(Budget) 기반 자원 할당**:
   - 시간 대신 섹터(또는 바이트) 수량을 할당합니다. 대용량 순차 쓰기 큐에는 큰 버짓을 부여하여 헤드 시크를 줄이고 장치 처리량을 극대화하며, 랜덤/대화형 큐에는 작은 버짓을 부여하여 지연 시간을 단축합니다.
2. **가상 시간 $V(t)$와 가상 종료 시각 $F_k$**:
   - 큐 $k$가 활성화될 때 가상 시작 시각 $S_k = \max(V(t), F_k^{\text{prev}})$.
   - 가상 종료 시각 $F_k = S_k + \frac{B_k}{W_{k, \text{eff}}}$.
   - 매 디스패치 시점마다 $S_k \le V(t)$ 조건을 만족하는 후보 중 $F_k$가 가장 작은 큐를 우선 선택합니다.
3. **대화형 부스트(Interactive Weight Boost)**:
   - 대화형 큐(`is_interactive=True`)는 유효 가중치 $W_{\text{eff}} = W \times \text{boost\_factor}$로 증폭되어, $F_k$가 훨씬 천천히 증가하므로 장치 우선 점유권을 확보합니다.
4. **버짓 소진 및 재스케줄링**:
   - 현재 서비스 중인 큐의 잔여 버짓(`remaining_budget`)이 0 이하가 되거나 큐의 요청이 모두 소진되면, 서비스 버스트가 종료되고 다음 큐로 전환됩니다.

---

## 📥 입력 형식 (Input Specification)

입력은 표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "default_budget_sectors": 64,
    "sector_service_time_ns": 1000,
    "interactive_boost_factor": 2.0
  },
  "queues": [
    {
      "id": "bulk_q",
      "weight": 100.0,
      "interactive": false,
      "budget_sectors": 64
    },
    {
      "id": "gui_q",
      "weight": 100.0,
      "interactive": true,
      "budget_sectors": 32
    }
  ],
  "operations": [
    {
      "type": "ENQUEUE_IO",
      "queue": "bulk_q",
      "req_id": "b1",
      "sectors": 64,
      "time_ns": 0
    },
    {
      "type": "ENQUEUE_IO",
      "queue": "bulk_q",
      "req_id": "b2",
      "sectors": 64,
      "time_ns": 0
    },
    {
      "type": "ENQUEUE_IO",
      "queue": "gui_q",
      "req_id": "g1",
      "sectors": 16,
      "time_ns": 10000
    },
    {
      "type": "ADVANCE_TIME",
      "to_time_ns": 200000
    }
  ]
}
```

### 제약조건 및 파라미터 규칙:
1. `config`:
   - `default_budget_sectors`: 기본 큐 버짓 섹터 수 (기본값 `64`).
   - `sector_service_time_ns`: 1섹터 디스패치 및 하드웨어 처리 소요 시간(나노초, 기본값 `1000`).
   - `interactive_boost_factor`: 대화형 큐 가중치 부스트 배수 (기본값 `2.0`).
2. `queues`:
   - `id`: 큐 고유 식별자 문자열.
   - `weight`: 기본 가중치 (양의 실수, 기본값 `100.0`).
   - `interactive`: 대화형 여부 (불리언, 기본값 `false`). 대화형이면 $W_{\text{eff}} = \text{weight} \times \text{boost\_factor}$, 비대화형이면 $W_{\text{eff}} = \text{weight}$.
   - `budget_sectors`: 해당 큐의 1회 서비스 버스트 버짓 (정수, 기본값 `default_budget_sectors`).
3. `operations`:
   - `ENQUEUE_IO`:
     - 파라미터: `queue`, `req_id`, `sectors`, `time_ns`.
     - 동작: 시뮬레이션 시간을 `time_ns`로 전진시키며 하드웨어 디스패치를 진행하고, 해당 큐에 I/O 요청을 큐잉합니다. 비활성(비어있던) 큐가 처음 요청을 받으면 활성화되어 가상 시작/종료 시각을 갱신합니다. 만약 대화형 큐가 활성화되었고 현재 서비스 중인 큐가 비대화형 큐라면 다음 요청 경계에서 선점(Preemption)하도록 플래그를 설정합니다.
   - `ADVANCE_TIME`:
     - 파라미터: `to_time_ns`.
     - 동작: 목표 시각까지 하드웨어 I/O 완료 및 큐 스케줄링을 순차적으로 수행합니다.

### 큐 선택 및 서비스 규칙:
1. 활성 큐 중 대기 중인 요청이 있는 큐들을 후보로 합니다.
2. 가상 시간 $V(t) < \min(S_k)$ 이면 $V(t) = \min(S_k)$로 가상 시간을 갱신합니다.
3. $S_k \le V(t) + 10^{-9}$를 만족하는 준비된 큐 중, 다음 우선순위로 선택합니다:
   - 1순위: `is_interactive`가 참인 큐 우선.
   - 2순위: 가상 종료 시각 $F_k$가 작은 순.
   - 3순위: `id` 문자열 오름차순.
4. 요청 $R$ (섹터 수 $sec$) 처리 시:
   - 하드웨어 시작 시각: $\text{start\_ns} = \max(\text{current\_time\_ns}, \text{device\_busy\_until\_ns})$
   - 완료 시각: $\text{comp\_ns} = \text{start\_ns} + sec \times \text{sector\_service\_time\_ns}$
   - 장치 점유 시각: $\text{device\_busy\_until\_ns} = \text{comp\_ns}$
   - 가상 시간 갱신: $V(t) = V(t) + \frac{sec}{W_{\text{eff}}}$
   - 잔여 버짓 차감: $\text{remaining\_budget} -= sec$
5. 요청 완료 후 버짓 검사:
   - $\text{remaining\_budget} \le 0$ 이거나 대기 요청이 없으면 현재 큐의 서비스 버스트가 종료됩니다.
   - 만약 아직 대기 요청이 남아 있다면 다음 버스트를 위해 $S_k = \max(V(t), F_k)$, $F_k = S_k + \frac{B_k}{W_{\text{eff}}}$, $\text{remaining\_budget} = B_k$로 재설정하고 다음 큐 선택으로 넘어갑니다.

---

## 📤 출력 형식 (Output Specification)

시뮬레이션 종료 시각의 BFQ 스케줄러 상태를 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)으로 출력합니다:

```json
{
  "final_time_ns": 200000,
  "virtual_time": 1.36,
  "total_dispatched_requests": 3,
  "queues": {
    "bulk_q": {
      "weight": 100.0,
      "is_interactive": false,
      "served_requests": 2,
      "served_sectors": 128,
      "pending_requests": 0,
      "total_service_time_ns": 128000,
      "preemptions_triggered": 0,
      "virtual_finish": 1.28
    },
    "gui_q": {
      "weight": 100.0,
      "is_interactive": true,
      "served_requests": 1,
      "served_sectors": 16,
      "pending_requests": 0,
      "total_service_time_ns": 16000,
      "preemptions_triggered": 0,
      "virtual_finish": 0.8
    }
  },
  "history": [
    {
      "time_ns": 0,
      "complete_ns": 64000,
      "queue": "bulk_q",
      "req_id": "b1",
      "sectors": 64,
      "remaining_budget": 0,
      "virtual_time": 0.64
    }
  ]
}
```

*참고*: `virtual_time` 및 `virtual_finish` 수치는 `round(val, 4)`를 적용합니다. `history`는 최초 10개 디스패치 이력을 기록합니다.

---

## 🎯 채점 기준 및 제약 조건

1. 정확성 100%: 8개 모든 테스트케이스의 수치 및 큐잉 통계가 완벽히 일치해야 합니다.
2. 부동소수점 오차: 가상 시간 및 종료 시각 계산 시 정밀도를 유지하고 출력 시 `round(..., 4)`를 적용합니다.
3. 선점 및 버짓 소진 시점의 상태 전이가 정확해야 합니다.
