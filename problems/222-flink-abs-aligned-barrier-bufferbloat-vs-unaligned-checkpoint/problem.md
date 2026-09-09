# 문제 222: 분산 스트림 처리(Distributed Stream Processing): Apache Flink 비동기 배리어 스냅샷(ABS)과 정렬 배리어(Aligned Barrier) 백프레셔 버퍼블로트 vs 비정렬 체크포인트(Unaligned Checkpoint) 및 Kafka 2PC 트랜잭션 타임아웃

## 1. 개요 (Incident Scenario)

초당 수백만 건의 금융 이상 거래 탐지(Fraud Detection) 및 실시간 정산 원장을 처리하는 엔터프라이즈 데이터 스트리밍 플랫폼 팀은 **Apache Flink**와 **Apache Kafka**를 연동하여 종단간 정확히 한 번(End-to-End Exactly-Once, EOS) 처리 아키텍처를 구축했습니다.

Flink는 분산 스냅샷 알고리즘(Chandy-Lamport 변형인 **Asynchronous Barrier Snapshotting, ABS**)을 통해 데이터 스트림 사이에 체크포인트 배리어($B_n$)를 주입하고, 싱크(Sink) 단에서는 Kafka 트랜잭션을 활용한 **2단계 커밋(Two-Phase Commit, 2PC Sink)** 프로토콜을 통해 완전한 무결성을 보장하도록 설계되었습니다.

그러나 특정 파티션에 트래픽이 집중되는 핫키(Hot Key) 데이터 편중과 특정 노드의 일시적 GC 정체(STW)가 발생한 직후, 다음과 같은 치명적인 파이프라인 전면 중단 장애가 연쇄적으로 발생했습니다:

1. **정렬 배리어(Aligned Barrier) 대기로 인한 극심한 백프레셔 버퍼블로트(Bufferbloat)**:
   다중 입력 채널(예: Shuffle/KeyBy 연산자)을 가진 Flink 오퍼레이터는 기본적으로 **정렬 체크포인트(Aligned Checkpoint)** 모드로 동작합니다.
   특정 입력 채널 3번에 지연(Straggler, 20초)이 발생하자, 이미 배리어 $B_n$을 수신한 나머지 채널 0, 1, 2번은 인과성 정합성을 유지하기 위해 **데이터 처리를 일시 중단하고 유입되는 레코드를 인풋 버퍼 풀에 맹목적으로 적재(Buffering)**하기 시작했습니다.
   적재된 인-플라이트(In-flight) 레코드 용량이 가용 버퍼 한도(`input_channel_buffer_capacity_mb = 256MB`)를 초과하여 1GB 이상으로 폭증했고, 업스트림 전체에 극심한 백프레셔(Backpressure)를 유발하여 시스템 전체 처리량이 0으로 추락했습니다(`BARRIER_ALIGNMENT_BUFFERBLOAT_STALL`).

2. **Kafka 2PC 트랜잭션 타임아웃 및 연쇄 파이프라인 크래시**:
   Flink의 `TwoPhaseCommitSinkFunction`은 배리어 $B_n$이 싱크에 도달하면 현재 트랜잭션을 Pre-commit하고, JobManager로부터 전역 체크포인트 완료 알림을 받아 정식 Commit을 수행합니다.
   그러나 업스트림의 배리어 정렬 지연으로 인해 전체 체크포인트 완료 시간이 Kafka 브로커의 트랜잭션 타임아웃(`kafka_transaction_timeout_ms = 60000ms`, 60초)을 초과하는 68.5초로 늘어났습니다.
   Kafka 트랜잭션 코디네이터는 해당 트랜잭션을 강제 만료(`ABORT`) 처리했고, 뒤늦게 커밋을 시도한 Flink 싱크는 `ProducerFencedException` 및 `InvalidTxnStateException`을 맞고 즉사하여 잡(Job)이 무한 재시작 루프에 빠졌습니다(`KAFKA_2PC_TRANSACTION_TIMEOUT_ABORT`).

