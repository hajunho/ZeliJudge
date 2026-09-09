# 094. 웹사이트 로딩 0초로 만들겠다고 TLS 1.3 0-RTT 켰더니 내 통장에서 돈이 두 번 빠져나갔어요?!: TLS 1.3 0-RTT 조기 데이터(Early Data) 재전송 공격과 안티 리플레이(Anti-Replay) 방어막

---

## 1. 비극의 시작 (Real-World Disaster)

핀테크 송금 서비스의 성능 최적화를 담당하던 신입 엔지니어 준호는 Nginx와 웹 애플리케이션의 지연시간(Latency)을 단축할 방법을 찾던 중, **TLS 1.3의 0-RTT (Zero Round-Trip Time) Early Data** 기능을 발견했습니다.

> **"대박이다! 이전 세션 티켓(PSK)만 있으면 핸드셰이크 왕복(1-RTT)을 완전히 없애고, 첫 번째 패킷(ClientHello)에 HTTP 요청을 실어 보낼 수 있잖아? 로딩 속도가 0ms가 되겠어!"**

준호는 신나서 서버 설정에 `ssl_early_data on;`을 켜고, 클라이언트 앱에도 송금 요청(`POST /transfer`)을 0-RTT Early Data로 전송하도록 활성화했습니다.

배포 직후 앱의 체감 속도는 번개처럼 빨라졌습니다.  
하지만 며칠 뒤, 카페 공용 와이파이에서 동생에게 30만 원을 송금한 고객들이 고객센터에 빗발치게 항의하기 시작했습니다:
> **"동생에게 30만 원을 한 번만 보냈는데, 통장에서 30만 원이 두 번 빠져나가서 총 60만 원이 인출되었습니다! 제 돈 돌려주세요!"**

보안팀이 긴급 감사에 착수했습니다.  
놀랍게도 데이터베이스 트랜잭션 코드에는 아무런 버그가 없었고, 통신 구간의 암호화도 완벽했습니다.  
해커는 패킷을 복호화하지도, 변조하지도 못했습니다. **단지 카페 와이파이 라우터에서 스니핑한 고객의 암호화된 첫 번째 패킷(`ClientHello + EncryptedEarlyData`)을 복사해서 서버로 그대로 다시 쐈을 뿐(Replay Attack)**이었습니다!

서버는 정상적인 세션 티켓이 담긴 패킷이었기에 아무 의심 없이 30만 원 송금을 한 번 더 실행해 버렸습니다.  
지연시간을 0초로 만들겠다는 욕심이 어떻게 고객의 통장을 털어버린 걸까요?

---

## 2. 밀봉 봉투와 복사기(Xerox)의 비극: 왜 0-RTT는 재전송에 취약한가?

왕실 중앙은행의 VIP 고객 창구를 상상해 보세요:

1. **정상적인 1-RTT 정식 창구**:
   - 손님이 번호표를 뽑고 은행원에게 신분증을 보여줍니다(핸드셰이크 1회 왕복).
   - 은행원은 손님의 얼굴과 신분증을 대조하고, **현장에서 즉석으로 생성된 일회용 난수(Ephemeral Key)**로 암호 서명을 주고받은 뒤 송금을 처리합니다. 중간의 도둑이 끼어들 틈이 없습니다.
2. **초고속 0-RTT 직통 창구**:
   - 신분증 검사 시간이 아깝다며, 은행장이 지난번 발급해 준 **특수 암호 밀봉 봉투(세션 티켓, PSK)**를 들고 옵니다.
   - 손님은 신분증 검사 없이, 밀봉 봉투 안에 "100만 원 송금해 줘" 편지를 넣어서 창구에 툭 던지고(Early Data) 뒤도 안 돌아보고 떠납니다.
3. **복사기를 든 도둑 (Replay Attack)**:
   - 도둑은 봉투를 뜯어보거나 위조할 수 없습니다(암호화).
   - 하지만 도둑에게는 **복사기(Xerox)**가 있습니다!
   - 도둑은 손님이 던진 봉투를 사진 찍듯 똑같이 복사해서 은행 창구에 5번 더 집어넣었습니다.
4. **은행원의 착각**:
   - 은행원은 "어? 우리 은행 특수 암호 봉투가 맞네!"라며 5번의 복사본을 모두 진짜로 믿고 총 6번(600만 원)을 송금해 고객의 통장을 거덜 냅니다!

---

## 3. 핵심 아키텍처 및 요구사항

당신은 RFC 8446(TLS 1.3) 및 RFC 8470(Early Data) 규격을 준수하는 TLS 1.3 0-RTT 조기 데이터 수락 엔진 및 3단계 안티 리플레이(Anti-Replay) 방어막을 구축해야 합니다.

