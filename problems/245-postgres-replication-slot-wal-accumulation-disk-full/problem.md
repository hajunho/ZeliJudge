# Problem 245: 데이터베이스 스토리지 및 고가용성: PostgreSQL 복제 슬롯(Replication Slot) WAL 무제한 누적, 디스크 풀(Full) PANIC 크래시 및 `max_slot_wal_keep_size` 무효화

## 1. 개요 및 배경 시나리오

엔터프라이즈 환경에서 PostgreSQL 데이터베이스는 고가용성(HA)을 위한 스트리밍 복제(Physical Streaming Replication)와 마이크로서비스 간 이벤트 드리븐 동기화를 위한 CDC(Change Data Capture, Debezium / Kafka Connect) 논리적 복제(Logical Replication)를 널리 활용합니다.

PostgreSQL은 복제 지연(Replication Lag)이 발생하더라도 스탠바이 노드나 CDC 컨슈머가 필요한 트랜잭션 로그를 놓치지 않도록 **복제 슬롯(Replication Slot)** 메커니즘을 제공합니다. 복제 슬롯이 활성화되면, 주(Primary) 서버의 체크포인터(Checkpointer)는 슬롯의 **`restart_lsn`**보다 오래된 WAL(Write-Ahead Log, `pg_wal/`) 세그먼트를 **절대로 삭제하거나 재활용(Recycle)하지 않고 디스크에 보존**합니다.

```
                      PostgreSQL 복제 슬롯과 WAL 누적 메커니즘
                      
 Current WAL LSN: 50,000 MB (pg_current_wal_lsn)
                  │
                  ▼
  pg_wal/ ┌───────┬───────┬───────┬───────┬───────┬───────┬───────┬───────┐
  디스크:  │ WAL 1 │ WAL 2 │  ...  │ WAL k │  ...  │  ...  │ WAL N │       │  ==> 100% DISK FULL!
          └───────┴───────┴───────┴───────┴───────┴───────┴───────┴───────┘
              ▲                               ▲
              │                               │
        restart_lsn                     HA Standby LSN
    [Debezium CDC 슬롯 멈춤!]            (정상 동기화 중)
    (네트워크 단절 / Pod OOM 다운)
              │
              ▼
    [체크포인터의 WAL 삭제 거부!]
    "restart_lsn 이전의 WAL은 절대 지울 수 없다!"
    --> 10GB, 50GB, 100GB... WAL 무제한 폭증!
    --> PANIC: could not write to file "pg_wal/..." - No space left on device
    --> Primary DB 즉시 비정상 강제 다운! (전사 장애)
```

그러나 프로덕션 환경에서 다음과 같은 치명적인 스토리지 재앙이 발생합니다:

1. **복제 슬롯 중단에 의한 WAL 무제한 누적 및 디스크 풀 PANIC (`REPLICATION_SLOT_WAL_DISK_FULL_PANIC`)**:
   - CDC 파이프라인(Debezium, Flink 등)의 워커 노드가 OOM으로 죽거나 네트워크 단절로 수 시간 동안 멈춤.
   - 복제 슬롯의 `restart_lsn`이 과거 오프셋에 멈춰버림.
   - Primary DB에는 수많은 쓰기 트랜잭션이 지속적으로 유입되어 새로운 WAL을 계속 생성함.
   - `max_slot_wal_keep_size`가 기본값(`-1`, 무제한)으로 설정된 경우, 체크포인터는 WAL 세그먼트를 단 하나도 삭제하지 못하고 디스크에 계속 쌓아둠.
   - 결국 호스트 디스크 용량이 **100% 소진**되어 `PANIC: could not write to file "pg_wal/..." - No space left on device` 에러와 함께 **Primary DB가 즉시 강제 종료**되는 치명적인 대참사가 발생함.

