# 문제 230: 분산 스토리지 Ceph: BlueStore OSD Onode 캐시 고갈과 BlueFS RocksDB 컴팩션 스파이크 vs OSD 플래핑(Flapping) 방어 시뮬레이터

## 1. 개요 및 배경 (Incident Scenario)

수 페타바이트(PB) 규모의 오픈스택 및 쿠버네티스 영구 볼륨(Ceph RBD/CephFS) 클러스터에서 특정 스토리지 노드들이 무더기로 다운되었다가 살아나기를 반복하는 연쇄 **OSD 플래핑 폭풍(OSD Flapping Storm)**이 발생하여 클러스터 전체가 마비되었습니다.

Ceph은 레거시 FileStore(XFS 위에서의 이중 저널링 오버헤드)를 대체하여 원시 블록 디바이스(Raw Block Device)에 직접 I/O를 수행하는 **BlueStore** 스토리지 엔진을 채택하고 있습니다. BlueStore는 객체의 데이터(Data)는 디바이스에 직접 스트리밍하고, 객체 메타데이터(Onode, Extent 맵, omap)는 **BlueFS**라는 경량 파일시스템 위에서 구동되는 임베디드 **RocksDB**에 보관합니다.

수억 개의 소형 객체(Small Objects) 생성 및 메타데이터 갱신 트래픽이 폭증하던 중, 시스템 엔지니어링 팀은 세 가지 치명적인 병목 현상을 마주했습니다:

1. **Onode 캐시 고갈 및 메타데이터 쓰레싱 (Onode Cache Eviction Thrashing)**:
   - Ceph의 각 객체는 고유 메타데이터 구조체인 `Onode`(리눅스 커널의 inode와 유사)를 갖습니다. `onode_cache_size_mb`가 활성 객체 워킹셋에 비해 너무 작으면 Onode 적중률이 50% 미만으로 급락하여 객체를 읽을 때마다 RocksDB 및 디스크로의 메타데이터 조회가 강제되어 지연시간이 20배 이상 폭증(`ONODE_CACHE_EVICTION_THRASHING`)했습니다.
2. **RocksDB BlueFS 컴팩션 스톨 (Compaction Stall Spike)**:
   - 메타데이터 쓰기 버스트가 발생하면 RocksDB의 L0$\rightarrow$L1 컴팩션이 대규모로 격발됩니다. BlueFS가 느린 HDD와 디스크를 공유하거나 배경 컴팩션 스레드 수가 1개로 부족하면, RocksDB 쓰기 스톨(Write Stall)이 발생하여 OSD 프로세스 전체가 12~25초 동안 완전히 멈추는 프리징 현상(`ROCKSDB_BLUEFS_COMPACTION_STALL_SPIKE`)이 발생했습니다.
3. **하트비트 타임아웃과 OSD 플래핑 데스 스파이럴 (Heartbeat Timeout & Flapping Storm)**:
   - RocksDB 컴팩션으로 OSD가 25초간 프리징되는 동안, 피어 OSD들 간의 하트비트 핑 응답이 `osd_heartbeat_grace`(20초)를 초과했습니다.
   - 피어 OSD들은 해당 OSD를 `osd down`으로 모니터(MON)에 신고했고, 모니터는 즉시 CRUSH 맵을 갱신하여 수십 테라바이트의 피어링(Peering) 및 백필(Backfill) 데이터 복구를 시작했습니다.
   - 그러나 컴팩션이 끝나자마자 해당 OSD는 다시 살아나 `osd up`을 선언했고, 이로 인해 다운과 업이 무한 반복되며 클러스터 네트워크와 디스크가 완전히 붕괴(`OSD_HEARTBEAT_TIMEOUT_FLAPPING_STORM`)되었습니다.

엔지니어링 팀은 **BlueFS 전용 고속 NVMe 파티션 분리**, **RocksDB 배경 컴팩션 병렬화(4개 스레드)**, **디스크 I/O로부터 격리된 전용 하트비트 스레드**, 그리고 **충분한 Onode 캐시 크기**를 확보하여 OSD 플래핑을 완벽히 차단하기로 결정했습니다.

