# 문제 231 이론: Apache Kafka 로그 컴팩션(Log Compaction) 아키텍처와 SkimpyOffsetMap 메모리 관리 및 툼스톤(Tombstone) 수명 주기 심층 분석

## 1. Kafka 로그 보존 전략: Delete vs Compact

Apache Kafka는 토픽 단위로 두 가지 상호 배타적/결합 가능한 정리 정책(`cleanup.policy`)을 제공합니다:

```
[Kafka Cleanup Policy Comparison]

1. cleanup.policy = delete (기본값, Time/Size 기반):
Old Segments [0 ~ 100] ----(Older than 7 days)----> DELETE Entire Segment File!
(용도: 일반 이벤트 스트림, 로그 수집, 클릭스트림)

2. cleanup.policy = compact (Key 기반 스냅샷 유지):
Log: [K1:V1, Offset 0] [K2:V1, Offset 1] [K1:V2, Offset 2] [K3:V1, Offset 3]
After Compaction:
Log: [K2:V1, Offset 1] [K1:V2, Offset 2] [K3:V1, Offset 3]  (Offset 0 is purged!)
(용도: CDC 데이터베이스 변경 스트림, KTable 상태 저장소, 최신 사용자 프로필 캐시)
```

---

## 2. 로그 세그먼트의 구조와 Cleaner Thread 동작 원리

컴팩션 대상 파티션은 크게 두 영역으로 나뉩니다:
1. **클린 영역 (Clean Head)**: 이전에 이미 컴팩션이 완료되어 각 키당 1개의 최신 오프셋만 존재하는 정돈된 세그먼트들.
2. **더티 영역 (Dirty Tail)**: 신규 레코드들이 추가(Append)되어 키 중복이 누적된 미컴팩션 세그먼트들.

```
[Kafka Partition Log Layout]
+-------------------------------+-----------------------------------+-------------------+
| Clean Log (Already Compacted) | Dirty Log (To be compacted)       | Active Segment    |
| Seg 0: (K1@10, K2@12, K3@15)  | Seg 1: (K1@18, K4@20, K1@22)      | (Currently Open)  |
+-------------------------------+-----------------------------------+-------------------+
                                ^                                   ^
                                First Dirty Offset                  Log End Offset (LEO)
```

### 2.1 SkimpyOffsetMap의 메모리 메커니즘
로그 클리너(`kafka-log-cleaner-thread`)는 더티 영역의 세그먼트들을 스캔하며 각 키의 최신 오프셋을 기록하는 해시 테이블을 메모리에 구축합니다:
- **JVM 힙 오버헤드 방지**: 수천만 개의 Java 객체(`HashMap<Key, Long>`)를 힙에 생성하면 극심한 GC 일시 중지(Stop-the-World)가 발생하므로, 카프카는 **직접 오프-힙(Off-heap) 바이트 버퍼** 위에 **SkimpyOffsetMap**이라는 저수준 오픈 어드레싱 해시 테이블을 구현했습니다.
- **슬롯당 24바이트 소모**:
  - Key의 8바이트 MD5 해시
  - Value 오프셋 8바이트 (Long)
  - 슬롯 충돌 해결 및 체이닝 메타데이터 8바이트
- **OOM 크래시의 원인**: 더티 영역에 존재하는 고유 키(Unique Key) 수가 너무 많아 `unique_keys * 24B`가 `log.cleaner.dedupe.buffer.size`를 초과하면 클리너 스레드는 즉시 크래시하며 영구 중단됩니다.

---

## 3. 툼스톤(Tombstone)과 삭제 동기화의 함정

관계형 DB에서 `DELETE FROM users WHERE id = 101`이 실행되면, CDC(Debezium)는 카프카 토픽에 다음과 같은 특수 레코드를 발행합니다:
$$\text{Key: '101', Value: null}$$
이를 **툼스톤(Tombstone)**이라고 부릅니다.

```
[The Tombstone Lifecycle]
Step 1: Producer writes (Key: K1, Value: null) to log (Tombstone).
Step 2: Downstream consumers read the null value and delete K1 from their local DB/cache.
Step 3: Kafka keeps Tombstone for delete.retention.ms (e.g. 24 hours).
Step 4: Once elapsed_time >= delete.retention.ms, the cleaner thread permanently deletes K1.
```

### 3.1 툼스톤 조기 삭제 시 유령 데이터 부활 (Silent Resurrection)
만약 툼스톤이 즉시 삭제된다면:
- 지연된 컨슈머(Consumer Lag 발생)가 뒤늦게 토픽을 읽을 때, 삭제 이벤트(null)를 보지 못하고 과거의 생성/수정 이벤트만을 보게 되어 **삭제된 사용자가 컨슈머의 로컬 캐시에서 부활(Resurrection)**하는 치명적인 정합성 결함이 발생합니다.
- 따라서 `delete.retention.ms`는 반드시 가장 느린 컨슈머의 최대 허용 Lag보다 길게 설정되어야 합니다.

---

## 4. 프로덕션 운영 튜닝 가이드

| 브로커 설정 파라미터 | 권장 설정값 | 주의점 및 기대 효과 |
| :--- | :--- | :--- |
| **`log.cleaner.dedupe.buffer.size`** | 128MB ~ 512MB | 파티션당 고유 키 수에 맞추어 사이징 (`N_keys * 24B < Buffer`) |
| **`log.cleaner.threads`** | 2 ~ 4개 스레드 | 1개 스레드 장애 시 타 파티션 컴팩션 마비 방지 |
| **`min.cleanable.dirty.ratio`** | 0.5 (50%) | 너무 작으면 I/O 낭비, 너무 크면 디스크 낭비 |
| **`delete.retention.ms`** | 86400000 (24시간) | 컨슈머 최대 장애 복구 시간보다 길게 설정 |
| **`segment.ms`** | 7일 (또는 24시간) | 장기 유휴 토픽의 액티브 세그먼트 강제 롤링 및 컴팩션 유도 |
