# [분산 스트리밍/KRaft] Apache Kafka KRaft 메타데이터 쿼럼의 Snapshot Checkpointing과 Delta Replay 및 FetchSnapshot 동기화 엔진

## 문제 설명

Apache Kafka는 2.8 버전(KIP-500)부터 10년 넘게 유지해오던 무거운 외부 합의 코디네이터인 ZooKeeper 의존성을 완전히 제거하고, 자체 이벤트 소싱(Event-Sourced) Raft 합의 엔진인 **KRaft(Kafka Raft Metadata mode)**를 도입하여 Kafka 3.x+의 공식 표준 아키텍처로 안착시켰습니다.

기존 ZooKeeper 기반 아키텍처에서는 브로커나 파티션 수가 수만 개를 넘어가면 컨트롤러가 ZK로부터 메타데이터 전체 트리를 직렬화/역직렬화하여 가져오는 데 수십 초에서 수분의 리더 장애 복구(Failover) 지연이 발생했습니다.
반면 KRaft는 클러스터의 모든 메타데이터 변경(브로커 등록, 펜싱, 토픽 생성, 파티션 리더 변경, ISR 변경 등)을 단일 내부 Raft 파티션(`@metadata` 또는 `__cluster_metadata-0`)에 **불변의 이벤트 레코드(Immutable Event Records)** 형태로 연속 기록합니다.

### 🎯 핵심 엔지니어링 과제: 로그 비대화와 스냅샷 체크포인팅
메타데이터 레코드가 무한히 누적되면 Raft 로그 세그먼트가 디스크 공간을 고갈시키고, 신규 브로커 참여 시 수백만 개의 오래된 레코드를 재생해야 하는 심각한 래그(Lag)가 발생합니다:
1. **Metadata Snapshotter**:
   - 누적된 레코드 수가 임계치(`snapshot_interval_records`)에 도달하면 활성 컨트롤러는 현재 메모리의 전체 `MetadataImage`(브로커 상태, 토픽-파티션 맵)를 단일 스냅샷 이미지 파일로 동결 덤프합니다.
2. **Dynamic Head Log Truncation**:
   - 스냅샷 생성 후 스냅샷 오프셋 미만의 오래된 메타데이터 레코드들을 디스크에서 즉시 정리(`log_start_offset = snapshot_offset`)하여 활성 로그 크기를 작게 유지합니다.
3. **FetchSnapshot 폴백 (Lagged Broker Fallback)**:
   - 브로커가 네트워크 단절이나 긴 가비지 컬렉션(GC) 일시정지 후 컨트롤러에 메타데이터를 폴링할 때, 요청한 `fetch_offset`이 이미 잘려나간 `log_start_offset`보다 과거의 오프셋인 경우:
   - 컨트롤러는 증분 레코드 대신 `FETCH_SNAPSHOT_RESPONSE`를 반환하여 브로커가 최신 스냅샷을 일괄 로드하게 한 후, 스냅샷 이후의 잔여 증분 레코드만을 빠르게 따라잡게(Catch-Up) 합니다.

카프카 분산 스트리밍 플랫폼 엔지니어가 되어, KRaft의 **이벤트 소싱 메타데이터 이미지 갱신**, **주기적 스냅샷 생성 및 로그 헤드 트렁케이션**, 그리고 **뒤처진 브로커의 FetchSnapshot 폴백 동기화**를 정밀하게 재현하는 **KRaft 메타데이터 동기화 엔진**을 구현하십시오.

---

## KRaft 메타데이터 프로토콜 규격

### 1. 메타데이터 레코드 유형
- `REGISTER_BROKER`: `{"broker_id": int, "rack": str}` $\implies$ 브로커 상태를 `"ACTIVE"`로 등록.
- `FENCE_BROKER`: `{"broker_id": int}` $\implies$ 브로커 상태를 `"FENCED"`로 변경.
- `UNFENCE_BROKER`: `{"broker_id": int}` $\implies$ 브로커 상태를 다시 `"ACTIVE"`로 변경.
- `TOPIC_RECORD`: `{"name": str, "topic_id": str}` $\implies$ 토픽 객체 생성.
- `PARTITION_RECORD`: `{"topic_id": str, "partition_id": int, "replicas": list[int], "isr": list[int], "leader": int, "leader_epoch": int}` $\implies$ 토픽의 파티션 복제본 및 리더 정보 갱신.