본 문제에서는 BlueStore 설정 파라미터 및 메타데이터 버스트 워크로드에 따른 Onode 캐시 적중률, 컴팩션 스톨 시간, 하트비트 타임아웃 및 플래핑 여부를 시뮬레이션하고 최적 상태를 진단하는 프로그램을 구현합니다.

---

## 2. Ceph BlueStore 아키텍처 및 OSD 플래핑 흐름

```
[Ceph BlueStore Internal Architecture]
Raw Block Device (/dev/nvme0n1 or /dev/sda)
+-------------------------------------------------------------------------------+
| BlueStore OSD Process (RAM)                                                   |
|   [Onode LRU/2Q Cache] <----+ (Hit: 0.8ms ultra-fast read)                    |
|   [RocksDB Block Cache]     |                                                 |
+-----------------------------|-------------------------------------------------+
                              | Miss: Must query RocksDB!
+-----------------------------v-------------------------------------------------+
| BlueFS (Lightweight FS for Metadata)   | Raw Data Space (Direct Extents)      |
|   Embedded RocksDB:                    |   Object 1 Data: [Block 100 ~ 200]   |
|   - Onodes (Extents mapping, omap)     |   Object 2 Data: [Block 201 ~ 350]   |
|   - WAL & SSTables (L0 -> L1 Compaction)|   (Zero POSIX FS Double Journaling!) |
+----------------------------------------+--------------------------------------+

---------------------------------------------------------------------------------

[The OSD Flapping Death Spiral]
1. Metadata Burst -> RocksDB L0 Compaction Stall (25s Freeze)
2. Heartbeat Ping from Peer OSD timed out! (25s > osd_heartbeat_grace 20s)
3. Peer OSDs report: "OSD 42 is DOWN!" -> Monitor marks OSD 42 DOWN
4. CRUSH Map updates -> Triggers massive Multi-TB Backfill Recovery I/O Storm!
5. 2 seconds later: Compaction completes -> OSD 42 sends heartbeat: "I am UP!"
6. Monitor marks OSD 42 UP -> Cancels backfill -> Re-peering -> REPEAT FOREVER!
```

---