3. **비정렬 체크포인트(Unaligned Checkpoint) 도입을 통한 극적 구원**:
   Flink 1.11+에서 도입된 **비정렬 체크포인트(Unaligned Checkpoint)**는 배리어가 인풋 네트워크 버퍼 큐를 기다리지 않고 **즉시 추월(Overtake/Leapfrog)**하여 오퍼레이터에 도달합니다.
   채널 정렬 대기 시간($\Delta t_{\text{align}}$)이 0ms로 소멸하며, 네트워크 큐에 쌓인 미소비 레코드는 채널 상태(Channel State)로 스냅샷에 함께 저장됩니다. 체크포인트는 지연 채널의 존재와 무관하게 600ms 만에 완료되며, 버퍼블로트와 Kafka 2PC 타임아웃을 100% 원천 차단합니다(`OPTIMAL_UNALIGNED_CHECKPOINT_EOS`).

당신은 분산 스트리밍 인프라 전문가로서, Flink의 ABS 배리어 정렬 과정, 채널별 데이터 유입 속도에 따른 버퍼 누적량 계산, 체크포인트 및 Kafka 2PC 타임아웃 평가, 그리고 비정렬 체크포인트 최적화 효과를 시뮬레이션하는 진단 엔진을 작성해야 합니다.

---

## 2. 아키텍처 및 상태 모델

```
 [Aligned Checkpoints Mechanics: The Backpressure Trap]

  Channel 0 (Fast):  ───[Data]───[Data]───[Barrier Bn] ──────────► (Arrives at t=100ms)
                                                       │
  Channel 1 (Slow):  ───[Data]─── ... ───[Barrier Bn] ──────────► (Arrives at t=65000ms!)
                                                       │
  Operator State:                                      │
  * Channel 0 must PAUSE processing and BUFFER incoming data from t=100ms to t=65000ms!
  * In-flight buffer grows to 1357 MB! (Bufferbloat & Memory Pressure)
  * Checkpoint finishes at t=65.5s ===> EXCEEDS Kafka 60s Transaction Timeout!
  ===> Kafka Coordinator ABORTS Transaction! Sink crashes with ProducerFencedException!

 ───────────────────────────────────────────────────────────────────────────

 [Unaligned Checkpoints (UC) Mechanics: Overtaking & Zero Wait]

  Channel 0: ───[Barrier Bn OVERTAKES Data Buffers] ─────────────► (Arrives immediately)
  Channel 1: ───[Barrier Bn OVERTAKES Data Buffers] ─────────────► (Arrives immediately)

  Operator State:
  * Takes snapshot IMMEDIATELY without waiting for Channel 1 alignment!
  * Saves in-flight channel buffers directly into Checkpoint State!
  * Alignment Duration: 0 ms! Buffered Data during alignment: 0 MB!
  * Checkpoint finishes in 610 ms ===> Kafka 2PC Commits successfully!
```

### 시뮬레이션 동작 규격

1. **체크포인트 환경 설정**:
   - `checkpoint_mode`: `"ALIGNED"` 또는 `"UNALIGNED"`
   - `checkpoint_timeout_ms`: Flink 오퍼레이터 체크포인트 타임아웃(기본 30000ms)
   - `kafka_transaction_timeout_ms`: Kafka 2PC 트랜잭션 만료 타임아웃(기본 60000ms)
   - `input_channel_buffer_capacity_mb`: 인풋 채널 버퍼 풀 최대 수용 용량(MB)
   - `state_snapshot_base_duration_ms`: 로컬 상태 스토리지(RocksDB/Memory) 동기 스냅샷 기본 소요 시간(ms)

2. **채널 토폴로지 및 배리어 도달 모델**:
   - 각 채널은 `id`, `data_rate_mb_per_sec`, `barrier_arrival_delay_ms`를 가집니다.
   - 가장 빠른 배리어 도달 시각: $t_{\text{first}} = \min(\text{barrier\_arrival\_delay\_ms})$
   - 가장 늦은 배리어 도달 시각: $t_{\text{last}} = \max(\text{barrier\_arrival\_delay\_ms})$

