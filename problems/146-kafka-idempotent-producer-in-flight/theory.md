# Kafka 프로듀서 멱등성(Idempotent Producer)과 max.in.flight.requests.per.connection 순서 역전 참사

## 1. 개요 및 배경: "카프카는 파티션 내 순서를 보장한다면서요?!"

아파치 카프카(Apache Kafka)를 처음 배우는 수많은 개발자들은 공식 문서의 유명한 명제를 굳게 믿습니다:
> *"카프카는 동일한 파티션(Partition)에 전송된 레코드의 순서를 절대적으로 보장한다."*

하지만 이커머스 결제 파이프라인이나 금융 원장 시스템을 운영하다 보면, 다음과 같은 기괴하고 치명적인 장애를 마주하게 됩니다:

```
[주문 시스템]
Event #1 (Seq 0): ORDER_CREATED      (주문 생성)
Event #2 (Seq 1): PAYMENT_COMPLETED  (결제 완료)
Event #3 (Seq 2): SHIPPING_REQUESTED (배송 요청)
```

정상적인 비즈니스 흐름이라면 당연히 `주문 생성 -> 결제 완료 -> 배송 요청` 순으로 데이터베이스에 반영되어야 합니다.  
그런데 어느 날 새벽, 네트워크가 잠깐 출렁인 뒤 컨슈머 로그에 상상할 수 없는 에러가 폭풍처럼 찍힙니다:

```
ERROR: OrderNotFoundException: Cannot process PAYMENT_COMPLETED for Order #10023. Order does not exist!
FATAL: DuplicatePaymentException: Payment for Order #10023 was charged twice!
```

브로커 파티션의 오프셋을 직접 조회해 보니 경악할 만한 사실이 드러납니다:
```
Offset 0: PAYMENT_COMPLETED   <-- 결제가 주문보다 먼저 기록됨! (순서 역전)
Offset 1: ORDER_CREATED       <-- 주문이 뒤늦게 기록됨!
Offset 2: PAYMENT_COMPLETED   <-- 결제가 한 번 더 기록됨! (중복 결제)
Offset 3: SHIPPING_REQUESTED
```

분명 동일한 프로듀서가 단일 파티션으로 순서대로 전송했는데, **도대체 왜 파티션 내에서 메시지 순서가 뒤집히고(Reordering) 똑같은 메시지가 두 번 커밋(Duplication)된 것일까요?**

---

## 2. 순서 역전의 범인: 파이프라이닝과 `max.in.flight.requests.per.connection`

### (1) 프로듀서 파이프라이닝 (Pipelining)
네트워크 통신에서 요청 1개를 보내고 서버의 응답(ACK)을 받을 때까지 다음 요청을 보내지 않는 방식을 **Stop-and-Wait** 방식이라고 합니다.  
이 방식은 RTT(왕복 시간)가 20ms라면 1초에 기껏해야 50개의 요청밖에 처리하지 못하므로 처리율(Throughput)이 끔찍하게 낮아집니다.

따라서 카프카 프로듀서는 네트워크 대역폭을 최대로 활용하기 위해, 이전 요청의 응답을 기다리지 않고 여러 개의 배치 요청을 브로커로 연달아 쏘아 올리는 **파이프라이닝(Pipelining)** 기술을 기본으로 사용합니다.

이때 한 번에 서버 응답 없이 날아갈 수 있는 최대 미완료 요청 수를 결정하는 핵심 설정이 바로:
```properties
max.in.flight.requests.per.connection = 5  # (기본값: 5)
```
입니다. 즉, 프로듀서는 최대 5개의 요청 패킷을 브로커를 향해 동시에 네트워크 파이프에 밀어 넣을 수 있습니다.

### (2) 네트워크 지연과 재시도(Retry)가 만드는 순서 역전 시나리오
문제는 **`retries > 0` (재시도 활성화)** 상태에서 **네트워크 패킷 유실이나 순간적 지연**이 발생할 때 시작됩니다.

```
[클라이언트 프로듀서]                        [네트워크]                        [카프카 브로커 파티션]
   |                                            |                                      |
   |--- (1) Batch A (주문 생성) 전송 -----------> [지연/손실 발생!]                    |
   |--- (2) Batch B (결제 완료) 전송 -------------------------------------------------> | [Offset 0: 결제 완료 기록!]
   |                                                                                   |
   |<-- (3) Batch B 성공 ACK 회신 -----------------------------------------------------|
   |                                                                                   |
   | [Batch A 타임아웃 발생! retries=1 재시도]                                          |
   |--- (4) Batch A (주문 생성) 재전송 -----------------------------------------------> | [Offset 1: 주문 생성 기록!]
   |                                                                                   |
```