## 3. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "onode_cache_size_mb": 1024.0,
    "rocksdb_shared_cache_mb": 2048.0,
    "bluefs_dedicated_nvme": true,
    "max_background_compactions": 4,
    "osd_heartbeat_grace_sec": 20.0,
    "dedicated_heartbeat_thread": true,
    "sla_latency_ms": 50.0
  },
  "workload": {
    "object_count": 500000,
    "ops_per_sec": 15000.0,
    "write_ratio": 0.4,
    "metadata_mutation_burst": true
  }
}
```

- `config`:
  - `onode_cache_size_mb`: OSD 메모리 내 Onode 캐시 할당 크기 (MB)
  - `rocksdb_shared_cache_mb`: RocksDB 블록 캐시 크기 (MB)
  - `bluefs_dedicated_nvme`: BlueFS 및 RocksDB 저널/SST가 전용 NVMe 디스크에 분리되어 있는지 여부 (boolean)
  - `max_background_compactions`: RocksDB 배경 컴팩션 병렬 스레드 수 (기본 4)
  - `osd_heartbeat_grace_sec`: 피어 OSD 하트비트 응답 허용 최대 대기시간 (초, 기본 20.0)
  - `dedicated_heartbeat_thread`: 디스크 I/O 블로킹과 무관하게 독립 실행되는 전용 하트비트 스레드 여부 (boolean)
  - `sla_latency_ms`: 허용 최대 평균 I/O 지연시간 (ms, 기본 50.0)
- `workload`:
  - `object_count`: 활성 객체 수
  - `ops_per_sec`: 초당 입출력 연산 수
  - `write_ratio`: 쓰기 연산 비율 (0.0 ~ 1.0)
  - `metadata_mutation_burst`: 대규모 메타데이터 생성/삭제 버스트 발생 여부 (boolean)

---

## 4. 연산 및 시뮬레이션 공식

1. **Onode 캐시 요구량 및 적중률**:
   - 객체 1개당 Onode 크기는 약 1KB로 계산:
     $$\text{needed\_onode\_memory\_mb} = \frac{\text{object\_count} \times 1024}{1024 \times 1024}$$
   - 안전 워킹셋 계수 1.5배 적용:
     $$\text{onode\_cache\_hit\_ratio} = \min\left(1.0, \frac{\text{onode\_cache\_size\_mb}}{\max(1.0, \text{needed\_onode\_memory\_mb} \times 1.5)}\right)$$
2. **읽기 지연시간 및 RocksDB 미스 페널티**:
   - 베이스 디스크 읽기 시간: 0.8ms
   - 미스 페널티: `bluefs_dedicated_nvme == True`이면 4.5ms, False(느린 HDD)이면 22.0ms
     $$\text{read\_latency\_ms} = 0.8 + (1.0 - \text{onode\_cache\_hit\_ratio}) \times \text{rocksdb\_miss\_penalty\_ms}$$
3. **컴팩션 스톨 시간 계산 (`compaction_stall_duration_sec`)**:
   - `metadata_mutation_burst == False`이면 스톨 시간은 $0.0$초.
   - `metadata_mutation_burst == True`인 경우:
     - `bluefs_dedicated_nvme == False`: 느린 디스크로 인해 25.0초 스톨.
     - `bluefs_dedicated_nvme == True`이고 `max_background_compactions <= 1`: 단일 스레드 병목으로 12.0초 스톨.
     - `bluefs_dedicated_nvme == True`이고 `max_background_compactions >= 2`: 병렬 컴팩션으로 1.2초 스톨.
4. **하트비트 타임아웃 및 OSD 플래핑 판정**:
   - $\text{compaction\_stall\_duration\_sec} > \text{osd\_heartbeat\_grace\_sec}$:
     - `osd_down_declared = True`, `flapping_detected = True`
   - $\text{compaction\_stall\_duration\_sec} > 10.0$ 초이고 `dedicated_heartbeat_thread == False`:
     - 하트비트 스레드가 컴팩션 락에 묶여 동기 블록되므로: `osd_down_declared = True`, `flapping_detected = True`
5. **유효 지연시간 계산**:
   - $\text{effective\_latency\_ms} = \text{read\_latency\_ms} + (\text{compaction\_stall\_duration\_sec} \times 10.0)$

---

## 5. 진단 판정 (Verdict Rules)

1. `flapping_detected == True`:
   - `status`: `"FAILED"`
   - `verdict`: `"OSD_HEARTBEAT_TIMEOUT_FLAPPING_STORM"`
2. `compaction_stall_duration_sec >= 8.0`:
   - `status`: `"FAILED"`
   - `verdict`: `"ROCKSDB_BLUEFS_COMPACTION_STALL_SPIKE"`
3. `onode_cache_hit_ratio < 0.5`:
   - `status`: `"FAILED"`
   - `verdict`: `"ONODE_CACHE_EVICTION_THRASHING"`
4. $\text{effective\_latency\_ms} > \text{sla\_latency\_ms}$:
   - `status`: `"FAILED"`
   - `verdict`: `"CEPH_LATENCY_SLA_EXCEEDED"`
5. `bluefs_dedicated_nvme == True` 이고 $\text{onode\_cache\_hit\_ratio} \ge 0.8$ 이며 $\text{compaction\_stall} \le 2.0$초:
   - `status`: `"SUCCESS"`
   - `verdict`: `"OPTIMAL_BLUESTORE_TUNED_STEADY_STATE"`
6. 그 외 안정적 상태:
   - `status`: `"SUCCESS"`
   - `verdict`: `"STANDARD_BLUESTORE_ACCEPTABLE"`

---

## 6. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_BLUESTORE_TUNED_STEADY_STATE",
  "metrics": {
    "onode_cache_hit_ratio": 1.0,
    "effective_latency_ms": 12.8,
    "compaction_stall_sec": 1.2,
    "osd_down_declared": false,
    "flapping_detected": false
  }
}
```
