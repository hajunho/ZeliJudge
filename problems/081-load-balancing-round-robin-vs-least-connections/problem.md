# 081 - 물건 1개 산 손님과 카트 5개 채운 손님을 똑같이 나눠줬다고요?!: 로드 밸런싱의 함정과 라운드 로빈 vs 최소 활성 연결 (Round Robin vs Least Connections Load Balancing)

## 1. 현실 비유 & 배경 스토리

대형 마트에 계산대 3곳이 열려 있습니다. 🛒🏪  
안내 직원이 손님들을 1명씩 차례대로 번갈아 가며 계산대로 안내합니다.
> **"1번 손님은 1번 계산대, 2번 손님은 2번 계산대, 3번 손님은 3번 계산대, 4번 손님은 다시 1번 계산대..."**

이것이 바로 가장 널리 쓰이는 기본 로드 밸런싱 알고리즘인 **라운드 로빈 (Round Robin)**입니다.

```text
[손님들의 장바구니 현황]
- 손님 A: 라면 1봉지 (계산 시간: 1초)
- 손님 B: 껌 1통 (계산 시간: 1초)
- 손님 C: 카트 5개에 가득 담은 업소용 식자재 500개 (계산 시간: 60초)
- 손님 D: 카트 5개에 가득 담은 업소용 식자재 500개 (계산 시간: 60초)
```

만약 우연히 1번 계산대로 카트 5개짜리 손님(C, D)들이 연달아 배정된다면 어떻게 될까요?
- **1번 계산대**: 앞 손님 계산이 2분 넘게 안 끝나서 뒤에 줄 선 손님 20명이 멱살을 잡고 폭동을 일으킵니다 (CPU 100%, 스레드 풀 고갈, 타임아웃).
- **2번, 3번 계산대**: 라면 1봉지 손님을 1초 만에 보내고 점원이 하품하며 텅텅 놀고 있습니다.

안내 직원은 **"손님 수를 3개 계산대에 똑같이 1:1:1로 나눴으니 완벽하게 공평하다"**고 생각했지만,  
실제로는 **1번 계산대만 과부하로 터져나가고 마트 전체의 평균 대기 시간과 P99 지연시간이 폭발**했습니다.

현대 마이크로서비스(MSA)와 웹 서비스에 인입되는 요청의 소요 시간(Duration)은 극단적으로 비대칭적입니다.  
1ms 만에 끝나는 가벼운 헬스체크부터, 3,000ms가 걸리는 대용량 엑셀 다운로드나 AI 모델 추론 요청이 뒤섞여 들어옵니다.  
이때 서버의 내부 상태를 전혀 고려하지 않는 라운드 로빈을 적용하면 특정 서버로 무거운 작업이 쏠리는 **핫스팟(Hotspot / Convoy Effect)**이 발생합니다.

AWS ALB, Nginx, Envoy 등 엔터프라이즈 로드 밸런서는 이 문제를 **Least Connections (최소 활성 연결, Least In-Flight)** 알고리즘으로 해결합니다.  
각 서버가 현재 처리 중인 활성 연결 수(`in_flight`)를 실시간으로 추적하여, **현재 일거리가 가장 적은 유휴 서버로 신규 요청을 동적으로 우회 배정**함으로써 클러스터 전체의 부하를 완벽하게 평탄화하는 것입니다.

당신은 로드 밸런서 시뮬레이터를 구축하여, 비대칭 요청 워크로드 환경에서 **Round Robin**과 **Least Connections** 알고리즘의 동작 및 최대 활성 부하(Peak In-Flight) 차이를 계측해야 합니다!

---

## 2. 시뮬레이션 상세 사양

클러스터에는 $N$대의 백엔드 서버가 존재하며, ID는 $0, 1, \dots, N-1$입니다.  
각 서버는 여러 요청을 동시에 처리할 수 있으며, 현재 처리 중인 요청의 수를 **활성 연결 수(`in_flight`)**라고 합니다.

