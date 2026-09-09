# #168 1억 명 결제 DB를 무중단 마이그레이션하다 돈이 사라졌다구요?!: 듀얼 라이팅(Dual-Writing) 정합성 드리프트, 백필 레이스 컨디션과 CDC 단조 버전 펜싱(Zero-Downtime Live DB Migration: Dual-Writing Drift & Lost Updates vs CDC Monotonic Version Fencing)

## 1. 실무 장애 시나리오: "DB 점검 없이 무중단으로 옮긴다더니... 계좌 잔액이 5천만 원이나 줄어들었어요?!"

글로벌 핀테크 유니콘 '젤리페이'의 데이터 플랫폼팀은 초당 수만 건의 결제 트랜잭션이 발생하는 핵심 원장 데이터베이스(`account_balances`)를 기존 단일 MySQL(`DB_Old`)에서 글로벌 분산 SQL(`DB_New`)로 이관하는 **'무중단 실시간 라이브 마이그레이션(Zero-Downtime Live Migration)'** 프로젝트에 돌입했습니다.

금융 규제와 사용자 SLA상 단 1초의 점검 중단(Maintenance Downtime)도 허용되지 않았기에, 팀은 업계에서 널리 알려진 **4단계 듀얼 라이팅 마이그레이션 전략**을 채택했습니다:

```
[ Phase 1: Dual Writing ]      [ Phase 2: Historical Backfill ]
    Client API Requests           Background Worker Batch
         |                               |
    +----+----+                          | (Snapshot Read)
    |         |                          v
    v         v                     [ DB_Old ]
[ DB_Old ]  [ DB_New ] (Naive Write)     |
                                         | (Chunk Insert)
                                         v
                                    [ DB_New ] (CRITICAL RACE CONDITION!)
```

그러나 마이그레이션 시작 30분 만에 감사팀으로부터 긴급 비상벨이 울렸습니다. **신규 데이터베이스의 사용자 잔액이 기존 데이터베이스보다 수천만 원 적게 기록되는 치명적인 데이터 유실(Lost Update) 및 정합성 드리프트(Data Drift)**가 발생한 것입니다!

```
[ 재앙의 시나리오: 백필 덮어쓰기 레이스 컨디션 (The Backfill Overwrite Disaster) ]

Time(t)    Client Live Transaction              Backfill Batch Worker
--------------------------------------------------------------------------------------
 t = 5                                          Worker reads Snapshot of acc-1
                                                (Snapshot Balance: 100, Version: 1)
 t = 8     Live Write: acc-1 +50
           -> DB_Old Balance: 150, Version: 2
           -> Dual-write to DB_New (Fast Network: 2ms)
           -> DB_New Balance: 150, Version: 2
 t = 15                                         Slow Bulk Insert arrives at DB_New!
                                                (Carrying Snapshot: 100, Version: 1)
                                                WITHOUT VERSION FENCING:
                                                -> DB_New[acc-1] is OVERWRITTEN with 100!
--------------------------------------------------------------------------------------
결과: 방금 입금된 50달러가 감쪽같이 증발! (150 -> 100 롤백 참사)
      DB_Old = 150 (v2)  vs  DB_New = 100 (v1) -> 사일런트 데이터 오염!
```

사고 원인 분석 결과, 세 가지 치명적인 분산 시스템 결함이 드러났습니다:
1. **백필 덮어쓰기 레이스(Backfill Overwrite Race)**: 과거 시점의 스냅샷을 복사하는 대용량 백필 배치가 실시간으로 신규 DB에 먼저 반영된 최신 쓰기 데이터를 무차별 덮어써 버림.
2. **분산 파드 간 실시간 쓰기 도착 역전(Out-of-Order Dual-Write)**: 여러 API 서버 파드에서 발생한 연속 트랜잭션($v=2 	o v=3$)이 네트워크 지연 편차로 인해 신규 DB에 $v=3 	o v=2$ 순서로 도착하여, 구버전이 신규 버전을 덮어쓰는 갱신 손실 발생.
3. **네트워크 부분 실패(Partial Failure)**: `DB_Old` 쓰기는 성공했으나 `DB_New`로의 듀얼 라이트가 일시적 네트워크 장애로 누락되어 영구적인 데이터 불일치가 누적됨.