3. **체크포인트 모드별 동작 계산**:
   - **`ALIGNED` (정렬 체크포인트)**:
     - 배리어 정렬 소요 시간: $\Delta t_{\text{align}} = t_{\text{last}} - t_{\text{first}}$
     - 정렬 대기 중 누적 버퍼 데이터 계산: 이미 배리어가 도착한 채널들은 $t_{\text{last}}$까지 데이터 처리를 멈추고 버퍼링합니다.
       $$\text{total\_buffered\_mb} = \sum_{c} \left( \text{data\_rate}_c \times \frac{\max(0, t_{\text{last}} - \text{delay}_c)}{1000.0} \right)$$
     - 전체 체크포인트 완료 시각: $T_{\text{checkpoint}} = t_{\text{last}} + \text{state\_snapshot\_base\_duration\_ms}$
   - **`UNALIGNED` (비정렬 체크포인트)**:
     - 배리어가 인-플라이트 데이터 버퍼를 즉시 추월하므로 정렬 대기가 없습니다:
       $$\Delta t_{\text{align}} = 0.0\text{ ms}, \quad \text{total\_buffered\_mb} = 0.0\text{ MB}$$
     - 채널 상태 직렬화 오버헤드: $\text{overhead} = \sum (\text{data\_rate}_c) \times 0.5\text{ ms}$
     - 전체 체크포인트 완료 시각: $T_{\text{checkpoint}} = t_{\text{first}} + \text{state\_snapshot\_base\_duration\_ms} + \text{overhead}$

4. **장애 판정 및 최종 Verdict 규칙**:
   - `T_checkpoint > kafka_transaction_timeout_ms`:
     - `status = "FAILED"`, `verdict = "KAFKA_2PC_TRANSACTION_TIMEOUT_ABORT"`
   - `total_buffered_mb > input_channel_buffer_capacity_mb` 또는 `T_checkpoint > checkpoint_timeout_ms`:
     - `status = "FAILED"`, `verdict = "BARRIER_ALIGNMENT_BUFFERBLOAT_STALL"`
   - `checkpoint_mode == "UNALIGNED"`:
     - `status = "SUCCESS"`, `verdict = "OPTIMAL_UNALIGNED_CHECKPOINT_EOS"`
   - `checkpoint_mode == "ALIGNED"` 이고 $\Delta t_{\text{align}} \le 1000.0\text{ms}$ 이며 버퍼 점유율 $\le 20\%$:
     - `status = "SUCCESS"`, `verdict = "BALANCED_ALIGNED_CHECKPOINT_NORMAL"`
   - 그 외 경미한 지연:
     - `status = "SUCCESS"`, `verdict = "MODERATE_ALIGNMENT_BACKPRESSURE_WARNING"`

---

## 3. 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "checkpoint_mode": "ALIGNED",
    "checkpoint_timeout_ms": 30000.0,
    "kafka_transaction_timeout_ms": 60000.0,
    "input_channel_buffer_capacity_mb": 256.0,
    "state_snapshot_base_duration_ms": 500.0
  },
  "channels": [
    { "id": 0, "data_rate_mb_per_sec": 15.0, "barrier_arrival_delay_ms": 100.0 },
    { "id": 1, "data_rate_mb_per_sec": 15.0, "barrier_arrival_delay_ms": 120.0 },
    { "id": 2, "data_rate_mb_per_sec": 15.0, "barrier_arrival_delay_ms": 150.0 },
    { "id": 3, "data_rate_mb_per_sec": 15.0, "barrier_arrival_delay_ms": 250.0 }
  ]
}
```

---

## 4. 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다. 실수형 메트릭은 소수점 둘째 자리(비율은 넷째 자리)까지 반올림합니다.

```json
{
  "status": "SUCCESS",
  "verdict": "BALANCED_ALIGNED_CHECKPOINT_NORMAL",
  "metrics": {
    "checkpoint_mode": "ALIGNED",
    "total_channels": 4,
    "alignment_duration_ms": 150.0,
    "total_buffered_mb": 5.7,
    "total_checkpoint_duration_ms": 750.0,
    "buffer_utilization_ratio": 0.0223,
    "kafka_transaction_timeout_ms": 60000.0
  }
}
```
