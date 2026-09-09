# #165 초당 10만 건 쓰다 왜 갑자기 모든 DB 쓰기가 30초간 멈춰버려요?!: RocksDB/LSM-Tree 라이트 스톨(Write Stall)과 L0 컴팩션 부채(Compaction Debt) vs 동적 레벨 바이트 사이징 (RocksDB LSM-Tree Write Stall & Compaction Debt: L0 File Accumulation vs Dynamic Leveled Compaction)

## 1. 실무 장애 시나리오: "순차 쓰기라 빠르다더니, 트래픽 몰리자 쓰기 레이턴시가 500ms로 치솟고 DB가 굳어버렸어요!"

시계열 IoT 센서 데이터 및 대규모 결제 로그를 실시간 수집하는 '젤리데이터' 플랫폼은 초당 수만 건의 초고속 쓰기 처리를 위해 **LSM-Tree(Log-Structured Merge-tree) 기반 임베디드 스토리지 엔진(RocksDB/TiKV)**을 채택했습니다.

LSM-Tree는 디스크 무작위 쓰기(Random I/O)를 피하고 메모리의 **`MemTable`**에 먼저 기록한 뒤 순차적으로 플러시(Flush)하므로, 평상시 0.5ms 미만의 환상적인 쓰기 성능을 자랑했습니다.

그러던 어느 날, 대규모 프로모션과 실시간 데이터 폭증으로 **초당 10만 건의 대량 쓰기 버스트**가 쏟아졌습니다:

```
[ Client Traffic Burst (100,000 writes/sec) ]
                   │
                   ▼
       ┌───────────────────────┐
       │ Active MemTable (64MB)│
       └───────────┬───────────┘
                   │ MemTable Full! Sealed to Immutable
                   ▼
       ┌───────────────────────┐
       │ Immutable MemTables   │ (max_write_buffer_number: 2)
       │ [Imm-1] [Imm-2]       │ -> LIMIT REACHED!
       └───────────┬───────────┘
                   │ Flush thread too slow!
                   ▼
       ┌───────────────────────┐
       │ Level 0 (L0) SSTables │ (Overlapping Key Ranges!)
       │ [F1][F2][F3]...[F8]   │ -> l0_stop_writes_trigger (8) REACHED!
       └───────────┬───────────┘
                   │ Compaction I/O Debt Accumulation!
                   ▼
┌────────────────────────────────────────────────────────┐
│ ROCKSDB EMERGENCY BRAKE TRIGGERED: WRITE_STALL_STOP!   │
│ -> All incoming client writes are HARD BLOCKED!        │
│ -> Write Latency: 0.5ms -> 500ms (1,000x Spike!)       │
│ -> Read Amplification: Probing 10+ overlapping files!  │
│ -> Upstream microservices hit Connection Pool Timeout! │
└────────────────────────────────────────────────────────┘
```

모니터링 대시보드에 끔찍한 알람이 울려 퍼졌습니다:
1. **라이트 스톨(Write Stall) 대참사**:
   - 백그라운드 플러시 및 컴팩션 속도보다 클라이언트의 쓰기 속도가 훨씬 빠르자, `Immutable MemTable`이 한도(`max_immutable_memtables = 2`)에 도달하거나 `L0` 파일 개수가 정지 임계치(`l0_stop_trigger = 8`)에 도달했습니다.
   - RocksDB는 스토리지 붕괴를 막기 위해 클라이언트의 쓰기 스레드를 강제로 정지시키는 **`WRITE_STALL_STOP`** 비상 브레이크를 작동시켰습니다.
   - 쓰기 응답 시간이 0.5ms에서 수백 밀리초~수십 초로 폭증하며 상위 애플리케이션 스레드 풀이 고갈되었습니다.
2. **읽기 증폭(Read Amplification) 폭발**:
   - L1 이상의 레벨은 키 범위가 상호 배타적(Non-overlapping)이지만, **L0의 SSTable 파일들은 서로 키 범위가 겹칩니다(Overlapping Key Ranges)**.
   - L0 파일이 8개 쌓이자, 단 1건의 데이터를 읽으려 해도 활성 MemTable, 불변 MemTable, 그리고 **8개의 L0 파일을 전부 뒤져야(전수 조사)** 하는 읽기 지연 참사가 터졌습니다!

---

## 2. RocksDB 라이트 스톨(Write Stall) 3단계 상태 전이

RocksDB는 백그라운드 I/O 부채 상태에 따라 3단계로 쓰기 정책을 제어합니다:

| 상태 | 진입 조건 | 클라이언트 영향 | 레이턴시 페널티 |
| :--- | :--- | :--- | :--- |
| **`NORMAL`** | L0 파일 수 < `l0_slowdown_trigger` and Immutable 수 < `max_immutable_memtables` | 즉시 메모리 기록 및 수락 (`accepted: true`) | 정상 (0.5ms) |
| **`WRITE_STALL_SLOWDOWN`** | L0 파일 수 $\ge$ `l0_slowdown_trigger` | 의도적 인위적 지연 주입 후 수락 (`accepted: true`) | 스로틀링 (25.0ms) |
| **`WRITE_STALL_STOP`** | L0 파일 수 $\ge$ `l0_stop_trigger` or Immutable 수 $\ge$ `max_immutable_memtables` | **쓰기 요청 거부/동결** (`accepted: false`) | **차단/정지 (500.0ms)** |

---

## 3. 구현 명세 및 동작 규칙

