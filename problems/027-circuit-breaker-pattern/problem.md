# [ZeliJudge #027] 옆 동네 서버가 터졌는데 우리 서버까지 죽어요?: 서킷 브레이커(Circuit Breaker)와 장애 격리

## 📌 문제 배경 스토리
쇼핑몰 '젤리마켓'의 백엔드 개발자 젤리는 사용자가 결제할 때 외부 카드사(PG사) API를 호출하여 승인을 받는 결제 서비스를 운영하고 있었습니다.
젤리마켓 서버는 매우 건강했고 트래픽도 평소 수준이었습니다.
그런데 어느 날 오후, 젤리마켓의 모든 서버가 **동시에 뻗어버리는 대참사(연쇄 장애, Cascading Failure)**가 발생했습니다!

사건의 전말은 다음과 같았습니다:
1. 젤리마켓 서버는 문제가 없었으나, **외부 카드사(PG사) 전산망에 화재가 발생**하여 모든 결제 승인 API가 멈췄습니다.
2. 외부 카드사는 응답을 주지 않고 30초 동안 침묵(Timeout)했습니다.
3. 젤리마켓으로 들어온 수백 명의 결제 요청 스레드가 각각 외부 카드사의 30초 타임아웃을 멍하니 기다리며 스레드와 소켓 커넥션을 물고 늘어졌습니다.
4. 순식간에 젤리마켓의 톰캣/FastAPI 워커 스레드 풀(Thread Pool)이 100% 고갈되었습니다.
5. 결과: 외부 카드사 연동과 전혀 상관없는 **메인 페이지 조회, 로그인, 장바구니 담기 등 젤리마켓의 모든 핵심 기능까지 연쇄적으로 마비**되었습니다!

CTO는 긴급 점검 회의실에서 두꺼비집 스위치를 내리는 시늉을 하며 외쳤습니다:
*"젤리 씨! 옆집에 불이 났으면 우리 집 방화벽을 닫아서 불길이 번지지 않게 해야죠!"*
*"가정집에서 세탁기가 합선되면 아파트 전체가 정전되지 않도록 **두꺼비집의 누전 차단기(Circuit Breaker)가 스위치를 딱 내려서 전류를 차단**하잖아요!"*
*"외부 서비스가 연속으로 에러를 뿜으면 서킷을 **열어버려서(OPEN)**, 30초 동안 멍때리지 말고 **즉시 0.001초 만에 실패(Fast Fail)**시키거나 대체 응답을 돌려줘야 우리 서버의 스레드를 지킬 수 있습니다!"*

CTO는 외부 장애가 내부 핵심 서비스로 전파되는 것을 원천 차단하기 위해, **서킷 브레이커 상태 머신(Circuit Breaker FSM) 엔진**을 구현하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

서킷 브레이커는 세 가지 상태(`CLOSED`, `OPEN`, `HALF_OPEN`)를 가지는 유한 상태 머신(FSM)입니다.

### 1. 서킷 브레이커 설정 (`CONFIG FAILURE_THRESHOLD:<N> RECOVERY_TIMEOUT:<timeout_ms> SUCCESS_THRESHOLD:<M>`)
- `FAILURE_THRESHOLD:<N>`: `CLOSED` 상태에서 **연속 $N$회** 실패 시 즉시 `OPEN` 상태로 전환 ($1 \le N \le 1,000$)
- `RECOVERY_TIMEOUT:<timeout_ms>`: `OPEN` 상태로 전환된 시점부터 이 시간(밀리초) 동안은 외부 API를 호출하지 않고 즉시 차단(Fast Fail) ($1 \le timeout\_ms \le 10^9$)
- `SUCCESS_THRESHOLD:<M>`: `HALF_OPEN` 상태에서 **연속 $M$회** 성공 시 정상 상태인 `CLOSED`로 전격 복구 ($1 \le M \le 1,000$)
- 시스템 초기 상태 ($t=0$ 이전): 상태는 `CLOSED`, 연속 실패 횟수는 0입니다.

---

### 2. 요청 도착 및 상태 머신(FSM) 평가 규칙

각 요청은 시각 $t$ (밀리초) 오름차순으로 주어집니다:
`REQ <t> <call_result>`
- `<call_result>`: 만약 외부 API를 실제로 호출했을 때 외부 서버가 돌려줄 가상의 응답 (`SUCCESS` 또는 `FAIL`).

요청이 도착했을 때 서킷 브레이커는 다음 알고리즘에 따라 판정합니다:

#### 단계 1: 상태 확인 및 냉각 시간 만료 검사
- 만약 현재 상태가 `OPEN`이고, 현재 시각 $t \ge open\_time + timeout\_ms$ 라면:
  - 냉각 시간(Recovery Timeout)이 지났으므로 시스템은 시험 가동 모드인 **`HALF_OPEN` 상태로 전환**됩니다 (`state_changes += 1`).
  - `HALF_OPEN`의 연속 성공 카운터를 0으로 초기화합니다.

#### 단계 2: 현재 상태별 액션 수행

1. **현재 상태가 `OPEN`인 경우 (차단 모드)**:
   - 외부 API를 절대로 호출하지 않고, 스레드 낭비 없이 0ms 만에 즉시 거절(Fast Fail)합니다.
   - 출력: `REQ <t> STATE:OPEN ACTION:FAST_FAIL`
   - (`blocked_count += 1`)

