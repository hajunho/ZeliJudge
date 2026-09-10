# [분산 스토리지/LSM 엔진] Ceph BlueStore BlueFS 메타데이터 할당 실패와 RocksDB WAL/DB 스필오버(Spillover) 참사 및 슬로우 OSD 플래핑 제어

## 문제 설명

대규모 페타바이트급 분산 오브젝트·블록 스토리지인 Ceph는 고성능 raw 디스크 제어를 위해 POSIX 파일시스템(ext4, XFS)을 완전히 우회하고 사용자 공간에서 직접 블록 디바이스를 관리하는 **BlueStore** 스토리지 백엔드를 사용합니다.
BlueStore는 내부적으로 분산 오브젝트의 extent 맵, 속성 메타데이터(omap), 할당 정보(freelist), 트랜잭션 선행 기록 로그(Write-Ahead Log, WAL)를 저장하기 위해 임베디드 LSM(Log-Structured Merge) 트리 엔진인 **RocksDB**를 구동합니다.

RocksDB는 사용자 공간 가상 파일시스템인 **BlueFS** 위에서 실행되며, 고성능 처리를 위해 일반적으로 3계층의 이기종(Heterogeneous) 디스크 계층화(Tiering)를 구성합니다:
1. **`wal` 계층**: 초저지연 NVMe 디스크 (RocksDB WAL 전용, ~25μs 지연 시간)
2. **`db` 계층**: 고속 SSD 디스크 (RocksDB SSTable 메타데이터 전용, ~120μs 지연 시간)
3. **`slow` 계층**: 대용량 HDD/QLC 디스크 (실제 유저 오브젝트 Data 페이로드 저장, ~15,000μs 지연 시간)

### 💥 프로덕션 장애 시나리오: 메타데이터 스필오버(Spillover) 참사
클러스터에 쓰기 워크로드가 급증하여 고속 `db` 또는 `wal` 디바이스의 여유 공간이 고갈되면, BlueFS는 RocksDB 프로세스의 크래시를 방지하기 위해 남아 있는 공간인 **`slow` (HDD) 디스크로 메타데이터 할당을 자동 전이(Spillover)**시킵니다.
이때 치명적인 장애가 연쇄적으로 폭발합니다:
1. **I/O 지연 시간 100배 폭증**: 초당 수천 회 발생하는 WAL 동기화 및 Level-0 Compaction I/O가 HDD의 기계식 헤드 탐색 지연(~15ms)을 만나면서 OSD의 쓰기 레이턴시가 수십 마이크로초에서 수백 밀리초 단위로 수직 상승합니다.
2. **OSD 하트비트 타임아웃과 플래핑(Flapping)**: 기존 단일 큐 스레드 모델에서는 스토리지 I/O 블로킹이 OSD 피어 간 하트비트 핑(`osd_heartbeat_grace`, 기본 20초) 처리 스레드까지 잠식합니다. 피어 OSD들은 해당 OSD를 비정상(`DOWN`)으로 선언하고, 블로킹이 풀리면 다시 `UP`으로 보고되면서 **클러스터 전체에 PG 피어링 및 리커버리 스톰(Peering & Recovery Storm)**이 몰아치는 대참사가 발생합니다.
3. **스마트 제어 메커니즘**: BlueStore는 이를 방어하기 위해 **BlueFS 스필오버 감지 임계치**, **클라이언트 쓰기 스로틀링(`THROTTLED_UP`)**, 그리고 **하트비트 전용 독립 우선순위 스레드 디커플링(`heartbeat_decoupled`)**을 도입하였습니다.

클라우드 스토리지 엔지니어가 되어, Ceph BlueStore의 3계층 디바이스 공간 할당, RocksDB WAL/DB 스필오버 경로, 그리고 하트비트 디커플링에 따른 OSD 플래핑 방어 동작을 정확하게 재현하는 **BlueStore 스필오버 시뮬레이션 및 플래핑 제어 엔진**을 구현하십시오.

