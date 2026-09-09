# #052 서버가 잠깐 멈췄는데 재시도가 폭풍처럼 몰아쳐요?!: 재시도 폭풍(Retry Storm)과 지수 백오프 + 지터(Exponential Backoff with Jitter)

---

## 1. 현실 세계 비유: 고장 난 지하철 개찰구와 1,000명의 카드 연타 손님들

출근길 신도림역의 지하철 개찰구를 상상해 보세요.

```text
❌ 무지성 즉시 재시도 (IMMEDIATE):
   개찰구 단말기(서버)가 1초 동안 랙(Lag)이 걸려 카드가 인식이 안 됩니다.
   손님 1,000명이 카드를 떼지 않고 "띡띡띡띡!" 1초에 10번씩 미친 듯이 연타합니다.
   순식간에 10,000개의 신호가 단말기 메인보드로 쏟아져 들어가 단말기 CPU가 타버립니다(영구 사망).

❌ 고정 간격 백오프 (FIXED - 동기화 파동의 저주):
   역무원이 다급하게 방송합니다: "손님 여러분, 2초 쉬었다가 다시 찍어주세요!"
   그러자 1,000명이 숨을 죽이고 2초를 센 뒤, 정확히 2초가 되는 순간 동시에 "띡!" 카드를 찍습니다.
   동시에 1,000개의 전류가 유입되어 단말기 퓨즈가 또 날아갑니다.
   2초마다 거대한 쓰나미(Synchronization Waves / Resonating Thundering Herd)가 규칙적으로 단말기를 강타합니다!

✅ 지수 백오프 + 완전 지터 (FULL_JITTER):
   역무원이 안내합니다: "각자 마음속으로 1~8초 사이 아무 숫자나 생각하시고, 그 시간만큼 쉬었다가 제각각 찍으세요!"
   어떤 사람은 1초 뒤, 어떤 사람은 2.5초 뒤, 어떤 사람은 4초 뒤, 어떤 사람은 7초 뒤에 제각각 카드를 찍습니다.
   1,000명의 폭발적인 트래픽이 시간 축 전체로 부드럽게 평탄화(Flattening)되어 분산됩니다.
   개찰구는 초당 5명씩 무리 없이 여유롭게 처리하며, 1,000명 전원이 100% 안전하게 지하철을 탑니다!
```

마이크로서비스(MSA)와 분산 시스템에서 가장 흔하게 발생하는 대형 장애 중 하나는  
**"외부 서비스나 DB가 3초 동안 잠깐 멈췄는데, 수만 대의 클라이언트가 동시에 재시도(Retry)를 날려서 복구 자체를 불가능하게 만드는 재시도 폭풍(Retry Storm)"**입니다.

AWS, Google Cloud, Netflix 같은 빅테크 기업들이 전사 마이크로서비스 호출 클라이언트에  
**"Exponential Backoff with Full Jitter"**를 강제하는 이유를 시뮬레이션을 통해 체득해 봅시다.

---

## 2. 문제 개요

당신은 대규모 결제 및 주문 게이트웨이의 시스템 안정성 엔지니어(SRE)입니다.  
결제 승인 서버가 일시적인 장애 윈도우(`SERVER_DOWN_WINDOW`)를 겪은 후 복구될 때,  
클라이언트의 3대 재시도 전략(**IMMEDIATE**, **FIXED**, **FULL_JITTER**)을 동일한 트래픽에 대해 시뮬레이션하고,  
재시도 폭풍에 따른 과부하 탈락률과 지터 도입에 따른 신뢰성 개선도(`JITTER_RELIABILITY_ADVANTAGE`)를 정밀 계측하세요.

### 시뮬레이션 상세 규칙

