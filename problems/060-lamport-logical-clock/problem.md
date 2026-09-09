# #060 질문보다 답변이 먼저 뜨는 타임머신 버그?!: 분산 시계 드리프트와 램포트 논리적 시계 (Physical Clock Drift vs Lamport Logical Clock)

---

## 1. 현실 세계 비유: 5분 느린 벽시계와 5분 빠른 손목시계

서로 다른 마을에 사는 철수와 영희가 우편으로 대화를 나눕니다.

```text
❌ 물리 시계의 배신 (NAIVE - 타임머신 역전 버그):
   1. 철수네 집 벽시계는 10분 느립니다 (스큐: -10분).
   2. 영희네 집 손목시계는 10분 빠릅니다 (스큐: +10분).
   3. 철수가 실제 시각 12:00에 "오늘 저녁에 치킨 먹을래?" 편지를 보냅니다.
      -> 편지 봉투에 찍힌 철수네 집 시계: [11:50]
   4. 우체부가 10분 만에 배달하여 영희가 실제 시각 12:10에 편지를 받았습니다.
   5. 영희는 기뻐하며 실제 시각 12:15에 "응 치킨 좋아!" 답장을 썼습니다.
      -> 답장 봉투에 찍힌 영희 손목시계: [12:25]
   6. 그런데 만약 철수네 시계가 1시간 느리고, 영희가 3분 만에 답장했다면?!
      - 영희 답장에 찍힌 시각: [11:45]
      - 철수 질문에 찍힌 시각: [11:50]
   7. 중앙 우체국이 편지 봉투 시각대로 정렬하여 게시판에 붙였습니다:
      - [11:45]: 영희 -> "응 치킨 좋아!" (답변이 먼저 뜸!)
      - [11:50]: 철수 -> "오늘 저녁에 치킨 먹을래?" (질문이 나중에 뜸!)
   8. 결과: 영희가 미래를 예지하고 답변을 먼저 보낸 꼴이 되어 메신저 타임라인이 완전히 뒤죽박죽 난장판이 됩니다!

✅ 램포트 논리적 시계 (LAMPORT LOGICAL CLOCK):
   1. 레슬리 램포트 주치의가 나타나 말합니다. "벽시계 숫자는 쳐다보지도 마라! 편지마다 인과 카운터 번호표를 붙여라!"
   2. 철수가 질문을 보낼 때 카운터를 1 올려서 보냅니다: [번호표: 1]
   3. 영희는 [번호표: 1] 편지를 받는 순간, 자신의 카운터를 max(내카운터, 1) + 1 = [번호표: 2]로 올립니다.
   4. 영희가 답장을 쓸 때 카운터를 1 더 올려서 보냅니다: [번호표: 3]
   5. 두 집의 시계가 1시간씩 어긋나 있든 말든, 번호표 순서(1 -> 2 -> 3)대로 정렬하면
      "질문(1) -> 수신(2) -> 답변(3)"의 완벽한 인과관계가 100% 보존됩니다!
```

---

## 2. 문제 개요

당신은 글로벌 분산 실시간 채팅 및 이벤트 소싱 플랫폼의 수석 분산 시스템 엔지니어입니다.  
전 세계 리전에 분산된 서버들은 NTP(Network Time Protocol) 동기화 오차, 가상머신 일시정지 등으로 인해 각각 수십~수백 밀리초의 물리 시계 드리프트(Clock Skew)를 겪고 있습니다.

이때,
1. 각 노드의 로컬 물리 타임스탬프(`phys_ts`)로 단순 정렬하는 **물리 시계 모델(PHYSICAL)**과
2. 레슬리 램포트의 인과 관계 알고리즘 기반 **논리적 시계 모델(LAMPORT)**

두 타임라인 정렬 방식을 시뮬레이션하고, 메시지 전송 및 노드 내부 인과 관계를 위반하는 타임머신 역전 이상 현상(`PHYSICAL_INVERSIONS`)과 램포트 시계의 인과 무결성 방어율(`ANOMALIES_PREVENTED`)을 정밀 계측하세요.

---

## 3. 입력 형식

표준 입력(`sys.stdin`)으로 노드별 시계 스큐 정보와 액션 스트림이 주어집니다.

```text
NODES
<node_id> <clock_skew_ms>
<node_id> <clock_skew_ms>
...
ACTIONS
LOCAL <event_id> <node_id> <real_time>
MESSAGE <msg_id> <src_node> <dst_node> <send_real_time> <delay_ms>
...
```

### 파라미터 규격
- `NODES`: 분산 시스템의 노드 목록과 각 노드의 물리 시계 오차 (ms 단위 정수, 음수는 느림, 양수는 빠름).
- `ACTIONS`: 실제 자연 시각(`real_time`)에 발생한 동작 목록.
  - `LOCAL <event_id> <node_id> <real_time>`:
    - 특정 노드에서 발생한 단독 로컬 이벤트.
  - `MESSAGE <msg_id> <src_node> <dst_node> <send_real_time> <delay_ms>`:
    - `src_node`에서 `send_real_time`에 전송되는 네트워크 메시지.
    - `src_node`에서는 이벤트 `<msg_id>_SEND`가 `send_real_time`에 발생합니다.
    - `dst_node`에서는 이벤트 `<msg_id>_RECV`가 `send_real_time + delay_ms` 시점에 도착하여 발생합니다.

---

