# Problem #038: 새로고침 10번 눌렀더니 똑같은 알림이 10개 왔어요?!: 메시지 큐 At-Least-Once와 컨슈머 멱등성

## 📖 실무 스토리: 비동기 큐로 뺐더니 1명에게 1만 원 쿠폰이 5장씩 나갔습니다!

이커머스 스타트업의 주니어 개발자 나코딩은 주문 완료 시 고객에게 카카오톡 알림톡을 발송하고 1만 원 할인 쿠폰을 발급하는 로직이 주문 API 속도를 갉아먹는다는 사실을 발견했습니다.

나코딩은 성능을 개선하기 위해 대용량 분산 메시지 큐(Kafka / RabbitMQ / AWS SQS)를 도입했습니다:
* 주문 서버(Producer)는 주문이 성공하면 주문 이벤트 메시지를 메시지 큐에 발행(`PUBLISH`)하고 즉시 응답합니다.
* 발송 서버(Consumer)는 큐에서 메시지를 꺼내(`CONSUME`) 알림톡 API를 호출하고 유저에게 1만 원 쿠폰을 INSERT합니다.

> **나코딩**: "이제 주문 API가 0.05초 만에 끝나네! 비동기 메시지 큐 최고다!"

하지만 배포 다음 날 아침, **재무팀과 CS팀이 사색이 되어 개발팀으로 달려왔습니다!**

1. **"고객 한 명에게 '주문 완료' 알림톡이 5개 연속으로 쏟아졌어요!"**
   * 발송 서버(Consumer)가 메시지를 받아 쿠폰을 잘 발급하고 브로커에게 "처리 완료했습니다"라는 확인증(ACK)을 보냈습니다.
   * 그런데 네트워크 일시 지연으로 이 `ACK` 패킷이 브로커에게 제시간에 도착하지 못하고 타임아웃(Ack Timeout)이 났습니다!
   * 브로커는 컨슈머가 죽은 줄 알고 **동일한 메시지(`msg_1`)를 다시 전송(Redelivery)**했습니다!
   * 순진한 컨슈머는 "어? 새 메시지네?" 하고 또 쿠폰을 주고 알림톡을 또 쐈습니다!
2. **"결제 버튼 광클했더니 1만 원 쿠폰이 중복으로 2장 발급되었어요!"**
   * 유저가 결제 버튼을 빠르게 2번 클릭하여 주문 서버(Producer)가 서로 다른 메시지 ID(`msg_101`, `msg_102`)로 동일한 주문(`order_5001`)에 대한 쿠폰 지급 메시지를 2개 발행했습니다!
   * 컨슈머는 메시지 ID가 다르다는 이유로 쿠폰을 2번 지급해 버렸습니다!

> **"결과: 하룻밤 사이에 수천만 원어치의 쿠폰이 중복 지급되어 회사가 막대한 재정적 손실을 입었습니다!"**

분산 시스템의 메시지 브로커는 네트워크 장애 앞에서도 메시지가 유실되지 않도록 **최소 1회 전송(At-Least-Once)**을 기본으로 제공합니다.
즉, **"메시지가 중복으로 도착하는 것은 버그가 아니라 네트워크의 자연스러운 물리적 법칙"**입니다!

따라서 컨슈머는 동일한 메시지나 동일한 비즈니스 요청이 100번 오더라도 단 한 번만 실행되도록 **멱등성(Idempotency)**을 반드시 갖추어야 합니다.

여러분의 임무는 3가지 컨슈머 모델(NAIVE, MSG_ONLY, FULL_IDEMPOTENT)을 시뮬레이션하고, 메시지 중복과 비즈니스 중복을 완벽히 차단하여 회사의 재정적 손실을 방어하는 멱등 컨슈머 엔진을 구현하는 것입니다!

---

## 🎯 문제 요구사항

수신되는 메시지 스트림을 순서대로 처리하며, 3가지 컨슈머 전략의 상태와 집행 비용을 계측하십시오:

### 1. 3대 컨슈머 모델 동작 규칙

각 메시지는 `RECEIVE <msg_id> <biz_key> <amount>` 형태로 수신됩니다:
* `msg_id`: 메시지 고유 식별자 (네트워크 ACK 유실 시 브로커가 동일한 `msg_id`를 재전송함)
* `biz_key`: 비즈니스 엔티티 고유 키 (예: `order_1001`, 프로듀서 재시도 시 다른 `msg_id`로 동일 `biz_key`가 유입될 수 있음)
* `amount`: 해당 메시지 실행 시 집행되는 비용(금액)

1. **전략 1: NAIVE (무방비 컨슈머)**
   * 중복 검사를 전혀 수행하지 않습니다.
   * 모든 수신 메시지에 대해 무조건 비즈니스 로직을 실행합니다 (`EXECUTED`).
   * 매번 `amount`만큼 비용이 누적 집행됩니다.

2. **전략 2: MSG_ONLY (메시지 ID 중복 검사 컨슈머 - 초보의 함정)**
   * 메시지 ID(`msg_id`)가 이전에 수신되어 처리된 적이 있는지 검사합니다.
   * 이미 등장한 `msg_id`인 경우:
     * 메시지 재전송으로 판단하고 비즈니스 로직을 건너뜁니다 (`SKIPPED_MSG_DUP`). 비용은 0원입니다.
   * 처음 등장한 `msg_id`인 경우:
     * 비즈니스 로직을 실행합니다 (`EXECUTED`). `amount`만큼 비용이 누적되고 해당 `msg_id`를 처리 완료 목록에 등록합니다.
   * *(주의: `biz_key`가 중복되더라도 `msg_id`가 다르면 막지 못하고 실행해 버립니다!)*

