# PostgreSQL MVCC: Heap-Only Tuples (HOT)와 인덱스 쓰기 증폭 심층 분석

## 1. 개요: PostgreSQL Append-only MVCC와 MySQL InnoDB의 근본적 차이

관계형 데이터베이스에서 동시성을 제어하는 MVCC(Multi-Version Concurrency Control) 아키텍처는 스토리지 엔진 설계에 따라 완전히 다른 두 가지 방식으로 나뉩니다.

### 1.1 MySQL InnoDB (인플레이스 갱신 + 언두 로그)
- **클러스터형 인덱스(Clustered Index)** 구조: 테이블 자체가 Primary Key 기준의 B+Tree로 정렬되어 저장됩니다.
- **인플레이스 갱신(In-place Update)**: `UPDATE` 시 기존 레코드 위치를 직접 덮어쓰며, 과거 버전 데이터는 별도의 **언두 로그(Undo Log)** 세그먼트에 기록합니다.
- **보조 인덱스(Secondary Index)의 간접 포인팅**: 보조 인덱스는 데이터의 물리적 위치가 아닌 **Primary Key 값**만을 가리킵니다. 따라서 비PK 컬럼을 업데이트해도 보조 인덱스는 단 1개도 수정할 필요가 없습니다.

### 1.2 PostgreSQL (추가 전용 힙 + TID 직접 매핑)
- **힙 파일(Heap File)** 구조: 행(Row)들은 정렬되지 않은 채 8KB 힙 페이지에 순차적으로 삽입됩니다.
- **추가 전용 갱신(Append-only Update)**: 언두 로그가 존재하지 않으며, `UPDATE`가 발생하면 기존 튜플은 삭제 마킹(Dead Tuple)되고, **새로운 버전의 튜플(New Tuple)을 힙 페이지의 빈 공간에 새로 삽입**합니다.
- **보조 인덱스의 물리 주소 직접 매핑**: 모든 인덱스(B-Tree, GIN, GiST)는 튜플의 물리적 주소인 **TID (Tuple ID = Block Number + Offset)**를 직접 가리킵니다.

이로 인해 튜플이 갱신되어 물리적 위치(TID)가 바뀌면, 이론적으로 **테이블에 정의된 모든 보조 인덱스에 새 TID를 가리키는 인덱스 엔트리를 새로 삽입**해야 하는 치명적인 쓰기 증폭이 발생합니다.

---

## 2. 2016년 Uber PostgreSQL 이탈 사태와 인덱스 쓰기 증폭

2016년 Uber 엔지니어링 팀은 *"Why Uber Engineering Switched from Postgres to MySQL"*이라는 기술 블로그를 발표하며 전 세계 DB 커뮤니티에 큰 충격을 주었습니다.

핵심 원인은 바로 **인덱스 쓰기 증폭(Index Write Amplification)**이었습니다:
- Uber의 운행 기록(`trips`) 테이블에는 상태, 기사 위치, 승객 정보 등 수많은 조회를 위해 10개 이상의 보조 인덱스가 걸려 있었습니다.
- 승차 완료 시 `status`나 비고 컬럼 하나를 업데이트하면:
  - 힙 페이지에 튜플이 새로 쓰여 TID가 변경됨.
  - 10개의 모든 인덱스에 새로운 B-Tree 리프 엔트리가 삽입됨.
  - 10개의 인덱스 페이지가 더티(Dirty) 상태가 되어 디스크로 플러시되어야 함.
  - WAL(Write-Ahead Log) 기록량이 수십 배로 폭증하고 SSD I/O 대역폭이 완전히 포화됨.
  - 버퍼 풀(Buffer Pool)의 유효 캐시가 쫓겨나고 B-Tree 인덱스 비대화(Index Bloat)로 쿼리 성능이 추락함.

---

## 3. HOT (Heap-Only Tuples) 최적화의 구조와 작동 원리

이러한 Append-only MVCC의 태생적 한계를 극복하기 위해 PostgreSQL 8.3에 도입된 혁신적인 기술이 바로 **HOT (Heap-Only Tuples)**입니다.

### 3.1 HOT 성공을 위한 2대 필수 조건
1. **인덱스 컬럼 불변 (No Indexed Columns Modified)**:
   `UPDATE` 문이 변경하는 컬럼들 중에 보조 인덱스가 걸려 있는 컬럼이 단 하나도 없어야 합니다.
2. **동일 페이지 내 여유 공간 (Same-page Free Space)**:
   새로운 튜플 버전이 기존 튜플이 위치한 **정확히 동일한 8KB 힙 페이지** 내의 여유 공간에 적재될 수 있어야 합니다.

### 3.2 HOT 체인(HOT Chain)과 인덱스 쓰기 0건의 기적

