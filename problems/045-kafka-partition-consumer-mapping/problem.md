# #045 카프카 컨슈머를 10대로 늘렸는데 왜 3대만 일해요?!: 파티션(Partition)과 컨슈머 그룹(Consumer Group)의 1:1 매핑 법칙

---

## 1. 현실 세계 비유: 피자 3판과 10명의 식사 당번

회사 탕비실에 피자 3판(파티션 3개)이 배달되었고, 10명의 배고픈 직원들(컨슈머 그룹의 인스턴스 10대)이 모여들었습니다.

```text
🍕 피자 0번 판, 🍕 피자 1번 판, 🍕 피자 2번 판

카프카(Kafka)의 우주 철칙:
"메시지의 처리 순서를 100% 보장하기 위해, 하나의 파티션(피자 1판)은
 동일한 컨슈머 그룹 내에서 반드시 단 1명의 컨슈머만 전담해서 순서대로 먹어야 한다!"

결과:
- 직원 1: 피자 0번 전담 흡입 중
- 직원 2: 피자 1번 전담 흡입 중
- 직원 3: 피자 2번 전담 흡입 중
- 직원 4 ~ 10 (총 7명): 옆에서 손가락만 빨며 멍하니 구경 중 (IDLE 상태)
```

수많은 주니어 개발자와 AI 바이브 코더들이 "메시지 큐(Consumer Lag)가 밀린다"며 무작정 컨슈머 서버를 10대, 20대로 스케일아웃합니다.  
그리고 월말에 **AWS 클라우드 서버 비용은 5배로 폭탄을 맞았는데, 메시지 처리 속도는 단 1%도 빨라지지 않은 참사**를 목격하고 경악합니다.

원인은 단 하나, **토픽의 파티션 개수($P$)가 컨슈머 그룹의 병렬 처리 절대 상한선(Concurrency Ceiling)**이라는 카프카의 핵심 기본기를 몰랐기 때문입니다!

---

## 2. 문제 개요

당신은 대규모 실시간 스트리밍 인프라를 운영하는 카프카 플랫폼 엔지니어입니다.  
동적으로 컨슈머가 합류(`JOIN`)하거나 이탈(`LEAVE`)하고, 메시지가 발행(`PUBLISH`) 및 소비(`CONSUME`)되는 환경에서,  
카프카의 파티션 할당 전략(`ROUND_ROBIN`, `RANGE`)과 리밸런싱(Rebalance) 상태 머신을 시뮬레이션하고,  
유휴 컨슈머로 인한 클라우드 자원 낭비(`WASTED_CONSUMER_RESOURCES_DETECTED`)를 정밀 계측하세요.

### 시뮬레이션 상세 규칙

#### 1. 공통 환경
- `TOPIC_PARTITIONS <P>`: 토픽의 파티션 개수 ($1 \le P \le 1,000$). 파티션 번호는 $0, 1, \dots, P-1$.
- `STRATEGY <RANGE | ROUND_ROBIN>`: 파티션 분배 전략.
- 현재 참여 중인 컨슈머 목록은 사전순(Lexicographical order)으로 정렬된 멤버 ID 목록으로 관리됩니다.

#### 2. 파티션 할당 알고리즘 (리밸런싱)
컨슈머가 `JOIN` 또는 `LEAVE`할 때마다 리밸런싱이 발생하여 파티션이 전원 재할당됩니다.
참여 컨슈머 수를 $C = len(consumers)$라고 할 때:

- **ROUND_ROBIN 전략**:
  - 파티션 $0$번부터 $P-1$번까지 차례대로, 정렬된 컨슈머들에게 순환 배정합니다:
    - 파티션 $p \to consumers[p \pmod C]$
- **RANGE 전략**:
  - 파티션을 연속된 구간으로 나누어 컨슈머에게 배정합니다:
    - 기본 파티션 수 $num = P // C$, 나머지 $rem = P \% C$.
    - 처음 $rem$명의 컨슈머는 각각 $num + 1$개씩 연속된 파티션을 가져갑니다.
    - 나머지 컨슈머들은 각각 $num$개씩 연속된 파티션을 가져갑니다.
- **유휴 컨슈머 (IDLE)**:
  - 만약 $C > P$ 라면, 파티션을 1개도 할당받지 못한 $C - P$대의 컨슈머는 `IDLE` 상태(할당: `NONE`)가 됩니다.
  - 이 유휴 컨슈머들은 CPU/메모리만 축내며 메시지를 전혀 소비할 수 없습니다.

#### 3. 메시지 발행과 소비
- `PUBLISH <partition_id> <message_count>`:
  - 지정된 파티션의 큐(Lag)에 메시지 수가 누적됩니다.
- `CONSUME <max_per_consumer>`:
  - 파티션을 할당받은 각 **활성 컨슈머(Active Worker)**는, 자신에게 할당된 각 파티션 $p$에서 최대 $max\_per\_consumer$개만큼 메시지를 꺼내어 소비합니다:
    - 소비량 = $\min(partition\_lag[p], max\_per\_consumer)$
  - `IDLE` 컨슈머는 할당된 파티션이 없으므로 아무 일도 하지 못합니다 (소비량 0).

---

## 3. 입력 형식

```text
TOPIC_PARTITIONS <P>
STRATEGY <ROUND_ROBIN | RANGE>
EVENTS <E>
JOIN <consumer_id>
LEAVE <consumer_id>
PUBLISH <partition_id> <message_count>
CONSUME <max_per_consumer>
... (총 E개의 줄)
```

