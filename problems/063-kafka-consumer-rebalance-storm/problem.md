# Problem 063: 카프카 리밸런싱 폭풍과 협력적 스티키 할당자 (Kafka Rebalance Storm & Cooperative Sticky Assignor)

## 문제 설명

대규모 실시간 데이터 파이프라인을 운영 중인 당신의 팀에서 심각한 프로덕션 장애가 발생했습니다:
> "쿠버네티스에서 컨슈머 팟을 새로운 버전으로 롤링 배포했을 뿐인데,  
> 롤링 배포가 진행되는 5분 동안 전체 메시지 처리가 100% 멈춰버렸습니다!  
> 그사이 카프카 랙(Consumer Lag)이 수백만 건 쌓여서 실시간 결제 알림이 전부 지연되었습니다!"

로그를 분석한 결과, 원인은 카프카의 고전적 파티션 할당 프로토콜인 **Eager Rebalance**였습니다:
- 새로운 팟이 뜨거나 기존 팟이 내려갈 때마다, **살아있는 모든 컨슈머가 자신이 소유한 모든 파티션을 일제히 반환(Revoke All Partitions)**했습니다.
- 모든 파티션이 회수되는 동안 그룹 전체가 **Stop-The-World** 상태에 빠졌고,
- 팟이 1개씩 순차 재기동될 때마다 이 전면 회수-재할당 과정이 반복되며 끔찍한 **리밸런싱 폭풍(Rebalance Storm)**을 일으킨 것입니다!

당신은 Apache Kafka 2.4+의 표준인 **협력적 스티키 할당자(Cooperative Sticky Assignor)**를 구현하여,  
소유권 이전이 꼭 필요한 최소한의 파티션만 조용히 선별 반환(`Cooperative Revocation`)하고,  
기존 컨슈머의 파티션은 멈춤 없이 그대로 보존(`Sticky Retention`)하는 고효율 무중단 리밸런싱 엔진을 구축해야 합니다.

동일한 컨슈머 이벤트 시퀀스에 대해 **Eager Assignor**와 **Cooperative Sticky Assignor**의 파티션 할당 및 이동 내역을 시뮬레이션하고 비교하는 프로그램을 작성하세요.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정
- `NUM_PARTITIONS <num>`: 토픽의 총 파티션 개수 $N$.
- 파티션 식별자는 `P0, P1, P2, ..., P(N-1)` 로 주어집니다.
- 컨슈머 식별자는 임의의 문자열이며, 정렬 시 사전식 오름차순을 따릅니다.

### 2. Eager RoundRobin Assignor 동작 규칙
- `JOIN <consumer_id>` 또는 `LEAVE <consumer_id>` 이벤트 발생 시:
  - **1단계 (전원 반환)**: 현재 살아있던 모든 컨슈머가 보유하고 있던 **모든 파티션을 즉시 일괄 반환**합니다.
    - 반환된 파티션 수 = 기존에 할당되어 있던 전체 파티션 수의 합 (`REVOKED`).
  - **2단계 (백지 상태 라운드로빈 재분배)**:
    - 현재 활성 컨슈머 $M$개(`active_consumers`, 사전순 정렬)에게 `P0`부터 `P(N-1)`까지 라운드로빈으로 배분합니다:
      - `P_i` $\to$ `active_consumers[i % M]`
    - 각 컨슈머가 새로 할당받은 파티션 중, 리밸런싱 직전에 자신이 소유하지 않았던 새로운 파티션의 개수의 합을 `MIGRATED`로 기록합니다.

### 3. Cooperative Sticky Assignor 동작 규칙
- **목표 균등 할당량 (Target Quota)**:
  - 활성 컨슈머 수 $M$개일 때, `base = N // M`, `rem = N % M`.
  - 사전순 상위 `rem`개 컨슈머의 목표치는 `base + 1`개, 나머지 컨슈머는 `base`개입니다.
- **1단계 (선별적 협력 반환)**:
  - `LEAVE <consumer_id>`인 경우: 떠난 컨슈머가 쥐고 있던 파티션만 반환(`REVOKED`)되어 미할당 풀(`unassigned_pool`)로 이동합니다. **(살아있는 다른 컨슈머의 파티션은 1개도 건드리지 않습니다!)**
  - `JOIN <consumer_id>`인 경우:
    - 현재 자신의 파티션 수가 목표치(`target_quota`)를 초과하는 컨슈머만 초과분만큼 반환합니다.
    - 각 초과 컨슈머는 번호가 큰 파티션(예: P5, P4...)부터 필요한 만큼만 반환하여 `unassigned_pool`로 넘깁니다 (`REVOKED`).
    - 목표치를 초과하지 않은 컨슈머는 파티션을 **전혀 반환하지 않고 계속 보유**합니다.
- **2단계 (미할당 파티션 최소 배분)**:
  - `unassigned_pool`에 있는 파티션들을 번호 오름차순(P0, P1...)으로 정렬합니다.
  - 현재 할당량이 자신의 목표치보다 부족한 컨슈머(사전순)에게 순서대로 배분합니다.
- **지표 집계**:
  - `RETAINED`: 이번 리밸런싱 전후로 동일한 컨슈머에게 유지된 파티션 총합.
  - `MIGRATED`: 이번 리밸런싱으로 새롭게 주인이 바뀐 파티션 총합.