### 1) 라운드 로빈 엔진 (`ROUND_ROBIN`)
- 초기 포인터는 $0$번 서버를 가리킵니다.
- 요청이 들어오면 현재 포인터가 가리키는 서버에 배정하고, 포인터를 다음 서버로 순환 전진시킵니다:
  $$\text{target} = \text{pointer}, \quad \text{pointer} = (\text{pointer} + 1) \pmod N$$
- 서버의 현재 `in_flight` 상태는 전혀 고려하지 않습니다.

### 2) 최소 활성 연결 엔진 (`LEAST_CONNECTIONS`)
- 요청이 들어오면, 현재 `in_flight`가 가장 작은 서버를 선택하여 배정합니다.
- 만약 최소 활성 연결 수를 가진 서버가 여러 대라면(Tie), **서버 ID가 가장 작은 서버**를 선택합니다 (결정론적 Tie-breaker).

### 3) 요청 라이프사이클 및 시간 흐름 (Discrete Ticks)
- 요청 도착 시 (`REQUEST <req_id> <duration>`):
  - 배정된 서버: `in_flight += 1`, `allocations += 1`, `peak_in_flight = max(peak_in_flight, in_flight)`.
  - 해당 요청의 완료 예정 시각: $\text{finish\_tick} = \text{current\_tick} + \text{duration}$.
- 틱 전진 시 (`STEP <ticks>`):
  - `<ticks>`번 반복하며 1틱씩 전진합니다.
  - `current_tick += 1`로 시간이 흐른 뒤, 두 엔진 각각에서 $\text{finish\_tick} \le \text{current\_tick}$을 만족하는 모든 완료 요청들을 종료 처리합니다:
    - 해당 서버의 `in_flight -= 1`
    - 엔진의 `completed_requests += 1`

---

## 3. 입력 명령 프로토콜

표준 입력(stdin)으로 다음 명령어들이 한 줄씩 주어집니다:

1. `INIT <num_servers>`
   - 백엔드 서버 대수 $N$ ($1 \le N \le 100$)으로 시뮬레이터를 초기화합니다.
   - 출력: `INITIALIZED NUM_SERVERS=<num_servers>`

2. `REQUEST <req_id> <duration>`
   - 현재 틱(`current_tick`)에 소요 시간 `<duration>` 틱짜리 새 요청을 인입합니다.
   - 두 엔진에 동일하게 전달되어 각각의 전략에 따라 라우팅됩니다.
   - 출력: `ROUTED <req_id> DURATION=<duration>`

3. `STEP <ticks>`
   - 시뮬레이션을 `<ticks>` 틱만큼 전진시키며 완료된 요청들을 처리합니다.
   - 출력: `STEPPED <ticks> TICKS (CURRENT_TICK: <current_tick>)`

4. `RUN_UNTIL_IDLE <max_ticks>`
   - 두 엔진 모두 활성 요청(`active_in_flight == 0`)이 전혀 없을 때까지, 혹은 최대 `<max_ticks>` 틱만큼 전진합니다.
   - 두 엔진 모두 완전히 유휴 상태에 도달하면:
     `IDLE_REACHED AT TICK <current_tick>`
   - 그렇지 않고 `<max_ticks>` 틱에 도달하면:
     `MAX_TICKS_REACHED AT TICK <current_tick>`

5. `STATUS`
   - 두 엔진의 현재 상태를 다음 형식으로 출력합니다:
     ```
     === ROUND_ROBIN ===
     TOTAL_REQUESTS: <인입된 총 요청 수>
     COMPLETED: <완료된 총 요청 수>
     ACTIVE_IN_FLIGHT: <클러스터 전체 현재 활성 요청 수 합계>
     PEAK_IN_FLIGHT: <어떤 단일 서버라도 기록한 최대 동시 활성 요청 수>
     SERVER_IN_FLIGHT: [s0, s1, ...]
     SERVER_ALLOCATIONS: [s0, s1, ...]
     === LEAST_CONNECTIONS ===
     TOTAL_REQUESTS: <인입된 총 요청 수>
     COMPLETED: <완료된 총 요청 수>
     ACTIVE_IN_FLIGHT: <클러스터 전체 현재 활성 요청 수 합계>
     PEAK_IN_FLIGHT: <어떤 단일 서버라도 기록한 최대 동시 활성 요청 수>
     SERVER_IN_FLIGHT: [s0, s1, ...]
     SERVER_ALLOCATIONS: [s0, s1, ...]
     ```
     *(단, `SERVER_IN_FLIGHT`와 `SERVER_ALLOCATIONS`는 Python 리스트 문자열 형식 `[0, 1, 2]`로 출력)*

