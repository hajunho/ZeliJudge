# #057 한 번만 결제했는데 왜 통장에서 돈이 두 번 빠져나가요?!: 네트워크 타임아웃과 API 멱등성 (Idempotency Key & Deduplication)

---

## 1. 현실 세계 비유: 영수증 종이가 떨어진 햄버거집 카운터 vs 스마트 키오스크

손님이 햄버거 가게에서 치즈버거 세트(7,000원)를 주문하는 상황을 상상해 보세요.

```text
❌ 멱등성 없는 카운터 (NAIVE):
   1. 손님: "치즈버거 세트 1개(7,000원) 주세요!" (1만 원 지폐 전달)
   2. 점원: 돈을 금고에 넣고 포스기에 주문을 정상 접수했습니다.
   3. 점원: 영수증을 주려는데 포스기 프린터 종이가 똑 떨어졌습니다! (네트워크 응답 유실 / Lost ACK)
   4. 손님: (5분 동안 영수증을 못 받아 멍하니 서 있다가) "어? 돈이 안 들어갔나?"
   5. 손님: "치즈버거 세트 1개(7,000원) 주세요!" (또 1만 원 지폐 전달, 재시도)
   6. 점원: "네 감사합니다!" 하고 돈을 또 금고에 넣고 버거 2세트를 주방에 주문 넣어버립니다!
   7. 결과: 손님은 버거 1개 먹으려다 14,000원이 뜯겼고, 통장에선 돈이 두 번 빠져나갔습니다!

✅ 주문 번호표가 찍힌 스마트 키오스크 (IDEMPOTENT):
   1. 손님: 고유한 주문 번호표 [ORD-9821](Idempotency Key)을 제시하며 결제를 요청합니다.
   2. 키오스크: [ORD-9821]을 금고에 기록하고 7,000원 결제 완료!
   3. 키오스크: 통신망 일시 순단으로 손님 스마트폰 화면에 "타임아웃(Timeout)" 에러가 뜹니다.
   4. 손님: 불안해서 같은 주문 번호표 [ORD-9821]로 재시도(Retry) 결제를 누릅니다.
   5. 키오스크: "잠깐! [ORD-9821]은 10초 전에 이미 정상 결제(TX_000001)됐잖아?"
   6. 키오스크: 돈을 또 빼지 않고, 방금 전 성공했던 영수증(TX_000001)을 그대로 다시 화면에 띄워줍니다!
   7. 결과: 손님이 재시도 버튼을 100번 연타해도 결제는 정확히 단 1번만 일어납니다!
```

---

## 2. 문제 개요

당신은 대규모 이커머스 및 글로벌 결제 게이트웨이(PG사)의 코어 백엔드 엔지니어입니다.  
모바일 환경에서는 터널 진입, 기지국 핸드오버, Wi-Fi 불안정 등으로 인해 **"서버는 결제를 성공시켰으나 클라이언트는 응답 패킷을 받지 못하는 네트워크 타임아웃"**이 빈번하게 발생합니다.

이때 클라이언트 앱이 단순 재시도(Retry)를 날릴 때,
1. 멱등성을 고려하지 않은 **단순 결제 서버(NAIVE)**와
2. `Idempotency-Key` 헤더와 분산 락, 결과 캐싱을 결합한 **멱등성 보장 서버(IDEMPOTENT)**

두 아키텍처의 동작 과정을 시뮬레이션하고, 고객의 중복 결제(`DUP_CHARGES`) 방지 및 금융 손실 방어액(`FINANCIAL_LOSS_PREVENTED`)을 정밀 계측하세요.

---

## 3. 입력 형식

표준 입력(`sys.stdin`)으로 시스템 설정과 초기 유저 잔액, 결제 요청 스트림이 주어집니다.

```text
IDEMPOTENCY_TTL_MS <ttl_ms>
BALANCES
<user_id> <balance>
<user_id> <balance>
...
REQUESTS
<req_id> <user_id> <amount> <idempotency_key> <timestamp> <duration_ms>
<req_id> <user_id> <amount> <idempotency_key> <timestamp> <duration_ms>
...
```