1. 프로듀서가 **Batch A (주문 생성)**를 먼저 전송합니다. (In-flight: 1)
2. 곧바로 **Batch B (결제 완료)**를 전송합니다. (In-flight: 2)
3. 그런데 하필 인터넷 회선 순단으로 **Batch A** 패킷이 지연되거나 손실됩니다.
4. 반면 뒤따라 출발한 **Batch B**는 멀쩡한 경로를 타고 브로커에 1등으로 도착합니다.
5. 브로커는 아무 의심 없이 Batch B를 **Offset 0**에 영구 기록합니다.
6. 프로듀서는 Batch A에 대한 ACK를 받지 못해 `request.timeout.ms` 후 Batch A를 **재전송(Retry)**합니다.
7. 뒤늦게 브로커에 도착한 Batch A는 **Offset 1**에 기록됩니다!

결과적으로 프로듀서가 의도한 순서(A $	o$ B)가 브로커 파티션에서 **B $	o$ A**로 완전히 뒤집혀 버렸습니다.

---

## 3. 중복 커밋의 범인: 네트워크 ACK 유실 (At-Least-Once의 비극)

카프카의 기본 전송 보장 수준은 **적어도 한 번(At-Least-Once)**입니다.
만약 브로커가 메시지를 디스크에 정상적으로 기록(Commit)한 직후, 프로듀서에게 돌려보내는 **ACK 응답 패킷만 네트워크에서 증발**하면 어떤 일이 벌어질까요?

1. 브로커: "Offset 0에 결제 완료 저장 끝! ACK 보낸다."
2. 네트워크: (ACK 패킷 유실!)
3. 프로듀서: "어? 타임아웃 동안 ACK가 안 오네? 브로커가 못 받았나 보다. 다시 보내야지!" (재전송)
4. 브로커: "어라? 결제 완료 메시지가 또 왔네? 새로운 메시지인가 보다!" $	o$ **Offset 1에 중복 저장!**

이로 인해 10만 원 결제 메시지가 2번 기록되어 고객 계좌에서 20만 원이 빠져나가는 중복 결제 참사가 일어납니다.

---

## 4. 고전적 해결책의 비극: `max.in.flight = 1`의 성능 참사

이 문제를 해결하기 위해 과거 카프카 개발자들은 다음과 같이 설정했습니다:
```properties
retries = 3
max.in.flight.requests.per.connection = 1
```

미완료 요청을 1개로 제한하면, Batch A의 ACK가 올 때까지 Batch B를 절대 전송하지 않으므로 순서 역전은 100% 방지할 수 있습니다.

**하지만 대가가 너무나 가혹했습니다:**
* 네트워크 RTT가 10ms라면, 아무리 고성능 서버라도 연결당 초당 100번 이상 전송할 수 없습니다.
* 프로듀서의 처리율(TPS)이 기존 대비 **1/5 ~ 1/10 수준으로 폭락**하여 대규모 트래픽을 감당하지 못하고 프로듀서 버퍼 풀이 고갈(BufferExhaustedException)되어 서비스가 마비됩니다.

---

## 5. 진정한 구원 투수: KIP-98 프로듀서 멱등성 (`enable.idempotence = true`)

Apache Kafka 0.11(KIP-98)부터 카프카는 성능 저하 없이(`max.in.flight`를 최대 5까지 유지하면서) 순서 보장과 중복 제거를 동시에 달성하는 **멱등성 프로듀서(Idempotent Producer)**를 도입했습니다. (Kafka 3.0부터는 기본값 `true`)

```properties
enable.idempotence = true
acks = all
max.in.flight.requests.per.connection = 5  # 최대 5까지 순서 완벽 보장!
retries = 2147483647
```

### (1) 멱등성 프로듀서의 핵심 원리: PID와 Sequence Number

프로듀서 멱등성의 핵심은 **"브로커가 프로듀서와 메시지의 주민등록번호를 추적하는 것"**입니다.

1. **Producer ID (PID)**:
   * 프로듀서가 처음 시작될 때 브로커 클러스터에 핸드셰이크(`InitProducerId`)를 요청하여 고유한 64비트 정수 ID(PID)를 발급받습니다.
2. **시퀀스 번호 (Sequence Number, SN)**:
   * 프로듀서는 각 토픽의 **파티션마다 독립적인 시퀀스 카운터**를 유지합니다.
   * 메시지를 보낼 때마다 $0, 1, 2, 3 \dots$ 순서대로 단조 증가하는 32비트 정수 Sequence Number를 메시지 헤더에 부여합니다.