## 4. 시뮬레이션 및 램포트 시계 알고리즘 규칙

모든 사건은 실제 시간(`real_time`) 순서대로 시뮬레이션 큐에서 실행됩니다. (시각이 같을 경우 입력 파일 액션 순서, 단일 액션 내에서는 SEND $\to$ LOCAL $\to$ RECV 순).

### 물리 타임스탬프 계산
임의의 노드 `N`에서 실제 시각 `T`에 사건이 발생할 때 기록되는 물리 타임스탬프:
$$\text{phys\_ts} = T + \text{skew}[N]$$

### 램포트 논리적 시계(Lamport Clock) 갱신 규칙
각 노드는 초기값 0을 갖는 정수 카운터 `lamport[N]`을 유지합니다:
1. **로컬 이벤트(`LOCAL`)**:
   - `lamport[node] += 1`
   - 이벤트의 논리 시계: `lamp_ts = lamport[node]`
2. **메시지 전송(`SEND`)**:
   - `lamport[src] += 1`
   - 이벤트의 논리 시계: `lamp_ts = lamport[src]`
   - 메시지 패킷에 `lamp_ts`를 첨부하여 전송.
3. **메시지 수신(`RECV`)**:
   - 메시지에 실려온 전송 시계 `send_lamp_ts`를 확인.
   - `lamport[dst] = max(lamport[dst], send_lamp_ts) + 1`
   - 이벤트의 논리 시계: `lamp_ts = lamport[dst]`

### 인과 관계 간선(Causal Edges) 수집
시스템 내에서 "반드시 A가 B보다 먼저 일어나야 하는" 직접 인과 관계 간선 $(A \to B)$:
1. **노드 내부 순서**: 동일 노드에서 직전에 발생한 이벤트 $\to$ 현재 이벤트
2. **메시지 전송-수신**: `<msg_id>_SEND` $\to$ `<msg_id>_RECV`

### 타임라인 정렬 및 역전 이상 현상(Inversion) 판정
- **물리 타임라인 (PHYSICAL)**:
  - 모든 이벤트를 `(phys_ts, node_id, event_id)` 오름차순으로 정렬.
  - 인과 간선 $(A \to B)$에 대해, 정렬된 타임라인에서 $B$가 $A$보다 앞에 위치하면 **인과성 붕괴(Causal Inversion, `physical_inversions += 1`)**로 판정!
- **램포트 논리 타임라인 (LAMPORT)**:
  - 모든 이벤트를 `(lamp_ts, node_id, event_id)` 오름차순으로 정렬.
  - 램포트 정리에 의해 $A \to B \implies \text{lamp\_ts}(A) < \text{lamp\_ts}(B)$이므로, 인과 역전은 항상 0건(`lamport_inversions = 0`)입니다.

---

## 5. 출력 형식

표준 출력(`sys.stdout`)으로 발생 순서대로 각 이벤트의 정보와 최종 요약 통계를 출력합니다.

```text
EVENT <ev_id> NODE:<node> PHYS_TS:<phys_ts> LAMP_TS:<lamp_ts>
...
SUMMARY TOTAL_EVENTS:<total_events> CAUSAL_EDGES:<causal_edges>
SUMMARY PHYSICAL_INVERSIONS:<phys_inversions>
SUMMARY LAMPORT_INVERSIONS:<lamp_inversions>
SUMMARY ANOMALIES_PREVENTED:<phys_inversions>
```

---

## 6. 입출력 예시

### 예시 입력
```text
NODES
node_A 100
node_B -100
ACTIONS
LOCAL e1 node_A 100
MESSAGE m1 node_A node_B 200 20
LOCAL e2 node_B 300
```

### 예시 출력
```text
EVENT e1 NODE:node_A PHYS_TS:200 LAMP_TS:1
EVENT m1_SEND NODE:node_A PHYS_TS:300 LAMP_TS:2
EVENT m1_RECV NODE:node_B PHYS_TS:120 LAMP_TS:3
EVENT e2 NODE:node_B PHYS_TS:200 LAMP_TS:4
SUMMARY TOTAL_EVENTS:4 CAUSAL_EDGES:3
SUMMARY PHYSICAL_INVERSIONS:1
SUMMARY LAMPORT_INVERSIONS:0
SUMMARY ANOMALIES_PREVENTED:1
```

### 결과 해석
- `m1_SEND`는 실제 시각 200ms에 node_A(스큐 +100ms)에서 발생하여 `PHYS_TS = 300`입니다.
- `m1_RECV`는 실제 시각 220ms에 node_B(스큐 -100ms)에서 발생하여 `PHYS_TS = 120`입니다.
- 물리 타임스탬프만 보면 메시지가 120ms에 먼저 도착하고, 300ms에 나중에 발송된 **기괴한 타임머신 역전 버그(1건)**가 발생합니다!
- 반면 램포트 논리 시계는 `m1_SEND(LAMP_TS=2)` $\to$ `m1_RECV(LAMP_TS=3)`로 완벽하게 전진하여 인과 관계를 100% 온전하게 보존해 냈습니다.

---

## 7. 제약 조건 및 복잡도 요구사항
- 총 이벤트 수 $E \le 100,000$.
- 노드 수 $N \le 1,000$.
- 정렬 및 인과 검증을 $O(E \log E)$ 이하의 시간 복잡도로 5.0초 제한 시간 내에 통과해야 합니다.
