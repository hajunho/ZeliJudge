# 080 - 독약 메시지 하나 때문에 100만 건 주문이 멈췄어요?!: 메시지 큐의 독약 알약(Poison Pill)과 데드 레터 큐(Dead Letter Queue, DLQ)

## 1. 현실 비유 & 배경 스토리

하루 10만 통의 우편물을 분류하는 대형 우체국 자동화 센터를 상상해 보세요. 🏢✉️  
컨베이어 벨트를 타고 편지들이 초당 100통씩 바코드 스캐너를 통과하고 있습니다.  
그런데 누군가 실수로 주소란에 정체불명의 화학 약품을 쏟아 바코드가 타버린 불량 편지 1통이 스캐너에 도착했습니다.

스캐너는 "삐-익! 판독 오류!"를 울리며 벨트를 멈춥니다.

```text
❌ [단순 재시도 시스템의 비극 (Naive Retry without DLQ)]
"오류 났네? 다시 읽어봐!" -> 1초 뒤 재시도 -> "삐-익! 판독 오류!"
"또 오류네? 다시 읽어봐!" -> 1초 뒤 재시도 -> "삐-익! 판독 오류!"
... (영원히 무한 반복) ...
```

이 단 한 통의 불량 편지 때문에 컨베이어 벨트 전체가 영구 정지(Head-of-Line Blocking)됩니다.  
뒤에 줄 서 있던 10만 통의 정상 우편물(수능 합격 통지서, 법원 등기, 병원 검사 결과)은 단 1통도 배송되지 못하고 우체국 창고가 터져나갑니다.

이것이 바로 Apache Kafka, AWS SQS, RabbitMQ 등 메시지 큐 시스템에서 가장 악명 높은 **독약 알약(Poison Pill)**과 **헤드 오브 라인 블로킹(Head-of-Line Blocking)** 참사입니다.

네트워크 순단 같은 일시적 오류는 몇 초 뒤 재시도하면 해결되지만, **잘못된 JSON, 필수 필드 누락, 0으로 나누기 버그**가 포함된 독약 메시지는 100만 번을 다시 시도해도 영원히 실패합니다.  
메시지 큐는 순서 보장을 위해 실패한 메시지가 성공(Commit / ACK)할 때까지 다음 메시지로 넘어가지 않으므로, 단 1개의 독약 메시지로 인해 전사 메시지 처리가 완전히 멈춰버리는 것입니다!

AWS, Netflix, Uber 등 빅테크 기업들은 이 문제를 **Dead Letter Queue (DLQ, 사장된 편지함 / 격리 병동)** 패턴으로 해결합니다.  
허용된 재시도 횟수(`max_retries`)를 초과한 결함 메시지를 즉시 DLQ로 격리 오프로딩하고, 메인 큐는 다음 정상 메시지로 진도(Offset Advance)를 빼서 시스템 전체의 영구 마비를 방지하는 것입니다.  
추후 엔지니어는 DLQ에 격리된 메시지를 분석하여 버그를 수정한 뒤 **재주입(Redrive/Replay)**하여 단 1건의 데이터 유실도 없이(Zero Data Loss) 안전하게 처리합니다.

당신은 메시지 큐 시뮬레이터를 구축하여, 독약 메시지가 인입되었을 때 **Naive Retry** 엔진과 **DLQ** 엔진의 동작 및 복구 메커니즘을 비교 구현해야 합니다!

---

## 2. 시뮬레이션 상세 사양

시뮬레이터는 동일한 입력에 대해 두 개의 독립된 엔진을 병렬로 동작시킵니다:
1. **`NAIVE` 엔진**: DLQ가 없는 단순 재시도 엔진.
   - 메시지 처리가 실패(`POISON`)하면 트랜잭션이 롤백되어 오프셋을 커밋하지 못합니다.
   - 따라서 해당 독약 메시지는 **메인 큐 맨 앞에 그대로 유지**되며, 다음 시도 때도 계속 해당 메시지를 처리하려다 실패합니다.
   - 결과적으로 뒤에 있는 모든 정상 메시지들이 영구히 블로킹(HOL Blocking)됩니다.
2. **`DLQ` 엔진**: Dead Letter Queue와 Redrive Policy가 적용된 엔터프라이즈 엔진.
   - 각 메시지는 실패 횟수(`retries`)를 추적합니다.
   - 실패 시 `msg.retries`가 1 증가합니다.
   - 만약 `msg.retries >= max_retries`에 도달하면:
     - 해당 메시지를 메인 큐에서 제거(`popleft`)하여 **DLQ에 격리 보관**합니다.
     - 메인 큐는 오프셋을 커밋하고 다음 메시지로 정상 전진합니다!
   - 아직 `msg.retries < max_retries`라면:
     - 큐 맨 앞에 유지되어 다음 시도에 재시도됩니다.