3. **브로커의 파티션별 상태 추적 (ProducerStateManager)**:
   * 브로커는 각 파티션 메모리에 `(PID, LastSequenceNumber)` 맵을 보관합니다.
   * 브로커가 다음에 기대하는 시퀀스 번호를 `Expected Sequence Number = LastSN + 1`이라고 합니다.

---

### (2) 브로커의 3대 검증 로직 (수신된 SN에 따른 판정)

브로커에 `(PID, Sequence Number = K)`를 가진 레코드 배치가 도착했을 때:

#### Case 1: $K == 	ext{Expected SN}$ (정상 순서 인입)
* 브로커: "완벽해! 내가 기다리던 $K$번째 메시지가 정확한 순서로 도착했군."
* **동작**: 파티션 로그에 정상 커밋하고, 메모리의 `LastSN = K`, `Expected SN = K + 1`로 갱신한 뒤 성공 ACK를 반환합니다.

#### Case 2: $K < 	ext{Expected SN}$ (중복 메시지 인입 - Duplicate Defense)
* 브로커: "어? $K$번째 메시지는 이미 전에 받아서 커밋했는데 또 왔네? 프로듀서가 ACK를 못 받아서 재전송했구나!"
* **동작**: **파티션 로그에 절대 중복 기록하지 않고(Drop)**, 프로듀서에게는 **성공(ACK)**을 회신합니다!
* **결과**: 네트워크 유실로 인한 재전송에도 데이터 중복이 100% 원천 차단됩니다.

#### Case 3: $K > 	ext{Expected SN}$ (순서 역전 감지 - Out-of-Order Defense)
* 브로커: "잠깐! 나는 지금 $Expected SN$번째 메시지를 기다리고 있는데, 갑자기 건너뛰고 $K$번째 메시지가 먼저 왔다고? 중간 메시지가 어디선가 지연되고 있군!"
* **동작**: 메시지 커밋을 **단호히 거부**하고, 프로듀서에게 **`OutOfOrderSequenceException`** 에러를 즉시 반환합니다!
* **결과**: 순서가 뒤틀린 메시지가 먼저 저장되는 것을 방지합니다. 프로듀서는 미완료된 이전 메시지들의 처리가 완료되거나 재전송될 때까지 내부 전송 윈도우 큐를 재정렬하여 순서를 엄격히 맞춥니다.

---

### (3) 왜 `max.in.flight.requests.per.connection`은 최대 5까지만 가능할까?

카프카 브로커의 `ProducerStateManager`는 메모리 절약과 고속 탐색을 위해 각 PID 및 파티션별로 **최근 커밋된 시퀀스 번호의 이력을 최대 5개까지만 슬라이딩 윈도우로 보관**합니다.
만약 `max.in.flight`가 5를 초과하면(예: 6 이상), 패킷이 6개 이상 뒤섞였을 때 브로커가 해당 패킷이 중복인지 순서 역전인지 윈도우 범위를 벗어나 식별할 수 없게 됩니다.

따라서 멱등성 프로듀서(`enable.idempotence=true`) 환경에서는:
* `max.in.flight.requests.per.connection <= 5`로 설정할 때, **최대 5개의 고속 파이프라이닝을 유지하면서도 단 1건의 순서 역전과 중복 없이 완벽한 순서 보장(Exactly-Once In-Order Delivery)**을 달성할 수 있습니다!

---

## 6. 요약: 프로듀서 설정별 트레이드오프 비교표

| 설정 조합 | 순서 보장 (Order) | 중복 방지 (Deduplication) | 처리율 (Throughput) | 실무 평가 |
|:---|:---:|:---:|:---:|:---|
| `idempotence=false`, `in-flight=5`, `retries>0` | ❌ **역전 발생** | ❌ **중복 발생** | 🚀 최상 | **최악의 설정**: 패킷 지연 시 순서 뒤틀림 & 2중 결제 참사 |
| `idempotence=false`, `in-flight=1`, `retries>0` | ✅ 보장 | ❌ **중복 발생** | 🐢 최악 (1/10) | 순서는 지키나 RTT 병목으로 프로듀서 버퍼 폭사 |
| `enable.idempotence=true`, `in-flight=5`, `retries=MAX` | ✅ **완벽 보장** | ✅ **100% 제거** | 🚀 **초고속 유지** | **실무 표준 (KIP-98)**: 제로 오버헤드로 정확한 1회 순서 보장 |
