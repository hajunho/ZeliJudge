# 문제 231: 분산 메시징 Kafka: 컴팩션 토픽(Log Compaction) 클리너 스레드(Cleaner Thread) OffsetMap OOM과 툼스톤(Tombstone) 누적 디스크 고갈 시뮬레이터

## 1. 개요 및 배경 (Incident Scenario)

대규모 결제 및 주문 트랜잭션을 실시간으로 처리하는 Apache Kafka 클러스터에서 데이터베이스 CDC(Change Data Capture: Debezium) 및 Kafka Streams의 KTable 상태 저장용 컴팩션 토픽(`cleanup.policy=compact`)이 무한정 비대해지며 브로커 디스크 용량이 100% 고갈(`COMPACTED_TOPIC_DISK_EXHAUSTION`)되는 심각한 인프라 장애가 발생했습니다.

컴팩션 토픽은 각 메시지 키(Key)별로 가장 최신의 오프셋(Latest Offset)만을 보존하고 이전의 중복 레코드를 삭제함으로써 한정된 디스크 공간 내에서 최신 상태 스냅샷을 영구 유지해야 합니다. 그러나 데이터 플랫폼 엔지니어링 팀은 다음과 같은 카프카 내부 메커니즘의 결함에 직면했습니다:

1. **클리너 스레드의 SkimpyOffsetMap OOM 크래시 (Cleaner Thread Crash)**:
   - Kafka의 백그라운드 로그 컴팩터(`kafka-log-cleaner-thread`)는 세그먼트의 더티(Dirty) 영역을 청소하기 위해 인메모리 해시 테이블인 **SkimpyOffsetMap**을 빌드합니다.
   - 각 고유 키마다 24바이트(MD5 해시 8B + 오프셋 8B + 슬롯 메타데이터 8B)의 메모리를 소모합니다.
   - 단시간에 수백만 개의 고유 키가 유입될 때 `dedupe_buffer_size_mb`가 16MB 등 협소하게 설정되어 있으면, 오프셋 맵이 메모리 한도를 초과하여 클리너 스레드가 조용히 비정상 종료(`LOG_CLEANER_OFFSET_MAP_OOM_CRASH`)됩니다.
   - 클리너 스레드가 죽으면 토픽의 중복 데이터가 전혀 삭제되지 않고 수 기가바이트씩 쌓이며 브로커 디스크를 완전히 고갈시킵니다.
2. **더티 비율(Dirty Ratio) 미달로 인한 청소 건너뜀 (Dirty Ratio Threshold)**:
   - 카프카는 디스크 I/O 낭비를 막기 위해 세그먼트의 더티 비율이 `min.cleanable.dirty.ratio`(기본 0.5)를 넘지 않으면 컴팩션을 의도적으로 건너뜁니다(`CLEANER_DIRTY_RATIO_BELOW_THRESHOLD_SKIPPED`).
3. **툼스톤(Tombstone) 누적과 보존 기한 미도래 (Tombstone Retention Bloat)**:
   - 레코드 삭제를 나타내는 페이로드 없는 메시지(`Key: id, Value: null`)인 툼스톤은 다운스트림 컨슈머들이 삭제 사실을 인지할 수 있도록 `delete.retention.ms`(기본 24시간) 동안 의무적으로 디스크에 유지되어야 합니다. 대량 삭제가 발생했을 때 이 보존 기한이 지나기 전까지는 툼스톤이 제거되지 않아 일시적으로 디스크 팽창 경고(`TOMBSTONE_RETENTION_UNEXPIRED_BLOAT`)가 발생합니다.

본 문제에서는 Kafka 컴팩션 설정(`dedupe_buffer_size_mb`, `min_cleanable_dirty_ratio`, `delete_retention_ms`, `cleaner_threads`) 및 워크로드(메시지 수, 고유 키 수, 툼스톤 비율)에 따른 디스크 점유율, 오프셋 맵 메모리 요구량, 압축률을 시뮬레이션하고 클리너의 안정성을 진단하는 프로그램을 구현합니다.

