# 문제 235: 분산 스토리지 Ceph/ZFS 침묵의 데이터 부패(Bit-Rot)와 딥 스크러빙(Deep Scrub) CRC32c 무결성 검증 vs 백그라운드 I/O 쓰로틀링

## 1. 개요 및 배경 (Incident Scenario)

수 페타바이트(PB) 규모의 데이터레이크와 오브젝트 스토리지를 운영하는 금융 인프라 클러스터에서 아무런 디스크 하드웨어 에러(I/O Error)가 발생하지 않았음에도 불구하고, 수개월 전 아카이빙된 거래 명세서와 고객 계약서 PDF 파일의 내용이 손상되는 치명적인 **침묵의 데이터 부패(Silent Bit-Rot / Data Corruption)** 사고가 발생했습니다.

하드웨어 제조사의 자체 SMART 진단이나 일반적인 운영체제 파일시스템(ext4, XFS)은 디스크 컨트롤러가 `EIO`를 리턴하지 않는 한 읽어온 비트가 물리적으로 변조되었는지 검증할 방법이 없습니다. 우주선(Cosmic Rays)에 의한 비트 플립, 자기 디스크 표면의 자성 감쇄, NAND 플래시의 플로팅 게이트 전하 누설, 드라이브 펌웨어의 조용한 쓰기 누락 등으로 인해 디스크에 기록된 비트가 서서히 오염되는 현상을 **비트 부패(Bit-Rot)**라고 부릅니다.

이러한 침묵의 부패를 조기에 박멸하기 위해 분산 스토리지 엔진(Ceph BlueStore, ZFS, MinIO)은 주기적으로 전체 데이터의 비트를 전수 검사하는 **딥 스크러빙(Deep Scrubbing)**을 수행합니다.

```
[Ceph Placement Group (PG) Deep Scrub & Auto-Repair Architecture]

Primary OSD (PG 1.0)               Secondary OSD 1 (PG 1.0)           Secondary OSD 2 (PG 1.0)
+------------------------+         +------------------------+         +------------------------+
| Object A (4MB Payload) |         | Object A (4MB Payload) |         | Object A (4MB Payload) |
| Read & Compute CRC32c  |         | Read & Compute CRC32c  |         | Read & Compute CRC32c  |
| CRC: 0x9A4F (CORRUPTED)|         | CRC: 0x3E12 (HEALTHY)  |         | CRC: 0x3E12 (HEALTHY)  |
+-----------+------------+         +-----------+------------+         +-----------+------------+
            |                                  |                                  |
            v                                  v                                  v
+----------------------------------------------------------------------------------------------+
| Deep Scrub Master: Compare CRC across all 3 Replicas                                         |
| -> Primary CRC Mismatch Detected! (Bit-Rot identified)                                       |
| -> Automatic Repair: Stream intact 4MB block from Secondary 1 to overwrite Primary OSD!      |
+----------------------------------------------------------------------------------------------+
```

그러나 딥 스크러빙은 스토리지의 모든 오브젝트 페이로드를 디스크에서 100% 다시 읽어 들이므로 막대한 디스크 대역폭과 CPU 연산을 소모합니다. 엔지니어링 팀은 운영 중 다음과 같은 문제에 직면했습니다:

1. **딥 스크러빙 미수행 시 침묵의 부패 방치 (`SILENT_BIT_ROT_UNDETECTED_DATA_CORRUPTION`)**:
   - 딥 스크러빙을 끄거나 감사 주기만 연장할 경우 손상된 데이터가 고객에게 그대로 서빙되어 데이터 정합성이 영구 파괴됩니다.
2. **주간 피크 타임 I/O 포화와 SLA 붕괴 (`SCRUBBING_IO_PEAK_SATURATION_SLA_VIOLATION`)**:
   - 주간 업무 피크 시간에 시간 제한(`scrub_time_window_enabled`) 없이 무제한 I/O 우선순위(`REALTIME`)로 딥 스크러빙이 실행되면 디스크 대역폭이 100% 포화되어 고객 서비스의 P99 지연시간이 SLA(50ms)를 초과해 150ms 이상으로 치솟습니다.
3. **가용 복제본 부재로 인한 영구 유실 (`BIT_ROT_DETECTED_PERMANENT_DATA_LOSS`)**:
   - 프라이머리 OSD에서 비트 부패가 발견되었으나 세컨더리 복제본이 모두 다운되었거나 이미 손상된 경우 복구할 원본이 없어 영구 결손이 발생합니다.
4. **최적화된 쓰로틀링과 자동 복구 (`OPTIMAL_THROTTLED_DEEP_SCRUB_AUTO_REPAIRED`)**:
   - 심야 오프피크 시간대(23시~06시) 제한, 청크 간 슬립 주기(`scrub_sleep_sec`), 리눅스 I/O 우선순위(`ionice -c 3 IDLE`) 적용을 통해 고객 지연시간을 11ms 이하로 유지하면서 100% 비트 부패를 감지하고 자동 복구(Auto-Repair)합니다.

---