### 파라미터 규격
- `IDEMPOTENCY_TTL_MS <ttl_ms>`: 멱등성 키 캐시의 유효 시간 (ms 단위, 정수, 기본값: `86400000` = 24시간).
- `BALANCES`: 유저별 초기 보유 잔액 목록. (유저 잔액이 지정되지 않은 경우 기본값 `0`).
- `REQUESTS`: 클라이언트 결제 요청 목록.
  - `req_id`: 고유 요청 식별자 문자열 (예: `req-1`, `req-2`).
  - `user_id`: 결제를 시도하는 유저 ID 문자열.
  - `amount`: 결제 요청 금액 (양의 정수).
  - `idempotency_key`: 클라이언트가 제공한 멱등성 키 (문자열 또는 미제공 시 `NONE`).
  - `timestamp`: 요청이 서버에 도달한 시각 (ms 단위 정수, $\ge 0$).
  - `duration_ms`: 서버가 결제 및 DB 트랜잭션을 처리하는 데 걸리는 시간 (ms 단위 정수, 기본값 `50`).
    - 즉, 시각 `T`에 시작된 요청은 `T + duration_ms` 시점에 완료됩니다.

---

## 4. 시뮬레이션 상세 규칙

요청들은 도달 시각(`timestamp`) 순서대로 처리됩니다. (시각이 같을 경우 입력 파일에 먼저 등장한 순서대로 우선 처리).

### 모델 A: 단순 결제 모델 (NAIVE)
- 멱등성 키나 분산 락을 전혀 검증하지 않고, 들어오는 모든 요청을 독립적인 결제로 취급합니다.
- 요청 시각 `T`에 유저의 현재 잔액(`balance`)을 확인합니다:
  - **`balance >= amount`인 경우**:
    - 즉시 잔액에서 `amount`를 차감하고, `SUCCESS` 상태를 반환합니다.
    - 단, 해당 요청이 `idempotency_key != "NONE"`이고, **과거 `(user_id, idempotency_key)`에 대해 이미 `SUCCESS` 처리된 이력이 있으며, 그 유효 기간(`T <= 이전_완료시각 + ttl_ms`) 내에 재요청된 경우**:
      - 이는 중복 결제(`duplicate_charges += 1`)로 판정되며, 차감된 금액은 초과 청구액(`overcharged_amount += amount`)에 누적됩니다.
  - **`balance < amount`인 경우**:
    - 잔액을 차감하지 않고 `INSUFFICIENT_FUNDS` 상태를 반환합니다.

### 모델 B: 멱등성 보장 모델 (IDEMPOTENT)
- 멱등성 상태 머신은 `IN_FLIGHT (처리 중)`과 `COMPLETED_CACHE (완료 캐시)`를 엄격하게 관리합니다.
- 요청 시각 `T`에 도달하면, 먼저 `완료시각 <= T`인 모든 처리 중(`IN_FLIGHT`) 작업들을 완료 캐시(`COMPLETED_CACHE`)로 전이시킵니다.
- `idempotency_key == "NONE"`인 경우:
  - 멱등키가 없으므로 NAIVE와 동일하게 일반 결제로 실행합니다. (성공 시 `SUCCESS`, 잔액 부족 시 `INSUFFICIENT_FUNDS`).