2. **현재 상태가 `HALF_OPEN`인 경우 (시험 가동 모드)**:
   - 시험 삼아 외부 API를 실제로 1회 호출해 봅니다 (`<call_result>` 확인).
   - **`<call_result>`가 `SUCCESS`인 경우**:
     - 연속 성공 카운터를 1 증가시킵니다.
     - 출력: `REQ <t> STATE:HALF_OPEN ACTION:HALF_OPEN_CALL:SUCCESS`
     - (`passed_count += 1`)
     - 만약 연속 성공 카운터가 $M$에 도달했다면:
       - 외부 서버가 완전히 복구된 것으로 판단하고 **`CLOSED` 상태로 전환**합니다 (`state_changes += 1`).
       - 연속 실패 카운터를 0으로 리셋합니다.
   - **`<call_result>`가 `FAIL`인 경우**:
     - 아직 외부 서버가 아프므로 즉시 다시 **`OPEN` 상태로 재추락**합니다 (`state_changes += 1`, `open_time = t`).
     - 출력: `REQ <t> STATE:HALF_OPEN ACTION:HALF_OPEN_CALL:FAIL`
     - (`passed_count += 1`, 호출 자체는 통과했으나 실패로 기록)

3. **현재 상태가 `CLOSED`인 경우 (정상 통전 모드)**:
   - 외부 API를 정상적으로 호출합니다.
   - **`<call_result>`가 `SUCCESS`인 경우**:
     - 연속 실패 카운터를 0으로 리셋합니다.
     - 출력: `REQ <t> STATE:CLOSED ACTION:PASSTHROUGH:SUCCESS`
     - (`passed_count += 1`)
   - **`<call_result>`가 `FAIL`인 경우**:
     - 연속 실패 카운터를 1 증가시킵니다.
     - 출력: `REQ <t> STATE:CLOSED ACTION:PASSTHROUGH:FAIL`
     - (`passed_count += 1`)
     - 만약 연속 실패 카운터가 $N$에 도달했다면:
       - 즉시 **`OPEN` 상태로 전환**합니다 (`state_changes += 1`, `open_time = t`).

---

## 📥 입력 형식 (Input)

- 첫째 줄에 서킷 브레이커 설정이 주어집니다:
  `CONFIG FAILURE_THRESHOLD:<N> RECOVERY_TIMEOUT:<timeout_ms> SUCCESS_THRESHOLD:<M>`
- 둘째 줄에 총 요청의 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 셋째 줄부터 $Q$개의 줄에 걸쳐 각 요청 정보가 주어집니다:
  `REQ <t> <call_result>`
  - `<t>`는 $0 \le t \le 10^{12}$ 범위의 단조 증가하는 정수입니다.
  - `<call_result>`는 `SUCCESS` 또는 `FAIL`입니다.

---

## 📤 출력 형식 (Output)

- 각 요청에 대해 처리 결과를 한 줄씩 출력합니다:
  `REQ <t> STATE:<state> ACTION:<action>`
- 모든 요청이 끝난 후 마지막 줄에 종합 통계를 출력합니다:
  `SUMMARY TOTAL:<Q> PASSED:<passed_cnt> BLOCKED:<blocked_cnt> STATE_CHANGES:<change_cnt>`
  - `<passed_cnt>`: 실제로 외부 호출을 시도한 횟수 (`PASSTHROUGH` + `HALF_OPEN_CALL`)
  - `<blocked_cnt>`: 외부 호출을 시도하지 않고 즉시 차단한 횟수 (`FAST_FAIL`)
  - `<change_cnt>`: 상태가 변경된 총 횟수

---

## 💡 입출력 예시 (Example)

### 예시 입력 1
```text
CONFIG FAILURE_THRESHOLD:3 RECOVERY_TIMEOUT:100 SUCCESS_THRESHOLD:2
8
REQ 0 FAIL
REQ 10 FAIL
REQ 20 FAIL
REQ 30 SUCCESS
REQ 119 FAIL
REQ 120 SUCCESS
REQ 130 SUCCESS
REQ 140 SUCCESS
```

### 예시 출력 1
```text
REQ 0 STATE:CLOSED ACTION:PASSTHROUGH:FAIL
REQ 10 STATE:CLOSED ACTION:PASSTHROUGH:FAIL
REQ 20 STATE:CLOSED ACTION:PASSTHROUGH:FAIL
REQ 30 STATE:OPEN ACTION:FAST_FAIL
REQ 119 STATE:OPEN ACTION:FAST_FAIL
REQ 120 STATE:HALF_OPEN ACTION:HALF_OPEN_CALL:SUCCESS
REQ 130 STATE:HALF_OPEN ACTION:HALF_OPEN_CALL:SUCCESS
REQ 140 STATE:CLOSED ACTION:PASSTHROUGH:SUCCESS
SUMMARY TOTAL:8 PASSED:6 BLOCKED:2 STATE_CHANGES:3
```

### 예시 설명 1
- $t=0, 10, 20$: 3회 연속 실패로 $t=20$에 `CLOSED -> OPEN` 전환 (`state_changes = 1`, 회복 만료 시점: $20 + 100 = 120$ms).
- $t=30, 119$: 아직 $120$ms 이전이므로 외부 호출 없이 즉시 차단 (`FAST_FAIL`, `blocked_cnt = 2`).
- $t=120$: $t \ge 120$ms로 냉각 시간 경과! `OPEN -> HALF_OPEN` 전환 (`state_changes = 2`). 시험 호출 성공 1회.
- $t=130$: 시험 호출 2회째 성공! 연속 2회 도달하여 `HALF_OPEN -> CLOSED` 정상 복구 (`state_changes = 3`).
- $t=140$: 정상 `CLOSED` 상태에서 호출 성공.
- 최종 통계: 총 8건 중 6건 통과, 2건 차단, 상태 변경 3회!