---

## 시뮬레이션 및 계산 규격

### 1. 디바이스 계층 구조 및 기본 상태
- `wal`: 초저지연 NVMe (용량 `capacity_bytes`, 기본 지연 `write_latency_us`)
- `db`: 고속 SSD (용량 `capacity_bytes`, 기본 지연 `write_latency_us`)
- `slow`: 대용량 HDD (용량 `capacity_bytes`, 기본 지연 `write_latency_us`)
- 각 디바이스는 현재 사용량(`used_bytes`), 여유 공간(`free_bytes = capacity - used`), 사용률(`usage_ratio = used / capacity`), 스필오버 유입량(`spillover_in_bytes`)을 추적합니다.

### 2. 공간 할당 및 스필오버(Spillover) 규칙
1. **`WRITE_WAL` (크기 $S$)**:
   - `wal` 디바이스의 여유 공간이 $S$ 이상이면 `wal`에 할당, 지연 시간은 `wal.write_latency_us`.
   - `wal` 공간 부족 시 `db` 디바이스 여유 공간 확인:
     - `db`에 공간이 있으면 `db`에 할당, `total_wal_spillover_bytes += S`, `db.spillover_in_bytes += S`, 지연 시간은 `db.write_latency_us`. 진단 코드 `WAL_SPILLED_TO_DB` 등록.
   - `db`도 공간 부족 시 `slow` 디바이스에 할당:
     - `total_wal_spillover_bytes += S`, `slow.spillover_in_bytes += S`, 지연 시간은 `slow.write_latency_us`. 진단 코드 `WAL_SPILLED_TO_SLOW_TIER_CATASTROPHE` 등록.
2. **`WRITE_SST_METADATA` (크기 $S$)**:
   - `db` 디바이스의 여유 공간이 $S$ 이상이면 `db`에 할당, 지연 시간은 `db.write_latency_us`.
   - `db` 공간 부족 시 `slow` 디바이스에 할당:
     - `total_db_spillover_bytes += S`, `slow.spillover_in_bytes += S`, 지연 시간은 `slow.write_latency_us`. 진단 코드 `DB_SST_SPILLED_TO_SLOW_TIER` 등록.
3. **`COMPACT_L0` (공간 회수)**:
   - `db`에서 `space_freed_db_bytes`만큼 공간을 회수 (`max(0, used - freed)`).
   - `slow`에서 `space_freed_slow_bytes`만큼 공간을 회수.
   - 컴팩션 자체의 I/O 지연 시간으로 `db.write_latency_us * 2` 기록.
4. **`CLIENT_WRITE_REQ` (페이로드 크기 $S$)**:
   - `db`의 여유 공간 비율이 `bluefs_spillover_halt_ratio` 미만이거나 이미 DB 스필오버가 발생한 경우:
     - 클라이언트 쓰기 스로틀링 활성화(`is_throttled = True`).
     - 지연 시간은 `slow.write_latency_us` (또는 `db.write_latency_us * 5`).
   - 정상 시 지연 시간은 `db.write_latency_us`.

