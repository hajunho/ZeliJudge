# 문제 239: 분산 메시징 아키텍처: Kafka 모놀리식 파티션 vs Pulsar/BookKeeper 세그먼트 스토리지(Ledger Ensemble)와 좀비 브로커 펜싱(Fencing)

## 1. 개요 및 배경 (Incident Scenario)

초당 수십만 건의 금융 이벤트와 주문 로그를 실시간 처리하는 엔터프라이즈 데이터 플랫폼에서 브로커 증설 및 노드 장애 복구와 관련하여 두 분산 메시징 엔진(Apache Kafka vs Apache Pulsar) 간의 구조적 차이로 인한 대형 장애가 발생했습니다.

### 1. Kafka의 모놀리식 파티션 복제 한계 (Monolithic Partition Copying)
Kafka 클러스터에 신규 브로커를 투입하고 파티션 리밸런싱(`kafka-reassign-partitions.sh`)을 실행하자, **500GB 크기의 단일 파티션 파일 전체를 네트워크로 복사**하는 작업이 시작되었습니다.
- 10Gbps 네트워크 대역폭이 100% 포화되면서 인터-브로커 통신이 마비되었고, 정상적인 프로듀서의 P99 발행 지연시간이 280ms 이상으로 폭증하며 400초(약 7분) 동안 클러스터가 극심한 병목(`KAFKA_MONOLITHIC_PARTITION_REBALANCE_STALL`)에 빠졌습니다.

### 2. Pulsar의 세그먼트 기반 스토리지(Apache BookKeeper)의 혁신과 함정
반면 Apache Pulsar는 **컴퓨팅(Stateless Broker)과 스토리지(Stateful BookKeeper)를 완전히 분리**한 2계층 아키텍처를 채택했습니다. 파티션은 거대한 단일 파일이 아니라 수백 MB 단위의 **원장(Ledger / Segment)**으로 잘게 쪼개져 분산 저장됩니다:

```
[Kafka Monolithic Partition vs Pulsar/BookKeeper Segment Architecture]

Kafka Monolithic Architecture:
Broker 1 (Local Disk): [ Topic A - Partition 0: 500GB Single Continuous Log File ]
                       │
                       │ (Rebalance: MUST COPY 500GB over 10Gbps network! 400s Stall)
                       v
Broker 2 (Local Disk): [ Copying 500GB... Network Saturated, P99 Latency 285ms ]

Pulsar / BookKeeper Decoupled Architecture:
Stateless Broker: [ Ownership Metadata: Partition 0 -> Broker 2 (12ms ZK metadata update) ]
                  (Zero Data Movement! 0GB Network Copied!)
Storage Tier (Bookies):
[ Bookie 1 ] [ Bookie 2 ] [ Bookie 3 ] [ Bookie 4 ] [ Bookie 5 ]
  Ledger 1     Ledger 1     Ledger 1     Ledger 2     Ledger 2   (Ensemble E=5, Qw=3, Qa=2)
```

그러나 Pulsar/BookKeeper 도입 후 다음과 같은 실무 운영 장애가 발생했습니다:
1. **저장장치 분리 미흡으로 인한 fsync 스파이크 (`BOOKKEEPER_JOURNAL_SHARED_DISK_LATENCY_SPIKE`)**:
   - BookKeeper는 초저지연 쓰기 확인을 위한 **Journal (순차 쓰기 + fsync)**과 압축/인덱싱을 위한 **EntryLog (배치 버퍼링 쓰기)**의 두 가지 디스크 I/O 경로를 갖습니다.
   - 단일 물리 디스크에 Journal과 EntryLog를 함께 배치하면 백그라운드 컴팩션 플러시가 Journal의 `fsync`를 방해하여 P99 쓰기 지연시간이 270ms 이상으로 튀어 오릅니다.
2. **좀비 브로커와 원장 펜싱 부재 (`ZOMBIE_BROKER_SPLIT_BRAIN_APPEND_CORRUPTION`)**:
   - Broker 1이 긴 GC 일시정지로 ZooKeeper 락을 잃고 Broker 2가 파티션 소유권을 인계받았을 때, 잠에서 깬 Broker 1(좀비 브로커)이 자신이 여전히 소유자라고 착각하고 쓰기를 시도했습니다.
   - 신규 브로커가 이전 원장을 **펜싱(Ledger Fencing, `LedgerRecoveryOp`)**하지 않았다면, 좀비 브로커의 쓰기가 승인되어 원장의 마지막 확인 오프셋(LAC, Last Add Confirmed)이 꼬이고 데이터가 비가역적으로 오염됩니다.
3. **최적 운영 (`OPTIMAL_PULSAR_SEGMENT_BOOKKEEPER_STORAGE`)**:
   - NVMe Journal 분리, Bookie 장애 시 신규 원장 자동 개설(`ensemble_switches = 1`), 원장 펜싱 활성화, 0바이트 무복사 12ms 초고속 브로커 페일오버 달성.

본 문제에서는 메시징 시스템 구조(Kafka vs Pulsar), BookKeeper 앙상블 쿼럼, Journal 분리 여부 및 원장 펜싱에 따른 리밸런싱 소요 시간, 쓰기 지연시간, 스플릿 브레인 오염 여부를 시뮬레이션합니다.

---

