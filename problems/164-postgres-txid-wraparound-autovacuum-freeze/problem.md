# Problem #164: DB CPU도 여유로운데 왜 갑자기 모든 쓰기가 거부돼요?!: PostgreSQL MVCC Transaction ID (TXID) Wraparound 재앙과 Autovacuum Freeze 비상 셧다운 방어 (PostgreSQL MVCC Transaction ID Wraparound & Emergency Autovacuum Freeze)

---

## 🏢 실무 장애 시나리오

초당 수만 건의 결제 및 로그를 처리하는 글로벌 B2B SaaS 기업의 메인 PostgreSQL 클러스터(PostgreSQL 15)에서 평온하던 월요일 오전, 전례 없는 전면 서비스 마비 사태가 발생했습니다.

DB 서버의 CPU 사용률은 15% 미만이었고, 메모리와 디스크 I/O 역시 지극히 여유로웠습니다.
하지만 애플리케이션의 모든 `INSERT`, `UPDATE`, `DELETE` 트랜잭션이 일제히 다음과 같은 치명적인 에러를 뿜어내며 100% 실패하기 시작했습니다:

```text
ERROR: database is not accepting commands to avoid wraparound data loss in database "production_db"
HINT: Stop the postmaster and vacuum that database in single-user mode.
```

데이터베이스가 **"데이터 유실을 막기 위해 더 이상 명령을 받지 않겠다"**며 스스로 문을 걸어 잠그고 **비상 읽기 전용 셧다운(Emergency Read-Only Shutdown)**에 돌입한 것이었습니다!

인프라 로그를 긴급 역추적한 결과, 충격적인 사실이 밝혀졌습니다:
- 수년 전 한 개발자가 쓰기 성능을 올리겠다며 마이그레이션 백업 테이블(`legacy_audit_archive`)에 대해 `ALTER TABLE legacy_audit_archive SET (autovacuum_enabled = false);`를 설정해 두었습니다.
- 메인 서비스 테이블들은 열심히 진공 청소(Autovacuum)되고 있었지만, **단 한 번도 청소되지 않은 이 방치된 백업 테이블의 `relfrozenxid`가 100에 멈춰 있었습니다.**
- 전체 데이터베이스의 `datfrozenxid`는 가장 오래된 테이블에 묶이므로, 21.4억 번의 트랜잭션이 누적되자 데이터베이스의 나이(Age)가 한계선인 $2^{31}$에 도달했습니다.
- 만약 트랜잭션이 조금만 더 진행되어 래핑어라운드(Wraparound)가 발생하면, 수년 치의 과거 데이터 튜플들이 **"미래에 생성될 데이터"로 판정되어 `SELECT` 쿼리에서 영구히 증발(Silent Data Loss)**하는 대참사가 발생하기 때문에 커널이 비상 셧다운을 단행한 것이었습니다.

PostgreSQL의 32비트 트랜잭션 ID 순환 비교 모델과 튜플 동결(Freezing) 메커니즘을 시뮬레이션하여, 래핑어라운드 임계치를 감시하고 비상 셧다운과 데이터 유실을 완벽히 방어해주세요!

---

## 🎯 문제 설명

PostgreSQL 데이터베이스 설정(`config`)과 트랜잭션 실행 및 유지보수 작업(`operations`)을 순차적으로 처리하여, 최종 데이터베이스 상태 요약 통계(`get_summary()`)를 반환하는 `solve(input_data)` 함수를 작성하세요.

### 1. 트랜잭션 ID 및 MVCC 가시성 규칙
- 트랜잭션 ID(TXID)는 32비트 순환 모듈로 공간($2^{32}$)으로 동작합니다.
- 가시성 한계선: $\text{WRAPAROUND\_HORIZON} = 2^{31} = 2,147,483,648$
- 튜플 가시성 판정:
  - `frozen == True`인 튜플은 **항상 가시적(Visible)**입니다. (절대 유실되지 않음)
  - `frozen == False`인 튜플: $\Delta = (\text{current\_xid} - \text{xmin}) \pmod{2^{32}}$
    - $\Delta < 2^{31}$: 과거 데이터 $\to$ **정상 가시 (Visible)**
    - $\Delta \ge 2^{31}$: 미래 데이터로 취급 $\to$ **침묵의 데이터 유실 (Invisible!)**

### 2. 데이터베이스 나이(Age)와 4단계 상태 머신
- 각 테이블의 나이: $\text{age}_t = \text{current\_xid} - \text{relfrozenxid}_t$
- 데이터베이스 전체 나이: $\text{max\_age} = \text{current\_xid} - \text{datfrozenxid}$
  - $\text{datfrozenxid} = \min_{t \in \text{Tables}}(\text{relfrozenxid}_t)$