---

## 입력 형식

```text
NUM_PARTITIONS <num>
<ACTION> <consumer_id>
...
```

- 첫 번째 줄: `NUM_PARTITIONS <num>` ($1 \le \text{num} \le 100$)
- 이후 줄들: 다음 두 명령 중 하나:
  - `JOIN <consumer_id>`
  - `LEAVE <consumer_id>`

---

## 출력 형식

각 이벤트마다 3줄씩 출력합니다 (인덱스는 1부터 시작):
```text
EVENT <idx> <ACTION> <consumer_id>
  EAGER: REVOKED:<revoked> MIGRATED:<migrated> ASSIGNMENTS:<assignments>
  STICKY: REVOKED:<revoked> MIGRATED:<migrated> RETAINED:<retained> ASSIGNMENTS:<assignments>
```

- `ASSIGNMENTS` 형식:
  - 컨슈머는 사전순 정렬: `c1`, `c2`...
  - 각 컨슈머의 파티션은 번호 오름차순: `C1=[P0,P1,P2]`
  - 여러 컨슈머는 쉼표(`,`)로 구분: `C1=[P0,P2],C2=[P1,P3]`
  - 활성 컨슈머가 0명이면 `ASSIGNMENTS:NONE`

모든 이벤트 처리가 끝난 후, 최종 요약 3줄을 출력합니다:
```text
SUMMARY EAGER TOTAL_REVOCATIONS:<r1> TOTAL_MIGRATIONS:<m1>
SUMMARY STICKY TOTAL_REVOCATIONS:<r2> TOTAL_MIGRATIONS:<m2> TOTAL_RETAINED:<ret2>
SUMMARY REVOCATIONS_SAVED:<r1 - r2> (EFFICIENCY:<pct>%)
```
- `EFFICIENCY`는 `((r1 - r2) / r1) * 100`을 소수점 둘째 자리까지 출력합니다. (만약 `r1 == 0`이면 `0.00%`)

---

## 입출력 예시

### 예시 1: 6개 파티션 점진적 확장 및 축소

**입력:**
```text
NUM_PARTITIONS 6
JOIN C1
JOIN C2
JOIN C3
LEAVE C2
JOIN C4
```

**출력:**
```text
EVENT 1 JOIN C1
  EAGER: REVOKED:0 MIGRATED:6 ASSIGNMENTS:C1=[P0,P1,P2,P3,P4,P5]
  STICKY: REVOKED:0 MIGRATED:6 RETAINED:0 ASSIGNMENTS:C1=[P0,P1,P2,P3,P4,P5]
EVENT 2 JOIN C2
  EAGER: REVOKED:6 MIGRATED:3 ASSIGNMENTS:C1=[P0,P2,P4],C2=[P1,P3,P5]
  STICKY: REVOKED:3 MIGRATED:3 RETAINED:3 ASSIGNMENTS:C1=[P0,P1,P2],C2=[P3,P4,P5]
EVENT 3 JOIN C3
  EAGER: REVOKED:6 MIGRATED:4 ASSIGNMENTS:C1=[P0,P3],C2=[P1,P4],C3=[P2,P5]
  STICKY: REVOKED:2 MIGRATED:2 RETAINED:4 ASSIGNMENTS:C1=[P0,P1],C2=[P3,P4],C3=[P2,P5]
EVENT 4 LEAVE C2
  EAGER: REVOKED:4 MIGRATED:3 ASSIGNMENTS:C1=[P0,P2,P4],C3=[P1,P3,P5]
  STICKY: REVOKED:2 MIGRATED:2 RETAINED:4 ASSIGNMENTS:C1=[P0,P1,P3],C3=[P2,P4,P5]
EVENT 5 JOIN C4
  EAGER: REVOKED:6 MIGRATED:4 ASSIGNMENTS:C1=[P0,P3],C3=[P1,P4],C4=[P2,P5]
  STICKY: REVOKED:2 MIGRATED:2 RETAINED:4 ASSIGNMENTS:C1=[P0,P1],C3=[P2,P4],C4=[P3,P5]
SUMMARY EAGER TOTAL_REVOCATIONS:22 TOTAL_MIGRATIONS:20
SUMMARY STICKY TOTAL_REVOCATIONS:9 TOTAL_MIGRATIONS:15 TOTAL_RETAINED:15
SUMMARY REVOCATIONS_SAVED:13 (EFFICIENCY:59.09%)
```

**설명:**
- `EVENT 2`: C2가 합류할 때 Eager는 C1의 6개 전원을 뺏어갔지만, Sticky는 딱 초과분 3개만 양보하고 3개는 그대로 유지(`RETAINED:3`)했습니다.
- `EVENT 4`: C2가 떠났을 때 Eager는 C1과 C3의 파티션까지 모조리 뺏어 재분배(REVOKED:4)했지만, Sticky는 C2의 파티션 2개만 회수하고 살아있는 C1과 C3의 기존 4개 파티션은 멈춤 없이 그대로 유지(`RETAINED:4`)했습니다!
- 전체 파티션 반환 비용을 22회에서 9회로 **59.09% 대폭 절감**했습니다!