### 1) 서버 설정 (`CONFIG`)
- `CONFIG <max_ticket_age_window_ms> <anti_replay_mode> <allow_non_idempotent>`
  - `max_ticket_age_window_ms`: 티켓 나이(Ticket Age) 허용 오차 윈도우 (예: `5000`ms = 5초).
  - `anti_replay_mode`:
    - `NONE`: 안티 리플레이 방어 없음 (모든 유효 티켓 재전송 수용 $\rightarrow$ 리플레이 공격 취약).
    - `SINGLE_USE`: 일회용 티켓 모드 (0-RTT에 1회 사용된 티켓은 즉시 소멸).
    - `WINDOW_FILTER`: 슬라이딩 윈도우 캐시 모드 (`client_random` 난수를 캐싱하여 중복 거부).
  - `allow_non_idempotent`:
    - `0`: RFC 8446 권고 준수. 비멱등 메서드(POST, PUT, DELETE 등)는 0-RTT에서 거부하고 `425 Too Early` 반환 후 1-RTT 풀 핸드셰이크 강제.
    - `1`: 비멱등 메서드도 0-RTT 수락 허용 (취약한 설정).
  - 출력: `CONFIG_OK window=<ms> anti_replay=<mode> allow_non_idempotent=<0|1>`

### 2) 세션 티켓 발급 (`ISSUE_TICKET`)
- `ISSUE_TICKET <ticket_id> <user_id> <balance>`
  - 이전 1-RTT 연결 완료 시 클라이언트에게 발급되는 세션 티켓(PSK)을 생성합니다.
  - 발급 시각은 현재 시각(`current_time_ms`)으로 기록됩니다.
  - 출력: `TICKET_ISSUED id=<ticket_id> user=<user_id> time=<current_time_ms>ms`

### 3) 0-RTT 조기 데이터 요청 검증 파이프라인 (`REQ_0RTT`)
- `REQ_0RTT <ticket_id> <client_random> <ticket_age_ms> <method> <path> [amount]`
  - `total_0rtt_reqs += 1`
  - **검증 1단계 (티켓 존재 여부)**:
    - `ticket_id`가 없으면 거부: `REJECT_EARLY_DATA reason=INVALID_TICKET`
  - **검증 2단계 (티켓 나이 오차 검증)**:
    - 서버 경과 시간: `elapsed = current_time_ms - ticket.issued_at`
    - 오차: `skew = abs(elapsed - ticket_age_ms)`
    - `skew > max_ticket_age_window_ms`이면 거부: `REJECT_EARLY_DATA reason=TICKET_AGE_SKEW_EXCEEDED skew=<skew>ms`
  - **검증 3단계 (안티 리플레이 검증)**:
    - `SINGLE_USE` 모드: 티켓이 이미 사용된 상태(`is_used == True`)이면 차단:
      `REJECT_EARLY_DATA reason=REPLAY_DETECTED_TICKET_REUSED` (`blocked_replays += 1`)
    - `WINDOW_FILTER` 모드: `client_random`이 윈도우 캐시에 이미 존재하면 차단:
      `REJECT_EARLY_DATA reason=REPLAY_DETECTED_NONCE_DUPLICATE` (`blocked_replays += 1`)
  - **검증 4단계 (HTTP 멱등성 검증 - RFC 8470)**:
    - `allow_non_idempotent == 0`이고 `method`가 비멱등 메서드(`POST`, `PUT`, `DELETE` 등)인 경우:
      - 조기 데이터 실행 거부 및 1-RTT 핸드셰이크 폴백 강제:
      - `REJECT_EARLY_DATA status=425_TOO_EARLY fallback=1RTT_REQUIRED`
  - **모든 검증 통과 시 (ACCEPT_EARLY_DATA)**:
    - 만약 이전에 동일한 `client_random`이 실행된 적이 있었다면(방어막 부재로 인한 중복 침해):
      `replay_breaches += 1`
    - 안티 리플레이 기록 갱신 (SINGLE_USE는 티켓 사용 완료 처리, WINDOW_FILTER는 Nonce 캐싱).
    - `accepted_0rtt += 1`
    - `GET` 등 안전한 메서드: `ACCEPT_EARLY_DATA status=200_OK result=BALANCE:<user.balance>`
    - `POST` 등 상태 변경 메서드: `user.balance -= amount`,  
      `ACCEPT_EARLY_DATA status=200_OK result=TRANSFERRED:<amount>_REMAINING:<user.balance>`

### 4) 1-RTT 풀 핸드셰이크 안전 요청 (`REQ_1RTT`)
- `REQ_1RTT <user_id> <method> <path> [amount]`
  - 0-RTT가 거부되거나 `425 Too Early`를 수신했을 때, 클라이언트가 1-RTT 정식 핸드셰이크를 완료한 후 안전하게 실행하는 요청입니다.
  - 1-RTT는 리플레이 공격 위험이 없으므로 항상 안전하게 정상 실행됩니다.
  - `GET`: `HANDSHAKE_1RTT_OK status=200_OK result=BALANCE:<user.balance>`
  - `POST`: `user.balance -= amount`,  
    `HANDSHAKE_1RTT_OK status=200_OK result=TRANSFERRED:<amount>_REMAINING:<user.balance>`