- `P`: 파티션 총 개수 (정수, $1 \le P \le 1,000$)
- `STRATEGY`: `ROUND_ROBIN` 또는 `RANGE`
- `E`: 이벤트 총 개수 ($1 \le E \le 30,000$)
- 각 명령:
  - `JOIN <consumer_id>`: 새 컨슈머 참여
  - `LEAVE <consumer_id>`: 컨슈머 종료/장애 이탈
  - `PUBLISH <partition_id> <message_count>`: 파티션에 메시지 추가
  - `CONSUME <max_per_consumer>`: 1개 파티션당 최대 소비량 틱

---

## 4. 출력 형식

- `JOIN` 또는 `LEAVE` 발생 시 (리밸런싱 결과):
  ```text
  REBALANCE STRATEGY:<strategy> ACTIVE_CONSUMERS:<active_cnt> IDLE_CONSUMERS:<idle_cnt>
  ASSIGNMENT <consumer_id> -> [p0,p1...] (또는 NONE)
  ... (사전순으로 정렬된 모든 참여 컨슈머 출력)
  ```
- `PUBLISH` 발생 시:
  ```text
  PUBLISH PARTITION:<p> ADDED:<msg_count> TOTAL_LAG:<total_lag>
  ```
- `CONSUME` 발생 시:
  ```text
  CONSUME ACTIVE_WORKERS:<active_cnt> PROCESSED:<processed_cnt> REMAINING_LAG:<remaining_lag>
  ```
- 모든 이벤트 처리 후 마지막 줄:
  ```text
  SUMMARY TOTAL_PARTITIONS:<P> TOTAL_MESSAGES_PUBLISHED:<total_pub> TOTAL_MESSAGES_CONSUMED:<total_con> FINAL_LAG:<final_lag> MAX_IDLE_CONSUMERS_OBSERVED:<max_idle> WASTED_CONSUMER_RESOURCES_DETECTED:<YES|NO>
  ```
  - `WASTED_CONSUMER_RESOURCES_DETECTED`: 관측된 최대 유휴 컨슈머 수(`max_idle`)가 1 이상이면 `YES`, 아니면 `NO`.

---

## 5. 입출력 예시

### 예시 입력 1
```text
TOPIC_PARTITIONS 3
STRATEGY ROUND_ROBIN
EVENTS 9
JOIN c-01
JOIN c-02
JOIN c-03
JOIN c-04
JOIN c-05
PUBLISH 0 10
PUBLISH 1 10
PUBLISH 2 10
CONSUME 5
```

### 예시 출력 1
```text
REBALANCE STRATEGY:ROUND_ROBIN ACTIVE_CONSUMERS:1 IDLE_CONSUMERS:0
ASSIGNMENT c-01 -> [0,1,2]
REBALANCE STRATEGY:ROUND_ROBIN ACTIVE_CONSUMERS:2 IDLE_CONSUMERS:0
ASSIGNMENT c-01 -> [0,2]
ASSIGNMENT c-02 -> [1]
REBALANCE STRATEGY:ROUND_ROBIN ACTIVE_CONSUMERS:3 IDLE_CONSUMERS:0
ASSIGNMENT c-01 -> [0]
ASSIGNMENT c-02 -> [1]
ASSIGNMENT c-03 -> [2]
REBALANCE STRATEGY:ROUND_ROBIN ACTIVE_CONSUMERS:3 IDLE_CONSUMERS:1
ASSIGNMENT c-01 -> [0]
ASSIGNMENT c-02 -> [1]
ASSIGNMENT c-03 -> [2]
ASSIGNMENT c-04 -> NONE
REBALANCE STRATEGY:ROUND_ROBIN ACTIVE_CONSUMERS:3 IDLE_CONSUMERS:2
ASSIGNMENT c-01 -> [0]
ASSIGNMENT c-02 -> [1]
ASSIGNMENT c-03 -> [2]
ASSIGNMENT c-04 -> NONE
ASSIGNMENT c-05 -> NONE
PUBLISH PARTITION:0 ADDED:10 TOTAL_LAG:10
PUBLISH PARTITION:1 ADDED:10 TOTAL_LAG:20
PUBLISH PARTITION:2 ADDED:10 TOTAL_LAG:30
CONSUME ACTIVE_WORKERS:3 PROCESSED:15 REMAINING_LAG:15
SUMMARY TOTAL_PARTITIONS:3 TOTAL_MESSAGES_PUBLISHED:30 TOTAL_MESSAGES_CONSUMED:15 FINAL_LAG:15 MAX_IDLE_CONSUMERS_OBSERVED:2 WASTED_CONSUMER_RESOURCES_DETECTED:YES
```

### 설명
- 토픽의 파티션은 3개뿐입니다 ($P = 3$).
- `c-01`, `c-02`, `c-03`까지는 1인당 1개씩 파티션을 맡아 완벽하게 일합니다.
- 하지만 욕심을 부려 `c-04`, `c-05`를 추가 투입하자, 파티션이 부족하여 두 컨슈머는 아무 파티션도 할당받지 못하고 `NONE` (유휴 놀고 있는 상태)이 됩니다.
- 메시지를 소비할 때도 오직 3대의 활성 워커만 일하여 15개를 처리하며, 잉여 컨슈머 2대는 0개를 처리합니다.
- 최종적으로 **클라우드 인스턴스 2대가 낭비되었음(`WASTED_CONSUMER_RESOURCES_DETECTED: YES`)**을 명확히 증명합니다.
