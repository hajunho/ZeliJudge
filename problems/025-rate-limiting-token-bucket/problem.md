# [ZeliJudge #025] 1초에 1,000명이 몰려왔다!: 처리율 제한 장치(Rate Limiting)와 토큰 버킷(Token Bucket)의 마법

## 📌 문제 배경 스토리
AI 스타트업 '젤리AI'의 백엔드 개발자 젤리는 사용자가 질문을 남기면 답변을 생성해 주는 무료 AI 챗봇 API를 출시했습니다.
오픈하자마자 커뮤니티에서 폭발적인 인기를 끌며 수많은 사용자가 접속했습니다.
하지만 30분 뒤, 젤리의 휴대폰으로 AWS 및 결제 알림 폭탄이 쏟아졌습니다:

1. 어떤 악의적인 사용자가 파이썬 스크립트로 **초당 500회의 무한 질문 매크로(봇)**를 돌렸습니다.
2. 데이터베이스 커넥션 풀이 1초 만에 100% 고갈되었고, OpenAI 연동 API 비용은 10분에 수백만 원이 청구되었습니다!
3. 정작 일반 선량한 사용자들은 *"서버 응답 없음 (504 Gateway Timeout)"* 에러를 보며 튕겨나갔습니다!

젤리는 부랴부랴 코드를 고쳤습니다:
```python
# [젤리가 작성한 단순 카운터]
if request_count_per_second > 10:
    return "429 Too Many Requests"
```
하지만 이 단순한 방식(Fixed Window Counter)은 치명적인 결함이 있었습니다:
- 매초 0.9초에 10개, 1.0초에 10개가 몰리면 **0.2초 사이에 20개의 요청이 서버를 강타**하여 서버가 여전히 다운되었습니다.
- 또한 평소에 요청을 아예 안 보내던 사용자가 검색창에 자동완성으로 3~4개의 검색어를 빠르게 타이핑하는 **정상적인 일시적 버스트(Burst) 트래픽**까지 융통성 없이 모조리 429 에러로 튕겨내 버렸습니다!

CTO는 젤리에게 글로벌 테크 기업(AWS, Stripe, Cloudflare)의 표준 아키텍처를 전수했습니다:
*"젤리 씨! 처리율 제한(Rate Limiting)의 황제는 바로 **토큰 버킷(Token Bucket) 알고리즘**이에요!"*
*"일정한 용량($C$)을 가진 물통에 일정한 속도(매 $REFILL\_MS$마다 1개)로 토큰이 채워집니다."*
*"평소에 요청이 없었을 때는 토큰이 가득 차 있으므로, 갑자기 3~5개의 요청이 순간적으로 폭주(Burst)해도 부드럽게 전부 수용해 줍니다!"*
*"하지만 토큰이 바닥나면 칼같이 `429 Too Many Requests`와 함께 **다음 토큰이 충전될 때까지 몇 밀리초를 기다려야 하는지(`Retry-After`)** 정확히 안내하여 서버를 완벽히 보호할 수 있습니다!"*

CTO는 트래픽 폭주로부터 서버를 지키는 무결점 API 게이트웨이를 구축하기 위해, **토큰 버킷 처리율 제한 시뮬레이터**를 개발하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

### 1. 버킷 설정 (`CONFIG CAPACITY:<C> REFILL_MS:<ms>`)
- `CAPACITY:<C>`: 버킷의 최대 토큰 수용 용량 $C$ ($1 \le C \le 10^9$)
- `REFILL_MS:<ms>`: 토큰 1개가 충전되는 데 소요되는 시간 (밀리초, $1 \le ms \le 10^6$)
- 시간 $t = 0$ 시점에 버킷은 **최대 용량 $C$개의 토큰으로 가득 채워져 있습니다** (`tokens = C`, 마지막 충전 기준 시각 $t_{last} = 0$).

---

### 2. 요청 도착 및 지연 충전(Lazy Refill) 알고리즘
요청은 도착 시각 $t$ (밀리초) 오름차순으로 주어집니다:
`REQ <timestamp>` ($t \ge 0$)

요청이 도착한 시각 $t$에 토큰 버킷은 다음 4단계를 순서대로 거칩니다:

