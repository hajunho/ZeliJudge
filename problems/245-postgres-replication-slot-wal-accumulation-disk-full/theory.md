# Problem 245 Theory: PostgreSQL 스토리지와 복제 아키텍처 심층 분석 — WAL 라이프사이클, 복제 슬롯, 디스크 풀 PANIC 메커니즘 및 `max_slot_wal_keep_size`

관계형 데이터베이스 시스템(RDBMS)에서 **WAL(Write-Ahead Logging)**은 ACID 트랜잭션의 내구성(Durability)과 원자성(Atomicity), 그리고 충돌 복구(Crash Recovery)를 보장하는 핵심 불변 로그입니다. PostgreSQL에서는 이 WAL을 바탕으로 대기 서버로의 스트리밍 복제(Physical Streaming Replication)와 CDC(Change Data Capture)를 위한 논리적 디코딩(Logical Decoding)을 구현합니다.

본 문서에서는 PostgreSQL의 WAL 생성 및 체크포인트 회수 주기, 복제 슬롯(`pg_replication_slots`)의 동작 원리, 슬롯 지연 시 발생하는 디스크 풀 PANIC 메커니즘, 그리고 PostgreSQL 13에 도입된 `max_slot_wal_keep_size`의 설계 철학을 심층 분석합니다.

---

## 1. PostgreSQL WAL 라이프사이클과 체크포인트 (Checkpoint)

PostgreSQL은 모든 데이터 변경(INSERT, UPDATE, DELETE)을 디스크의 데이터 파일(Heap Table)에 직접 쓰기 전에, 먼저 공유 메모리 버퍼(`WAL Buffers`)를 거쳐 디스크의 **`pg_wal/` 디렉터리(16MB 크기의 세그먼트 파일들)**에 순차적으로 기록합니다.

```
                    PostgreSQL WAL 생성 및 회수 파이프라인
                    
 Transaction Writes ──► WAL Buffers ──► pg_wal/ (Segment Files: 16MB each)
                                               │
                                               ▼
                              [Checkpointer Background Process]
                              1. Dirty Buffers를 Data File로 플러시
                              2. Checkpoint REDO LSN 계산
                              3. 불필요해진 이전 WAL 세그먼트 삭제 또는 재활용!
                                               │
               ┌───────────────────────────────┴───────────────────────────────┐
               ▼                                                               ▼
   [복제 슬롯이 없을 때]                                           [복제 슬롯이 존재할 때]
   REDO LSN 이전의 오래된 WAL은                                    min(restart_lsn) 이전의 WAL만
   안전하게 즉시 삭제/재활용                                        삭제 가능! (슬롯이 잡고 있으면 영구 보류)
```

### 1.1 LSN (Log Sequence Number)
- WAL 내의 바이트 오프셋을 가리키는 64비트 정수입니다.
- 통상 16진수 형태인 `X/Y` (예: `1F/A003B8`)로 표기되며, 두 LSN 간의 차이는 `pg_wal_lsn_diff(lsn1, lsn2)`를 통해 바이트 단위로 정확히 계산할 수 있습니다.

### 1.2 체크포인터의 WAL 세그먼트 회수 규칙
체크포인터는 다음 조건을 모두 만족하는 WAL 파일만 안전하게 삭제하거나 다음 세그먼트로 재활용(`rename`)합니다:
1. 해당 세그먼트의 데이터가 데이터 파일로 플러시 완료됨 (REDO LSN 이전).
2. 아카이빙(`archive_command` / `archive_library`)이 완료됨.
3. **모든 유효한 복제 슬롯의 `restart_lsn`보다 과거의 파일일 것!**

---

## 2. 복제 슬롯 (Replication Slot)의 양날의 검

### 2.1 복제 슬롯의 탄생 배경
- 전통적인 복제 방식에서는 Primary가 자체 보존 파라미터(`wal_keep_size` / 과거 `wal_keep_segments`)에 지정된 양만큼만 WAL을 보관했습니다.
- 대기 서버의 네트워크가 일시적으로 단절되어 이 보존 한도를 넘어가면, Primary가 WAL을 지워버려 대기 서버가 영구적으로 동기화 불능(`WAL segment has already been removed`) 상태에 빠지는 문제가 있었습니다.
- **복제 슬롯의 도입**: 대기 서버가 실제로 읽고 커밋한 위치(`restart_lsn`)를 Primary의 카탈로그에 기록해 두고, **대기 서버가 해당 WAL을 소비할 때까지 Primary가 절대 삭제하지 않도록 보장**합니다.

### 2.2 물리적 슬롯 vs 논리적 슬롯
- **Physical Slot**: 바이트 단위의 로우 바이너리 WAL 복제(HA 스탠바이 노드).
- **Logical Slot**: WAL 레코드를 논리적 변경 스트림(JSON, 프로토콜 버퍼 등)으로 디코딩하여 외부 시스템(Debezium, Kafka, 타 DB)으로 스트리밍하는 슬롯. 트랜잭션이 커밋되기 전까지의 스냅샷을 위해 더 많은 WAL을 장시간 보류할 수 있음.

