# 문제 185: 데이터베이스 크래시 복구: ARIES 프로토콜, WAL과 Steal/No-Force 버퍼 풀 및 CLR 멱등 복구

## 문제 배경
현대 엔터프라이즈 관계형 데이터베이스(MySQL InnoDB, PostgreSQL, SQLite WAL, IBM DB2, Microsoft SQL Server 등)는 메모리 버퍼 풀(Buffer Pool)을 사용하여 디스크 I/O를 최소화하고 높은 트랜잭션 처리량을 달성합니다.

버퍼 풀 관리 정책은 크게 두 가지 축으로 나뉩니다:
1. **Steal vs No-Steal**:
   - **Steal**: 커밋되지 않은 트랜잭션의 더티 페이지(Dirty Page)라도 메모리가 부족하면 디스크로 방출(Flush)할 수 있도록 허용합니다. 버퍼 공간 활용도가 극대화되지만, 크래시 발생 시 디스크에 기록된 미커밋 데이터를 반드시 롤백(**Undo**)해야 합니다.
   - **No-Steal**: 커밋 전에는 절대 더티 페이지를 디스크에 쓰지 못하게 제한합니다. 트랜잭션 크기가 메모리 용량에 종속되어 처리량이 급감합니다.
2. **Force vs No-Force**:
   - **Force**: 트랜잭션이 커밋될 때 수정한 모든 더티 페이지를 디스크에 강제 동기화(Flush)합니다. 복구 시 재실행이 불필요하지만, 커밋마다 수많은 무작위 디스크 I/O가 발생하여 커밋 지연 시간이 폭증합니다.
   - **No-Force**: 커밋 시 더티 페이지를 즉시 디스크에 쓰지 않고 메모리에 둔 채 로그만 플러시합니다. 순차 I/O로 초고속 커밋을 지원하지만, 크래시 발생 시 커밋된 변경사항이 디스크에 없을 수 있으므로 반드시 재실행(**Redo**)해야 합니다.

현대 고성능 데이터베이스는 예외 없이 **Steal + No-Force** 조합을 채택합니다. 그리고 이 조합에서 ACID 원자성(Atomicity)과 지속성(Durability)을 완벽하게 보장하기 위해 C. Mohan 등이 창안한 **ARIES(Algorithms for Recovery and Isolation Exploiting Semantics)** 복구 프로토콜과 **WAL(Write-Ahead Logging)**을 사용합니다:

- **WAL 규칙**:
  - 규칙 1 (WAL 원칙): 더티 페이지를 디스크에 쓰기 전에, 해당 페이지의 수정을 기술한 로그 레코드가 먼저 비휘발성 디스크에 기록되어야 합니다 (`pageLSN <= flushedLSN`).
  - 규칙 2 (커밋 원칙): 트랜잭션의 `COMMIT` 로그 레코드가 디스크에 플러시되어야만 커밋이 완료된 것으로 간주합니다.

### ARIES 3단계 복구 라이프사이클
서버 장애/정전 후 재부팅 시 데이터베이스 엔진은 WAL 로그를 기반으로 3단계를 수행합니다:

1. **분석 단계 (Analysis Phase)**:
   - 최근 체크포인트(Checkpoint)부터 로그를 정방향 스캔하여 장애 발생 시점의 상태를 재구성합니다.
   - **더티 페이지 테이블(DPT)**: 메모리에 남아있던 더티 페이지와 해당 페이지를 처음 더럽힌 최소 LSN(`recLSN`)을 복원합니다. 모든 더티 페이지 중 가장 오래된 `recLSN`이 곧 Redo의 시작점(`smallest_rec_lsn`)이 됩니다.
   - **트랜잭션 테이블(Transaction Table)**: 장애 시점에 아직 커밋되지 않은 활성 트랜잭션들을 식별하여 **패배자(Losers)** 목록을 확정합니다.
2. **재실행 단계 (Redo Phase - "Repeating History")**:
   - `smallest_rec_lsn`부터 로그 끝까지 정방향 스캔하며, 장애 순간까지 일어난 모든 변경사항(커밋된 트랜잭션 및 패배자 트랜잭션 모두 포함)을 완벽하게 재현(Repeating History)합니다.
   - **DPT 최적화**: 페이지가 DPT에 없거나, 로그의 LSN이 DPT의 `recLSN`보다 작거나, 디스크 페이지의 `pageLSN`이 이미 해당 LSN 이상이면 불필요한 디스크 I/O를 건너뜁니다(`redo_skipped_count`).
3. **취소 단계 (Undo Phase & CLR 멱등 복구)**:
   - 패배자(Loser) 트랜잭션들의 변경사항을 역방향으로 롤백합니다.
   - 롤백 시 매 변경마다 **보상 로그 레코드(CLR, Compensation Log Record)**를 WAL에 기록합니다.
   - CLR은 직전에 취소한 작업의 이전 로그 포인터(`undo_next_lsn`)를 보관하며, **복구 도중 다시 크래시가 발생하더라도 이미 기록된 CLR은 절대 다시 Undo하지 않습니다(Idempotency)**. 따라서 무한 복구 루프에 빠지지 않고 안전하게 복구를 재개할 수 있습니다.