#### 1. 인프라 환경
- `SERVER_CAPACITY <cap>`: 서버가 단위 시간(정수 초 $t$)당 정상 처리할 수 있는 최대 요청 수 ($1 \le cap \le 1,000$).
- `SERVER_DOWN_WINDOW <start_t> <end_t>`: 서버의 일시 장애 구간 (초 단위, $start\_t \le t < end\_t$).
  - 이 구간 동안 서버의 가용 용량은 `0`이며, 인입되는 모든 요청은 서버 장애 실패(`DOWN_FAIL`)로 처리됩니다.
  - $t < start\_t$ 또는 $t \ge end\_t$ 구간에는 서버가 정상 가동되며, 초당 최대 $cap$개의 요청을 수용합니다.
- 특정 시각 $t$에 서버가 정상일 때:
  - 해당 시각에 도착한 순서대로 먼저 들어온 $cap$개는 `SUCCESS`로 완료됩니다.
  - $cap$개를 초과하여 들어온 요청은 용량 초과 과부하 실패(`OVERLOAD_FAIL`)로 처리됩니다.

#### 2. 재시도 파라미터
- `MAX_ATTEMPTS <max_attempts>`: 최대 시도 횟수 ($1 \le max\_attempts \le 10$). 최초 시도는 $attempt = 1$입니다.
- `BASE_DELAY_SEC <base_delay>`: 기본 지연 시간 ($1 \le base\_delay \le 60$).
- `CAP_DELAY_SEC <cap_delay>`: 최대 지연 시간 ($1 \le cap\_delay \le 300$).

#### 3. 세 가지 재시도 전략 ($attempt < MAX\_ATTEMPTS$일 때 다음 재시도 시각 $next\_t$)

1. **`IMMEDIATE` (무지성 즉시 재시도)**:
   - 지연 시간 없이 동일 시각에 즉시 재시도:
     $$next\_t = t$$
   - 같은 시각 $t$의 대기열 맨 뒤로 들어가 순차 재시도됩니다.

2. **`FIXED` (고정 간격 백오프)**:
   - 고정된 시간 뒤에 재시도:
     $$next\_t = t + BASE\_DELAY\_SEC$$

3. **`FULL_JITTER` (지수 백오프 + 완전 지터)**:
   - 시도 횟수에 따라 지수 상한 계산:
     $$temp = \min(CAP\_DELAY\_SEC, BASE\_DELAY\_SEC \times 2^{attempt - 1})$$
   - 결정론적 의사 난수 지터 계산:
     - `s = sum((i + 1) * ord(c) for i, c in enumerate(client_id))`
     - `jitter = (s * 31337 + attempt * 7919) % (temp + 1)`
   - 다음 재시도 시각:
     $$next\_t = t + \max(1, jitter)$$
     *(최소 1초 뒤에 재시도되도록 보장)*

- 만약 $attempt == MAX\_ATTEMPTS$에 도달했는데도 실패하면 `FINAL_FAIL`로 종료됩니다.

---

## 3. 입력 형식

```text
SERVER_CAPACITY <cap>
SERVER_DOWN_WINDOW <start_t> <end_t>
MAX_ATTEMPTS <max_attempts>
BASE_DELAY_SEC <base_delay>
CAP_DELAY_SEC <cap_delay>
EVENTS <E>
REQ <client_id> <timestamp>
... (총 E개의 REQ 줄)
```

- 모든 파라미터와 `timestamp`는 양의 정수입니다 ($1 \le E \le 30,000$).
- 동일 시각에 도착한 요청들은 인입된 순서대로(FIFO) 처리됩니다.

---

## 4. 출력 형식

각 원본 `REQ`마다 한 줄씩 3대 전략의 최종 결과(`SUCCESS` 또는 `FAIL`)와 총 시도 횟수(`ATTEMPTS`)를 출력합니다:
```text
REQ <client_id> AT:<t> IMMEDIATE:<st>,ATTEMPTS:<att> FIXED:<st>,ATTEMPTS:<att> JITTER:<st>,ATTEMPTS:<att>
```

모든 요청 처리 후 최종 성능 요약을 출력합니다:
```text
SUMMARY IMMEDIATE SUCCESS_RATE:<rate>% TOTAL_ATTEMPTS:<tot>
SUMMARY FIXED SUCCESS_RATE:<rate>% TOTAL_ATTEMPTS:<tot>
SUMMARY FULL_JITTER SUCCESS_RATE:<rate>% TOTAL_ATTEMPTS:<tot>
SUMMARY JITTER_RELIABILITY_ADVANTAGE:<adv>%
```

