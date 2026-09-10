# [이론 및 배경] Apache Kafka KRaft 아키텍처와 이벤트 소싱 메타데이터 스냅샷

## 1. ZooKeeper의 한계와 KIP-500 (Kafka Without ZooKeeper)의 탄생

전통적인 Apache Kafka 아키텍처(v0.8 ~ v2.7)에서 클러스터의 전역 메타데이터는 외부 분산 코디네이터인 **Apache ZooKeeper** 앙상블에 계층적 znode 트리 형태로 저장되었습니다.

### 1.1 ZooKeeper 아키텍처의 치명적 결함
1. **메타데이터 직렬화 및 동기화 병목**:
   - 파티션 수가 20만 개 이상으로 증가할 때, 액티브 컨트롤러는 ZooKeeper와 수만 개의 개별 znode Watcher를 맺어야 했습니다.
   - 컨트롤러 재선출(Failover) 시 ZooKeeper의 전체 메타데이터 트리를 동기적으로 읽어 역직렬화하는 데 수 분 이상 소요되어 클러스터가 일시 마비되었습니다.
2. **분할된 두 개의 합의 시스템 (Dual Quorum Problem)**:
   - 데이터 플레인은 Kafka ISR 복제 메커니즘을 사용하고, 컨트롤 플레인은 ZooKeeper ZAB 알고리즘을 사용하여 관리 복잡성과 장애 포인트가 이원화되었습니다.

### 1.2 KRaft의 해결책: 이벤트 소싱(Event Sourcing) 메타데이터
KRaft(KIP-500)는 ZooKeeper를 완전히 퇴출시키고, 메타데이터 자체를 **카프카 내부 Raft 파티션(`__cluster_metadata-0`)에 저장되는 불변의 이벤트 스트림**으로 전환하였습니다:
- 상태 변경은 명령형(Imperative) 업데이트가 아니라 이벤트 로그(Event Log)의 추가(`AppendRecord`)로만 이루어집니다.
- 브로커들은 컨트롤러로부터 파티션 데이터를 소비하듯 일반 카프카 `Fetch` 프로토콜을 통해 메타데이터 증분을 실시간으로 컨슘합니다.

---

## 2. In-Memory Metadata Image와 스냅샷 체크포인팅

### 2.1 MetadataImage의 구조
컨트롤러와 각 브로커 데몬은 메모리 상에 변경 불가능한(Immutable) 객체 그래프 형태의 `MetadataImage`를 유지합니다:
- `ClusterImage`: 브로커 등록 정보, 랙, 펜싱 상태
- `TopicsImage`: 토픽 UUID, 파티션별 복제본 배열(`replicas`), 동기화 복제본 집합(`isr`), 리더 브로커 ID 및 `leader_epoch`

이벤트 레코드가 도착할 때마다 자바 함수형 데이터 구조(Persistent Data Structure)처럼 기존 이미지를 바탕으로 새로운 델타 이미지를 원자적으로 생성하므로, 락(Lock) 경합 없이 수십만 개의 쿼리를 $\mathcal{O}(1)$로 고속 서빙할 수 있습니다.

### 2.2 왜 스냅샷이 필요한가?
카프카 클러스터가 수개월 동안 가동되면 수억 개의 메타데이터 이벤트(파티션 리밸런싱, 리더 변경, 토픽 생성/삭제)가 발생합니다.
스냅샷이 없다면:
1. 디스크 공간이 무한히 소모됩니다.
2. 컨트롤러 재시작 시 최초 레코드(오프셋 0)부터 모든 이벤트를 재생해야 하므로 부팅 시간이 수십 분으로 늘어납니다.
3. 신규 브로커가 조인할 때 수억 개의 오래된 이벤트를 순차 전송해야 합니다.

따라서 KRaft는 주기적으로 현재 메모리의 `MetadataImage` 전체를 바이너리 체크포인트 파일(`00000000000000000000-0000000000.checkpoint`)로 디스크에 덤프하고, 해당 오프셋 이전의 로그 헤드 세그먼트를 제거(Truncate Head)합니다.

---

## 3. 브로커 복제 프로토콜과 FetchSnapshot Fallback

브로커가 컨트롤러에 메타데이터를 요청하는 파이프라인:

```
[ Broker ]                                              [ KRaft Controller ]
    |                                                            |
    |--- Fetch(fetch_offset=100) ------------------------------->| (log_start_offset=0)
    |<-- FetchResponse([records 100~150], hw=150) ---------------| [Normal Incremental]
    |                                                            |
    | [Broker Network Partition / Long GC Pause for 2 hours]     | [Controller triggers Snapshot at 500]
    |                                                            | [Controller truncates log_start to 500]
    |                                                            |
    |--- Fetch(fetch_offset=150) ------------------------------->| (Wait! 150 < log_start_offset 500)
    |<-- FetchSnapshotResponse(snapshot_offset=500, image) ------| [Fallback to Snapshot!]
    |                                                            |
    | [Broker replaces in-memory image with Snapshot 500]        |
    |                                                            |
    |--- Fetch(fetch_offset=500) ------------------------------->| (Now in-sync with active log)
    |<-- FetchResponse([records 500~520], hw=520) ---------------| [Resume Incremental]
```

### 3.1 FetchSnapshot의 안전성 보장
1. 브로커가 요청한 오프셋이 이미 잘려나간 경우, 컨트롤러는 오류를 던지는 대신 즉시 가장 최신의 스냅샷 이미지를 전송합니다.
2. 브로커는 기존 불완전한 상태를 폐기하고 원자적으로 스냅샷 이미지로 상태를 치환합니다.
3. 스냅샷 오프셋부터 현재 High Watermark까지의 남은 소량의 증분 레코드만 추가 페치함으로써, 네트워크 단절이나 신규 노드 추가 시에도 수십 밀리초 내에 전역 클러스터 메타데이터와 완전 동기화(In-Sync)를 달성합니다.

---

## 4. 성능 및 가용성 비교 요약

| 지표 | ZooKeeper 기반 Kafka | KRaft 기반 Kafka |
|---|---|---|
| **최대 지원 파티션 수** | 약 200,000 파티션 (ZK 트리 한계) | **수백만 개 이상** (수십 배 확장) |
| **컨트롤러 Failover 소요 시간** | 수 초 ~ 수 분 (전체 트리 동기 리로드) | **수십 밀리초 ~ 1초 미만** (스냅샷 + 소량 델타 재생) |
| **외부 의존성** | 별도 JVM ZooKeeper 클러스터 3~5대 필수 | **외부 의존성 제로 (단일 바이너리)** |
| **보안 및 메타데이터 일관성** | SASL/ACL 이원화 관리 | **카프카 프로토콜 자체 ACL 및 암호화 통일** |
