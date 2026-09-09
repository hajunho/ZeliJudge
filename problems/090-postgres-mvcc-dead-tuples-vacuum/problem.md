# Problem #090: 10만 건 UPDATE 쳤더니 테이블이 왜 50GB로 부풀어요?!: PostgreSQL MVCC, 데드 튜플(Dead Tuple)과 진공 청소(Vacuum)의 비극

## 1. 문제 설명
대규모 데이터베이스를 운영하는 백엔드 엔지니어인 당신은 회원 테이블의 데이터가 10만 건뿐인데 디스크 용량이 50GB로 비대해지고 단순 `SELECT` 쿼리마저 수십 초씩 지연되는 심각한 장애를 마주했습니다.

MySQL(InnoDB)과 달리 **PostgreSQL은 모든 행이 불변(Immutable Tuple)으로 관리되는 MVCC 모델**을 따릅니다.  
따라서 `UPDATE`를 실행하면 기존 행을 제자리에서 덮어쓰지 않고, **기존 행에 사망 선고(`xmax`)를 내린 뒤 새 버전의 튜플(`xmin`)을 추가 삽입**합니다.  
이로 인해 사망한 찌꺼기인 **데드 튜플(Dead Tuple)** 이 테이블에 쌓이며, 주기적으로 **Autovacuum**이 이를 청소(Reclaim)하여 공간을 확보해야 합니다.

하지만 백그라운드 분석 스크립트나 관리자 세션이 트랜잭션을 열어둔 채 방치(`idle in transaction`)하면, 해당 트랜잭션의 **`xmin_horizon`** 이 과거에 묶여 **Autovacuum이 데드 튜플을 청소하지 못하고 전면 차단(`AUTOVACUUM_BLOCKED`)** 됩니다!  
결국 수백만 개의 유령 시체들이 디스크를 점령하는 **테이블 블로트(Table Bloat)** 가 발생합니다.

당신은 PostgreSQL의 튜플 라이프사이클(`xmin`, `xmax`)과 트랜잭션 가시성 지평선(`xmin_horizon`)을 추적하고, 데드 튜플 누적 및 Vacuum 청소 동작을 정밀하게 검증하는 시뮬레이터를 구축해야 합니다.

---

## 2. 시스템 동작 규칙

### (1) 스토리지 및 트랜잭션 모델
- 테이블은 고정 크기 슬롯의 페이지(Page)들로 구성됩니다. 한 페이지는 최대 `PAGE_CAPACITY`개의 튜플을 수용할 수 있습니다.
- 새로운 튜플이 삽입될 때, 마지막 페이지에 자리가 있으면 해당 페이지에 적재되고, 가득 찼다면 새 페이지가 할당됩니다 (`page_id = 0, 1, 2, ...`).
- 모든 튜플은 고유한 `tuple_id` (1부터 시작), `key`, `val`, `xmin`, `xmax`, `state`(`LIVE`, `DEAD`, `RECLAIMED`)를 가집니다.
- 트랜잭션이 시작될 때마다 단조 증가하는 고유 시퀀스 번호(`seq = 1, 2, 3, ...`)가 부여됩니다.
- 현재 활성(열려 있는) 트랜잭션 목록이 존재할 때, 가시성 지평선 `xmin_horizon`은 **활성 트랜잭션 중 가장 오래된 시퀀스 번호(oldest_xmin)** 가 됩니다:
  $$\text{xmin\_horizon} = \min(\text{active\_txs}) \quad (\text{활성 트랜잭션이 없으면 현재 최고 시퀀스} + 1)$$
- **Vacuum 청소 조건**: 데드 튜플의 $\text{xmax} < \text{xmin\_horizon}$ 일 때만 안전하게 공간을 청소(`RECLAIMED`)할 수 있습니다. 만약 $\text{xmax} \ge \text{xmin\_horizon}$ 이라면 활성 트랜잭션이 과거 스냅샷으로 조회할 수 있으므로 청소가 차단됩니다.

---

### (2) 액션 명세

1. `BEGIN <tx_id>`:
   - 새 트랜잭션을 시작하고 활성 목록에 추가합니다.
   - 출력:
     `ACT <idx> BEGIN <tx_id> ACTIVE_TXS:<count> XMIN_HORIZON:<tx_id_or_NONE>`
     (여기서 `<tx_id_or_NONE>`은 가장 오래된 활성 트랜잭션의 ID)

2. `INSERT <tx_id> <key> <val>`:
   - `<key>`에 대한 새 튜플을 생성합니다 (`xmin = current_tx_seq`, `xmax = 0`, `state = LIVE`).
   - 출력:
     `ACT <idx> INSERT <tx_id> KEY:<key> VAL:<val> TUPLE_ID:<t_id> PAGE:<p_id>`

3. `UPDATE <tx_id> <key> <val>`:
   - 해당 `<key>`의 현재 `LIVE` 튜플을 찾아 `xmax = current_tx_seq`, `state = DEAD`로 변경합니다.
   - 새 튜플을 생성하여 추가 삽입합니다 (`xmin = current_tx_seq`, `xmax = 0`, `state = LIVE`).
   - 출력:
     `ACT <idx> UPDATE <tx_id> KEY:<key> VAL:<val> OLD_TUPLE:<old_id> NEW_TUPLE:<new_id> PAGE:<p_id>`