당신은 데이터베이스 스토리지 엔진 코어 개발자로서, WAL 로그와 디스크 상태가 주어졌을 때 ARIES 3단계 복구 알고리즘을 정확하게 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 입력 형식
입력은 표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다.

```json
{
  "config": {
    "recovery_mode": "FULL_ARIES",
    "checkpoint_lsn": 0,
    "crash_at_clr_count": 1
  },
  "initial_disk": {
    "P1": {"page_lsn": 0, "content": "base1"},
    "P2": {"page_lsn": 0, "content": "base2"}
  },
  "wal_log": [
    {"lsn": 10, "tx_id": "T1", "type": "UPDATE", "page_id": "P1", "prev_lsn": 0, "old_val": "base1", "new_val": "v10"},
    {"lsn": 20, "tx_id": "T2", "type": "UPDATE", "page_id": "P2", "prev_lsn": 0, "old_val": "base2", "new_val": "v20"},
    {"lsn": 30, "tx_id": "T1", "type": "COMMIT", "prev_lsn": 10},
    {"lsn": 40, "tx_id": "T1", "type": "END", "prev_lsn": 30}
  ]
}
```

### 필드 설명
- `config`:
  - `recovery_mode` (string): 복구 모드.
    - `"FULL_ARIES"`: 정상적인 3단계 ARIES 복구.
    - `"NO_REDO"`: Redo 단계를 생략하여 No-Force 위반 데이터 유실 유발.
    - `"NO_UNDO"`: Undo 단계를 생략하여 Steal 위반 미커밋 데이터 누출 유발.
    - `"CRASH_DURING_UNDO"`: Undo 단계 중 지정된 횟수의 CLR 작성 후 2차 크래시 시뮬레이션.
  - `checkpoint_lsn` (int): 체크포인트 LSN (0이면 처음부터 스캔).
  - `crash_at_clr_count` (int): `CRASH_DURING_UNDO` 모드 시 크래시를 유발할 CLR 기록 횟수.
- `initial_disk`: 크래시 직전 비휘발성 디스크에 영구 저장되어 있던 페이지 상태 (`page_id` -> `page_lsn`, `content`).
- `wal_log`: 장애 발생 전까지 디스크에 안전하게 기록된 WAL 레코드 목록 (LSN 오름차순).
  - `type`: `"UPDATE"`, `"COMMIT"`, `"ABORT"`, `"END"`, `"CLR"`, `"CHECKPOINT"`, `"FLUSH_PAGE"`.
  - `checkpoint` 타입의 경우 `dpt` 및 `active_transactions` 스냅샷을 포함할 수 있습니다.

---

## 출력 형식
표준 출력(stdout)으로 복구 완료 후의 시스템 상태와 메트릭을 JSON 형태로 들여쓰기 2칸으로 출력합니다.

```json
{
  "status": "SUCCESS",
  "recovery_mode": "FULL_ARIES",
  "metrics": {
    "analysis_records_scanned": 4,
    "smallest_rec_lsn": 10,
    "redo_applied_count": 2,
    "redo_skipped_count": 0,
    "undo_clr_written": 1,
    "active_losers_count": 1,
    "crash_during_recovery": false,
    "verdict": "ARIES_RECOVERY_SUCCESS"
  },
  "final_disk": {
    "P1": {
      "page_id": "P1",
      "page_lsn": 10,
      "content": "v10"
    },
    "P2": {
      "page_id": "P2",
      "page_lsn": 50,
      "content": "base2"
    }
  },
  "dirty_page_table": {
    "P1": 10,
    "P2": 20
  },
  "loser_transactions": [
    "T2"
  ],
  "generated_clrs": [
    {
      "lsn": 50,
      "tx_id": "T2",
      "type": "CLR",
      "page_id": "P2",
      "prev_lsn": 20,
      "undo_next_lsn": 0,
      "new_val": "base2"
    }
  ]
}
```

### 판정(Verdict) 규칙
1. `recovery_mode == "NO_REDO"`:
   - `"NO_FORCE_DIRTY_PAGE_DATA_LOSS_CORRUPTION"`
2. `recovery_mode == "NO_UNDO"`:
   - `"STEAL_UNCOMMITTED_DIRTY_LEAK_CORRUPTION"`
3. `recovery_mode == "CRASH_DURING_UNDO"`이고 복구 도중 2차 크래시 발생:
   - `"REPEATING_CRASH_DURING_UNDO_IDEMPOTENT_CLR"`
4. 정상적으로 3단계 ARIES 복구를 완료한 경우:
   - `"ARIES_RECOVERY_SUCCESS"`