## 2. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "messaging_system": "PULSAR_BOOKKEEPER",
    "ensemble_size": 5,
    "write_quorum": 3,
    "ack_quorum": 2,
    "ledger_fencing_enabled": true,
    "journal_storage_separated": true,
    "broker_rebalance_requested": true,
    "partition_size_gb": 500.0,
    "network_bandwidth_gbps": 10.0
  },
  "workload": {
    "write_requests_per_sec": 50000,
    "entry_size_bytes": 1024,
    "failed_bookie_id": 2,
    "zombie_broker_resurrection": true
  }
}
```

### 필드 설명
- `config`:
  - `messaging_system` (str): `"PULSAR_BOOKKEEPER"`, `"KAFKA_MONOLITHIC"`
  - `ensemble_size` (int): 원장 저장에 할당된 Bookie 풀 크기 ($E$)
  - `write_quorum` (int): 각 엔트리가 복제되는 Bookie 수 ($Qw$)
  - `ack_quorum` (int): 쓰기 완료 응답에 필요한 최소 ACK 수 ($Qa$)
  - `ledger_fencing_enabled` (bool): 신규 브로커 선출 시 이전 원장 펜싱 활성화 여부
  - `journal_storage_separated` (bool): BookKeeper Journal 전용 NVMe 디스크 분리 여부
  - `broker_rebalance_requested` (bool): 브로커 간 파티션 재배치 트리거 여부
  - `partition_size_gb` (float): 파티션 총 데이터 크기 (GB)
  - `network_bandwidth_gbps` (float): 노드 간 네트워크 대역폭 (Gbps)
- `workload`:
  - `write_requests_per_sec` (int): 초당 쓰기 요청 수
  - `entry_size_bytes` (int): 메시지 엔트리 평균 크기 (Bytes)
  - `failed_bookie_id` (int): 시뮬레이션 중 고장난 Bookie 번호 (-1이면 정상)
  - `zombie_broker_resurrection` (bool): 구 브로커가 깨어나 쓰기를 시도하는 좀비 브로커 발생 여부

---

## 3. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 JSON 구조를 반환해야 합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_PULSAR_SEGMENT_BOOKKEEPER_STORAGE",
  "metrics": {
    "data_copied_gb": 0.0,
    "rebalance_duration_sec": 0.012,
    "p99_write_latency_ms": 2.8,
    "ledger_fenced_success": true,
    "split_brain_corrupted": false,
    "ensemble_switches": 1
  }
}
```

### 판정(Verdict) 및 상태(Status) 규칙
1. **`messaging_system == "KAFKA_MONOLITHIC"`**:
   - `broker_rebalance_requested == true`:
     - 500GB 전체 파티션 네트워크 복사 발생 (`rebalance_duration_sec = (partition_size_gb * 8.0) / net_bw_gbps`)
     - `status`: `"FAILED"`, `verdict`: `"KAFKA_MONOLITHIC_PARTITION_REBALANCE_STALL"`, `p99_write_latency_ms`: 285.0
   - 재배치가 없는 정상 상태:
     - `status`: `"SUCCESS"`, `verdict`: `"KAFKA_MONOLITHIC_PARTITION_STEADY_STATE"`, `p99_write_latency_ms`: 3.8
2. **`messaging_system == "PULSAR_BOOKKEEPER"`**:
   - `journal_storage_separated == false`:
     - Journal과 EntryLog 디스크 경합으로 P99 지연 폭증
     - `status`: `"FAILED"`, `verdict`: `"BOOKKEEPER_JOURNAL_SHARED_DISK_LATENCY_SPIKE"`, `p99_write_latency_ms`: 275.0
   - `zombie_broker_resurrection == true`이고 `ledger_fencing_enabled == false`:
     - 펜싱 실패로 좀비 브로커의 불법 쓰기 승인, 스플릿 브레인 데이터 오염
     - `status`: `"FAILED"`, `verdict`: `"ZOMBIE_BROKER_SPLIT_BRAIN_APPEND_CORRUPTION"`, `split_brain_corrupted`: `true`
   - 정상 구성:
     - 데이터 복사 0.0GB, 12ms 메타데이터 전이, 좀비 브로커 차단, P99 지연 2.8ms
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_PULSAR_SEGMENT_BOOKKEEPER_STORAGE"`

---

## 4. 예제 입출력

### 예제 1 (입력)
```json
{
  "config": {
    "messaging_system": "PULSAR_BOOKKEEPER",
    "ensemble_size": 5,
    "write_quorum": 3,
    "ack_quorum": 2,
    "ledger_fencing_enabled": true,
    "journal_storage_separated": true,
    "broker_rebalance_requested": true,
    "partition_size_gb": 500.0,
    "network_bandwidth_gbps": 10.0
  },
  "workload": {
    "write_requests_per_sec": 50000,
    "entry_size_bytes": 1024,
    "failed_bookie_id": 2,
    "zombie_broker_resurrection": true
  }
}
```

### 예제 1 (출력)
```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_PULSAR_SEGMENT_BOOKKEEPER_STORAGE",
  "metrics": {
    "data_copied_gb": 0.0,
    "rebalance_duration_sec": 0.012,
    "p99_write_latency_ms": 2.8,
    "ledger_fenced_success": true,
    "split_brain_corrupted": false,
    "ensemble_switches": 1
  }
}
```