### Redrive (Replay) 메커니즘
- 엔지니어가 버그를 패치한 상황을 시뮬레이션합니다.
- DLQ에 격리되어 있던 모든 메시지를 꺼내어:
  - 메시지 타입을 `NORMAL`로 정상화하고, `retries`를 0으로 리셋합니다.
  - DLQ 엔진의 메인 큐 맨 끝(`append`)에 원래 순서대로 재주입(Redrive)합니다.
  - DLQ는 완전히 비워집니다.
- NAIVE 엔진은 DLQ가 없으므로 `REDRIVE` 명령의 영향을 받지 않습니다.

---

## 3. 입력 명령 프로토콜

표준 입력(stdin)으로 다음 명령어들이 한 줄씩 주어집니다:

1. `INIT <max_retries>`
   - 시뮬레이터를 초기화합니다.
   - `max_retries`: DLQ 엔진의 최대 허용 재시도 횟수 ($1 \le max\_retries \le 10$).
   - 출력: `INITIALIZED MAX_RETRIES=<max_retries>`

2. `ENQUEUE <msg_id> <type> <payload>`
   - 두 엔진의 메인 큐에 동일한 메시지를 삽입합니다.
   - `<type>`: `NORMAL` (처리 시 100% 성공) 또는 `POISON` (처리 시 100% 예외 실패).
   - `<payload>`: 메시지 페이로드 문자열.
   - 출력: `ENQUEUED <msg_id> TYPE=<type>`

3. `CONSUME <count>`
   - 두 엔진이 각각 독립적으로 최대 `<count>`번의 메시지 소비 단계(Step)를 수행합니다.
   - 각 단계에서 자신의 큐가 비어있으면 아무 작업도 하지 않습니다.
   - 큐에 메시지가 있다면 맨 앞 메시지를 검사하여 규칙에 따라 처리합니다.
   - 출력: `CONSUMED <count> STEPS`

4. `REDRIVE`
   - DLQ 엔진의 DLQ에 격리된 모든 메시지를 `NORMAL`로 패치하여 메인 큐 끝에 재주입합니다.
   - 출력: `REDRIVEN <n> MESSAGES FROM DLQ` (여기서 `<n>`은 재주입된 메시지 수)

5. `STATUS`
   - 두 엔진의 현재 상태를 다음 형식으로 출력합니다:
     ```
     === NAIVE ENGINE ===
     PROCESSED: <성공적으로 처리된 총 메시지 수>
     FAILED_ATTEMPTS: <실패한 총 시도 횟수>
     MAIN_QUEUE_LAG: <메인 큐에 남아있는 메시지 수>
     DLQ_SIZE: 0
     HOL_BLOCKED: <메인 큐가 비어있지 않고 맨 앞 메시지가 POISON이면 TRUE, 아니면 FALSE>
     === DLQ ENGINE ===
     PROCESSED: <성공적으로 처리된 총 메시지 수>
     FAILED_ATTEMPTS: <실패한 총 시도 횟수>
     MAIN_QUEUE_LAG: <메인 큐에 남아있는 메시지 수>
     DLQ_SIZE: <현재 DLQ에 격리 보관 중인 메시지 수>
     HOL_BLOCKED: <메인 큐가 비어있지 않고 맨 앞 메시지가 POISON이면 TRUE, 아니면 FALSE>
     ```

---

## 4. 제약 조건

- $1 \le max\_retries \le 10$
- 단일 테스트케이스당 총 인입 메시지 수 $\le 3,000$
- 총 소비 스텝 수 $\le 10,000$
- `msg_id`와 `payload`는 공백 없는 영문자/숫자/언더스코어 문자열

---

## 5. 입출력 예시

### 예시 입력
```
INIT 3
ENQUEUE MSG_1 NORMAL order_item_1
ENQUEUE MSG_2 POISON broken_json_payload
ENQUEUE MSG_3 NORMAL order_item_3
ENQUEUE MSG_4 NORMAL order_item_4
STATUS
CONSUME 1
STATUS
CONSUME 3
STATUS
REDRIVE
STATUS
CONSUME 5
STATUS
```