```text
[B-Tree Index] ─────────┐
                        │ (Index Entry: TID = Page 1, LinePointer 1)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 8KB Heap Page 1                                             │
│                                                             │
│  [LinePointer 1] ───> [Tuple v1 (Root)]                     │
│                       - HEAP_HOT_UPDATED 플래그             │
│                       - t_ctid ───┐                         │
│                                   ▼                         │
│  [LinePointer 2] ───────────> [Tuple v2 (Heap-Only)]        │
│                               - HEAP_ONLY_TUPLE 플래그      │
│                               - t_ctid ───┐                 │
│                                           ▼                 │
│  [LinePointer 3] ───────────────────> [Tuple v3 (Latest)]   │
│                                       - HEAP_ONLY_TUPLE     │
│                                       - 최신 유효 데이터     │
└─────────────────────────────────────────────────────────────┘
```

HOT가 성공하면:
1. 기존 루트 튜플에 `HEAP_HOT_UPDATED` 플래그가 설정되고, `t_ctid` 포인터가 새 튜플을 가리킵니다.
2. 새 튜플은 `HEAP_ONLY_TUPLE`로 마킹됩니다.
3. **인덱스는 단 하나도 수정되지 않습니다!**
4. 인덱스 검색(Index Scan) 시 인덱스는 루트 튜플(LinePointer 1)을 가리키고, 스토리지 엔진은 동일 페이지 내에서 HOT 체인을 따라 최신 버전(v3)을 즉시 읽어냅니다. 동일 페이지 내의 포인터 순회이므로 추가 디스크 I/O가 전혀 발생하지 않습니다.

### 3.3 인페이지 프루닝 (In-page Pruning / Micro-Vacuum)
HOT의 또 다른 위대한 장점은 **가벼운 인라인 청소**입니다:
- 후속 `SELECT`나 `UPDATE`가 해당 8KB 페이지를 메모리로 읽을 때, 트랜잭션 스냅샷 상에서 더 이상 아무에게도 보이지 않는 과거 죽은 튜플(v1, v2)을 발견하면 즉시 페이지 내부 조각 모음(Pruning)을 수행합니다.
- LinePointer 1이 직접 LinePointer 3을 가리키도록 체인을 단축하고 죽은 바이트를 여유 공간으로 즉시 회수합니다.
- 대규모 `VACUUM` 프로세스를 기다리지 않고도 페이지 내에서 지속적으로 자가 치유가 이루어집니다.

---

## 4. `fillfactor`의 수학과 프로덕션 최적화

기본 설정에서 테이블의 `fillfactor`는 `100`입니다. 즉, 초기 `INSERT` 시 8KB 페이지가 빈틈없이 채워집니다.

### 4.1 `fillfactor = 100`일 때의 비극
페이지가 100% 가득 차 있으므로, `UPDATE`가 발생하면 새 튜플이 들어갈 자리가 0바이트입니다. 따라서 무조건 새 페이지로 이동하게 되어 **HOT 성공률이 0%로 추락**합니다.

### 4.2 최적의 `fillfactor` 튜닝
갱신이 빈번한 OLTP 테이블은 반드시 `fillfactor`를 낮춰야 합니다:

```sql
-- 8KB 페이지당 25% (약 2KB)의 여유 공간을 예약
ALTER TABLE trips SET (fillfactor = 75);
-- 기존 데이터 재정렬 적용
VACUUM FULL trips;
```

- `fillfactor = 75` 설정 시:
  - 8KB 페이지 중 약 6KB까지만 신규 행을 채우고, 나머지 2KB는 UPDATE 전용 예비 버퍼로 비워둡니다.
  - 행 크기가 256바이트라면, 한 페이지에서 최대 8번의 연속된 UPDATE가 인덱스 쓰기 0건으로 완벽하게 처리됩니다.
  - 인페이지 프루닝과 주기적 autovacuum이 결합되면, 페이지 크기가 영구히 8KB로 유지되면서 인덱스 비대화가 완전히 억제됩니다.

---

## 5. HOT 효율 모니터링 기법

프로덕션 데이터베이스에서 HOT 최적화가 정상 작동하고 있는지 감시하기 위한 표준 쿼리:

```sql
SELECT 
    relname AS table_name,
    n_tup_upd AS total_updates,
    n_tup_hot_upd AS hot_updates,
    ROUND(100.0 * n_tup_hot_upd / NULLIF(n_tup_upd, 0), 2) AS hot_ratio_pct
FROM pg_stat_user_tables
WHERE n_tup_upd > 0
ORDER BY n_tup_upd DESC;
```

- **`hot_ratio_pct`가 80% 이상**: HOT가 건강하게 작동 중이며 인덱스 쓰기 증폭이 효과적으로 방어되고 있음.
- **`hot_ratio_pct`가 20% 미만**: `fillfactor`가 너무 높거나, 잦은 `UPDATE` 컬럼에 불필요한 보조 인덱스가 걸려 있어 디스크 I/O가 낭비되고 있음을 의미합니다. 즉시 `fillfactor` 하향 조정 또는 인덱스 정리가 필요합니다.
