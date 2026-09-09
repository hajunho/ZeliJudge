# Problem 077: 분산 유일 ID 생성과 트위터 스노우플레이크 (Twitter Snowflake ID & Clock Backward Defense)

## 문제 설명

수천만 명의 유저가 주문/결제를 발생시키는 글로벌 분산 이커머스 플랫폼을 운영하던 엔지니어링 팀에 심각한 데이터 정합성 장애가 발생했습니다:
> "분산 DB 샤딩 환경에서 Auto Increment를 쓸 수 없어 128비트 랜덤 문자열(UUID v4)을 주문 테이블의 기본키(PK)로 썼더니, 데이터가 100만 건을 넘어서자마자 B-Tree 인덱스 페이지 스플릿(Page Split)이 폭증해 DB 쓰기 속도가 1/10 토막 났습니다!  
> 그래서 64비트 정수형 분산 ID 생성기(Snowflake)를 도입했는데, 이번에는 서버 NTP 시계가 과거로 2ms 되돌아간 순간 방금 발급했던 주문 번호와 똑같은 번호가 발행되어 DB에서 `Duplicate Key Error`가 터지고 결제 데이터가 유실되었습니다!"

이 장애의 근본 원인은 **분산 ID 생성의 3대 요구사항(고유성, 단조 증가성, 고성능)과 물리적 시계의 비신뢰성(Clock Drift / Clock Backward)**에 있었습니다:
- **UUID v4의 재앙 (B-Tree 인덱스 단편화)**:
  - 무작위 128비트 문자열은 시간 순서가 없습니다.
  - 데이터베이스의 Clustered Index(B-Tree)는 키 값의 순서대로 디스크에 저장되므로, 무작위 UUID가 들어오면 정렬된 B-Tree 중간을 비집고 들어가느라 기존 페이지를 둘로 쪼개는 **페이지 스플릿(Page Split)**이 끝없이 일어납니다.
- **트위터 스노우플레이크(Twitter Snowflake)의 탄생**:
  - 트위터는 64비트 정수 1개에 정보를 비트 단위로 압축했습니다:
    - **41비트 타임스탬프**: 기준 시점(Epoch) 이후 경과한 밀리초 (약 69년 사용 가능). 시간이 앞부분에 오므로 **자연스럽게 단조 증가(Monotonic Increase)**하여 B-Tree 인덱스 맨 끝에 순차 삽입($O(1)$)됩니다.
    - **10비트 노드 ID**: 최대 1,024개 노드/서버에서 분산 발행.
    - **12비트 시퀀스 번호**: 같은 밀리초 내에서 최대 4,096개의 ID를 고유하게 발행.
- **NTP 시계 역행(Clock Backward)의 함정**:
  - 서버의 물리적 시계는 윤초(Leap Second)나 NTP 동기화로 인해 과거로 1~5ms 정도 되돌아갈 수 있습니다.
  - 순진한 생성기(Naive Snowflake)는 시계가 과거로 가면 과거의 타임스탬프로 ID를 재발행하여 **치명적인 중복 충돌(`COLLISION_DETECTED`)**을 일으킵니다.
  - 견고한 생성기(Robust Snowflake)는 시계 역행을 감지하면 과거로 돌아가지 않고, **가상 시간(Virtual Clock)을 유지**하며 시퀀스를 이어받아 단조 증가성과 고유성을 100% 보장합니다!

전국 1,024개 지점 은행에서 번호표를 뽑아줄 때, 벽시계 배터리를 교체하느라 시계 바늘이 1분 뒤로 돌아갔다고 해서 방금 나간 100번 번호표를 다음 손님에게 또 주는 은행원이 되지 않으려면 견고한 시계 역행 방어 로직이 필수적입니다!

당신은 동일한 타임스탬프 및 시계 역행 스트림에 대해 단순 생성하는 **Naive Snowflake 엔진**과 가상 시간 전진을 적용한 **Robust Snowflake 엔진**의 충돌 발생 여부와 단조 증가성을 검증하는 분산 ID 생성 시뮬레이터를 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정 (`SYSTEM_CONFIG`)
- `EPOCH_MS <int>`: 기준 에포크 시점 밀리초 (예: 1700000000000).
- `NODE_ID <int>`: 노드 ID (0 ~ 1023, 10비트).

---

### 2. 64비트 Snowflake ID 비트 레이아웃
```text
 1 bit   41 bits (Timestamp)            10 bits (Node)   12 bits (Sequence)
┌─────┬───────────────────────────────┬────────────────┬─────────────────┐
│  0  │  current_time_ms - EPOCH_MS   │    NODE_ID     │  0 ~ 4095       │
└─────┴───────────────────────────────┴────────────────┴─────────────────┘
```
- 비트 시프트 연산:
  $$\text{ID} = ((\text{timestamp} - \text{EPOCH\_MS}) \ll 22) \mid (\text{NODE\_ID} \ll 12) \mid \text{sequence}$$

---

### 3. 두 가지 Snowflake ID 생성 메커니즘