- `SUCCESS_RATE`: `(성공한_클라이언트_수 / 전체_클라이언트_수) * 100.0` (소수점 둘째 자리까지 반올림, 예: `60.00%`)
- `TOTAL_ATTEMPTS`: 해당 전략에서 실제로 서버에 날린 총 누적 요청 시도 횟수
- `JITTER_RELIABILITY_ADVANTAGE`: `FULL_JITTER_SUCCESS_RATE - FIXED_SUCCESS_RATE` (소수점 둘째 자리까지 반올림, 예: `40.00%`, 음수면 `-5.00%`)

---

## 5. 입출력 예시

### 입력
```text
SERVER_CAPACITY 3
SERVER_DOWN_WINDOW 10 13
MAX_ATTEMPTS 4
BASE_DELAY_SEC 2
CAP_DELAY_SEC 8
EVENTS 10
REQ C00 10
REQ C01 10
REQ C02 10
REQ C03 10
REQ C04 10
REQ C05 10
REQ C06 10
REQ C07 10
REQ C08 10
REQ C09 10
```

### 출력
```text
REQ C00 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:SUCCESS,ATTEMPTS:3 JITTER:SUCCESS,ATTEMPTS:3
REQ C01 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:SUCCESS,ATTEMPTS:3 JITTER:SUCCESS,ATTEMPTS:3
REQ C02 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:SUCCESS,ATTEMPTS:3 JITTER:SUCCESS,ATTEMPTS:3
REQ C03 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:SUCCESS,ATTEMPTS:4 JITTER:SUCCESS,ATTEMPTS:3
REQ C04 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:SUCCESS,ATTEMPTS:4 JITTER:SUCCESS,ATTEMPTS:3
REQ C05 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:SUCCESS,ATTEMPTS:4 JITTER:SUCCESS,ATTEMPTS:3
REQ C06 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:FAIL,ATTEMPTS:4 JITTER:SUCCESS,ATTEMPTS:3
REQ C07 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:FAIL,ATTEMPTS:4 JITTER:SUCCESS,ATTEMPTS:3
REQ C08 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:FAIL,ATTEMPTS:4 JITTER:SUCCESS,ATTEMPTS:3
REQ C09 AT:10 IMMEDIATE:FAIL,ATTEMPTS:4 FIXED:FAIL,ATTEMPTS:4 JITTER:SUCCESS,ATTEMPTS:3
SUMMARY IMMEDIATE SUCCESS_RATE:0.00% TOTAL_ATTEMPTS:40
SUMMARY FIXED SUCCESS_RATE:60.00% TOTAL_ATTEMPTS:36
SUMMARY FULL_JITTER SUCCESS_RATE:100.00% TOTAL_ATTEMPTS:30
SUMMARY JITTER_RELIABILITY_ADVANTAGE:40.00%
```

#### 해설
- 손님 10명이 $t=10$에 도착했는데, 서버는 $10 \le t < 13$ 동안 DOWN 상태입니다.
- **IMMEDIATE**: $t=10$에 10명이 즉시 재시도를 4번씩 연타(총 40회)하지만, 서버가 계속 죽어있으므로 전원 소진(`FAIL`, 성공률 0%).
- **FIXED**: $t=10$(실패) $\to$ $t=12$(실패) $\to$ $t=14$(서버 복구!). 하지만 10명이 동시에 몰려와 용량(3)으로 인해 3명만 성공하고 7명은 탈락! $t=16$에 7명이 또 동시에 몰려와 3명만 성공하고 4명은 탈락! 성공률은 60%에 그칩니다.
- **FULL_JITTER**: 지터 난수로 인해 재시도 시각이 시간 축 전체로 부드럽게 분산되어 서버 초당 용량(3)을 초과하지 않고 10명 전원이 **100% 성공**합니다 (+40.00% 우위 달성).
