# 문제 223 이론: 데이터베이스 스토리지 엔진 WAL 체크포인트 스파이크(Checkpoint Spikes), 분산 플러시(Fuzzy Checkpoint)와 백엔드 쓰기(Backend Writes)

---

## 1. 관계형 데이터베이스에서 체크포인트(Checkpoint)의 당위성

### 1.1 Steal / No-Force 버퍼 관리 모델 (Gray & Reuter)
대부분의 현대 RDBMS(PostgreSQL, MySQL InnoDB, Oracle)는 고성능을 위해 **Steal / No-Force** 정책을 따릅니다.
- **No-Force**: 트랜잭션이 커밋되더라도 데이터 페이지를 즉시 디스크 테이블스페이스에 동기적으로 플러시(Fsync)하지 않습니다. 대신 크기가 훨씬 작고 순차 I/O인 WAL/Redo 로그 버퍼만 디스크에 플러시합니다.
- **Steal**: 메모리가 부족할 때 아직 커밋되지 않은 트랜잭션의 더티 페이지라도 디스크에 기록할 수 있습니다.

### 1.2 체크포인트의 세 가지 목적
1. **RTO(Recovery Time Objective) 단축**: 시스템 크래시 시 ARIES 복구 알고리즘이 재실행(Redo)해야 하는 시작 지점을 체크포인트 LSN으로 전진시킵니다.
2. **디스크 공간 회수**: 체크포인트 LSN 이전의 오래된 WAL 세그먼트 파일들을 안전하게 삭제하거나 재사용(Recycle)합니다.
3. **메모리 버퍼 풀 갱신**: 더티 페이지를 디스크 파일시스템과 동기화하여 파일 영속성을 보장합니다.

---

## 2. 날카로운 체크포인트(Sharp Checkpoint)와 I/O 스파이크

```
 [Sharp vs Fuzzy Checkpoint Disk I/O Profile]

  Disk Write Bandwidth (MB/s)
  250 ──┐  ┌─── Sharp Checkpoint: 100% Saturation! ───┐
        │  │                                          │
        │  │  (Incoming OLTP queries freeze for 4.5s) │
        │  │                                          │
   60 ──┼──┴──────────────────────────────────────────┴──
        │   Fuzzy Spread Flush (Target=0.9): Flat ~64 MB/s (No Stalls!)
    0 ──┴─────────────────────────────────────────────────────────────► Time
```

### 2.1 날카로운 체크포인트의 폐해
- 체크포인터 프로세스가 기동되자마자 버퍼 풀의 모든 더티 페이지를 OS 페이지 캐시로 전속력으로 기록한 뒤 연달아 `fsync()`를 호출합니다.
- 스토리지 컨트롤러와 디스크 드라이브 I/O 큐 깊이(Queue Depth)가 포화되어 100% I/O 바운드 상태에 도달합니다.
- 신규 쿼리가 페이지를 읽으려 할 때 디스크 헤드가 체크포인트 쓰기 요청에 묶여 대기열에 갇히고, 쿼리 응답시간이 수 초 이상으로 치솟는 **체크포인트 스파이크(Checkpoint Spikes)**가 발생합니다.

---

## 3. 퍼지 체크포인트(Fuzzy Spread Checkpoint)와 Rate Governor

PostgreSQL 8.3부터 도입된 분산 플러시(Spread Checkpoint)는 체크포인트 쓰기 작업을 시간상으로 고르게 분산합니다.

### 3.1 `checkpoint_completion_target`의 수학
체크포인터는 다음 체크포인트가 격발될 때까지의 시간 $T_{\text{interval}}$ 중 일정 비율 동안만 천천히 페이지를 쓰도록 목표 시간을 설정합니다:
$$T_{\text{target}} = T_{\text{interval}} \times \text{checkpoint\_completion\_target}$$
- 예: `checkpoint_timeout = 300초`, `checkpoint_completion_target = 0.9`
- 목표 쓰기 시간: $300 \times 0.9 = 270\text{초}$
- 더티 페이지가 12GB 누적되어 있다면:
  - 날카로운 체크포인트: 250 MB/s로 약 48초간 디스크 100% 장악 (극심한 스톨).
  - 분산 플러시: $12000\text{MB} / 270\text{초} \approx 44.4\text{ MB/s}$로 균등 쓰기 (디스크 여유 대역폭 82% 유지).

---

## 4. 백엔드 동기 쓰기(Backend Writes) 쓰레싱과 Bgwriter

### 4.1 백엔드 쓰기(`buffers_backend`)가 발생하는 이유
Checkpointer는 **체크포인트 주기를 맞추기 위해** 더티 페이지를 씁니다.
반면 Background Writer(`bgwriter`)는 **신규 쿼리를 실행할 백엔드 프로세스가 즉시 쓸 수 있는 클린 버퍼를 미리 만들어두기 위해** 동작합니다.

만약 쓰기 트랜잭션 속도가 너무 빨라 버퍼 풀의 클린 페이지가 모두 소진되면:
1. 유저 쿼리를 처리하던 백엔드 워커 스레드가 버퍼 할당(`BufferAlloc()`)을 시도합니다.
2. 클록 스윕(Clock Sweep) 알고리즘을 돌려도 비어있는 클린 버퍼가 없습니다.
3. 백엔드 스레드는 어쩔 수 없이 자신이 직접 디스크에 더티 페이지를 동기적으로 플러시(`FlushBuffer()`)합니다.
4. 이것이 `pg_stat_bgwriter`의 `buffers_backend` 카운터로 누적되며, 백엔드 프로세스들이 I/O에 갇혀 쿼리 지연이 폭증하고 동시성 처리량이 붕괴합니다.

### 4.2 최적 튜닝 처방전
1. **`checkpoint_completion_target = 0.9`**: 쓰기 I/O를 최대 90% 기간에 걸쳐 부드럽게 분산.
2. **`max_wal_size` 확장 (16GB ~ 64GB)**: 빈번한 조기 체크포인트 방지.
3. **`bgwriter_lru_maxpages` & `bgwriter_delay` 최적화**: 백엔드 동기 쓰기를 0으로 억제.