이를 해결하기 위해 Stripe, Uber, GitHub 등 글로벌 빅테크는 나이브한 듀얼 라이팅을 폐기하고, **단조 버전 펜싱(Monotonic Version Fencing)**, **트랜잭셔널 아웃박스(Transactional Outbox) + CDC(Change Data Capture)**, 그리고 **다크 리드 정합성 대사(Dark Read Reconciliation Validator)** 기반의 차세대 무중단 마이그레이션 아키텍처를 적용합니다.

당신은 이 세 가지 마이그레이션 모드를 모두 시뮬레이션하고, 갱신 손실을 원천 차단하며 100% 무결성을 검증하는 무중단 마이그레이션 오케스트레이션 엔진을 구축해야 합니다.

---

## 2. 시뮬레이션 모델 및 아키텍처 규격

### (1) 3대 마이그레이션 모드 (`mode`)
1. **`NAIVE_DUAL_WRITE` (나이브 듀얼 라이팅 - 안티패턴)**:
   - 애플리케이션이 `DB_Old`와 `DB_New`에 동시에 독립적으로 쓰기를 시도합니다.
   - 신규 DB에 버전 검증(`WHERE version < incoming_version`)이 없어, 과거 백필 청크나 지연된 실시간 쓰기가 신규 DB의 최신 데이터를 무차별 덮어씁니다 (`lost_updates_detected` 증가).
   - 네트워크 부분 실패 발생 시 신규 DB에 영구적인 데이터 누락이 발생합니다.
2. **`VERSION_FENCED_DUAL_WRITE` (단조 버전 펜싱 듀얼 라이팅)**:
   - 애플리케이션이 듀얼 라이팅을 수행하되, 신규 DB에 반영할 때 **단조 버전 조건부 업서트(Conditional Upsert)**를 적용합니다:
     $$\text{Condition: } \text{incoming\_version} > \text{existing\_version}$$
   - 만약 신규 DB에 이미 동일하거나 더 높은 버전이 존재한다면, 지연된 쓰기는 즉시 기각(Fenced)됩니다 (`stale_writes_fenced` 증가, 갱신 손실 0건 방어).
   - 단, 네트워크 부분 실패로 인한 누락은 듀얼 라이팅 자체의 한계로 인해 남아 있을 수 있습니다.
3. **`VERSION_FENCED_CDC` (트랜잭셔널 아웃박스 & CDC 스트리밍 - 골드 스탠다드)**:
   - 애플리케이션은 오직 `DB_Old`에만 원자적으로 트랜잭션을 커밋하고, WAL(Write-Ahead Log)/Outbox 테이블에 이벤트를 남깁니다 (듀얼 라이팅 부분 실패 원천 제거).
   - Debezium/Kafka CDC 스트림이 WAL 이벤트를 순차적으로 `DB_New`에 버전 펜싱과 함께 동기화합니다.
   - 다크 리드 정합성 대사(Reconciliation) 시 불일치가 발견되면 `DB_Old`의 최신 원본을 기반으로 자동 치유(Auto-heal)합니다.

---

### (2) 입력 파라미터 규격
JSON 형태로 표준 입력(`sys.stdin`)을 통해 주어집니다.
- `mode` (string): `"NAIVE_DUAL_WRITE"`, `"VERSION_FENCED_DUAL_WRITE"`, `"VERSION_FENCED_CDC"` 중 하나.
- `backfill_chunk_size` (int): 백필 작업자가 한 번에 읽고 쓰는 청크 단위 레코드 수 (기본값 2).
- `live_write_latency_ticks` (int): 실시간 쓰기가 `DB_New`에 전달되는 기본 네트워크 지연 (기본값 2 ticks).
- `backfill_latency_ticks` (int): 대용량 백필 청크가 `DB_New`에 반영되는 배치 네트워크 지연 (기본값 10 ticks).
- `timeline_events` (list): 시뮬레이션 타임라인 이벤트 목록.

### (3) 타임라인 이벤트 종류
1. `{"tick": t, "type": "SEED_OLD_DB", "records": [{"id": "acc-1", "balance": 100, "version": 1}, ...]}`:
   - 기존 데이터베이스(`DB_Old`)에 초기 원장 레코드들을 적재합니다.
