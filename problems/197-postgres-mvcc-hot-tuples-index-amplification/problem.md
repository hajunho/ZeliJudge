# Problem 197: PostgreSQL MVCC: HOT(Heap-Only Tuples) 최적화와 인덱스 쓰기 증폭(Write Amplification) 및 fillfactor 튜닝

## 문제 설명

글로벌 차량 호출 및 배달 플랫폼(Uber 스타일)의 핵심 트랜잭션 데이터베이스를 운영하는 DBA 및 플랫폼 엔지니어링 팀은 운행 기록(`trips`) 및 주문 테이블에서 심각한 디스크 I/O 병목과 SSD 수명 조기 고갈 사태를 겪었습니다.

테이블에는 빠른 검색을 위해 6개의 보조 인덱스(Secondary Indexes: `rider_id`, `driver_id`, `created_at`, `status`, `region_id` 등)가 생성되어 있었고, 초당 수만 건의 운행 상태 변경(`UPDATE trips SET note = ...`)이 쏟아지고 있었습니다.

심층 I/O 프로파일링 결과, 단 몇십 바이트의 텍스트 수정이었음에도 불구하고 다음과 같은 치명적인 **인덱스 쓰기 증폭(Index Write Amplification)**이 발생하고 있었습니다:

1. **PostgreSQL의 MVCC 튜플 추가 방식(Append-only MVCC)**:
   - PostgreSQL은 MySQL(InnoDB)과 달리 언두 로그(Undo Log)를 이용한 제자리 갱신(In-place Update)을 지원하지 않으며, 모든 `UPDATE`는 이전 버전 튜플을 삭제 마킹(Dead Tuple)하고 **새로운 버전의 튜플(New Tuple)을 힙 페이지에 새로 삽입**합니다.
   - 보조 인덱스는 테이블 튜플의 물리적 주소인 **TID (Tuple ID: 블록 번호 + 오프셋)**를 직접 가리킵니다.
2. **기본 `fillfactor = 100`의 참사: HOT (Heap-Only Tuples) 전멸**:
   - 기본 설정(`fillfactor = 100`)에서는 초기 `INSERT` 시 8KB 힙 페이지를 여유 공간 없이 100% 꽉 채웁니다.
   - 이후 `UPDATE`가 발생하면 동일한 8KB 페이지 내에 새 튜플을 담을 공간이 전혀 없으므로, 새 튜플은 **다른 힙 페이지로 쫓겨나 할당**됩니다.
   - 튜플의 물리적 블록 주소(TID)가 변경되었으므로, **테이블에 걸려 있는 6개의 모든 보조 인덱스에 새로운 인덱스 엔트리를 강제로 추가(Index Insert)**해야 합니다!
   - 단 1건의 UPDATE마다 1회의 테이블 쓰기 + 6회의 인덱스 쓰기 + WAL 로그 폭증이 발생하여, **쓰기 증폭률(Write Amplification)이 수십 배로 폭증**하고 B-Tree 인덱스가 비대화(Index Bloat)되어 버퍼 풀이 고갈되었습니다 (2016년 Uber가 Postgres에서 MySQL로 전환하게 만든 결정적 계기).
3. **HOT (Heap-Only Tuples) 최적화의 조건과 구원 원리**:
   - PostgreSQL 8.3부터 도입된 HOT 최적화는 두 가지 조건이 모두 만족될 때 동작합니다:
     1. **인덱스 컬럼 불변**: `UPDATE`가 인덱스로 지정된 컬럼을 단 하나도 변경하지 않아야 함 (`indexed_col_touched == False`).
     2. **동일 페이지 내 여유 공간 확보**: 새 튜플이 이전 튜플과 **동일한 8KB 힙 페이지** 내의 남은 여유 공간에 들어갈 수 있어야 함 (`old_page.free_bytes >= tuple_size`).
   - HOT가 성공하면:
     - 새 튜플은 동일 페이지 내에 저장되고 이전 튜플의 `t_ctid`가 새 튜플을 가리키는 **HOT 체인(HOT Chain)**을 형성합니다.
     - **모든 보조 인덱스 쓰기 횟수는 0건**입니다! 인덱스는 여전히 루트 튜플의 TID만 가리키며, 인덱스 검색 시 루트 튜플을 거쳐 동일 페이지 내의 HOT 체인을 따라 최신 버전을 즉시 읽어냅니다.
   - 테이블의 **`fillfactor`를 70~80%로 낮추면** 초기 삽입 시 페이지당 20~30%의 여유 공간이 예약되어, 후속 UPDATE들이 동일 페이지 내에서 안전하게 HOT로 처리되며 쓰기 I/O가 80% 이상 절감됩니다.