## 2. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "deep_scrub_enabled": true,
    "scrub_time_window_enabled": true,
    "current_cluster_hour": 2,
    "scrub_sleep_sec": 0.1,
    "io_priority_class": "IDLE",
    "disk_max_bandwidth_mb": 250.0,
    "client_sla_latency_ms": 50.0
  },
  "cluster_state": {
    "total_objects_scanned": 100000,
    "object_size_kb": 4096,
    "client_traffic_load": "OFF_PEAK",
    "primary_replica_crc_mismatches": 2,
    "secondary_healthy_replicas": 2
  }
}
```

### 필드 설명
- `config`:
  - `deep_scrub_enabled` (bool): 딥 스크러빙 활성화 여부
  - `scrub_time_window_enabled` (bool): 오프피크 시간대(23:00~06:00)에만 스크러빙을 제한하는 윈도우 활성화 여부
  - `current_cluster_hour` (int): 현재 클러스터 로컬 시각 (0~23)
  - `scrub_sleep_sec` (float): 오브젝트 청크 스크러빙 간 슬립 시간 (초)
  - `io_priority_class` (str): 스크러빙 I/O 스케줄링 우선순위 (`"IDLE"`, `"BEST_EFFORT"`, `"REALTIME"`)
  - `disk_max_bandwidth_mb` (float): 물리 디스크의 최대 순차 읽기 대역폭 (MB/s)
  - `client_sla_latency_ms` (float): 클라이언트 요청 응답 보장 SLA 한도 (ms)
- `cluster_state`:
  - `total_objects_scanned` (int): 스캔 대상 전체 오브젝트 수
  - `object_size_kb` (int): 오브젝트당 평균 크기 (KB, 기본 4096)
  - `client_traffic_load` (str): 클라이언트 실시간 트래픽 수준 (`"PEAK"`, `"OFF_PEAK"`)
  - `primary_replica_crc_mismatches` (int): CRC32c 체크섬 불일치로 감지된 손상 오브젝트 수
  - `secondary_healthy_replicas` (int): 복구에 사용 가능한 정상 상태 세컨더리 복제본 수

---

## 3. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 JSON 구조를 반환해야 합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_THROTTLED_DEEP_SCRUB_AUTO_REPAIRED",
  "metrics": {
    "corrupted_objects_detected": 2,
    "objects_repaired": 2,
    "scrub_disk_bandwidth_mb": 50.0,
    "client_p99_latency_ms": 11.0,
    "sla_violated": false
  }
}
```

### 판정(Verdict) 및 상태(Status) 규칙
1. **`deep_scrub_enabled == false`**:
   - `primary_replica_crc_mismatches > 0`: 비트 부패를 감지하지 못하고 방치
     - `status`: `"FAILED"`, `verdict`: `"SILENT_BIT_ROT_UNDETECTED_DATA_CORRUPTION"`
   - 손상 데이터가 없는 경우:
     - `status`: `"WARNING"`, `verdict`: `"DEEP_SCRUB_DISABLED_AUDIT_RISK"`
2. **피크 타임 I/O 포화 및 SLA 위반**:
   - 피크 타임에 시간 윈도우 없이 고대역폭 스크러빙 실행으로 `client_p99_latency_ms > client_sla_latency_ms`:
     - `status`: `"FAILED"`, `verdict`: `"SCRUBBING_IO_PEAK_SATURATION_SLA_VIOLATION"`, `sla_violated`: `true`
   - SLA는 넘지 않았으나 피크 타임에 우선순위 설정 미흡으로 지연시간 악화:
     - `status`: `"WARNING"`, `verdict`: `"SCRUBBING_IO_BURST_CLIENT_LATENCY_DEGRADATION"`, `sla_violated`: `false`
3. **비트 부패 감지 및 자동 복구**:
   - `primary_replica_crc_mismatches > 0`일 때:
     - `secondary_healthy_replicas == 0`: 복구할 건강한 복제본이 없어 영구 결손 발생
       - `status`: `"FAILED"`, `verdict`: `"BIT_ROT_DETECTED_PERMANENT_DATA_LOSS"`
     - 정상 복제본이 존재하여 자동 복구 완료:
       - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_THROTTLED_DEEP_SCRUB_AUTO_REPAIRED"`
   - 손상 데이터가 전혀 없는 청정 상태:
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_THROTTLED_DEEP_SCRUB_CLEAN"`

---

## 4. 예제 입출력

### 예제 1 (입력)
```json
{
  "config": {
    "deep_scrub_enabled": true,
    "scrub_time_window_enabled": true,
    "current_cluster_hour": 2,
    "scrub_sleep_sec": 0.1,
    "io_priority_class": "IDLE",
    "disk_max_bandwidth_mb": 250.0,
    "client_sla_latency_ms": 50.0
  },
  "cluster_state": {
    "total_objects_scanned": 100000,
    "object_size_kb": 4096,
    "client_traffic_load": "OFF_PEAK",
    "primary_replica_crc_mismatches": 2,
    "secondary_healthy_replicas": 2
  }
}
```

### 예제 1 (출력)
```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_THROTTLED_DEEP_SCRUB_AUTO_REPAIRED",
  "metrics": {
    "corrupted_objects_detected": 2,
    "objects_repaired": 2,
    "scrub_disk_bandwidth_mb": 50.0,
    "client_p99_latency_ms": 11.0,
    "sla_violated": false
  }
}
```
