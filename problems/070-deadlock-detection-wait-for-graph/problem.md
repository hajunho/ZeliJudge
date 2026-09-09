# Problem 070: 데이터베이스 데드락과 대기 그래프 사이클 탐지 (Database Deadlock & Wait-For Graph Cycle Detection)

## 문제 설명

대규모 결제 시스템을 운영하는 엔터프라이즈 데이터베이스 팀에서 원인 불명의 전사 마비 사고가 발생했습니다:
> "분명히 평소와 동일한 결제 및 재고 차감 트랜잭션 2개가 동시에 실행되었을 뿐인데, 데이터베이스 CPU는 0%인 채로 모든 커넥션이 50초 동안 멈춰 섰습니다!  
> 50초 동안 유입된 5,000건의 후속 요청들이 모조리 락 대기열에 갇혀 커넥션 풀이 전멸했고, 결국 `Lock wait timeout exceeded` 에러를 뿜으며 쇼핑몰 전체가 500 에러로 다운되었습니다!"

원인은 데이터베이스에서 흔히 발생하는 **교착 상태(Deadlock, 데드락)**였습니다:
- 트랜잭션 A가 상품 1의 행 락(Row Lock)을 쥔 채 상품 2의 락을 요청하고,
- 트랜잭션 B가 상품 2의 행 락을 쥔 채 상품 1의 락을 요청하면서,
- 서로가 서로의 자원을 영원히 기다리는 **환형 대기(Circular Wait)**에 빠진 것입니다.

좁은 외나무다리에서 마주친 두 마리 고집불통 염소가 서로 양보하지 않아 굶어 죽을 때까지 다리가 마비되는 것과 같습니다.  
이때 데이터베이스가 단순 타임아웃(Naive Timeout)에만 의존한다면, 50초라는 긴 시간 동안 시스템 전체가 동결(Freeze)되어 서비스가 파산에 이르게 됩니다.

현대 고성능 RDBMS(MySQL InnoDB, PostgreSQL 등)는 이를 방지하기 위해 **대기 그래프(Wait-For Graph) 기반 데드락 감지기(Deadlock Detector)**를 탑재하고 있습니다:
1. **대기 유향 그래프 실시간 유지**: 트랜잭션이 락을 얻지 못하고 대기할 때마다 $T_{\text{wait}} \to T_{\text{holder}}$ 간선을 연결합니다.
2. **사이클(Cycle) 즉시 탐지**: 그래프 상에서 순환 고리($T_1 \to T_2 \to T_1$)가 발견되는 즉시 데드락을 선포합니다.
3. **희생자 선정(Victim Selection) 및 즉각 롤백**: 사이클에 연루된 트랜잭션 중 **작업 비용(수정한 행 수 / Undo 로그 양)이 가장 적은 트랜잭션**을 희생자로 지정하여 강제 롤백하고 락을 즉각 해제합니다.
4. **0-Tick 복구**: 희생자가 쥐고 있던 락이 즉시 해제되므로, 살아남은 트랜잭션은 50초를 기다릴 필요 없이 **0틱 만에 즉시 락을 획득하고 정상 진행**합니다!

당신은 동일한 트랜잭션 락 요청 스트림에 대해 **Naive Timeout 엔진**과 **Active Deadlock Detection 엔진**의 대기 틱 수, 타임아웃 롤백, 데드락 즉시 해소 과정을 비교 시뮬레이션하는 데이터베이스 동시성 엔진을 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정
- `LOCK_TIMEOUT_TICKS <timeout_ticks>`: Naive 엔진에서 락 대기 시 허용되는 최대 틱 수 (기본값: 50).
  - 대기 시간이 이 틱에 도달하면 `TIMEOUT_ROLLBACK` 처리됨.

---

### 2. 두 가지 엔진 아키텍처

#### 1) Naive Timeout Engine (안티패턴)
- 데드락 감지기가 없습니다.
- 자원이 이미 다른 트랜잭션에 의해 점유되어 있으면 대기열(FIFO)에 진입합니다.
- `TICK <k>`가 진행될 때마다 대기 중인 모든 트랜잭션의 누적 대기 틱 수가 $k$만큼 증가합니다.
- 누적 대기 틱이 `LOCK_TIMEOUT_TICKS`에 도달하면 비로소 `TIMEOUT_ROLLBACK`이 발생하여 롤백되고, 점유 중이던 락이 해제되어 다음 대기자에게 승계됩니다.