당신은 PostgreSQL 스토리지 엔진의 힙 페이지 할당자, HOT 체인 형성, 인덱스 쓰기 증폭 및 `VACUUM` 공간 회수를 모델링하는 정밀 시뮬레이터를 개발해야 합니다.

---

## 핵심 시스템 파라미터 및 동작 모드

### 1. 시뮬레이션 모드 (`mode`)
- `OPTIMAL_HOT_TUNED`:
  - `fillfactor = 70~80`으로 설정하여 페이지당 20~30%의 여유 공간을 예약합니다.
  - 비인덱스 페이로드 컬럼 업데이트 시 80% 이상의 높은 HOT 성공률을 달성하여 인덱스 쓰기를 최소화합니다 (`OPTIMAL_HOT_INDEX_WRITE_MINIMIZED`, `status: SUCCESS`).
- `NAIVE_MAX_FILLFACTOR`:
  - 기본값인 `fillfactor = 100`을 사용하여 페이지가 초기 삽입으로 빈틈없이 꽉 찹니다.
  - 여유 공간이 0이므로 모든 `UPDATE`가 동일 페이지에 들어가지 못하고 HOT가 전면 실패합니다. 매 UPDATE마다 모든 보조 인덱스에 연쇄 쓰기가 발생하여 시스템이 붕괴합니다 (`INDEX_WRITE_AMPLIFICATION_FILLFACTOR_100_COLLAPSE`, `status: FAILED`).
- `INDEXED_COLUMN_UPDATE`:
  - `fillfactor`에 여유가 있더라도, `UPDATE` 대상 컬럼에 인덱스 컬럼(`status` 등)이 포함되어 있으면 PostgreSQL 규칙에 따라 HOT 자격을 즉시 상실하고 모든 인덱스를 갱신합니다 (`HOT_INELIGIBLE_INDEXED_COLUMN_UPDATE_BLOAT`, `status: FAILED`).

### 2. 페이지 및 튜플 규격
- 표준 힙 페이지 크기: `8192` 바이트 (8KB).
- 인덱스 엔트리 추가 비용: 1개 인덱스당 `32` 바이트 쓰기 발생.
- `VACUUM` 작업 시: 지정된 페이지 내의 죽은 튜플(Dead Tuples) 크기만큼 여유 공간(`free_bytes`)을 즉시 회수합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "mode": "OPTIMAL_HOT_TUNED",
    "fillfactor": 75,
    "num_indexes": 5,
    "indexed_columns": ["id", "email", "created_at"]
  },
  "workload": [
    {"op": "INSERT", "wallclock_ms": 0.0, "row_id": "account_0", "size_bytes": 256},
    {"op": "UPDATE", "wallclock_ms": 150.0, "row_id": "account_0", "columns": ["bio"], "size_bytes": 256},
    {"op": "VACUUM", "wallclock_ms": 200.0, "page_id": 1}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "mode": "OPTIMAL_HOT_TUNED",
    "fillfactor": 75,
    "num_indexes": 5,
    "total_inserts": 24,
    "total_updates": 8,
    "hot_updates_success": 8,
    "hot_updates_failed": 0,
    "hot_success_rate": 1.0
  },
  "metrics": {
    "total_inserts": 24,
    "total_updates": 8,
    "hot_updates_success": 8,
    "hot_updates_failed": 0,
    "hot_success_rate": 1.0,
    "table_writes_bytes": 8192,
    "index_writes_bytes": 3840,
    "total_writes_bytes": 12032,
    "index_entries_added": 120,
    "write_amplification_ratio": 1.47,
    "vacuum_reclaims_bytes": 0,
    "total_pages_allocated": 1,
    "verdict": "OPTIMAL_HOT_INDEX_WRITE_MINIMIZED"
  },
  "sample_events": [
    {
      "wallclock_ms": 150.0,
      "op": "UPDATE",
      "row_id": "account_0",
      "hot_result": "HOT_SUCCESS",
      "page_id": 1,
      "index_writes_bytes": 0
    }
  ]
}
```
