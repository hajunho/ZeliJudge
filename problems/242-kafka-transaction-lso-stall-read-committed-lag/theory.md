# Problem 242 Theory: Apache Kafka 트랜잭션 아키텍처 심층 분석 — Exactly-Once Semantics, Last Stable Offset (LSO) 정체 및 에포크 펜싱

Apache Kafka의 트랜잭션 기능(KIP-98: Exactly Once Delivery and Transactional Messaging)은 분산 메시징 시스템에서 단일 토픽 파티션뿐만 아니라 **복수 토픽-파티션 간의 원자적 쓰기(Atomic Multi-partition Writes)** 및 **소비-변환-생산(Consume-Transform-Produce) 파이프라인의 원자성**을 보장하는 핵심 인프라입니다.

본 문서에서는 트랜잭션 코디네이터의 2단계 커밋(2PC) 프로토콜, 로그 오프셋의 계층 구조(LEO vs HW vs LSO), LSO 정체로 인한 컨슈머 랙 폭증 메커니즘, 그리고 에포크 펜싱(Epoch Fencing)을 통한 스플릿 브레인 방어 원리를 심층 분석합니다.

---

## 1. Kafka 트랜잭션 아키텍처 및 2단계 커밋 (2PC)

Kafka 트랜잭션 시스템은 4가지 핵심 컴포넌트로 구성됩니다:

```
                  Kafka 트랜잭션 코디네이션 아키텍처
                  
   ┌───────────────────────────────────────────────────────────┐
   │                    Transactional Producer                 │
   │  - transactional.id: "order-payment-tx-0"                  │
   │  - Producer ID (PID): 1001, Monotonic Epoch: 3            │
   └───────────────┬───────────────────────────┬───────────────┘
                   │ 1. FindCoordinator        │ 3. Produce Data
                   │ 2. InitProducerId         │    (Transactional)
                   ▼                           ▼
   ┌───────────────────────────┐   ┌───────────────────────────┐
   │   Transaction Coordinator │   │      Partition Leader     │
   │  (Broker thread managing  │   │  (orders.payment.tx-0)    │
   │   __transaction_state)    │   │                           │
   └───────────────┬───────────┘   └───────────┬───────────────┘
                   │                           │
                   │ 4. EndTxn(COMMIT / ABORT) │
                   └──────────────────────────►│ 5. Write Control Marker
                                               │    (COMMIT / ABORT)
```

1. **`Transactional Producer`**: 고유한 `transactional.id`를 부여받으며, 브로커로부터 64비트 정수 `PID`(Producer ID)와 단조 증가하는 16비트 `Epoch`를 발급받습니다.
2. **`Transaction Coordinator`**: 브로커 내부에서 구동되는 특별한 모듈로, `__transaction_state` 내부 압축 토픽을 관리하며 트랜잭션의 상태 머신(`Empty`, `Ongoing`, `PrepareCommit`, `PrepareAbort`, `CompleteCommit`, `CompleteAbort`)을 추적합니다.
3. **`__transaction_state` Topic**: 트랜잭션 메타데이터를 저장하는 트랜잭션 로그입니다.
4. **`Control Marker (제어 마커)`**: 파티션 리더 브로커가 트랜잭션의 종료 시점에 파티션 세그먼트에 기록하는 특별한 내부 레코드(`ControlRecord`)입니다. 클라이언트에 페이로드로 노출되지 않으며, `COMMIT` 또는 `ABORT` 상태를 명시합니다.

---

## 2. 세 가지 로그 오프셋: LEO vs HW vs LSO

Kafka의 각 파티션은 데이터의 안전성과 격리 수준을 보장하기 위해 세 가지 서로 다른 오프셋 포인터를 엄격히 분리하여 관리합니다.

```
                    파티션 로그의 오프셋 계층 구조
                    
 Offset:    0     1     2     3     4     5     6     7     8     9   (LEO=10)
         ┌─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┐
 Entries │ C_0 │ C_0 │ T_1 │ N_2 │ N_2 │ T_1 │ N_2 │ N_2 │ T_1 │ ... │
         └─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┘
                           ▲                                   ▲
                           │                                   │
                          LSO                                 HW
                 (FirstUnstableOffset)                (All Replicas Acked)
```

1. **LEO (Log End Offset)**:
   - 파티션에 다음 메시지가 쓰여질 물리적 오프셋입니다.
2. **HW (High Watermark)**:
   - 파티션의 모든 ISR(In-Sync Replicas)에 복제 완료가 확인된 오프셋입니다.
   - **`isolation.level = read_uncommitted`** 컨슈머는 트랜잭션의 커밋/롤백 여부와 관계없이 HW 직전까지의 모든 메시지를 즉시 읽을 수 있습니다.
3. **LSO (Last Stable Offset)**:
   - **아직 커밋 또는 어보트되지 않은 최초의 활성 트랜잭션 오프셋(`FirstUnstableOffset`)**으로 정의됩니다.
   - 만약 파티션 내에 현재 진행 중인 트랜잭션이 전혀 없다면, $\text{LSO} = \text{HW}$가 됩니다.
   - **`isolation.level = read_committed`** 컨슈머는 **오직 LSO 직전까지만 메시지를 읽을 수 있습니다**.

