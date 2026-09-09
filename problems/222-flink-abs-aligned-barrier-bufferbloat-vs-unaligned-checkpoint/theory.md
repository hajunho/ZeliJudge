# 문제 222 이론: 분산 스트림 처리(Distributed Stream Processing) Asynchronous Barrier Snapshotting(ABS), 비정렬 체크포인트와 Kafka 2PC 트랜잭션

---

## 1. 스트림 처리에서 정확히 한 번(Exactly-Once)의 본질

실시간 데이터 스트리밍 시스템에서 장애 발생 시 데이터가 유실되거나 중복 처리되는 것은 금융 원장 및 빌링 시스템에서 치명적인 재앙을 초래합니다.

### 1.1 스트리밍 보장 수준
- **최대 한 번(At-Most-Once)**: 장애 발생 시 레코드를 드롭합니다. 유실 발생 가능.
- **최소 한 번(At-Least-Once)**: 장애 발생 시 오프셋을 되감아 재처리합니다. 중복(Duplicate) 발생.
- **정확히 한 번(Exactly-Once, EOS)**: 장애 복구 후에도 각 레코드가 상태(State)에 단 한 번만 반영된 것과 동일한 결과를 보장합니다.

### 1.2 Chandy-Lamport 알고리즘과 Flink ABS
1985년 Chandy와 Lamport가 제안한 분산 스냅샷 알고리즘은 전체 시스템을 멈추지 않고 분산 프로세스와 통신 채널의 전역 일관성 컷(Consistent Cut)을 기록합니다.
Apache Flink는 이를 DAG(Directed Acyclic Graph) 스트림 파이프라인에 최적화한 **비동기 배리어 스냅샷(Asynchronous Barrier Snapshotting, ABS, Carsten Binnig et al., VLDB 2015)**을 구현했습니다.

---

## 2. 정렬 체크포인트(Aligned Checkpoints)와 백프레셔의 악순환

```
 [The Aligned Checkpoint Deadlock Cycle]

     Hot Key Data Skew / GC Pause on Channel 3
                       │
                       ▼
         Barrier Arrival Delayed on Channel 3
                       │
                       ▼
       Channels 0, 1, 2 must PAUSE and BUFFER
                       │
                       ▼
       Input Buffers Exhausted (256MB Limit Reached)
                       │
                       ▼
    Backpressure Propagates UPSTREAM to Sources
                       │
                       ▼
  Next Barrier Injection DELAYED (Vicious Feedback Loop!)
```

### 2.1 배리어 정렬(Barrier Alignment)의 필요성
다중 입력 채널을 가진 연산자에서 채널 0번에 배리어 $B_n$이 먼저 도착했을 때, 채널 0번의 후속 레코드를 계속 처리하면 **체크포인트 $n$의 상태에 $B_n$ 이후의 데이터가 반영**됩니다.
그러나 채널 3번은 아직 $B_n$ 이전의 레코드를 보내고 있으므로, 이 상태에서 스냅샷을 찍으면 인과성 불일치(Causal Inconsistency)가 발생합니다.
따라서 Aligned Checkpoint 모드에서는 모든 입력 채널에서 $B_n$이 도착할 때까지 이미 도착한 채널들의 처리를 일시 정지하고 메모리에 버퍼링해야 합니다.

### 2.2 버퍼블로트(Bufferbloat)와 장애 발생 메커니즘
스트래글러가 발생하여 정렬 시간이 수십 초로 늘어나면:
- 빠른 채널들이 초당 수십 MB씩 유입되는 데이터를 메모리에 쌓아둡니다: $\text{Buffered} = \sum \text{Rate} \times \Delta t$
- 인풋 버퍼 풀이 고갈되면 네트워크 소켓 수신 윈도우가 닫히고, 업스트림 노드로 TCP 제로 윈도우 및 크레딧 고갈 백프레셔가 역류합니다.
- 체크포인트 완료 시간이 30초~60초 이상으로 폭증합니다.

---

## 3. Two-Phase Commit (2PC) Sink와 Kafka 트랜잭션 타임아웃

Flink 파이프라인 내부 상태가 Exactly-Once로 보존되더라도, 외부 스토리지(Kafka, MySQL)로의 출력 역시 Exactly-Once여야 종단간(End-to-End) EOS가 성립합니다.

### 3.1 Flink 2PC Sink 생명주기
1. **트랜잭션 시작**: 각 체크포인트 구간마다 Kafka Transactional Producer를 통해 새 트랜잭션 $T_n$을 개시합니다.
2. **Pre-commit**: 배리어 $B_n$이 싱크 연산자에 도달하면, 싱크는 $T_n$을 플러시하고 `producer.flush()` 후 Pre-commit 상태로 전환합니다.
3. **Commit**: JobManager가 모든 연산자로부터 스냅샷 성공 보고를 받고 체크포인트 $n$ 완료를 선언하면, 싱크에 RPC를 보내 $T_n$을 정식 커밋(`producer.commitTransaction()`)합니다.

### 3.2 타임아웃 붕괴 (Producer Fencing)
- Kafka 브로커는 트랜잭션 좀비 방지를 위해 `transaction.timeout.ms` (기본 60초) 타이머를 둡니다.
- 배리어 정렬 지연으로 체크포인트 총 완료 시간이 60초를 초과하면, 브로커 트랜잭션 코디네이터가 해당 트랜잭션을 강제로 폐기(`ABORT`)합니다.
- JobManager의 완료 신호를 받은 Flink 싱크가 커밋을 시도하면 `ProducerFencedException` 에러가 터지며 전체 Flink 잡이 다운됩니다.

---

## 4. 비정렬 체크포인트(Unaligned Checkpoints) 혁신

Flink 1.11에서 도입되고 1.13에서 프로덕션 안정화된 **Unaligned Checkpoints (UC)**는 배리어 정렬을 근본적으로 제거합니다.

```
 [Unaligned Checkpoints Overtaking Mechanism]

  In-flight Network Channel:
  [Record C]  [Record B]  [Record A]  <=== [Barrier Bn Injected]
                                                  │
  Priority Event Processing:                      ▼
  * Barrier Bn JUMPS to front of queue: [Barrier Bn] [Record C] [Record B] [Record A]
  * Arrives at Operator IMMEDIATELY! Alignment Wait = 0ms!
  * Records A, B, C in the wire are saved as 'Channel State' in Checkpoint storage!
```

1. **배리어 우선 추월(Priority Event Overtaking)**: 배리어는 데이터 버퍼 뒤에서 줄 서지 않고 최우선 이벤트로 큐를 뛰어넘습니다.
2. **채널 상태(Channel State) 저장**: 정렬 대기 없이 즉시 로컬 상태를 찍는 대신, 네트워크 채널에 아직 처리되지 않고 남아있는 버퍼들을 체크포인트 상태 파일에 함께 저장합니다.
3. **효과**: 배리어 도달 지연이 수십 초인 극단적 핫키 환경에서도 체크포인트가 **수백 밀리초(sub-second) 내에 완료**되어 백프레셔와 Kafka 2PC 타임아웃을 완벽하게 예방합니다.