---

## 3. 디스크 풀(Full) PANIC 크래시 참사 메커니즘

### 3.1 장애 발생 시나리오
1. Debezium 컨테이너가 OOM으로 사망하거나, 네트워크 방화벽 규칙 변경으로 CDC 워커가 Primary에 접근하지 못함.
2. 복제 슬롯은 등록되어 있으나 연결이 끊겨 `restart_lsn`이 오프셋 10GB 위치에 멈춤.
3. Primary DB에서는 정상적인 업무 쿼리가 대량 실행되며 시간당 20GB의 WAL을 쏟아냄.
4. 체크포인터가 주기적으로 실행되지만, `restart_lsn`이 10GB에 묶여 있으므로 단 하나의 WAL 세그먼트도 삭제할 수 없음 (`KeepLogSeg()` 함수가 삭제를 차단).
5. WAL이 `pg_wal/` 디렉터리에 50GB, 100GB, 200GB로 폭증하여 **호스트 디스크가 100% 가득 참**.

### 3.2 왜 단순한 쓰기 실패가 아니라 PANIC 크래시인가?
- 데이터베이스 트랜잭션의 ACID 원칙에 따라, WAL 파일에 기록하지 못한 트랜잭션은 커밋될 수 없습니다.
- 디스크 공간 부족(`ENOSPC`)으로 인해 WAL 쓰기가 실패하면, PostgreSQL은 데이터베이스 일관성이 완전히 파괴될 수 있다고 판단하여 `FATAL` 수준을 넘어 **`PANIC` 수준의 에러를 발생시키고 즉시 엔진을 비정상 강제 셧다운(Crash Shutdown)**합니다.
- 복구도 어렵습니다: 재시작 시에도 크래시 복구를 위해 WAL을 써야 하므로 디스크를 비우기 전에는 데이터베이스가 부팅조차 거부합니다!

---

## 4. PostgreSQL 13의 해결책: `max_slot_wal_keep_size`

Primary DB 전체가 다운되는 비극을 막기 위해, PostgreSQL 13에 핵심 안전장치인 **`max_slot_wal_keep_size`**가 도입되었습니다.

```
       max_slot_wal_keep_size를 통한 Primary 생존 아키텍처
       
   WAL Lag = pg_current_wal_lsn() - slot.restart_lsn
   
   if (WAL Lag > max_slot_wal_keep_size) {
       1. 슬롯의 wal_status를 'lost'로 변경 (무효화)
       2. 슬롯의 restart_lsn 보호를 해제하고 보류 중이던 WAL 세그먼트 즉시 회수!
       3. Primary 디스크 여유 공간 확보 -> 정상 서비스 지속
       4. 해당 슬롯을 사용하던 대기 서버/CDC는 동기화 실패 후 재구축 필요
   }
```

### 4.1 설계 철학: 주 서버의 가용성이 스탠바이의 보존보다 우선한다
- 지연된 복제 슬롯 1개 때문에 핵심 Primary DB가 크래시되는 것은 최악의 가용성 실패입니다.
- 지연량이 임계치(예: 50GB)를 초과하면, 해당 대기 서버나 CDC 컨슈머의 연결을 희생(무효화)시키더라도 Primary DB를 살려내는 것이 올바른 아키텍처적 트레이드오프입니다.
- 무효화된 슬롯은 추후 `pg_basebackup`이나 CDC 전체 스냅샷 재동기화를 통해 복구해야 합니다.

---

## 5. 실무 모니터링 쿼리 및 SRE 운영 런북

### 5.1 복제 슬롯 지연 실시간 감시 쿼리
```sql
SELECT 
    slot_name,
    slot_type,
    active,
    wal_status,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS wal_lag_size,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS flush_lag_size
FROM pg_replication_slots;
```

### 5.2 권장 프로덕션 튜닝 파라미터
| 파라미터 | 권장 설정값 | 설명 및 효과 |
| :--- | :--- | :--- |
| **`max_slot_wal_keep_size`** | 디스크 여유분의 $30\%\sim50\%$ (예: `32GB` ~ `64GB`) | 슬롯 지연 한도를 설정하여 디스크 풀 PANIC 원천 방지 |
| **`wal_keep_size`** | `2048MB` ~ `8192MB` | 슬롯이 없는 단순 복제나 짧은 재연결을 위한 최소 WAL 보존량 |
| **장기 비활성 슬롯 삭제** | `pg_drop_replication_slot('name')` | 더 이상 사용하지 않는 레거시 CDC 슬롯은 즉시 수동 드롭 |
| **알람 임계치** | WAL 디스크 사용률 75% 초과 시 긴급 PagerDuty 호출 | Primary 디스크 소진 전 수동 대응 골든타임 확보 |