#### 1) Naive Snowflake Engine (시계 역행 무방비)
- `GEN_ID <client_id> <time_ms>`:
  - `time_ms == last_timestamp`인 경우: `sequence = (sequence + 1) & 4095`.
  - `time_ms > last_timestamp`인 경우: `sequence = 0`, `last_timestamp = time_ms`.
  - **`time_ms < last_timestamp` (시계 역행 발생)**:
    - 아무런 방어 없이 `sequence = 0`, `last_timestamp = time_ms`로 과거 시각으로 되돌아감.
    - 과거에 이미 발급했던 ID와 동일한 ID가 생성되어 **중복 충돌(`COLLISION_DETECTED`)** 및 단조 증가성 파괴(`MONOTONIC:FALSE`) 발생!

#### 2) Robust Snowflake Engine (가상 시간 유지 & 시계 역행 완벽 방어)
- `GEN_ID <client_id> <time_ms>`:
  - **`time_ms < last_timestamp` (시계 역행 감지)**:
    - 타임스탬프를 과거로 되돌리지 않고 `last_timestamp`를 유지 (**가상 시간 유지 기법**).
    - `CLOCK_ADJUST:VIRTUAL_ADVANCED` 플래그 설정 및 조정 카운트 누적.
    - `sequence = (sequence + 1) & 4095`. 만약 `sequence == 0`이면 가상 틱 `last_timestamp += 1`.
  - `time_ms == last_timestamp`인 경우:
    - `sequence = (sequence + 1) & 4095`. 만약 `sequence == 0`이면 `last_timestamp += 1` 및 `CLOCK_ADJUST:VIRTUAL_ADVANCED`.
  - `time_ms > last_timestamp`인 경우:
    - 정상 시간 전진. `sequence = 0`, `last_timestamp = time_ms`.
  - 결과: 시계가 아무리 요동쳐도 이전에 발급한 어떤 ID보다 무조건 큰 값(`MONOTONIC:TRUE`)이 보장되며 **충돌 0건(`COLLISION:NONE`)**을 유지!

---

### 4. 액션 명세

#### 1) `GEN_ID <client_id> <current_time_ms>`
- ID 생성 요청.
- 출력 (3줄):
  ```text
  ACT <idx> GEN_ID CLIENT:<client_id> TIME:<time>ms
    NAIVE: ID:<id> MONOTONIC:<TRUE|FALSE> COLLISION:<NONE|COLLISION_DETECTED>
    ROBUST: ID:<id> MONOTONIC:<TRUE|FALSE> CLOCK_ADJUST:<NONE|VIRTUAL_ADVANCED> COLLISION:NONE
  ```

#### 2) `CHECK_METRICS`
- 누적 지표 점검.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_METRICS
    NAIVE: GENERATED:<cnt> COLLISIONS:<c_cnt> MONOTONIC_ERRORS:<m_cnt>
    ROBUST: GENERATED:<cnt> COLLISIONS:0 CLOCK_ADJUSTS:<adj_cnt>
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
EPOCH_MS <epoch_ms>
NODE_ID <node_id>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 실행 결과 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (5줄):
```text
SUMMARY TOTAL_ID_REQUESTS:<cnt>
SUMMARY NAIVE GENERATED:<cnt> COLLISIONS:<c_cnt> MONOTONIC_ERRORS:<m_cnt>
SUMMARY ROBUST GENERATED:<cnt> COLLISIONS:0 MONOTONIC_ERRORS:0
SUMMARY COLLISION_DEFENSE: 100%_SECURE
SUMMARY ID_GENERATOR_VERDICT: ROBUST_SNOWFLAKE_PREVENTS_COLLISION_AND_INDEX_FRAGMENTATION
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
EPOCH_MS 1700000000000
NODE_ID 5
ACTIONS
GEN_ID C1 1700000000999
GEN_ID C2 1700000001000
GEN_ID C3 1700000000999
CHECK_METRICS
```

**출력:**
```text
ACT 1 GEN_ID CLIENT:C1 TIME:1700000000999ms
  NAIVE: ID:4190130176 MONOTONIC:TRUE COLLISION:NONE
  ROBUST: ID:4190130176 MONOTONIC:TRUE CLOCK_ADJUST:NONE COLLISION:NONE
ACT 2 GEN_ID CLIENT:C2 TIME:1700000001000ms
  NAIVE: ID:4194324480 MONOTONIC:TRUE COLLISION:NONE
  ROBUST: ID:4194324480 MONOTONIC:TRUE CLOCK_ADJUST:NONE COLLISION:NONE
ACT 3 GEN_ID CLIENT:C3 TIME:1700000000999ms
  NAIVE: ID:4190130176 MONOTONIC:FALSE COLLISION:COLLISION_DETECTED
  ROBUST: ID:4194324481 MONOTONIC:TRUE CLOCK_ADJUST:VIRTUAL_ADVANCED COLLISION:NONE
ACT 4 CHECK_METRICS
  NAIVE: GENERATED:3 COLLISIONS:1 MONOTONIC_ERRORS:1
  ROBUST: GENERATED:3 COLLISIONS:0 CLOCK_ADJUSTS:1
SUMMARY TOTAL_ID_REQUESTS:3
SUMMARY NAIVE GENERATED:3 COLLISIONS:1 MONOTONIC_ERRORS:1
SUMMARY ROBUST GENERATED:3 COLLISIONS:0 MONOTONIC_ERRORS:0
SUMMARY COLLISION_DEFENSE: 100%_SECURE
SUMMARY ID_GENERATOR_VERDICT: ROBUST_SNOWFLAKE_PREVENTS_COLLISION_AND_INDEX_FRAGMENTATION
```