---

## 4. 제약 조건

- $1 \le \text{num\_servers} \le 100$
- $1 \le \text{duration} \le 1,000$
- 단일 입력당 총 요청 수 $\le 2,000$
- 총 전진 틱 수 $\le 10,000$

---

## 5. 입출력 예시

### 예시 입력
```
INIT 3
REQUEST R1 10
REQUEST R2 1
REQUEST R3 1
STEP 1
REQUEST R4 10
REQUEST R5 1
REQUEST R6 1
STEP 1
REQUEST R7 10
REQUEST R8 1
REQUEST R9 1
STEP 1
STATUS
RUN_UNTIL_IDLE 30
STATUS
```

### 예시 출력
```
INITIALIZED NUM_SERVERS=3
ROUTED R1 DURATION=10
ROUTED R2 DURATION=1
ROUTED R3 DURATION=1
STEPPED 1 TICKS (CURRENT_TICK: 1)
ROUTED R4 DURATION=10
ROUTED R5 DURATION=1
ROUTED R6 DURATION=1
STEPPED 1 TICKS (CURRENT_TICK: 2)
ROUTED R7 DURATION=10
ROUTED R8 DURATION=1
ROUTED R9 DURATION=1
STEPPED 1 TICKS (CURRENT_TICK: 3)
=== ROUND_ROBIN ===
TOTAL_REQUESTS: 9
COMPLETED: 6
ACTIVE_IN_FLIGHT: 3
PEAK_IN_FLIGHT: 3
SERVER_IN_FLIGHT: [3, 0, 0]
SERVER_ALLOCATIONS: [3, 3, 3]
=== LEAST_CONNECTIONS ===
TOTAL_REQUESTS: 9
COMPLETED: 6
ACTIVE_IN_FLIGHT: 3
PEAK_IN_FLIGHT: 2
SERVER_IN_FLIGHT: [1, 1, 1]
SERVER_ALLOCATIONS: [3, 3, 3]
IDLE_REACHED AT TICK 12
=== ROUND_ROBIN ===
TOTAL_REQUESTS: 9
COMPLETED: 9
ACTIVE_IN_FLIGHT: 0
PEAK_IN_FLIGHT: 3
SERVER_IN_FLIGHT: [0, 0, 0]
SERVER_ALLOCATIONS: [3, 3, 3]
=== LEAST_CONNECTIONS ===
TOTAL_REQUESTS: 9
COMPLETED: 9
ACTIVE_IN_FLIGHT: 0
PEAK_IN_FLIGHT: 2
SERVER_IN_FLIGHT: [0, 0, 0]
SERVER_ALLOCATIONS: [3, 3, 3]
```

### 힌트 & 분석
- **Round Robin**:
  - 누적 할당 수(`SERVER_ALLOCATIONS`)는 `[3, 3, 3]`으로 모든 서버에 동일하게 3개씩 분배되었습니다.
  - 하지만 무거운 작업(10틱) 3개가 0번 서버에 겹쳐서 들어가면서 `SERVER_IN_FLIGHT`가 `[3, 0, 0]`이 되었고, `PEAK_IN_FLIGHT`가 3까지 치솟아 0번 서버만 과부하 위험에 처했습니다!
- **Least Connections**:
  - 0번 서버가 10틱짜리 작업을 수행하는 동안, 가벼운 작업들을 빠르게 끝내고 유휴 상태가 된 1번, 2번 서버로 다음 작업들이 우선 배정되었습니다.
  - 그 결과 `SERVER_IN_FLIGHT`가 `[1, 1, 1]`로 균등하게 유지되고, `PEAK_IN_FLIGHT`도 2로 안정적으로 억제되었습니다!
