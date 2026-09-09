# 문제 248: Distributed SQL Database — TiKV/CockroachDB 분산 MVCC 가비지 컬렉션(GC) SafePoint 지연, Range Tombstone 스캔 증폭 및 Compaction Filter 최적화

## 1. 개요 (Incident Scenario)

대규모 글로벌 금융 핀테크 서비스에서 고가용성과 분산 트랜잭션 보장을 위해 분산 분할 SQL 데이터베이스(TiDB/TiKV, CockroachDB, YugabyteDB)를 프로덕션 환경에 배포했습니다. 해당 데이터베이스는 스냅샷 격리성(Snapshot Isolation)과 과거 시점 조회(Stale Read / AS OF SYSTEM TIME)를 지원하기 위해 모든 행(Row)에 대해 **다중 버전 동시성 제어(MVCC)**를 적용하며, RocksDB/Pebble 기반의 LSM-Tree 엔진 위에 `(Key_CommitTS -> Value)` 형태로 버전들을 누적 저장합니다.

그러나 정기 대규모 정산 배치 작업과 데이터 동기화 파이프라인(CDC / Change Data Capture)이 맞물린 날, 심각한 장애가 발생했습니다:
1. **정기 쿼리 타임아웃 대란 (Range Tombstone Scan Amplification)**: 단 10개의 유효 레코드를 조회하는 단순 범위 스캔(`RANGE_SCAN`) 쿼리가 수십 초 동안 멈추다가 `Region Busy / Query Timeout` 에러를 뱉었습니다. 확인 결과, 직전에 대량 삭제(Soft-Delete)된 수만 개의 **MVCC Delete Tombstone(삭제 묘비)**를 스토리지 엔진 반복자(Iterator)가 일일이 디코딩하고 건너뛰면서 스캔 증폭(Scan Amplification)이 수백 배로 치솟았습니다.
2. **GC SafePoint 정지 (SafePoint Stalled by Long-running Transaction / CDC)**: 데이터베이스 내부의 분산 GC 워커가 오래된 MVCC 버전을 정리하려 했으나, 3시간 전에 시작된 장기 실행 OLAP 분석 쿼리와 지연된 CDC 컨슈머가 `safe_point_ts`의 전진을 가로막았습니다. 그 결과 수천만 개의 무효 버전과 삭제 묘비가 디스크에 방치되었습니다.
3. **LSM-Tree 쓰기 멈춤 (Write Stall Storm)**: 장기 분석 쿼리가 종료되자 밀려있던 `safe_point_ts`가 수천 초 단위로 급진전했습니다. 레거시 GC 워커가 한꺼번에 수만 개의 명시적 RangeDelete 묘비를 LSM-Tree Level 0에 쏟아부었고, 이로 인해 L0 파일 개수 폭증 및 컴팩션 부채(Compaction Debt)가 폭발하며 클러스터 전체가 **RocksDB Write Stall** 상태에 빠져 모든 쓰기가 마비되었습니다.

당신은 분산 데이터베이스 코어 엔지니어로서, 클러스터 설정, 초기 MVCC 버전들, 활성 트랜잭션, CDC 체인지피드, 그리고 이벤트 스트림을 바탕으로 분산 MVCC SafePoint 계산, GC 실행(Compaction Filter vs Legacy RangeDel), Range Scan 스캔 증폭 메커니즘을 정확하게 시뮬레이션하고, 장애 근본 원인(Root Cause)과 엔터프라이즈 최적화 방안을 도출해야 합니다.

---

## 2. 아키텍처 및 상태 머신 (System Architecture & State Machine)