- `idempotency_key != "NONE"`인 경우:
  1. **제1 방어선 (동시 중복 클릭 방어)**:
     - 해당 키가 현재 `IN_FLIGHT` 상태(이전 요청이 아직 실행 중)라면:
     - $\to$ `CONFLICT_IN_FLIGHT` 반환 (HTTP 409 Conflict, 잔액 차감 없음).
  2. **제2 방어선 (과거 완료 이력 확인 & TTL)**:
     - 해당 키가 `COMPLETED_CACHE`에 존재하는 경우:
       - 만약 `T > 완료시각 + ttl_ms` (TTL 만료): 캐시에서 삭제하고 3단계(신규 요청)로 진행.
       - 만약 유효 기간 내라면:
         - **파라미터 변조 검증**: 저장된 페이로드(`user_id`, `amount`)와 현재 요청의 정보가 1개라도 다르면:
           - $\to$ `PAYLOAD_MISMATCH` 반환 (HTTP 422 Unprocessable Entity, 잔액 차감 없음).
         - 페이로드가 정확히 일치한다면:
           - 과거 성공한 결제라면 $\to$ `CACHED_SUCCESS` 반환 (잔액 재차감 0회, 기존 영수증 반환).
           - 과거 잔액 부족 실패라면 $\to$ `CACHED_INSUFFICIENT_FUNDS` 반환 (동일한 실패 상태 보존).
  3. **제3 방어선 (신규 결제 실행 및 락 획득)**:
     - 키가 진행 중이지도 않고 유효한 캐시도 없다면, `IN_FLIGHT`에 등록하고 신규 실행합니다.
     - 잔액 검사:
       - `balance >= amount`: 잔액 차감 후 `SUCCESS` 기록.
       - `balance < amount`: 잔액 유지 후 `INSUFFICIENT_FUNDS` 기록.
     - 작업 완료 시각은 `T + duration_ms`로 설정됩니다.

---

## 5. 출력 형식

모든 요청의 처리 결과와 요약 통계를 표준 출력(`sys.stdout`)으로 출력합니다.

```text
REQ <req_id> NAIVE:<naive_status> IDEM:<idem_status>
...
SUMMARY NAIVE CHARGES:<successful_charges> DUP_CHARGES:<duplicate_charges> OVERCHARGED:<overcharged_amount>
SUMMARY IDEM CHARGES:<idem_success_charges> CACHED:<cached_responses> CONFLICTS:<conflict_in_flight> MISMATCHES:<payload_mismatches>
SUMMARY FINANCIAL_LOSS_PREVENTED:<overcharged_amount> DUP_CHARGES_PREVENTED:<duplicate_charges>
```

---

## 6. 입출력 예시

### 예시 입력
```text
IDEMPOTENCY_TTL_MS 86400000
BALANCES
user_1 10000
REQUESTS
req-1 user_1 3000 k1 100 50
req-2 user_1 3000 k1 120 50
req-3 user_1 3000 k1 200 50
```

### 예시 출력
```text
REQ req-1 NAIVE:SUCCESS IDEM:SUCCESS
REQ req-2 NAIVE:SUCCESS IDEM:CONFLICT_IN_FLIGHT
REQ req-3 NAIVE:SUCCESS IDEM:CACHED_SUCCESS
SUMMARY NAIVE CHARGES:3 DUP_CHARGES:2 OVERCHARGED:6000
SUMMARY IDEM CHARGES:1 CACHED:1 CONFLICTS:1 MISMATCHES:0
SUMMARY FINANCIAL_LOSS_PREVENTED:6000 DUP_CHARGES_PREVENTED:2
```

### 결과 해석
- **NAIVE 모델**:
  - `req-1`에서 3,000원 정상 결제 (잔액 7,000원).
  - `req-2`는 `req-1`이 처리 중인 120ms에 들어왔으나 락이 없어 또 3,000원 결제 (잔액 4,000원, 중복 결제!).
  - `req-3`는 네트워크 타임아웃 후 재시도했으나 또 3,000원 결제 (잔액 1,000원, 삼중 결제!).
  - 총 3회 결제되어 6,000원이 초과 인출되었습니다.
- **IDEMPOTENT 모델**:
  - `req-1`에서 3,000원 정상 결제 (잔액 7,000원).
  - `req-2`는 처리 중(`IN_FLIGHT`) 경합으로 `CONFLICT_IN_FLIGHT` 즉시 기각.
  - `req-3`는 완료 캐시를 감지하여 0원의 추가 차감 없이 `CACHED_SUCCESS`로 기존 성공 결과 반환!
  - 최종 6,000원의 금융 손실과 2회의 불필요한 중복 결제를 완벽히 방어해 냈습니다.

---

## 7. 제약 조건 및 복잡도 요구사항
- 총 요청 수 $E \le 100,000$.
- 최소 힙(Priority Queue) 또는 효율적인 이벤트 정렬을 사용하여 $O(E \log E)$ 이하의 시간 복잡도로 완료해야 합니다.
- 5.0초 제한 시간 내에 통과해야 합니다.