---

## 2. 아키텍처 및 로그 컴팩션 흐름

```
[Kafka Log Compaction Segment Architecture]
Log Partition: [Segment 0 (Clean)] [Segment 1 (Clean)] [Segment 2 (Dirty)] [Segment 3 (Active)]
                                                        ^
                                                        | Log Cleaner processes Dirty segments
+-------------------------------------------------------v-----------------------+
| Kafka Log Cleaner Thread                                                      |
|   1. Build In-Memory SkimpyOffsetMap:                                         |
|      Key "K1" -> Offset 102                                                   |
|      Key "K2" -> Offset 105 (Latest)                                          |
|      (Requires: Unique_Keys * 24 Bytes in dedupe_buffer_size_mb)                |
|   2. If needed_memory > dedupe_buffer_size: CRASH! (OOM Thread Death)         |
|   3. Write Cleaned Segment: Keep only highest offset per key                  |
|   4. Tombstone Check: If Value == null:                                       |
|      - Elapsed >= delete_retention_ms -> DELETE Tombstone (GC)                |
|      - Elapsed < delete_retention_ms  -> KEEP Tombstone (Downstream safety)   |
+-------------------------------------------------------------------------------+
```

---

## 3. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "dedupe_buffer_size_mb": 128.0,
    "min_cleanable_dirty_ratio": 0.5,
    "delete_retention_ms": 86400000,
    "max_disk_capacity_mb": 10000.0,
    "cleaner_threads": 2
  },
  "workload": {
    "total_messages": 3000000,
    "unique_keys_count": 500000,
    "avg_message_size_bytes": 500,
    "tombstone_ratio": 0.1,
    "elapsed_time_since_delete_ms": 7200000
  }
}
```

- `config`:
  - `dedupe_buffer_size_mb`: 클리너 스레드가 오프셋 맵 구축에 사용할 최대 메모리 크기 (MB, 기본 128.0)
  - `min_cleanable_dirty_ratio`: 컴팩션이 시작되기 위한 최소 더티 비율 (기본 0.5)
  - `delete_retention_ms`: 툼스톤 메시지가 디스크에서 완전히 삭제(GC)되기 전까지 보존되는 시간 (ms, 기본 86400000 = 24시간)
  - `max_disk_capacity_mb`: 파티션에 할당된 최대 허용 디스크 용량 (MB)
  - `cleaner_threads`: 활성화된 로그 클리너 스레드 수 (0이면 비활성화)
- `workload`:
  - `total_messages`: 유입된 전체 레코드 수
  - `unique_keys_count`: 고유 메시지 키 수
  - `avg_message_size_bytes`: 평균 메시지 바이트 크기 (기본 500바이트)
  - `tombstone_ratio`: 삭제(null 페이로드) 레코드 비율 (0.0 ~ 1.0)
  - `elapsed_time_since_delete_ms`: 삭제 이벤트 발생 후 경과 시간 (ms)

---

## 4. 연산 및 시뮬레이션 공식

1. **원시 데이터 용량 및 오프셋 맵 메모리 요구량**:
   - $\text{raw\_volume\_mb} = (\text{total\_messages} \times \text{avg\_message\_size\_bytes}) / (1024 \times 1024)$
   - SkimpyOffsetMap은 고유 키 1개당 24바이트(해시 8B + 오프셋 8B + 슬롯 8B) 소모:
     $$\text{needed\_offset\_map\_mb} = \frac{\text{unique\_keys\_count} \times 24}{1024 \times 1024}$$
2. **더티 비율(Dirty Ratio) 계산**:
   - 중복 데이터 비율 추정:
     $$\text{dirty\_ratio} = \frac{\text{raw\_volume\_mb} - \frac{\text{unique\_keys\_count} \times \text{avg\_size}}{1024^2}}{\max(1.0, \text{raw\_volume\_mb})}$$
     (범위 제한: $[0.1, 1.0]$)
3. **컴팩션 실행 및 툼스톤 GC 로직**:
   - `cleaner_threads <= 0`: 컴팩터 비활성화로 청소 건너뜀 (`cleaner_skipped = True`), $\text{final\_disk} = \text{raw\_volume}$
   - `dirty_ratio < min_cleanable_dirty_ratio`: 더티 임계치 미달로 청소 건너뜀 (`cleaner_skipped = True`), $\text{final\_disk} = \text{raw\_volume}$
   - $\text{needed\_offset\_map\_mb} > \text{dedupe\_buffer\_size\_mb}$:
     - 오프셋 맵 메모리 초과로 클리너 스레드 OOM 크래시 (`cleaner_oom = True`), 컴팩션 실패로 $\text{final\_disk} = \text{raw\_volume}$
   - 정상 컴팩션 실행 시:
     - $\text{tombstones\_count} = \lfloor \text{unique\_keys\_count} \times \text{tombstone\_ratio} \rfloor$
     - $\text{active\_keys\_count} = \text{unique\_keys\_count} - \text{tombstones\_count}$
     - $\text{elapsed\_time\_since\_delete\_ms} \ge \text{delete\_retention\_ms}$:
       - 툼스톤 안전 만료(GC): $\text{surviving\_records} = \text{active\_keys\_count}$
     - $\text{elapsed\_time\_since\_delete\_ms} < \text{delete\_retention\_ms}$:
       - 툼스톤 유지 필요: $\text{surviving\_records} = \text{active\_keys\_count} + \text{tombstones\_count}$
       - `tombstone_ratio >= 0.3` 이면 `tombstone_leak = True` (임시 팽창)
     - $\text{final\_disk\_usage\_mb} = (\text{surviving\_records} \times \text{avg\_message\_size\_bytes}) / (1024 \times 1024)$
4. **디스크 고갈 및 압축률 판정**:
   - $\text{final\_disk\_usage\_mb} > \text{max\_disk\_capacity\_mb}$ 이면 $\text{disk\_exhausted} = \text{True}$
   - $\text{compaction\_ratio} = \max(0.0, 1.0 - (\text{final\_disk\_usage\_mb} / \text{raw\_volume\_mb}))$

---

## 5. 진단 판정 (Verdict Rules)

1. `cleaner_oom == True`:
   - `status`: `"FAILED"`
   - `verdict`: `"LOG_CLEANER_OFFSET_MAP_OOM_CRASH"`
2. `disk_exhausted == True`:
   - `status`: `"FAILED"`
   - `verdict`: `"COMPACTED_TOPIC_DISK_EXHAUSTION"`
3. `cleaner_skipped == True` 이고 `cleaner_threads <= 0`:
   - `status`: `"FAILED"`
   - `verdict`: `"LOG_CLEANER_DISABLED_GROWTH_RISK"`
4. `cleaner_skipped == True` 이고 `dirty_ratio < min_cleanable_dirty_ratio`:
   - `status`: `"SUCCESS"`
   - `verdict`: `"CLEANER_DIRTY_RATIO_BELOW_THRESHOLD_SKIPPED"`
5. `tombstone_leak == True`:
   - `status`: `"WARNING"`
   - `verdict`: `"TOMBSTONE_RETENTION_UNEXPIRED_BLOAT"`
6. $\text{compaction\_ratio} \ge 0.4$:
   - `status`: `"SUCCESS"`
   - `verdict`: `"OPTIMAL_KAFKA_LOG_COMPACTION_STEADY_STATE"`
7. 그 외 정상 컴팩션 완료:
   - `status`: `"SUCCESS"`
   - `verdict`: `"STANDARD_LOG_CLEANING_COMPLETE"`

---

## 6. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_KAFKA_LOG_COMPACTION_STEADY_STATE",
  "metrics": {
    "raw_volume_mb": 1430.51,
    "final_disk_usage_mb": 214.58,
    "compaction_ratio": 0.85,
    "needed_offset_map_mb": 11.44,
    "dedupe_buffer_size_mb": 128.0,
    "dirty_ratio": 0.8333,
    "cleaner_oom": false,
    "disk_exhausted": false
  }
}
```