### 3. I/O 스톨(Stall) 및 하트비트 플래핑(Flapping) 판정
- `slow` 디바이스 수준의 높은 지연(지연 시간 $\ge 	ext{slow.write\_latency\_us}$)이 발생할 때마다 연속 스톨 시간(`consecutive_stall_ms += lat_ms`)이 누적됩니다. 빠른 I/O가 발생하면 $50	ext{ms}$씩 스톨 누적이 해소됩니다.
- **`HEARTBEAT_TICK` (경과 시간 `elapsed_ms`)**:
  - `heartbeat_decoupled == False` (스토리지 I/O와 하트비트 스레드가 결합된 레거시 모드):
    - 만약 누적 스톨 시간이 `osd_heartbeat_grace_ms` 이상이면:
      - OSD 상태가 정상이었던 경우 즉시 `is_down = True`, `flapping_events += 1`, 진단 코드 `OSD_HEARTBEAT_EXPIRED_PEER_DECLARED_DOWN (stall=...ms)` 등록.
    - 만약 누적 스톨 시간이 해소되어 `osd_heartbeat_grace_ms` 미만으로 내려왔고 이미 `is_down` 상태였다면:
      - OSD가 다시 부활하며 `is_down = False`, `flapping_events += 1`, 진단 코드 `OSD_REVIVED_TRIGGERING_PEERING_RECOVERY_STORM` 등록.
  - `heartbeat_decoupled == True` (하트비트 독립 우선순위 스레드 분리 모드):
    - 스토리지 I/O 스톨과 무관하게 하트비트 핑이 정상 처리되므로 `is_down = False` 유지.
  - `consecutive_stall_ms = max(0, consecutive_stall_ms - elapsed_ms)`.

### 4. 최종 OSD 상태(`osd_state`) 및 지연 통계
- `is_down == True` 이거나 `flapping_events > 1`: `"FLAPPING_DOWN"`
- `db` 디바이스의 여유 공간 비율 $< 	ext{bluefs\_spillover\_halt\_ratio}$: `"STALL_HALT"`
- `is_throttled == True` 이거나 스필오버가 발생한 경우: `"THROTTLED_UP"`
- 그 외 정상: `"HEALTHY_UP"`
- 지연 시간 통계:
  - `avg_latency_us`: 평균 지연 시간 (소수점 첫째 자리 반올림)
  - `p99_latency_us`: P99(99th 백분위수) 지연 시간 ($\lceil 0.99 	imes N ceil - 1$ 인덱스)
  - `max_latency_us`: 최대 지연 시간

---

## 입력 형식

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 주어집니다:
```json
{
  "cluster_id": "PROD_CEPH_NVME_01",
  "osd_id": 42,
  "devices": {
    "wal": {"capacity_bytes": 10000000, "used_bytes": 0, "tier": "FAST_NVME", "write_latency_us": 25},
    "db": {"capacity_bytes": 50000000, "used_bytes": 0, "tier": "SSD", "write_latency_us": 120},
    "slow": {"capacity_bytes": 1000000000, "used_bytes": 0, "tier": "HDD", "write_latency_us": 15000}
  },
  "config": {
    "bluefs_min_free_ratio": 0.10,
    "bluefs_spillover_halt_ratio": 0.02,
    "osd_heartbeat_grace_ms": 20000,
    "heartbeat_decoupled": false
  },
  "workload_ops": [
    {"type": "WRITE_WAL", "size_bytes": 2000000},
    {"type": "WRITE_SST_METADATA", "size_bytes": 10000000},
    {"type": "HEARTBEAT_TICK", "elapsed_ms": 1000}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 계산된 결과를 JSON 문자열(단일 라인)로 출력합니다:
```json
{
  "cluster_id": "PROD_CEPH_NVME_01",
  "osd_id": 42,
  "osd_state": "THROTTLED_UP",
  "heartbeat_decoupled": false,
  "flapping_events_count": 0,
  "total_wal_spillover_bytes": 0,
  "total_db_spillover_bytes": 0,
  "latency_stats_us": {
    "avg_latency_us": 72.5,
    "p99_latency_us": 120,
    "max_latency_us": 120
  },
  "devices": {
    "wal": {"capacity_bytes": 10000000, "used_bytes": 2000000, "free_bytes": 8000000, "usage_ratio": 0.2, "spillover_in_bytes": 0},
    "db": {"capacity_bytes": 50000000, "used_bytes": 10000000, "free_bytes": 40000000, "usage_ratio": 0.2, "spillover_in_bytes": 0},
    "slow": {"capacity_bytes": 1000000000, "used_bytes": 0, "free_bytes": 1000000000, "usage_ratio": 0.0, "spillover_in_bytes": 0}
  },
  "diagnostics": []
}
```