```
 [ Distributed SQL Coordinator (PD / GC Leader) ]
            │
            │ Periodically Calculate:
            │ safe_point_ts = min(now - gc_life_time, min(active_txns), min(cdc_checkpoints))
            ▼
    ┌────────────────────────────────────────────────────────┐
    │  Broadcast safe_point_ts to all Storage Nodes (TiKV)   │
    └──────────────────────────┬─────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
    [ Legacy RangeDel Mode ]         [ CompactionFilter Mode ]
    - Explicit Delete writes to L0   - On-the-fly purge during compaction
    - Purge >= 10,000 versions       - Zero extra L0 write overhead
      ==> LSM Write Stall!           - Stable latency & throughput!

 ═══════════════════════════════════════════════════════════════════════
 [ LSM-Tree Key Versions for "order_0001" ]
 
  Key_TS=1500 (DELETE)  ◄── Visible Tombstone at read_ts=1600
  Key_TS=1200 (val_v2)  ◄── Obsolete Version (if commit_ts <= safe_point_ts)
  Key_TS=1000 (val_v1)  ◄── Obsolete Version
```

### (1) SafePoint 계산 규칙
- 이상적인 후보 SafePoint: `candidate = current_ts - gc_life_time_sec`.
- 활성 트랜잭션(`active_txns`):
  - 각 트랜잭션의 실행 시간 `current_ts - start_ts > max_txn_time_sec`인 경우, `kill_lagging_txns == true`이면 강제 종료(Abort)되어 차단 목록에서 제외됩니다.
  - 생존 트랜잭션 중 가장 작은 `start_ts`가 존재하고 이것이 `candidate`보다 작으면 `effective_limit = min_txn_ts`가 됩니다.
- CDC 체인지피드(`cdc_feeds`):
  - 가장 지연된 체크포인트 `min_cdc_ts`가 존재하고 이것이 `candidate`보다 작으면 `effective_limit = min(effective_limit, min_cdc_ts)`.
- 신규 SafePoint: `new_safe_point = max(safe_point_ts, effective_limit)`.
- **지연 감지**: 만약 `candidate > new_safe_point`라면:
  - 트랜잭션에 의해 차단된 경우: `stalled_by_txn = true`
  - CDC 체인지피드에 의해 차단된 경우: `stalled_by_cdc = true`

### (2) MVCC 버전 보존 및 가비지 컬렉션 규칙
- 키마다 최신순(내림차순)으로 버전들이 정렬되어 있습니다.
- `commit_ts > safe_point_ts`인 버전들은 스냅샷 격리성을 위해 무조건 보존됩니다.
- `commit_ts <= safe_point_ts`인 버전 중:
  - **가장 최신 버전 1개**만 보존됩니다 (단, 이 최신 버전이 `is_delete == true`인 삭제 묘비라면 완전히 영구 삭제됩니다).
  - 그보다 더 오래된 구버전들은 모두 쓸모없는 버전(Obsolete Versions)으로 간주되어 즉시 정리(Purge)됩니다.
- **LSM Write Stall 발생 조건**:
  - `gc_mode == "LEGACY_RANGEDEL"` 모드에서 단일 GC 주기 동안 정리된 버전 수가 $\ge 10,000$건 이상이면 대량의 삭제 레코드 발생으로 인해 `lsm_write_stalls += 1`이 기록됩니다.
  - `gc_mode == "COMPACTION_FILTER"` 모드에서는 컴팩션 과정에서 인라인으로 제거되므로 쓰기 스톨이 발생하지 않습니다.

### (3) Range Scan 반복자 및 스캔 증폭 계산
- `RANGE_SCAN(start_key, end_key, read_ts, limit)`:
  - 사전순으로 $[start\_key, end\_key]$ 범위의 키들을 순회합니다.
  - 각 키의 버전 체인을 탐색하며 `commit_ts <= read_ts`인 최초의 가시적(Visible) 버전을 찾습니다.
  - 그 버전이 유효한 행(`is_delete == false`)이면 `valid_results += 1`.
  - 만약 최신 버전이 삭제 묘비(`is_delete == true`)이거나 미래 버전들이어서 건너뛴 경우 `tombstones_scanned`가 누적됩니다.
- 스캔 증폭비(Scan Amplification):
  $$	ext{amp} = rac{	ext{keys\_evaluated}}{\max(1, 	ext{valid\_results})}$$