### 예시 출력
```
INITIALIZED MAX_RETRIES=3
ENQUEUED MSG_1 TYPE=NORMAL
ENQUEUED MSG_2 TYPE=POISON
ENQUEUED MSG_3 TYPE=NORMAL
ENQUEUED MSG_4 TYPE=NORMAL
=== NAIVE ENGINE ===
PROCESSED: 0
FAILED_ATTEMPTS: 0
MAIN_QUEUE_LAG: 4
DLQ_SIZE: 0
HOL_BLOCKED: FALSE
=== DLQ ENGINE ===
PROCESSED: 0
FAILED_ATTEMPTS: 0
MAIN_QUEUE_LAG: 4
DLQ_SIZE: 0
HOL_BLOCKED: FALSE
CONSUMED 1 STEPS
=== NAIVE ENGINE ===
PROCESSED: 1
FAILED_ATTEMPTS: 0
MAIN_QUEUE_LAG: 3
DLQ_SIZE: 0
HOL_BLOCKED: TRUE
=== DLQ ENGINE ===
PROCESSED: 1
FAILED_ATTEMPTS: 0
MAIN_QUEUE_LAG: 3
DLQ_SIZE: 0
HOL_BLOCKED: TRUE
CONSUMED 3 STEPS
=== NAIVE ENGINE ===
PROCESSED: 1
FAILED_ATTEMPTS: 3
MAIN_QUEUE_LAG: 3
DLQ_SIZE: 0
HOL_BLOCKED: TRUE
=== DLQ ENGINE ===
PROCESSED: 1
FAILED_ATTEMPTS: 3
MAIN_QUEUE_LAG: 2
DLQ_SIZE: 1
HOL_BLOCKED: FALSE
REDRIVEN 1 MESSAGES FROM DLQ
=== NAIVE ENGINE ===
PROCESSED: 1
FAILED_ATTEMPTS: 3
MAIN_QUEUE_LAG: 3
DLQ_SIZE: 0
HOL_BLOCKED: TRUE
=== DLQ ENGINE ===
PROCESSED: 1
FAILED_ATTEMPTS: 3
MAIN_QUEUE_LAG: 3
DLQ_SIZE: 0
HOL_BLOCKED: FALSE
CONSUMED 5 STEPS
=== NAIVE ENGINE ===
PROCESSED: 1
FAILED_ATTEMPTS: 8
MAIN_QUEUE_LAG: 3
DLQ_SIZE: 0
HOL_BLOCKED: TRUE
=== DLQ ENGINE ===
PROCESSED: 4
FAILED_ATTEMPTS: 3
MAIN_QUEUE_LAG: 0
DLQ_SIZE: 0
HOL_BLOCKED: FALSE
```

### 힌트 & 분석
1. `CONSUME 1` 후:
   - 두 엔진 모두 맨 앞의 `MSG_1 (NORMAL)`을 성공적으로 처리합니다 (`PROCESSED: 1`).
   - 이제 두 엔진의 큐 맨 앞에 `MSG_2 (POISON)`이 도달하면서 `HOL_BLOCKED: TRUE`가 됩니다.
2. `CONSUME 3` 후:
   - **NAIVE**: 3번 모두 `MSG_2`에 부딪혀 실패합니다 (`FAILED_ATTEMPTS: 3`). 메인 큐는 여전히 3건이 묶여있고 `HOL_BLOCKED: TRUE`가 유지됩니다.
   - **DLQ**: 3번째 실패로 `retries == 3 (max_retries)`에 도달하여 즉시 `MSG_2`를 DLQ로 격리합니다! 메인 큐는 2건으로 줄고, 다음 메시지가 `NORMAL`이 되면서 `HOL_BLOCKED: FALSE`로 풀립니다!
3. `REDRIVE` 후:
   - DLQ에 격리되었던 메시지가 정상화되어 메인 큐 끝에 재배치됩니다 (`DLQ_SIZE: 0`, `MAIN_QUEUE_LAG: 3`).
4. `CONSUME 5` 후:
   - **NAIVE**: 또다시 5번 동안 `MSG_2`와 씨름하다 `FAILED_ATTEMPTS: 8`로 마비되며 `PROCESSED: 1`에서 멈춥니다.
   - **DLQ**: 메인 큐에 있던 `MSG_3`, `MSG_4`와 재주입된 `MSG_2`까지 모두 성공적으로 처리하여 `PROCESSED: 4`, `MAIN_QUEUE_LAG: 0`, `DLQ_SIZE: 0`으로 100% 무손실 완전 복구에 성공합니다!
