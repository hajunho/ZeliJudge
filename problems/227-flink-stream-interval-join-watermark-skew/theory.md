# 문제 227 이론: Apache Flink 분산 스트림 인터벌 조인(Interval Join)과 워터마크 스큐(Watermark Skew) 및 RocksDB 상태 생명주기 심층 분석

## 1. 스트림 조인의 본질적 과제와 윈도우 조인의 한계

전통적인 배치 데이터베이스(RDBMS, Data Warehouse)의 조인은 정적 테이블 전체를 메모리나 디스크에 적재한 뒤 해시 조인(Hash Join)이나 소트 머지 조인(Sort-Merge Join)을 수행합니다.
그러나 무한히 연속되는 데이터 스트림(Unbounded Stream)에서는 미래의 데이터를 무한정 기다릴 수 없으므로, 조인의 유효 범위를 제한하는 **시간적 경계(Temporal Constraint)**가 반드시 필요합니다.

```
[Windowed Join (Tumbling Window) vs Interval Join]

Tumbling Window Join (Fixed 10-Minute Buckets):
Window 0: [00:00 ~ 00:10) | Window 1: [00:10 ~ 00:20) | Window 2: [00:20 ~ 00:30)
* Order at 00:09:50 (in Window 0)
* Payment at 00:10:05 (in Window 1)
-> Window Join compares ONLY elements sharing the exact same window!
-> Result: MISSED JOIN! Even though the events are only 15 seconds apart!

Interval Join (Relative Continuous Offsets):
For each Order e_A with timestamp t_A:
Join matches any Payment e_B with timestamp t_B where:
t_A + LowerBound <= t_B <= t_A + UpperBound
(e.g., t_A - 5 min <= t_B <= t_A + 30 min)
-> Result: PERFECT MATCH! Continuous sliding relationship without artificial boundary cuts.
```

---

## 2. 인터벌 조인의 내부 동작과 RocksDB 상태 보존 원리

Flink의 `KeyedStream.intervalJoin(otherStream).between(lower, upper)`는 양방향 상태 버퍼링 메커니즘을 사용합니다:

1. **상태 버퍼링 (State Buffering)**:
   - 왼쪽 스트림 $A$(주문)에서 이벤트 $e_A(t_A)$가 도착하면, 오른쪽 스트림 $B$의 상태 버퍼를 검색하여 조인 조건을 만족하는 이벤트를 방출하고, $e_A$ 자신을 $A$의 상태 버퍼(RocksDB MapState)에 저장합니다.
   - 오른쪽 스트림 $B$(결제)에서 이벤트 $e_B(t_B)$가 도착하면, $A$의 상태 버퍼를 검색하여 매칭 후 $e_B$ 자신을 $B$의 상태 버퍼에 저장합니다.
2. **이벤트 시간 워터마크 기반 상태 정리 (Watermark-Driven State Cleanup)**:
   - $e_A$는 미래에 도착할 $e_B$와 매칭되어야 하므로, 오른쪽 스트림의 워터마크가 $t_A + \text{upper\_bound}$를 초과하기 전까지는 상태에서 삭제할 수 없습니다.
   - 연산자의 현재 워터마크 $W$가 $t_A + \text{upper\_bound}$를 넘어서는 순간, Flink의 이벤트 타임 타이머(Event Time Timer)가 격발되어 RocksDB에서 $e_A$를 안전하게 삭제(Tombstone 처리)합니다.

---

## 3. 워터마크 스큐(Watermark Skew)와 유휴 파티션(Idle Partition)의 재앙

Flink에서 다중 파티션(Kafka 토픽의 N개 파티션)이나 업스트림 병렬 태스크로부터 스트림을 소비할 때, 연산자의 출력 워터마크는 **모든 입력 채널 워터마크의 최솟값**으로 결정됩니다:

$$W_{\text{operator}} = \min(W_1, W_2, \dots, W_p)$$

```
[Watermark Stalling Mechanism]
Kafka Partition 0 (High Traffic) : Watermark = 12:00:00
Kafka Partition 1 (High Traffic) : Watermark = 11:59:50
Kafka Partition 2 (ZERO Traffic) : Watermark = 09:30:00 (FROZEN!)
-------------------------------------------------------------
Operator Combined Watermark      = min(12:00, 11:59, 09:30) = 09:30:00!
```

### 3.1 유휴 파티션이 유발하는 장애
- 파티션 2에 신규 메시지가 유입되지 않으면 파티션 2의 워터마크는 전진하지 않습니다.
- 그 결과, 연산자의 복합 워터마크가 과거 시점(09:30)에 동결됩니다.
- 상태 정리 타이머($W \ge t + \text{upper}$)가 영원히 격발되지 않습니다.
- 파티션 0과 1에서 정상 처리된 수천만 건의 이벤트가 RocksDB에 계속 쌓여 디스크 용량을 고갈시키고, 체크포인트 크기가 수백 GB로 폭증하며 최종적으로 JVM Direct Memory 및 TaskManager 프로세스가 OOM으로 사망합니다.

### 3.2 해결책: `WatermarkStrategy.withIdleness()`
Flink 1.11+에서는 유휴 채널을 감지하는 메커니즘을 제공합니다:
```java
WatermarkStrategy<OrderEvent> watermarkStrategy = WatermarkStrategy
    .<OrderEvent>forBoundedOutOfOrderness(Duration.ofSeconds(10))
    .withIdleness(Duration.ofMinutes(1)); // 1분간 이벤트가 없으면 IDLE 마킹!
```
- 지정된 시간 동안 이벤트가 발생하지 않는 채널을 `IDLE` 상태로 전환합니다.
- 복합 워터마크 계산 시 `IDLE` 채널을 일시 제외하므로, 활성 채널들의 워터마크만으로 $W$가 정상 전진하여 RocksDB 상태가 적시에 정리됩니다.
- 추후 유휴 파티션에 새 레코드가 유입되면 즉시 `ACTIVE`로 복귀하여 데이터 정합성을 유지합니다.

---

## 4. 실무 스트림 조인 운영 튜닝 체크리스트

| 항목 | 권장 설정 / 원칙 | 주의점 및 장애 패턴 |
| :--- | :--- | :--- |
| **조인 방식 선택** | 비동기 시간차 발생 시 반드시 **Interval Join** 채택 | Tumbling/Sliding Window 사용 시 경계선 분할로 대량 데이터 유실 |
| **워터마크 아이들니스** | `withIdleness(Duration.ofMinutes(1~5))` 필수 설정 | 미설정 시 유휴 가맹점/파티션 발생 순간 RocksDB OOM 유발 |
| **상태 보존(State TTL)** | Flink Interval Join 내장 타이머에 위임 (별도 TTL 비권장) | `StateTtlConfig`를 임의 적용하여 TTL이 상한선보다 짧으면 조기 삭제 |
| **RocksDB 백엔드 튜닝** | Flash SSD, 블룸 필터(Bloom Filter), 증분 체크포인트 활성화 | Key-Value 룩업 I/O 병목 완화 및 SSTable 압축 필터 최적화 |