#### 2) Active Deadlock Detection Engine (모범 설계)
- 락 요청이 블로킹될 때마다 즉시 대기 그래프(Wait-For Graph)에 $T_{\text{wait}} \to T_{\text{holder}}$ 간선을 추가하고 사이클 검사를 수행합니다.
- **사이클이 없을 때**: 정상 대기 상태 유지.
- **사이클이 발견되었을 때 (데드락!)**:
  - 사이클을 구성하는 트랜잭션들 중 **비용(`cost`)이 가장 낮은 트랜잭션**을 희생자(`VICTIM`)로 선정합니다.
  - 비용이 동일한 경우, 트랜잭션 ID의 숫자 부분이 더 큰 트랜잭션을 희생자로 선정합니다 (Tie-breaking Rule).
  - 희생자 트랜잭션을 즉시 롤백(`DEADLOCK_ROLLBACK`):
    - 희생자가 쥐고 있던 모든 락을 즉각 해제하여 대기자에게 승계합니다.
    - 희생자가 대기 중이던 락 요청을 큐에서 제거합니다.
  - 결과적으로 데드락이 **시간 경과(0-Tick) 없이 즉시 해소**됩니다.

---

### 3. 6대 액션 명세

#### 1) `START_TX <tx_id> <cost>`
- 트랜잭션 시작 (비용/작업량 부여).
- 출력 (1줄):
  ```text
  ACT <idx> START_TX <tx_id> COST:<cost>
  ```

#### 2) `ACQUIRE_LOCK <tx_id> <res_id>`
- 자원에 대한 배타락 요청.
- 획득 성공 시:
  ```text
  ACT <idx> ACQUIRE_LOCK <tx_id> RES:<res_id>
    NAIVE: GRANTED
    DETECTOR: GRANTED
  ```
- 블로킹 시 (데드락 없음):
  ```text
  ACT <idx> ACQUIRE_LOCK <tx_id> RES:<res_id>
    NAIVE: BLOCKED (WAITING_ON:<holder>)
    DETECTOR: BLOCKED (WAIT_FOR:<holder>)
  ```
- 블로킹 시 (데드락 사이클 감지!):
  ```text
  ACT <idx> ACQUIRE_LOCK <tx_id> RES:<res_id>
    NAIVE: BLOCKED (WAITING_ON:<holder>)
    DETECTOR: DEADLOCK_DETECTED CYCLE:[<cycle_path>] VICTIM:<victim_tx> (COST:<cost>) RESOLVED
  ```
  - `<cycle_path>`: `T2->T1->T2` 형식으로 사이클 순환 경로 표기.

#### 3) `RELEASE_LOCK <tx_id> <res_id>`
- 점유 중인 락 명시적 반환.
- 출력 (3줄):
  ```text
  ACT <idx> RELEASE_LOCK <tx_id> RES:<res_id>
    NAIVE: RELEASED
    DETECTOR: RELEASED
  ```

#### 4) `COMMIT_TX <tx_id>`
- 트랜잭션 정상 커밋 (보유 중인 모든 락 해제 및 대기자에게 승계).
- 출력 (3줄):
  ```text
  ACT <idx> COMMIT_TX <tx_id>
    NAIVE: <COMMITTED|FAILED_ALREADY_...> RELEASED_LOCKS:<cnt>
    DETECTOR: <COMMITTED|FAILED_ALREADY_...> RELEASED_LOCKS:<cnt>
  ```

#### 5) `TICK <ticks>`
- 시간 경과. Naive 엔진에서 블로킹 대기 중인 트랜잭션의 누적 대기 시간 증가 및 타임아웃 판정.
- 출력 (3줄):
  ```text
  ACT <idx> TICK <ticks>
    NAIVE: TIME_ADVANCED WAITING_TXS:<cnt> TIMEOUT_EVENTS:<cnt>
    DETECTOR: TIME_ADVANCED WAITING_TXS:<cnt> TIMEOUT_EVENTS:<cnt>
  ```