2. `{"tick": t, "type": "START_BACKFILL"}`:
   - 백그라운드 백필 프로세스를 시작합니다. `db_old`의 키 순서대로 `backfill_chunk_size`만큼 스냅샷을 읽어 `backfill_latency_ticks` 후 `DB_New`에 청크 단위로 기록합니다. 이전 청크 기록이 완료되면 다음 청크가 자동으로 트리거됩니다.
3. `{"tick": t, "type": "LIVE_WRITE", "id": "acc-1", "delta": 50, "custom_delay": d}`:
   - 실시간 트랜잭션이 발생하여 `db_old[id]`의 잔액을 `delta`만큼 변경하고 버전을 1 증가시킵니다 (`balance += delta`, `version += 1`).
   - `custom_delay`가 지정되어 있다면 지정된 지연 틱 후에 `DB_New`에 도착합니다 (도착 역전 시뮬레이션).
   - CDC 모드에서는 `DB_New`로 직접 전송하지 않고 `wal_queue`에 이벤트를 적재합니다.
4. `{"tick": t, "type": "NETWORK_PARTIAL_FAILURE", "target": "DB_NEW", "id": "acc-2"}`:
   - 네트워크 장애 모의: 다음번에 `DB_New`로 전송되는 해당 ID의 실시간 쓰기 1건을 네트워크에서 누락(Drop)시킵니다 (`partial_failures_occurred += 1`).
5. `{"tick": t, "type": "CDC_FLUSH"}`:
   - `VERSION_FENCED_CDC` 모드 전용: 현재까지 `wal_queue`에 쌓여 있는 모든 CDC 이벤트를 순서대로 `DB_New`에 버전 펜싱을 적용하여 반영하고 큐를 비웁니다.
6. `{"tick": t, "type": "RUN_RECONCILIATION"}`:
   - 다크 리드(Dark Read) 정합성 대사기: `DB_Old`와 `DB_New`의 모든 레코드를 전수 비교하여 불일치(잔액 불일치, 버전 불일치, 누락 레코드) 개수를 측정합니다.
   - `VERSION_FENCED_CDC` 또는 `VERSION_FENCED_DUAL_WRITE` 모드에서는 불일치 레코드가 발견되면 `DB_Old`의 최신 레코드를 기반으로 `DB_New`에 버전 펜싱 업서트를 수행하여 자동 치유(Auto-heal)합니다 (`reconciled_heals_count += 1`).
7. `{"tick": t, "type": "ATTEMPT_CUTOVER"}`:
   - 트래픽 컷오버(Traffic Cutover) 시도: 신규 DB로의 읽기/쓰기 완전 전환 가능 여부를 엄격하게 판정합니다.

---

### (4) 컷오버 성공 요건 (Cutover Gates)
`ATTEMPT_CUTOVER` 시점에 다음 **5대 요건이 모두 충족**되어야 컷오버가 승인됩니다:
1. **백필 완료**: 모든 기존 레코드에 대한 백필 배치가 100% 완료되었는가?
2. **CDC 큐 소진**: `wal_queue`에 미반영된 백로그 이벤트가 0건인가?
3. **갱신 손실 0건**: 시뮬레이션 동안 발생한 `lost_updates_detected == 0`인가?
4. **데이터 드리프트 0건**: 현재 `DB_Old`와 `DB_New` 간 불일치 레코드(`drift_records_count`)가 0개인가?
5. **완전성**: `db_old`의 모든 키가 `db_new`에 존재하는가?

하나라도 미충족 시 컷오버는 즉각 거절되며 시스템을 보호합니다.

---

## 3. 출력 메트릭 및 판정 기준

시뮬레이션 완료 시 다음과 같은 JSON 구조를 반환해야 합니다:

```json
{
  "metrics": {
    "total_live_writes": 1,
    "backfill_rows_read": 2,
    "backfill_rows_written": 2,
    "cdc_events_emitted": 1,
    "cdc_events_applied": 1,
    "stale_writes_fenced": 1,
    "lost_updates_detected": 0,
    "partial_failures_occurred": 0,
    "drift_records_count": 0,
    "reconciled_heals_count": 0,
    "cutover_success": true,
    "cutover_tick": 30,
    "verdict": "ZERO_DOWNTIME_CUTOVER_SUCCESS"
  },
  "sample_timeline": [ ... ]
}
```