- 잔여 안전 트랜잭션 수: $\text{remaining\_xids\_to\_stop} = \max(0, (2^{31} - 1) - \text{max\_age})$
- 상태 머신:
  - $\text{remaining} \le 0$: **`WRAPAROUND_DATA_LOSS`** (이벤트: `SILENT_DATA_LOSS_DETECTED`)
  - $\text{remaining} \le \text{emergency\_stop\_remaining}$: **`EMERGENCY_READ_ONLY`** (이벤트: `EMERGENCY_SHUTDOWN_TRIGGERED`, 모든 신규 쓰기 차단)
  - $\text{max\_age} \ge (2^{31} - 100,000,000)$: **`WARNING`** (이벤트: `WARNING_APPROACHING_WRAPAROUND`)
  - 그 외: **`HEALTHY`** (진공 청소로 상태 복구 시 `HEALTH_RESTORED_POST_VACUUM` 이벤트 기록)

### 3. 작업(`operations`) 처리 규칙
- **`ADVANCE_TX`**:
  - `xid_count`만큼 `current_xid` 증가 및 `writes` 튜플 삽입.
  - `EMERGENCY_READ_ONLY` 상태인 경우 쓰기 거부 (`ERROR_EMERGENCY_READ_ONLY`).
- **`AUTOVACUUM_TICK`**:
  - 각 테이블에 대해:
    - $\text{age}_t \ge \text{autovacuum\_freeze\_max\_age}$: **안티 래핑어라운드 강제 동결** (`autovacuum_enabled` 무시, 전수 동결, 이벤트: `AUTOVACUUM_WRAPAROUND_TRIGGERED:<table_name>`)
    - $\text{autovacuum\_enabled} == \text{True}$이고 $\text{age}_t \ge \text{vacuum\_freeze\_min\_age}$: 해당 나이 이상의 튜플 동결.
- **`VACUUM_MANUAL`**:
  - 수동 `VACUUM FREEZE` 실행. `force_freeze == True`인 경우 대상 테이블의 모든 언프로즌 튜플을 즉시 동결하고 `relfrozenxid = current_xid`로 갱신.
- **`QUERY`**:
  - 테이블 튜플들의 MVCC 가시성 전수 검사 및 유실된 튜플 집계.

---

## 📥 입력 형식 (Input Format)

```json
{
  "config": {
    "autovacuum_freeze_max_age": 200000000,
    "vacuum_freeze_min_age": 50000000,
    "emergency_stop_remaining": 10000000,
    "initial_xid": 1000,
    "tables": {
      "users": {
        "relfrozenxid": 100,
        "autovacuum_enabled": true,
        "tuples": [
          {"id": 1, "xmin": 100, "frozen": false}
        ]
      }
    }
  },
  "operations": [
    {"type": "ADVANCE_TX", "xid_count": 60000000},
    {"type": "AUTOVACUUM_TICK"}
  ]
}
```

---

## 📤 출력 형식 (Output Format)

```json
{
  "current_xid": 60001000,
  "database_state": "HEALTHY",
  "datfrozenxid": 60001000,
  "max_age": 0,
  "remaining_xids_to_stop": 2147483647,
  "events_log": [],
  "tables": {
    "users": {
      "relfrozenxid": 60001000,
      "age": 0,
      "frozen_count": 1,
      "unfrozen_count": 0,
      "invisible_count": 0
    }
  }
}
```

---

## 💡 입출력 예시

### 예제 1: 정상 점진적 Autovacuum (Case 1 Baseline)
- 6천만 트랜잭션 경과 후 autovacuum 주기 도달.
- `vacuum_freeze_min_age`(5천만)를 넘긴 튜플이 정상 동결되고, `datfrozenxid`가 전진하여 나이가 0으로 리셋됨 (`HEALTHY`).

### 예제 2: 래핑어라운드 비상 읽기 전용 셧다운 (Case 3 Disaster)
- 방치된 테이블로 인해 나이가 21.43억에 도달, 잔여 트랜잭션이 400만 개($\le 5,000,000$)로 감소.
- `EMERGENCY_READ_ONLY` 상태로 전환되며 후속 쓰기 작업 거부 (`ERROR_EMERGENCY_READ_ONLY`).

---

## ⚙️ 제약 조건 (Constraints)
- $0 \le \text{xmin} < 2^{32}$
- $1 \le N_{\text{tables}} \le 16$
- $1 \le N_{\text{operations}} \le 500$
- $0 \le \text{emergency\_stop\_remaining} \le 200,000,000$