---

## 3. LSO 정체(Stall)와 `read_committed` 컨슈머 랙 폭증

### 3.1 왜 LSO는 미완결 트랜잭션을 건너뛸 수 없는가?
- 만약 컨슈머가 아직 커밋되지 않은 트랜잭션 $T_1$을 건너뛰고 그 뒤에 있는 비트랜잭션 메시지 $N_2$를 먼저 읽는다면:
  - 이후 $T_1$이 성공적으로 커밋되었을 때, 컨슈머는 과거 오프셋으로 되돌아갈 수 없으므로 **메시지 순서 보장(Ordering Guarantee)**이 파괴됩니다.
  - 반대로 $T_1$이 롤백(`ABORT`)된다면 건너뛴 것은 다행이지만, 커밋될지 롤백될지 사전에 알 수 없으므로 원자성을 보장하기 위해 커널/브로커는 **LSO 이후의 모든 메시지 전달을 완전히 차단**합니다.

### 3.2 프로덕션 재앙: 단 1개의 프로듀서 행으로 인한 전사 파이프라인 마비
- 파티션 0번에 초당 1,000건의 비트랜잭션 로그/주문 데이터가 유입되고 있습니다.
- 트랜잭션 프로듀서 $P_{\text{tx}}$가 오프셋 1,000번에서 트랜잭션을 열고 메시지 1건을 쓴 후, 예기치 않은 데이터베이스 데드락이나 JVM Full GC로 인해 멈춤(Hang) 상태에 빠졌습니다.
- 비트랜잭션 프로듀서들은 오프셋 1,001번부터 50,000번까지 메시지를 쏟아붓고 복제가 완료되어 HW는 50,000으로 올라갑니다.
- 하지만 LSO는 **오프셋 1,000번에 고정**됩니다!
- 결과:
  - `read_committed`로 동작하는 모든 컨슈머 그룹(정산, 빌링, 실시간 재고 차감 등)은 오프셋 1,000번에서 완전히 멈춰 섭니다.
  - 컨슈머 랙이 0에서 49,000으로 수직 상승하며 알람이 울리고 서비스 장애가 발생합니다.
  - 트랜잭션 프로듀서와 무관한 일반 메시지들까지 전부 볼모로 잡히는 **Head-of-Line Blocking**이 발생합니다.

### 3.3 `transaction.timeout.ms`의 함정
- Kafka의 `transaction.timeout.ms` 기본값은 60,000ms(1분)이며, 브로커 상한선(`transaction.max.timeout.ms`)은 최대 15분까지 늘어날 수 있습니다.
- 이 타임아웃이 만료되기 전까지 트랜잭션 코디네이터는 프로듀서가 살아있다고 믿고 아무런 조치도 취하지 않으므로, 장애 복구 전까지 시스템이 영구적으로 지연됩니다.

---

## 4. 에포크 펜싱(Epoch Fencing)과 좀비 방어

트랜잭션 코디네이터가 타임아웃을 감지하면 다음과 같은 펜싱 절차를 밟습니다:

```
[트랜잭션 코디네이터의 좀비 프로듀서 펜싱 및 LSO 해제]
1. Coordinator가 타임아웃 감지 -> __transaction_state에 PrepareAbort 기록
2. Partition Leader에 ABORT 제어 마커 기록 -> ProducerStateManager가 FirstUnstableOffset 갱신
3. LSO가 즉시 1,000번에서 50,000번(HW)으로 점프! -> 컨슈머 랙 즉시 해소
4. Producer Epoch를 3에서 4로 증가(Bumping)
5. 뒤늦게 깨어난 좀비 프로듀서가 이전 Epoch=3으로 쓰기 시도 시:
   -> 브로커가 ProducerFencedException 반환하며 즉각 거절!
```

---

## 5. 실무 모니터링 지표 및 아키텍처 베스트 프랙티스

| 점검 항목 | 설정 및 모니터링 지표 | 권장 프로덕션 기준 |
| :--- | :--- | :--- |
| **토픽 파티션 분리** | 물리적 토픽 격리 | 대용량 비트랜잭션 트래픽과 미션 크리티컬 트랜잭션 트래픽을 절대 동일 파티션에 섞지 말 것 |
| **트랜잭션 타임아웃 단축** | `transaction.timeout.ms` | 기본 60초에서 애플리케이션 SLA에 맞게 `5000` ~ `15000` (5~15초)로 대폭 축소 |
| **LSO 정체 모니터링** | `UnderMinIsr`, `FirstUnstableOffset` | `HW - LSO > 임계치(100)` 발생 시 즉시 긴급 알람 설정 |
| **강제 롤백 수단 확보** | `kafka-transactions.sh` CLI / AdminClient | 코디네이터가 처리하지 못하는 데드락 트랜잭션을 관리자가 강제 `abortTransaction()` 할 수 있는 런북 구비 |