#### 6) `CHECK_STATUS`
- 현재 활성 트랜잭션 수, 블로킹 수, 누적 블로킹 틱 수 확인.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_STATUS
    NAIVE: ACTIVE_TXS:<cnt> BLOCKED_TXS:<cnt> TOTAL_BLOCKED_TICKS:<ticks> TIMEOUT_ROLLBACKS:<cnt>
    DETECTOR: ACTIVE_TXS:<cnt> BLOCKED_TXS:<cnt> TOTAL_BLOCKED_TICKS:<ticks> DEADLOCK_RESOLVED:<cnt>
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
LOCK_TIMEOUT_TICKS <timeout_ticks>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 출력 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (5줄):
```text
SUMMARY TOTAL_TRANSACTIONS:<tot_tx>
SUMMARY NAIVE TOTAL_BLOCKED_TICKS:<ticks> TIMEOUT_ROLLBACKS:<cnt>
SUMMARY DETECTOR TOTAL_BLOCKED_TICKS:<ticks> DEADLOCK_RESOLVED:<cnt> 0_TICK_RECOVERIES:<cnt>
SUMMARY LATENCY_SAVED_TICKS:<diff> (BLOCKING_REDUCTION:<pct:.2f>%)
SUMMARY ENGINE_VERDICT: DETECTOR_PREVENTS_SYSTEM_FREEZE
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
LOCK_TIMEOUT_TICKS 50
ACTIONS
START_TX T1 10
START_TX T2 5
ACQUIRE_LOCK T1 R1
ACQUIRE_LOCK T2 R2
ACQUIRE_LOCK T1 R2
ACQUIRE_LOCK T2 R1
TICK 50
CHECK_STATUS
COMMIT_TX T1
```

**출력:**
```text
ACT 1 START_TX T1 COST:10
ACT 2 START_TX T2 COST:5
ACT 3 ACQUIRE_LOCK T1 RES:R1
  NAIVE: GRANTED
  DETECTOR: GRANTED
ACT 4 ACQUIRE_LOCK T2 RES:R2
  NAIVE: GRANTED
  DETECTOR: GRANTED
ACT 5 ACQUIRE_LOCK T1 RES:R2
  NAIVE: BLOCKED (WAITING_ON:T2)
  DETECTOR: BLOCKED (WAIT_FOR:T2)
ACT 6 ACQUIRE_LOCK T2 RES:R1
  NAIVE: BLOCKED (WAITING_ON:T1)
  DETECTOR: DEADLOCK_DETECTED CYCLE:[T2->T1->T2] VICTIM:T2 (COST:5) RESOLVED
ACT 7 TICK 50
  NAIVE: TIME_ADVANCED WAITING_TXS:0 TIMEOUT_EVENTS:2
  DETECTOR: TIME_ADVANCED WAITING_TXS:0 TIMEOUT_EVENTS:0
ACT 8 CHECK_STATUS
  NAIVE: ACTIVE_TXS:0 BLOCKED_TXS:0 TOTAL_BLOCKED_TICKS:100 TIMEOUT_ROLLBACKS:2
  DETECTOR: ACTIVE_TXS:1 BLOCKED_TXS:0 TOTAL_BLOCKED_TICKS:0 DEADLOCK_RESOLVED:1
ACT 9 COMMIT_TX T1
  NAIVE: FAILED_ALREADY_TIMEOUT_ROLLBACK RELEASED_LOCKS:0
  DETECTOR: COMMITTED RELEASED_LOCKS:2
SUMMARY TOTAL_TRANSACTIONS:2
SUMMARY NAIVE TOTAL_BLOCKED_TICKS:100 TIMEOUT_ROLLBACKS:2
SUMMARY DETECTOR TOTAL_BLOCKED_TICKS:0 DEADLOCK_RESOLVED:1 0_TICK_RECOVERIES:1
SUMMARY LATENCY_SAVED_TICKS:100 (BLOCKING_REDUCTION:100.00%)
SUMMARY ENGINE_VERDICT: DETECTOR_PREVENTS_SYSTEM_FREEZE
```
