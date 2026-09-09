# 문제 248 이론: Distributed SQL MVCC SafePoint 지연, Range Tombstone 스캔 증폭 및 LSM Compaction Filter 아키텍처

---

## 1. 분산 SQL 데이터베이스의 MVCC와 키 인코딩

분산 분할 데이터베이스(TiDB/TiKV, CockroachDB, YugabyteDB)는 다중 버전 동시성 제어(MVCC)를 통해 일관된 읽기와 쓰기 동시성을 달성합니다.

```
+--------------------------------------------------------------------+
| Logical Table Row: (id=42, name="Alice", balance=100)              |
+--------------------------------------------------------------------+
                                │ Encode
                                ▼
+--------------------------------------------------------------------+
| LSM-Tree Physical Storage Key-Value                                |
|                                                                    |
| Key Format:   TableID_RowID_CommitTS                               |
|               t_100_r_0042_1700000002 -> (name="Alice", bal=120)   |
|               t_100_r_0042_1700000001 -> (name="Alice", bal=100)   |
|               t_100_r_0042_1699999990 -> [DELETE TOMBSTONE]        |
+--------------------------------------------------------------------+
```

클라이언트가 특정 시점 $T_{	ext{read}}$로 트랜잭션을 시작하면, 스토리지 엔진은 $CommitTS \le T_{	ext{read}}$인 버전 중 가장 최신의 값을 반환합니다. 이를 통해 읽기 트랜잭션은 어떠한 락(Lock)도 획득하지 않고 안전하게 데이터를 읽을 수 있습니다(Snapshot Isolation).

---

## 2. 분산 GC 워커와 SafePoint 동기화 알고리즘

데이터가 업데이트되거나 삭제될수록 과거 버전들이 LSM-Tree에 계속 쌓이게 됩니다. 저장 공간 낭비와 읽기 성능 저하를 방지하기 위해 분산 코디네이터(TiDB PD 또는 CockroachDB Intent Resolver)는 주기적으로 **SafePoint**를 산출하여 모든 스토리지 노드(Region Peer)에 전파합니다.

$$	ext{SafePoint} = \min\left( 	ext{Now} - 	ext{GC\_Life\_Time},\, \min_{t \in 	ext{ActiveTxns}} (	ext{StartTS}_t),\, \min_{c \in 	ext{CDC Feeds}} (	ext{CheckpointTS}_c) ight)$$

```
  [ Time Axis ]
  ────────────────────────────────────────────────────────────►
  0           SafePoint (Blocked!)            Candidate (Now - TTL)
  │               │                                   │
  ▼               ▼                                   ▼
 [Purged Area]   [Protected MVCC Area: Still Active]
                  ▲
                  │ Zombie OLAP Query (StartTS=1000)
```

### (1) 장기 실행 트랜잭션의 함정 (Zombie Reader Problem)
사용자가 수 시간 동안 실행되는 대형 통계 쿼리(`SELECT ... GROUP BY`)를 실행하거나 트랜잭션을 시작한 뒤 커밋하지 않은 채 커넥션을 방치하면, 그 트랜잭션의 `start_ts`가 전역 SafePoint의 전진을 영구적으로 가로막습니다.
- SafePoint가 전진하지 못하면 데이터베이스 내의 모든 테이블에 대한 가비지 컬렉션이 전면 중단됩니다.
- 데이터베이스 용량이 급증하고 디스크가 차오릅니다.

### (2) 지연된 CDC 체인지피드 (Lagging Changefeed)
Kafka나 외부 데이터 웨어하우스로 실시간 변경분을 복제하는 CDC 프로세스가 네트워크 장애나 컨슈머 과부하로 멈추면, 다운스트림 복제 보장을 위해 SafePoint가 CDC 체크포인트에 묶여 고정됩니다.

---

## 3. Range Tombstone과 스캔 증폭 (Scan Amplification)

대량의 데이터를 삭제(Batch DELETE / TTL 만료)한 직후, 삭제된 레코드들은 물리적으로 디스크에서 사라지는 것이 아니라 **MVCC Delete Tombstone**이라는 삭제 플래그 레코드로 기록됩니다.

```
 [ Query: SELECT * FROM orders WHERE id BETWEEN 1 AND 1000 LIMIT 10 ]
 
 Iterator.Seek("orders_0001")
 ├─ orders_0001: Tombstone (Deleted) -> skip
 ├─ orders_0002: Tombstone (Deleted) -> skip
 ├─ ... (998 more tombstones skipped)
 └─ orders_1000: Living Row -> returned!
 
 Evaluated Keys: 1000, Valid Returned: 1 ==> Scan Amplification = 1000x!
```

### 성능 붕괴 원인:
1. RocksDB의 블록 기반 테이블 반복자는 Tombstone 역시 유효한 키-값 엔트리로 취급하여 블록 캐시에서 압축을 풀고 파싱해야 합니다.
2. 수만 개의 연속된 Tombstone을 읽는 동안 CPU 사용률이 100%로 치솟고 디스크 I/O가 폭증하여 쿼리 타임아웃(`Region is busy / Context deadline exceeded`)이 발생합니다.

---

## 4. GC 모드 비교: Legacy RangeDel vs CompactionFilter

### (1) Legacy RangeDel (Key-by-Key / RangeDelete Marker)
- 과거 TiKV 및 분산 DB는 GC 워커가 스토리지 키를 스캔하여 오래된 버전에 대해 명시적인 `DeleteRange` 또는 단일 `Delete` 레코드를 생성하여 LSM-Tree L0에 다시 썼습니다.
- **치명적 결함**: GC 자체가 또 다른 쓰기 워크로드가 되어 Level 0에 수만 개의 SST 파일을 쏟아붓습니다. 이는 극심한 **컴팩션 부채(Compaction Debt)**를 유발하여 정상적인 애플리케이션의 INSERT/UPDATE가 일시 중지되는 **LSM Write Stall** 사태를 부릅니다.

### (2) CompactionFilter (In-Compaction Version Pruning)
- RocksDB/Pebble의 `CompactionFilter` 인터페이스를 활용하여, 백그라운드 컴팩션이 SSTable 파일들을 병합(SST Merge)하는 순간에 인라인으로 MVCC 헤더와 SafePoint를 비교합니다.
- `commit_ts <= safe_point_ts`인 쓸모없는 과거 버전과 최종 삭제 묘비를 그 자리에서 디스크 버퍼에 쓰지 않고 조용히 폐기(Drop)합니다.
- **장점**:
  - 별도의 L0 쓰기 I/O가 0건입니다.
  - 쓰기 증폭(Write Amplification)과 LSM Write Stall이 원천 방지됩니다.

---

## 5. 실무 최적화 권고사항 및 프로덕션 런북

1. **RocksDB Compaction Filter 활성화**:
   - `gc.enable-compaction-filter = true` 설정으로 대규모 GC 시 쓰기 정체 완전 방지.
2. **트랜잭션 실행 시간 상한 강제 (`max-txn-time`)**:
   - `max-execution-time` 또는 `idle_in_transaction_session_timeout`을 설정하여 방치된 좀비 세션을 자동 강제 종료.
3. **CDC 체크포인트 최대 지연 시간 설정 (`gc-ttl`)**:
   - CDC 지연이 임계치(예: 24시간)를 초과하면 해당 체인지피드를 자동 일시정지(`error / pause`)하고 SafePoint를 전진시켜 주 데이터베이스를 보호.
4. **블룸 필터 및 바운드 탐색 (`enable_seek_bounds`)**:
   - Prefix Bloom Filter를 적용하여 묘비만 있는 데이터 블록의 디스크 읽기를 사전에 우회.