3. **전략 3: FULL_IDEMPOTENT (완전 멱등 컨슈머 - Golden Standard)**
   * 2단계 원자적 중복 검사를 수행합니다:
     1. **1차 검사 (`msg_id`)**: `msg_id`가 이미 처리 완료 목록에 있는 경우 $\to$ 즉시 건너뜁니다 (`SKIPPED_MSG_DUP`). 비용 0원.
     2. **2차 검사 (`biz_key`)**: `msg_id`는 신규지만, `biz_key`가 이미 성공적으로 처리된 적이 있는 경우 $\to$ 비즈니스 중복으로 판단하고 건너뜁니다 (`SKIPPED_BIZ_DUP`). 해당 `msg_id`를 처리 목록에 기록하며 비용은 0원입니다.
     3. **신규 요청**: 둘 다 처음인 경우 $\to$ 비즈니스 로직을 실행합니다 (`EXECUTED`). `amount`만큼 비용이 누적되고 `msg_id`와 `biz_key`를 모두 처리 완료 목록에 등록합니다.

---

## 📥 입력 형식 (Input Format)

```text
EVENTS <N>
RECEIVE <msg_id_1> <biz_key_1> <amount_1>
RECEIVE <msg_id_2> <biz_key_2> <amount_2>
...
```

* 첫 번째 줄: `EVENTS` 키워드 뒤에 총 수신 메시지 개수 $N$ ($1 \le N \le 40,000$)이 주어집니다.
* 두 번째 줄부터 $N$개의 줄에 걸쳐 각 수신 이벤트가 주어집니다:
  * `RECEIVE <msg_id> <biz_key> <amount>`
  * `msg_id`: 메시지 고유 식별자 문자열
  * `biz_key`: 비즈니스 고유 키 문자열
  * `amount`: 집행 금액 정수 ($0 \le amount \le 1,000,000$)

---

## 📤 출력 형식 (Output Format)

각 `RECEIVE` 이벤트마다 다음 형식으로 1줄씩 출력합니다:
```text
MSG <msg_id> BIZ:<biz_key> NAIVE:<naive_status> MSG_ONLY:<mo_status> FULL:<full_status>
```
* 상태값: `EXECUTED`, `SKIPPED_MSG_DUP`, `SKIPPED_BIZ_DUP`

모든 이벤트 처리 후 마지막 줄에 종합 통계(Summary)를 1줄 출력합니다:
```text
SUMMARY TOTAL_MSGS:<N> NAIVE_COST:<naive_cost> MSG_ONLY_COST:<mo_cost> FULL_COST:<full_cost> TOTAL_COST_SAVED:<cost_saved> BIZ_DUPS_BLOCKED:<biz_dups_blocked>
```
* `NAIVE_COST`: NAIVE 컨슈머의 총 집행 금액
* `MSG_ONLY_COST`: MSG_ONLY 컨슈머의 총 집행 금액
* `FULL_COST`: FULL_IDEMPOTENT 컨슈머의 총 집행 금액
* `TOTAL_COST_SAVED`: `NAIVE_COST - FULL_COST` (완전 멱등 컨슈머가 방어해 낸 총 재정적 손실액)
* `BIZ_DUPS_BLOCKED`: FULL_IDEMPOTENT 컨슈머가 2차 비즈니스 키 검사를 통해 `SKIPPED_BIZ_DUP`으로 차단한 횟수 (MSG_ONLY는 뚫렸지만 FULL이 막아낸 건수)

---

## 💡 입출력 예제 (Sample I/O)

### 예제 입력
```text
EVENTS 5
RECEIVE msg_1 order_1001 10000
RECEIVE msg_1 order_1001 10000
RECEIVE msg_2 order_1001 10000
RECEIVE msg_3 order_1002 5000
RECEIVE msg_3 order_1002 5000
```

### 예제 출력
```text
MSG msg_1 BIZ:order_1001 NAIVE:EXECUTED MSG_ONLY:EXECUTED FULL:EXECUTED
MSG msg_1 BIZ:order_1001 NAIVE:EXECUTED MSG_ONLY:SKIPPED_MSG_DUP FULL:SKIPPED_MSG_DUP
MSG msg_2 BIZ:order_1001 NAIVE:EXECUTED MSG_ONLY:EXECUTED FULL:SKIPPED_BIZ_DUP
MSG msg_3 BIZ:order_1002 NAIVE:EXECUTED MSG_ONLY:EXECUTED FULL:EXECUTED
MSG msg_3 BIZ:order_1002 NAIVE:EXECUTED MSG_ONLY:SKIPPED_MSG_DUP FULL:SKIPPED_MSG_DUP
SUMMARY TOTAL_MSGS:5 NAIVE_COST:40000 MSG_ONLY_COST:25000 FULL_COST:15000 TOTAL_COST_SAVED:25000 BIZ_DUPS_BLOCKED:1
```

---

## 힌트 & 핵심 점검 사항
1. **2번째 이벤트 (`msg_1` 재수신)**: 네트워크 ACK 유실로 동일한 `msg_1`이 다시 유입되었습니다. MSG_ONLY와 FULL 모두 `SKIPPED_MSG_DUP`으로 깔끔히 방어합니다.
2. **3번째 이벤트 (`msg_2`, `order_1001`)**: 클라이언트의 결제 연타로 다른 `msg_id`로 동일 주문이 유입되었습니다! MSG_ONLY는 `msg_2`가 처음이라며 또 10,000원을 집행해 버리지만, FULL은 `order_1001`이 이미 처리되었음을 알고 `SKIPPED_BIZ_DUP`으로 차단하여 10,000원을 지켜냅니다!
3. **총 비용 비교**: NAIVE는 40,000원이 지출되었으나 FULL은 정상적인 단 15,000원만 집행하여 무려 25,000원의 중복 지급 사고를 완벽히 막아냈습니다!