2. **PostgreSQL 13+의 구원투수: `max_slot_wal_keep_size` 무효화 (`REPLICATION_SLOT_INVALIDATED_LOST`)**:
   - Primary DB 전체가 뻗는 재앙을 막기 위해, PostgreSQL 13부터 안전 임계치인 **`max_slot_wal_keep_size`**가 도입됨.
   - 특정 슬롯의 지연량($\text{current\_lsn} - \text{restart\_lsn}$)이 설정값을 초과하면, 커널은 지연된 슬롯을 과감히 **무효화(`wal_status = 'lost'`)**하고 보류 중이던 WAL을 강제 회수하여 주 데이터베이스의 생존을 보장함.

3. **장기 비활성 슬롯 방치 경고 (`ABANDONED_REPLICATION_SLOT_LAG_WARNING`)**:
   - 개발이나 테스트용으로 생성해 두고 방치된(Abandoned) 비활성 복제 슬롯이 수 기가바이트의 WAL을 쥐고 있어 디스크 용량을 지속적으로 갉아먹는 위험 상황.

본 과제에서는 PostgreSQL 복제 슬롯, 체크포인트 WAL 회수 알고리즘, `max_slot_wal_keep_size` 임계치 및 슬롯 무효화 상태 머신을 정밀하게 시뮬레이션하고 문제를 진단해야 합니다.

---

## 2. 상태 머신 및 동작 명세

시뮬레이터는 데이터베이스 설정(`db_config`), 복제 슬롯 목록(`replication_slots`), 그리고 일련의 이벤트(`events`)를 처리합니다.

### 2.1 데이터베이스 설정 (`db_config`)
- `disk_capacity_mb`: 호스트 디스크 총 용량 (MB).
- `base_data_size_mb`: 테이블 및 인덱스 기본 데이터 용량 (MB).
- `wal_segment_size_mb`: WAL 1개 파일 크기 (기본 16MB).
- `max_slot_wal_keep_size_mb`: 슬롯 최대 허용 WAL 지연 크기 (MB, `-1`이면 무제한).
- `min_wal_size_mb`: 체크포인트 후에도 최소 보존하는 WAL 크기 (기본 1024MB).

### 2.2 이벤트 동작 규칙 (`events`)

1. **`WRITE_BURST` (`wal_generated_mb`)**:
   - 주 데이터베이스에 트랜잭션이 발생하여 `wal_generated_mb`만큼의 신규 WAL이 생성됨.
   - $\text{current\_lsn\_mb} \mathrel{+}= \text{wal\_generated\_mb}$.
   - 현재 총 디스크 사용량: $\text{base\_data\_size\_mb} + (\text{current\_lsn\_mb} - \text{earliest\_wal\_lsn\_mb})$.
   - 디스크 용량이 `disk_capacity_mb`에 도달하거나 초과하면 **즉시 `db_crashed_disk_full = true`로 전이되며 시뮬레이션 종료**.

2. **`SLOT_ADVANCE` (`slot_name`, `consumed_mb`)**:
   - 복제 슬롯이 WAL을 소비하여 `restart_lsn_mb`를 전진시킴 ($\min(\text{current\_lsn\_mb}, \text{restart\_lsn\_mb} + \text{consumed\_mb})$).
   - 상태를 `active`로 유지.

3. **`SLOT_FAILURE` (`slot_name`, `reason`)**:
   - 컨슈머 다운 또는 네트워크 장애로 인해 복제 슬롯의 상태가 `inactive`로 변경되고 소비가 멈춤.