본 문제에서는 LSM-Tree 스토리지 엔진과 컴팩션 라이프사이클을 시뮬레이션하는 `LSMStorageEngine`을 구현해야 합니다.

### (1) 스토리지 계층 구조
1. **`active_memtable`**: 현재 쓰기를 수신하는 인메모리 딕셔너리. 크기가 `memtable_capacity`에 도달하면 불변 상태로 동결되어 `immutable_memtables`로 이동하고 새 활성 MemTable이 생성됩니다.
2. **`immutable_memtables`**: 디스크 L0로 플러시 대기 중인 불변 큐 (최대 허용 개수: `max_immutable_memtables`).
3. **`l0_files`**: 디스크 Level 0 SSTable 파일들의 목록. 키 범위가 겹칠 수 있으므로 새 파일이 항상 맨 앞(인덱스 0)에 추가됩니다.
4. **`l1_storage`**: 컴팩션을 통해 정렬 병합된 Level 1 단일 정렬 런(Sorted Run, Non-overlapping).

### (2) 연산(Operations) 처리 규칙
- **`PUT (key, val)`**:
  - 쓰기 스톨 조건을 검사합니다:
    - `len(l0_files) >= l0_stop_trigger` OR `len(immutable_memtables) >= max_immutable_memtables` $	o$ `status = "WRITE_STALL_STOP"`, `latency_ms = 500.0`, `accepted = false`.
    - `len(l0_files) >= l0_slowdown_trigger` $	o$ `status = "WRITE_STALL_SLOWDOWN"`, `latency_ms = 25.0`, `accepted = true`.
    - 그 외 $	o$ `status = "NORMAL"`, `latency_ms = 0.5`, `accepted = true`.
  - `accepted = true`인 경우만 `active_memtable`에 `{"val": val, "tombstone": false}`로 기록합니다.
- **`DELETE (key)`**:
  - `PUT`과 동일한 스톨 조건을 검사합니다.
  - `accepted = true`인 경우 `active_memtable`에 **삭제 묘비(`tombstone: true`, `val: null`)**를 기록합니다 (LSM-Tree는 삭제도 Append-Only).
- **`GET (key)`**:
  - 최신 데이터부터 순차적으로 탐색(Probe)하며 탐색 횟수(`read_probes`)를 누적합니다:
    1. `active_memtable` 확인 (1 probe). 키가 있으면 탐색 종료.
    2. `immutable_memtables` 최신순 확인 (각각 1 probe). 키가 있으면 탐색 종료.
    3. `l0_files` 최신순 확인 (키 범위가 겹치므로 키를 찾을 때까지 파일당 1 probe). 키가 있으면 탐색 종료.
    4. `l1_storage` 확인 (1 probe).
  - 탐색 도중 키를 발견했을 때 `tombstone: true`이면 삭제된 키이므로 `found = false, val = null`로 반환합니다. 키를 찾지 못해도 `found = false, val = null`입니다.
- **`TICK` (백그라운드 스레드 주기)**:
  1. **Flush**: `immutable_memtables`에 대기 중인 가장 오래된(인덱스 0) MemTable이 있다면 꺼내어 `l0_files` 맨 앞(인덱스 0)에 추가합니다 (`flushed_immutable = true`).
  2. **Compaction**: `len(l0_files) >= l0_compaction_trigger`이면, 현재 모든 L0 파일들을 오래된 순서부터 최신 순서대로 병합한 뒤 `l1_storage`에 덮어씁니다. 이때 `tombstone: true`인 키는 `l1_storage`에서 영구 제거(Purge)됩니다. 컴팩션 완료 후 `l0_files`는 빈 리스트가 됩니다.

---

## 4. 입출력 형식

### 입력 형식 (JSON on `sys.stdin`)
```json
{
  "config": {
    "memtable_capacity": 3,
    "max_immutable_memtables": 2,
    "l0_compaction_trigger": 3,
    "l0_slowdown_trigger": 5,
    "l0_stop_trigger": 8
  },
  "operations": [
    { "type": "PUT", "key": "k1", "val": "v1" },
    { "type": "PUT", "key": "k2", "val": "v2" },
    { "type": "GET", "key": "k1" },
    { "type": "TICK" }
  ]
}
```

### 출력 형식 (JSON on `sys.stdout`)
```json
{
  "summary": {
    "total_writes": 2,
    "normal_writes": 2,
    "slowdown_writes": 0,
    "stopped_writes": 0,
    "write_stall_occurred": false,
    "total_reads": 1,
    "avg_read_probes": 1.0,
    "total_compactions": 0,
    "final_l0_files": 0,
    "final_immutable_memtables": 0,
    "final_l1_keys": 0
  },
  "results": [
    {
      "op": "PUT",
      "key": "k1",
      "status": "NORMAL",
      "latency_ms": 0.5,
      "accepted": true,
      "l0_count": 0,
      "immutable_count": 0
    },
    {
      "op": "PUT",
      "key": "k2",
      "status": "NORMAL",
      "latency_ms": 0.5,
      "accepted": true,
      "l0_count": 0,
      "immutable_count": 0
    },
    {
      "op": "GET",
      "key": "k1",
      "found": true,
      "val": "v1",
      "read_probes": 1
    },
    {
      "op": "TICK",
      "flushed_immutable": false,
      "compacted_l0_files": 0,
      "remaining_l0": 0,
      "remaining_imm": 0,
      "l1_total_keys": 0
    }
  ]
}
```
