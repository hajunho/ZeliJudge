# [ZeliJudge #024] 새로고침 5번 눌렀더니 결제가 5번 됐어요?!: 멱등성(Idempotency)과 멱등키의 방패

## 📌 문제 배경 스토리
쇼핑몰 '젤리마켓'의 백엔드 개발자 젤리는 포인트 결제 및 주문 처리 API를 개발했습니다.
젤리는 사용자가 결제 요청을 보내면 단순히 계좌 잔액을 확인하고 차감하는 일반적인 `POST /api/pay` 엔드포인트를 구현했습니다:

```python
# [젤리가 작성한 단순 결제 엔드포인트]
@app.post("/api/pay")
def process_payment(amount: int):
    if user.balance >= amount:
        user.balance -= amount
        return {"status": "CHARGED", "balance": user.balance}
    else:
        return {"status": "INSUFFICIENT"}
```

젤리는 생각했습니다:
*"결제 버튼 누르면 잔액 깎고 성공 리턴하면 끝이지! 뭐 다른 게 필요한가?"*

하지만 서비스 오픈 첫날, 대형 결제 사고가 터졌습니다:
1. 어떤 고객이 40,000원짜리 상품을 구매하기 위해 **[결제하기]** 버튼을 눌렀습니다.
2. 서버는 결제를 정상 처리하여 40,000원을 깎았으나, 고객의 스마트폰 와이파이가 0.1초 동안 끊겨서 성공 응답 패킷이 고객의 폰에 도착하지 못했습니다.
3. 고객의 폰 화면에는 *"통신 지연 중... 잠시만 기다려주세요"* 팝업이 떴고, 당황한 고객은 **[새로고침]을 누르고 결제 버튼을 3번 연속 광클**했습니다!
4. 젤리의 순진한 서버는 이 요청들을 각각 "새로운 결제"로 인식하여, **동일한 주문에 대해 총 3번(120,000원)을 중복 결제(Double Charge)**해 버렸습니다!
5. 고객은 통장에 있던 100,000원이 순식간에 바닥나고 마이너스가 되어 고객센터로 전화해 오열했습니다!

CTO는 긴급 회의를 소집하여 젤리를 호출했습니다:
*"젤리 씨! 분산 네트워크 환경에서는 패킷이 유실되거나 지연되어 클라이언트가 재시도(Retry)하는 일이 일상다반사예요!"*
*"동일한 요청을 한 번 실행하든, 100번 재시도하든 시스템의 최종 결과가 항상 똑같이 유지되는 성질을 **멱등성(Idempotency)**이라고 합니다!"*
*"클라이언트가 요청 헤더에 고유한 일회용 토큰인 **멱등키(Idempotency-Key)**를 실어 보내도록 하고, 서버는 이미 처리된 멱등키가 다시 들어오면 **실제 결제를 다시 실행하지 않고 이전에 저장해 둔 응답을 그대로 돌려주는 캐시 재생(Cached Replay)**을 해야 한다고요!"*

CTO는 멱등키의 강력한 중복 결제 방어 효과를 검증하기 위해,
1. 멱등키 없이 재시도 요청을 그대로 받아 중복 과금 참사가 발생하는 `NAIVE` 엔진
2. 멱등키를 활용하여 최초 1회만 결제하고 재시도는 안전하게 캐시 응답하는 `IDEMPOTENT` 엔진
두 엔진을 대조 시뮬레이션하는 **멱등 결제 검증 엔진**을 구현하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

사용자의 초기 계좌 잔액(`INIT_BALANCE`)이 주어지며, 이후 $Q$개의 결제 요청이 순차적으로 들어옵니다:
`REQ <idempotency_key> <amount>`

- `<idempotency_key>`: 1~50자의 고유 문자열. (단, 멱등키가 없는 레거시 요청은 `-`로 주어짐)
- `<amount>`: 결제 요청 금액 (양의 정수).

---

### 1. NAIVE 엔진 (멱등성 없는 무차별 결제)
- 멱등키 존재 여부와 무관하게, 요청이 도착할 때마다 무조건 현재 잔액을 확인하고 결제를 시도합니다:
  - 현재 잔액 $\ge amount$ 이면: 잔액에서 $amount$를 실제로 차감하고 결과는 `CHARGED`
  - 현재 잔액 $< amount$ 이면: 결제 실패, 잔액 변동 없이 결과는 `INSUFFICIENT`
- 판정 결과: `NAIVE:<결과>`

---

### 2. IDEMPOTENT 엔진 (멱등키 기반 안전 결제)
- `<idempotency_key>`가 `-` (키 없음)인 경우:
  - 멱등키가 없으므로 매번 실제로 결제를 시도합니다.
  - 잔액 충분 시 차감(`CHARGED`), 부족 시 거절(`INSUFFICIENT`)
  - 결과 포맷: `NO_KEY:<결과>`