4. **`CHECKPOINT`**:
   - 체크포인터가 구동되어 오래된 WAL 세그먼트 삭제/재활용을 시도:
     - 1단계: 유효한 슬롯(`active`, `inactive`)들을 순회하며 WAL 지연량($\text{lag} = \text{current\_lsn\_mb} - \text{restart\_lsn\_mb}$) 검사.
     - `max_slot_wal_keep_size_mb > 0`이고 $\text{lag} > \text{max\_slot\_wal\_keep\_size\_mb}$인 경우:
       - 해당 슬롯의 상태를 **`lost`**로 무효화하고 `invalidation_reason = "max_slot_wal_keep_size_exceeded"` 기록.
     - 2단계: 무효화되지 않은 유효 슬롯들의 `restart_lsn_mb` 중 최솟값을 보존 한계선(`retained_horizon`)으로 설정.
     - 유효 슬롯이 하나도 없으면 $\max(0, \text{current\_lsn\_mb} - \text{min\_wal\_size\_mb})$를 한계선으로 설정.
     - `earliest_wal_lsn_mb`를 `retained_horizon`으로 갱신하여 이전 WAL을 삭제/회수.

---

### 2.3 감지해야 할 이상 징후 (`anomalies`) 및 권장안 (`recommendations`)

- `"REPLICATION_SLOT_WAL_DISK_FULL_PANIC"`:
  - WAL 누적으로 인해 디스크 사용률이 100%에 도달하여 데이터베이스가 크래시된 경우.
  - 권장안: `"CONFIGURE_MAX_SLOT_WAL_KEEP_SIZE"`, `"DROP_OR_REPAIR_ABANDONED_REPLICATION_SLOTS"`
- `"REPLICATION_SLOT_INVALIDATED_LOST"`:
  - `max_slot_wal_keep_size` 초과로 인해 지연된 슬롯이 무효화(`lost`)된 경우.
  - 권장안: `"REBUILD_SUBSCRIBER_FROM_FRESH_SNAPSHOT"`
- `"ABANDONED_REPLICATION_SLOT_LAG_WARNING"`:
  - 비활성(`inactive`) 슬롯이 5,000MB 이상의 WAL을 지연 보류 중인 경우.
  - 권장안: `"DROP_OR_REPAIR_ABANDONED_REPLICATION_SLOTS"`

---

## 3. 입력 형식 (`sys.stdin`)

표준 입력으로 단일 JSON 객체가 주어집니다.

```json
{
  "db_config": {
    "disk_capacity_mb": 50000,
    "base_data_size_mb": 10000,
    "wal_segment_size_mb": 16,
    "max_slot_wal_keep_size_mb": 5000,
    "min_wal_size_mb": 256
  },
  "replication_slots": [
    {"slot_name": "debezium_cdc", "slot_type": "logical", "status": "active", "restart_lsn_mb": 0}
  ],
  "events": [
    {"time_ms": 1000, "type": "SLOT_FAILURE", "slot_name": "debezium_cdc", "reason": "WORKER_OOM_CRASH"},
    {"time_ms": 2000, "type": "WRITE_BURST", "wal_generated_mb": 10000},
    {"time_ms": 3000, "type": "CHECKPOINT"}
  ]
}
```

---

## 4. 출력 형식 (`sys.stdout`)

표준 출력으로 JSON 객체를 단일 행으로 출력합니다 (`ensure_ascii=False`).

```json
{
  "current_wal_lsn_mb": 10000,
  "current_disk_used_mb": 10000,
  "disk_utilization_pct": 20.0,
  "active_wal_size_mb": 0,
  "retained_wal_count": 1,
  "slots_status": {
    "debezium_cdc": {
      "status": "lost",
      "wal_lag_mb": 10000,
      "restart_lsn_mb": 0,
      "invalidation_reason": "max_slot_wal_keep_size_exceeded"
    }
  },
  "db_crashed_disk_full": false,
  "anomalies": [
    "REPLICATION_SLOT_INVALIDATED_LOST"
  ],
  "recommendations": [
    "REBUILD_SUBSCRIBER_FROM_FRESH_SNAPSHOT",
    "PROACTIVE_WAL_DISK_USAGE_ALERTING"
  ],
  "diagnosis": "max_slot_wal_keep_size(5000MB) 초과로 지연된 복제 슬롯이 안전하게 비활성화(lost)되어 주 데이터베이스 디스크 풀 크래시를 방어함."
}
```