### 최종 판정 (`verdict`) 기준
1. `metrics["lost_updates_detected"] > 0`인 경우:  
   $\rightarrow$ `"MIGRATION_FAILED_LOST_UPDATES"` (신규 DB에 구버전 데이터가 덮어써져 잔액/데이터 증발 참사 발생)
2. `metrics["drift_records_count"] > 0`인 경우:  
   $\rightarrow$ `"MIGRATION_FAILED_DATA_DRIFT"` (양쪽 DB 간 레코드 잔액 또는 버전 불일치 존재)
3. 백필이 미완료되었거나 CDC 백로그가 남아 있어 컷오버가 거절된 경우:  
   $\rightarrow$ `"MIGRATION_FAILED_BACKLOG_REMAINING"` (미처리 백로그로 인한 안전 거절)
4. 모든 컷오버 게이트를 통과하고 성공적으로 컷오버된 경우:  
   $\rightarrow$ `"ZERO_DOWNTIME_CUTOVER_SUCCESS"` (단 1초의 중단 및 데이터 유실 없는 완벽한 무중단 마이그레이션 성공)

---

## 4. 입출력 예시

### 입력 (예시)
```json
{
  "mode": "VERSION_FENCED_CDC",
  "backfill_chunk_size": 2,
  "live_write_latency_ticks": 2,
  "backfill_latency_ticks": 10,
  "timeline_events": [
    {"tick": 0, "type": "SEED_OLD_DB", "records": [
      {"id": "acc-1", "balance": 100, "version": 1},
      {"id": "acc-2", "balance": 200, "version": 1}
    ]},
    {"tick": 5, "type": "START_BACKFILL"},
    {"tick": 8, "type": "LIVE_WRITE", "id": "acc-1", "delta": 50},
    {"tick": 12, "type": "CDC_FLUSH"},
    {"tick": 25, "type": "RUN_RECONCILIATION"},
    {"tick": 30, "type": "ATTEMPT_CUTOVER"}
  ]
}
```

### 출력 (예시)
```json
{
  "metrics": {
    "total_live_writes": 1,
    "backfill_rows_read": 2,
    "backfill_rows_written": 1,
    "cdc_events_emitted": 1,
    "cdc_events_applied": 1,
    "stale_writes_fenced": 1,
    "lost_updates_detected": 0,
    "partial_failures_occurred": 0,
    "drift_records_count": 0,
    "reconciled_heals_count": 0,
    "cutover_success": true,
    "cutover_tick": 30,
    "verdict": "ZERO_DOWNTIME_CUTOVER_SUCCESS"
  },
  "sample_timeline": [
    {
      "tick": 0,
      "event": "SEED_OLD_DB",
      "count": 2
    },
    {
      "tick": 5,
      "event": "START_BACKFILL",
      "total_records": 2
    },
    {
      "tick": 5,
      "event": "BACKFILL_CHUNK_READ",
      "keys": ["acc-1", "acc-2"],
      "records": [
        {"id": "acc-1", "balance": 100, "version": 1, "updated_at": 0},
        {"id": "acc-2", "balance": 200, "version": 1, "updated_at": 0}
      ]
    },
    {
      "tick": 8,
      "event": "LIVE_WRITE_OLD_DB",
      "id": "acc-1",
      "new_balance": 150,
      "version": 2
    },
    {
      "tick": 8,
      "event": "CDC_WAL_EMITTED",
      "id": "acc-1",
      "version": 2
    },
    {
      "tick": 12,
      "event": "CDC_EVENT_APPLIED",
      "id": "acc-1",
      "balance": 150,
      "version": 2
    },
    {
      "tick": 15,
      "event": "STALE_BACKFILL_WRITE_FENCED",
      "id": "acc-1",
      "existing_version": 2,
      "fenced_version": 1
    },
    {
      "tick": 15,
      "event": "BACKFILL_COMPLETED",
      "total_rows": 2
    },
    {
      "tick": 25,
      "event": "RECONCILIATION_CHECK",
      "drift_count": 0,
      "drift_keys": []
    },
    {
      "tick": 30,
      "event": "CUTOVER_SUCCESSFUL",
      "total_records": 2
    }
  ]
}
```