- `<idempotency_key>`가 유효한 문자열인 경우:
  1. **최초 실행 (`FIRST_RUN`)**:
     - 해당 멱등키가 서버에 처음 접수된 경우입니다.
     - 실제로 잔액을 확인하고 결제를 수행합니다 (충분 시 차감 `CHARGED`, 부족 시 거절 `INSUFFICIENT`).
     - 이 판정 결과를 해당 멱등키와 함께 메모리 캐시에 영구 보관합니다.
     - 결과 포맷: `FIRST_RUN:<결과>`
  2. **캐시 재생 (`CACHED_REPLAY`)**:
     - 해당 멱등키가 이미 이전에 처리되어 캐시에 기록이 존재하는 경우입니다 (네트워크 재시도, 중복 클릭 등).
     - **어떤 경우에도 실제 잔액 차감이나 상태 변경을 일절 수행하지 않습니다!**
     - 최초 실행 당시 보관해 두었던 이전 결과(`CHARGED` 또는 `INSUFFICIENT`)를 캐시에서 꺼내어 그대로 반환합니다.
     - 결과 포맷: `CACHED_REPLAY:<이전결과>`

---

## 📥 입력 형식 (Input)

- 첫째 줄에 계좌의 초기 잔액이 주어집니다:
  `INIT_BALANCE <initial_balance>` ($1 \le initial\_balance \le 10^{12}$)
- 둘째 줄에 총 결제 요청의 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 셋째 줄부터 $Q$개의 줄에 걸쳐 각 요청 정보가 주어집니다:
  `REQ <idempotency_key> <amount>`
  - `<amount>`는 $1 \le amount \le 10^9$ 범위의 정수입니다.

---

## 📤 출력 형식 (Output)

- 각 요청에 대해 두 엔진의 처리 결과를 한 줄씩 출력합니다:
  `TX NAIVE:<naive_res> IDEMPOTENT:<status>:<res>`
- 모든 요청이 끝난 후 마지막 줄에 최종 요약을 출력합니다:
  `SUMMARY NAIVE_BAL:<bal> IDEMPOTENT_BAL:<bal> DIFF:<diff>`
  - `<diff>`: 멱등키 덕분에 고객이 중복 과금당하지 않고 지켜낸 금액 (`IDEMPOTENT_BAL - NAIVE_BAL`).

---

## 💡 입출력 예시 (Example)

### 예시 입력 1
```text
INIT_BALANCE 100000
4
REQ pay-uuid-001 40000
REQ pay-uuid-001 40000
REQ pay-uuid-001 40000
REQ pay-uuid-002 70000
```

### 예시 출력 1
```text
TX NAIVE:CHARGED IDEMPOTENT:FIRST_RUN:CHARGED
TX NAIVE:CHARGED IDEMPOTENT:CACHED_REPLAY:CHARGED
TX NAIVE:INSUFFICIENT IDEMPOTENT:CACHED_REPLAY:CHARGED
TX NAIVE:INSUFFICIENT IDEMPOTENT:FIRST_RUN:INSUFFICIENT
SUMMARY NAIVE_BAL:20000 IDEMPOTENT_BAL:60000 DIFF:40000
```

### 예시 설명 1
- **1번째 요청** (`pay-uuid-001 40000`):
  - NAIVE: 잔액 100,000에서 40,000 차감 -> 잔액 60,000원 (`CHARGED`)
  - IDEMPOTENT: 최초 실행, 40,000 차감 -> 잔액 60,000원 (`FIRST_RUN:CHARGED`)
- **2번째 요청** (`pay-uuid-001 40000` 재전송):
  - NAIVE: 60,000에서 또 40,000 차감 -> 잔액 20,000원 (`CHARGED`)
  - IDEMPOTENT: 이미 처리된 키! 잔액 차감 없이 최초 결과 반환 (`CACHED_REPLAY:CHARGED`, 잔액 60,000 유지!)
- **3번째 요청** (`pay-uuid-001 40000` 또 재전송):
  - NAIVE: 잔액 20,000으로 40,000원 부족 -> 실패 (`INSUFFICIENT`)
  - IDEMPOTENT: 캐시 재생! 잔액 변동 없이 최초 성공 결과 반환 (`CACHED_REPLAY:CHARGED`)
- **4번째 요청** (`pay-uuid-002 70000` 새 결제):
  - NAIVE: 잔액이 20,000원밖에 안 남아 새 결제 실패 (`INSUFFICIENT`)
  - IDEMPOTENT: 잔액이 60,000원이라 70,000원 부족 -> 실패 (`FIRST_RUN:INSUFFICIENT`)
- **최종 요약**:
  - NAIVE는 중복 결제로 20,000원만 남았지만, IDEMPOTENT는 60,000원을 온전히 보존하여 고객의 돈 40,000원을 지켜냈습니다!