- `enable_seek_bounds == true`인 경우 프리픽스 블룸 필터 및 바운드 탐색 덕분에 $	ext{amp} \le 20.0$으로 억제됩니다.
- 만약 $	ext{amp} > 	ext{max\_scan\_amplification}$이거나 `tombstones_scanned > 5000`인 경우 쿼리 타임아웃(`query_timeouts += 1`)이 발생합니다.

---

## 3. 입력 사양 (Input Specification)

표준 입력(`sys.stdin`)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "cluster_config": {
    "gc_life_time_sec": 600,
    "max_txn_time_sec": 300,
    "kill_lagging_txns": false,
    "gc_mode": "LEGACY_RANGEDEL",
    "max_scan_amplification": 100,
    "enable_seek_bounds": false
  },
  "initial_ts": 2000,
  "initial_safe_point_ts": 500,
  "initial_active_txns": [
    {"txn_id": "txn_analytics_1", "name": "olap_report", "start_ts": 600}
  ],
  "initial_cdc_feeds": [],
  "initial_kv_versions": [
    {"key": "order_0001", "commit_ts": 1500, "is_delete": true, "val": ""}
  ],
  "events": [
    {"type": "ADVANCE_TIME", "new_ts": 2500},
    {"type": "TRIGGER_GC"},
    {
      "type": "RANGE_SCAN",
      "query_id": "scan_orders_pending",
      "start_key": "order_0000",
      "end_key": "order_0149",
      "read_ts": 2500,
      "limit": 10
    }
  ]
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(`sys.stdout`)으로 다음 필드를 포함하는 JSON 객체를 출력합니다:

```json
{
  "final_state": {
    "current_ts": 2500,
    "safe_point_ts": 600,
    "active_txns_count": 1,
    "total_kv_keys": 151,
    "total_versions": 151
  },
  "metrics": {
    "total_tombstones_scanned": 150,
    "query_timeouts": 1,
    "timed_out_queries": ["scan_orders_pending"],
    "lsm_write_stalls": 0,
    "obsolete_versions_purged": 0
  },
  "root_cause": "RANGE_SCAN_TIMEOUT_DUE_TO_TOMBSTONE_AMPLIFICATION",
  "recommendations": [
    "ENABLE_ROCKSDB_COMPACTION_FILTER_GC",
    "ENFORCE_MAX_TXN_EXECUTION_TIME_LIMIT",
    "ENABLE_PREFIX_BLOOM_FILTER_AND_SEEK_BOUNDS"
  ]
}
```

### 진단 규칙 (Root Cause Hierarchy)
1. `query_timeouts > 0` $ightarrow$ `"RANGE_SCAN_TIMEOUT_DUE_TO_TOMBSTONE_AMPLIFICATION"`
2. `lsm_write_stalls > 0` $ightarrow$ `"LSM_WRITE_STALL_DUE_TO_MASSIVE_TOMBSTONE_PURGE"`
3. `stalled_by_txn == true` $ightarrow$ `"GC_SAFEPOINT_STALLED_BY_LONG_RUNNING_TXN"`
4. `stalled_by_cdc == true` $ightarrow$ `"GC_SAFEPOINT_STALLED_BY_LAGGING_CDC"`
5. 기타 정상 상태 $ightarrow$ `"HEALTHY_MVCC_GC_AND_SCAN_OPERATION"`

### 권고사항 도출 규칙
- `gc_mode == "LEGACY_RANGEDEL"`: `"ENABLE_ROCKSDB_COMPACTION_FILTER_GC"`
- `not kill_lagging_txns`: `"ENFORCE_MAX_TXN_EXECUTION_TIME_LIMIT"`
- `not enable_seek_bounds`: `"ENABLE_PREFIX_BLOOM_FILTER_AND_SEEK_BOUNDS"`
- `stalled_by_cdc == true`: `"SET_CDC_MAX_STALENESS_AND_AUTO_PAUSE"`
- 해당 사항이 없으면: `["MONITOR_MVCC_VERSION_COUNT_AND_SST_HEALTH"]`