### 2. 스냅샷 생성 및 로그 정리 (Log Truncation)
- 메타데이터 레코드가 추가될 때마다 단조 증가 오프셋($0, 1, 2, \dots$)이 부여되며 `current_image`에 반영됩니다.
- 아직 스냅샷되지 않은 미압축 레코드 수($	ext{next\_offset} - 	ext{log\_start\_offset}$)가 설정된 `snapshot_interval_records` 이상이 되거나 명시적인 `FORCE_SNAPSHOT` 이벤트가 발생하면:
  1. 현재 오프셋 $S = 	ext{next\_offset}$에 스냅샷을 생성합니다.
  2. 스냅샷 딕셔너리(`{"snapshot_offset": S, "snapshot_epoch": E, "image": ...}`)를 저장하고 진단 코드 `METADATA_SNAPSHOT_CREATED: offset={S}, epoch={E}`를 등록합니다.
  3. $S$ 미만의 로그 레코드들을 모두 제거하고 `log_start_offset = S`로 전진시킵니다. 진단 코드 `LOG_TRUNCATED: old_start={old}, new_start={S}`를 등록합니다.

### 3. 브로커 Fetch 및 FetchSnapshot 폴백 처리
- 브로커 $B$가 `BROKER_FETCH`를 요청할 때:
  - 브로커의 현재 오프셋이 $f_{	ext{offset}}$일 때:
  - **증분 Fetch (`f_offset >= log_start_offset`)**:
    - `log`에서 `offset >= f_offset`인 증분 레코드들을 반환.
    - 브로커는 이를 로컬 이미지에 차례로 적용하고 오프셋을 `high_watermark`로 갱신.
  - **FetchSnapshot 폴백 (`f_offset < log_start_offset`)**:
    - 요청한 오프셋이 이미 잘려나갔으므로 `FETCH_SNAPSHOT_RESPONSE` 반환.
    - 진단 코드 `FETCH_SNAPSHOT_FALLBACK_TRIGGERED: broker={B}, fetch_offset={f_offset}, log_start={log_start_offset}` 등록.
    - 브로커는 로컬 이미지를 스냅샷 상태로 즉시 덮어쓰고 오프셋을 `snapshot_offset`으로 점프.
    - 만약 `snapshot_offset < high_watermark`라면 후속 증분 Fetch를 연속 수행하여 최신 오프셋까지 동기화 완료.

---

## 입력 형식

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "cluster_id": "PROD_KRAFT_CLUSTER",
    "leader_epoch": 1,
    "snapshot_interval_records": 5
  },
  "workload_events": [
    {"type": "APPEND_RECORD", "record": {"type": "REGISTER_BROKER", "data": {"broker_id": 1, "rack": "rack-1"}}},
    {"type": "APPEND_RECORD", "record": {"type": "TOPIC_RECORD", "data": {"name": "orders", "topic_id": "t-orders"}}},
    {"type": "BROKER_FETCH", "broker_id": 10}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 계산된 결과를 JSON 문자열(단일 라인)로 출력합니다:
```json
{
  "cluster_id": "PROD_KRAFT_CLUSTER",
  "active_controller_epoch": 1,
  "high_watermark": 2,
  "log_start_offset": 0,
  "active_log_records_retained": 2,
  "latest_snapshot_offset": null,
  "metrics": {
    "total_records_appended": 2,
    "snapshots_created": 0,
    "log_truncations_performed": 0,
    "fetch_snapshot_fallbacks": 0,
    "incremental_fetches": 1
  },
  "controller_metadata_summary": {
    "total_brokers": 1,
    "total_topics": 1
  },
  "controller_image": { ... },
  "broker_sync_status": {
    "10": {
      "synchronized_offset": 2,
      "brokers_count": 1,
      "topics_count": 1,
      "in_sync_with_controller": true
    }
  },
  "diagnostics": []
}
```