4. `DELETE <tx_id> <key>`:
   - 해당 `<key>`의 현재 `LIVE` 튜플을 찾아 `xmax = current_tx_seq`, `state = DEAD`로 변경합니다.
   - 출력:
     `ACT <idx> DELETE <tx_id> KEY:<key> DEAD_TUPLE:<t_id>`

5. `COMMIT <tx_id>`:
   - 트랜잭션을 커밋하고 활성 목록에서 제거합니다.
   - 출력:
     `ACT <idx> COMMIT <tx_id> ACTIVE_TXS:<count> XMIN_HORIZON:<tx_id_or_NONE>`

6. `VACUUM`:
   - 현재 시점의 `xmin_horizon`을 기준으로 테이블 전체를 스캔하여 청소합니다.
   - 상태가 `DEAD`인 튜플 중:
     - $\text{xmax} < \text{xmin\_horizon}$ 인 튜플 $\to$ `state = RECLAIMED`로 전환 (이번 라운드 청소 완료 카운트 증가).
     - $\text{xmax} \ge \text{xmin\_horizon}$ 인 튜플 $\to$ 청소 보류 (블로킹 카운트 증가).
   - 테이블 블로트율 계산:
     $$\text{BLOAT} = \frac{\text{현재 DEAD 튜플 수}}{\text{현재 LIVE 튜플 수} + \text{현재 DEAD 튜플 수}} \times 100.0\%$$
     (분모가 0이면 0.0%)
   - 만약 보류된 데드 튜플(`BLOCKED_DEAD`)이 1개 이상 있다면 `[AUTOVACUUM_BLOCKED]` 플래그를 붙여 출력합니다:
     `ACT <idx> VACUUM RECLAIMED:<reclaimed_this_run> BLOCKED_DEAD:<blocked_cnt> LIVE:<live_cnt> BLOAT:<bloat_pct:.1f>% [AUTOVACUUM_BLOCKED]`
     보류된 데드 튜플이 없다면:
     `ACT <idx> VACUUM RECLAIMED:<reclaimed_this_run> BLOCKED_DEAD:0 LIVE:<live_cnt> BLOAT:<bloat_pct:.1f>%`

---

## 3. 입력 형식

```text
SYSTEM_CONFIG
PAGE_CAPACITY <int>
ACTIONS
<ACTION_1>
<ACTION_2>
...
```

---

## 4. 출력 형식

각 액션마다 `ACT <act_idx> ...` 한 줄씩 출력합니다.  
모든 액션 완료 후 `SUMMARY`를 출력합니다:

```text
SUMMARY TOTAL_ACTIONS:<cnt>
SUMMARY TOTAL_PAGES:<total_pages>
SUMMARY TOTAL_LIVE_TUPLES:<live_cnt>
SUMMARY TOTAL_DEAD_TUPLES:<dead_cnt>
SUMMARY TOTAL_RECLAIMED_TUPLES:<total_reclaimed>
SUMMARY TABLE_BLOAT_RATIO:<bloat_pct:.1f>%
SUMMARY VACUUM_BLOCKED_INCIDENT: <TRUE|FALSE>
```

- `VACUUM_BLOCKED_INCIDENT`: 시뮬레이션 중 `[AUTOVACUUM_BLOCKED]`가 1회라도 발생했다면 `TRUE`, 아니면 `FALSE`.

---

## 5. 입출력 예시

### 예시 입력 1
```text
SYSTEM_CONFIG
PAGE_CAPACITY 3
ACTIONS
BEGIN TX_ZOMBIE
BEGIN TX_1
INSERT TX_1 user_1 100
UPDATE TX_1 user_1 200
COMMIT TX_1
VACUUM
COMMIT TX_ZOMBIE
VACUUM
```

### 예시 출력 1
```text
ACT 1 BEGIN TX_ZOMBIE ACTIVE_TXS:1 XMIN_HORIZON:TX_ZOMBIE
ACT 2 BEGIN TX_1 ACTIVE_TXS:2 XMIN_HORIZON:TX_ZOMBIE
ACT 3 INSERT TX_1 KEY:user_1 VAL:100 TUPLE_ID:1 PAGE:0
ACT 4 UPDATE TX_1 KEY:user_1 VAL:200 OLD_TUPLE:1 NEW_TUPLE:2 PAGE:0
ACT 5 COMMIT TX_1 ACTIVE_TXS:1 XMIN_HORIZON:TX_ZOMBIE
ACT 6 VACUUM RECLAIMED:0 BLOCKED_DEAD:1 LIVE:1 BLOAT:50.0% [AUTOVACUUM_BLOCKED]
ACT 7 COMMIT TX_ZOMBIE ACTIVE_TXS:0 XMIN_HORIZON:NONE
ACT 8 VACUUM RECLAIMED:1 BLOCKED_DEAD:0 LIVE:1 BLOAT:0.0%
SUMMARY TOTAL_ACTIONS:8
SUMMARY TOTAL_PAGES:1
SUMMARY TOTAL_LIVE_TUPLES:1
SUMMARY TOTAL_DEAD_TUPLES:0
SUMMARY TOTAL_RECLAIMED_TUPLES:1
SUMMARY TABLE_BLOAT_RATIO:0.0%
SUMMARY VACUUM_BLOCKED_INCIDENT: TRUE
```