### 5) 시간 경과 (`TICK <delta_ms>`)
- `current_time_ms += delta_ms`
- `WINDOW_FILTER` 모드에서 캐시된 `client_random` 중 경과 시간이 `max_ticket_age_window_ms`를 초과한 만료된 Nonce들을 메모리에서 자동 제거(Evict)합니다.
- 출력: `TICK_OK time=<current_time_ms>ms evicted_nonces=<count>`

### 6) 보안 상태 진단 (`STATS`)
- `total_0rtt`: 총 0-RTT 요청 횟수
- `accepted`: 수락된 0-RTT 횟수
- `rejected`: 거부된 0-RTT 횟수
- `blocked_replays`: 차단된 리플레이 공격 횟수
- `breaches`: 방어 실패로 중복 실행된 리플레이 침해 횟수
- `health` 판정 기준:
  - `breaches > 0`: **`COMPROMISED`** (이중 송금 등 보안 침해 발생)
  - `anti_replay_mode == "NONE"` 또는 `allow_non_idempotent == 1`: **`VULNERABLE`** (취약한 설정)
  - 그 외: **`SECURE`** (철통 보안 유지)
- 출력 형식:
  `STATS total_0rtt=<total> accepted=<acc> rejected=<rej> blocked_replays=<blk> breaches=<breaches> health=<health>`

---

## 4. 입출력 형식

### 입력
표준 입력(stdin)으로 여러 줄의 명령어가 주어집니다. 빈 줄이나 `#`으로 시작하는 주석은 무시합니다.

- `CONFIG <window_ms> <anti_replay_mode> <allow_non_idempotent>`
- `ISSUE_TICKET <ticket_id> <user_id> <balance>`
- `REQ_0RTT <ticket_id> <client_random> <ticket_age_ms> <method> <path> [amount]`
- `REQ_1RTT <user_id> <method> <path> [amount]`
- `TICK <delta_ms>`
- `STATS`

### 출력
각 명령어의 실행 결과를 표준 출력(stdout)으로 한 줄씩 출력합니다.

---

## 5. 입출력 예시

### 예시 1: 취약한 서버 vs 안전한 서버 비교
**입력:**
```text
CONFIG 5000 NONE 1
ISSUE_TICKET t1 user_alice 1000000
REQ_0RTT t1 rand_1 0 POST /transfer 300000
REQ_0RTT t1 rand_1 50 POST /transfer 300000
STATS
CONFIG 5000 WINDOW_FILTER 0
ISSUE_TICKET t2 user_bob 1000000
REQ_0RTT t2 rand_2 0 POST /transfer 300000
REQ_1RTT user_bob POST /transfer 300000
REQ_0RTT t2 rand_2 50 POST /transfer 300000
STATS
```

**출력:**
```text
CONFIG_OK window=5000 anti_replay=NONE allow_non_idempotent=1
TICKET_ISSUED id=t1 user=user_alice time=0ms
ACCEPT_EARLY_DATA status=200_OK result=TRANSFERRED:300000_REMAINING:700000
ACCEPT_EARLY_DATA status=200_OK result=TRANSFERRED:300000_REMAINING:400000
STATS total_0rtt=2 accepted=2 rejected=0 blocked_replays=0 breaches=1 health=COMPROMISED
CONFIG_OK window=5000 anti_replay=WINDOW_FILTER allow_non_idempotent=0
TICKET_ISSUED id=t2 user=user_bob time=0ms
REJECT_EARLY_DATA status=425_TOO_EARLY fallback=1RTT_REQUIRED
HANDSHAKE_1RTT_OK status=200_OK result=TRANSFERRED:300000_REMAINING:700000
REJECT_EARLY_DATA status=425_TOO_EARLY fallback=1RTT_REQUIRED
STATS total_0rtt=2 accepted=0 rejected=2 blocked_replays=0 breaches=0 health=SECURE
```

---

## 6. 실무 아키텍트 가이드: 어떻게 해결해야 하는가?

1. **RFC 8446 원칙: 0-RTT에서는 오직 안전한 멱등(Idempotent) 요청만 허용하라**:
   - `GET /`, `GET /static/...` 같은 정적 리소스나 멱등한 조회 요청만 0-RTT Early Data로 수락하세요.
   - 결제(`POST /pay`), 주문(`POST /order`), 송금(`POST /transfer`), 삭제(`DELETE /item`) 등 상태를 변경하는 API는 Nginx나 애플리케이션 프레임워크에서 Early Data 헤더(`Early-Data: 1`)를 감지하여 반드시 **`425 Too Early`**를 응답해야 합니다.
2. **리버스 프록시(Nginx, Cloudflare)의 안티 리플레이 캐시 활성화**:
   - Nginx: `ssl_early_data on;` 사용 시 반드시 `$ssl_early_data` 변수를 확인하여 비멱등 요청을 차단(`if ($ssl_early_data) { return 425; }`)해야 합니다.
   - Cloudflare: 0-RTT 활성화 시 기본적으로 GET 요청만 허용하고 POST 요청은 자동으로 1-RTT 핸드셰이크를 거치도록 필터링합니다.