1. **시간 경과에 따른 토큰 충전**:
   - 마지막 충전 기준 시각 $t_{last}$로부터 경과한 시간 $\Delta t = t - t_{last}$
   - 새롭게 생성된 토큰 수:
     $$\Delta tokens = \lfloor \frac{\Delta t}{REFILL\_MS} \rfloor$$
   - 버킷 내 토큰 충전 (단, 최대 용량 $C$를 초과할 수 없음):
     $$tokens = \min(C, tokens + \Delta tokens)$$
   - 충전 기준 시각 갱신:
     - 만약 버킷이 가득 찬 경우 ($tokens == C$): 자투리 시간을 버리고 현재 시각으로 리셋 ($t_{last} = t$)
     - 가득 차지 않은 경우: 충전에 사용된 시간만큼만 전진 ($t_{last} = t_{last} + \Delta tokens \times REFILL\_MS$)  
       *(남은 자투리 시간은 다음 요청을 위해 완벽히 보존됨)*

2. **토큰 소비 및 허용/차단 판정**:
   - **승인 (`ALLOWED`)**:
     - 현재 $tokens \ge 1$인 경우:
     - 토큰을 1개 차감하고 ($tokens = tokens - 1$) 요청을 승인합니다:
       `REQ <t> ALLOWED REMAINING:<tokens>`
   - **차단 (`THROTTLED`)**:
     - 현재 $tokens < 1$ (토큰 0개)인 경우:
     - 요청이 거절(HTTP 429)되며, 다음 토큰 1개가 완충될 때까지 필요한 대기 시간을 계산합니다:
       $$next\_wait = REFILL\_MS - (t - t_{last})$$
     - 토큰 차감 없이 다음 결과를 출력합니다:
       `REQ <t> THROTTLED RETRY_AFTER:<next_wait>ms`

---

## 📥 입력 형식 (Input)

- 첫째 줄에 버킷 설정이 주어집니다:
  `CONFIG CAPACITY:<C> REFILL_MS:<ms>`
- 둘째 줄에 총 요청의 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 셋째 줄부터 $Q$개의 줄에 걸쳐 각 요청의 도착 시각 $t$가 주어집니다:
  `REQ <t>` ($0 \le t \le 10^{12}$, $t$는 이전 요청 이상으로 단조 증가함)

---

## 📤 출력 형식 (Output)

- 각 요청에 대해 한 줄씩 처리 결과를 출력합니다:
  `REQ <t> ALLOWED REMAINING:<tokens>` 또는 `REQ <t> THROTTLED RETRY_AFTER:<next_wait>ms`
- 모든 요청이 끝난 후 마지막 줄에 종합 통계를 출력합니다:
  `SUMMARY TOTAL:<Q> ALLOWED:<allowed_cnt> THROTTLED:<throttled_cnt>`

---

## 💡 입출력 예시 (Example)

### 예시 입력 1
```text
CONFIG CAPACITY:3 REFILL_MS:100
7
REQ 0
REQ 10
REQ 20
REQ 30
REQ 150
REQ 180
REQ 500
```

### 예시 출력 1
```text
REQ 0 ALLOWED REMAINING:2
REQ 10 ALLOWED REMAINING:1
REQ 20 ALLOWED REMAINING:0
REQ 30 THROTTLED RETRY_AFTER:70ms
REQ 150 ALLOWED REMAINING:0
REQ 180 THROTTLED RETRY_AFTER:20ms
REQ 500 ALLOWED REMAINING:2
SUMMARY TOTAL:7 ALLOWED:5 THROTTLED:2
```

### 예시 설명 1
- $t=0$: 버킷 풀(3개). 1개 써서 잔여 2개 (`ALLOWED REMAINING:2`).
- $t=10$: 충전 없음. 1개 써서 잔여 1개 (`ALLOWED REMAINING:1`).
- $t=20$: 충전 없음. 1개 써서 잔여 0개 (`ALLOWED REMAINING:0`). 버킷 텅 빔!
- $t=30$: 충전 없음. 토큰 0개이므로 차단! $t=100$에 다음 토큰이 나오므로 남은 시간은 $100 - 30 = 70$ms (`THROTTLED RETRY_AFTER:70ms`).
- $t=150$: $150$ms 경과로 1개 충전($t_{last}=100$). 1개 즉시 소진 (`ALLOWED REMAINING:0`).
- $t=180$: $180 - 100 = 80$ms 경과로 충전 안 됨. 차단! 다음 토큰 충전($t=200$)까지 20ms 남음 (`THROTTLED RETRY_AFTER:20ms`).
- $t=500$: 한참 뒤에 와서 버킷 3개 완충. 1개 써서 잔여 2개 (`ALLOWED REMAINING:2`).
- 최종 7건 중 5건 통과, 2건 차단!
