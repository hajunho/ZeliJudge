# CS 이론 백서: TLS 1.3 0-RTT 조기 데이터(Early Data) 재전송 공격과 안티 리플레이(Anti-Replay) 방어막

> **"로딩 속도를 0초로 만들겠다고 TLS 1.3 0-RTT를 켰더니, 네트워크 해커가 결제 패킷을 복사해서 똑같이 보냈을 뿐인데 통장에서 돈이 두 번 빠져나갔습니다."**  
> 이 문제는 암호 알고리즘이 뚫린 것이 아니라, **지연시간 최적화를 위해 핸드셰이크를 생략한 0-RTT의 구조적 한계(Replay Vulnerability)와 HTTP 멱등성의 부재**에서 발생합니다.

---

## 1. 현실 비유: 위조 불가능한 밀봉 봉투와 복사기(Xerox)의 비극

왕실 중앙은행에는 VIP 고객들을 위한 **초고속 직통 창구(0-RTT 창구)**가 있습니다.

```
[VIP 고객]  --- (암호 밀봉 봉투 던짐: "동생에게 100만 원 송금해 줘") ---> [0-RTT 직통 창구]
```

1. **정상적인 1-RTT 정식 창구**:
   - 고객이 번호표를 뽑고 신분증을 보여줍니다(핸드셰이크 왕복 1회).
   - 은행원이 고객의 얼굴과 신분증을 확인한 후, 그 자리에서 실시간 비밀 서명을 받아 송금합니다.
   - 중간에 도둑이 끼어들 틈이 전혀 없습니다.
2. **초고속 0-RTT 직통 창구**:
   - "신분증 검사하고 번호표 뽑는 시간이 너무 아깝다!"며 은행장이 이전 방문 때 발급해 준 **특수 암호 밀봉 봉투(세션 티켓, PSK)**를 들고 옵니다.
   - 고객은 신분증 검사 없이, 밀봉 봉투 안에 "100만 원 송금해 줘" 편지를 넣어서 창구에 툭 던지고(Early Data) 뒤도 안 돌아보고 갑니다.
3. **복사기(Xerox)를 든 도둑의 공격 (Replay Attack)**:
   - 길거리에 서 있던 도둑은 밀봉 봉투를 훔쳐보거나 위조할 수 없습니다. 암호화가 완벽하기 때문입니다.
   - 하지만 도둑에게는 **복사기(Replay)**가 있습니다!
   - 도둑은 고객이 던진 봉투를 사진 찍듯 똑같이 복사해서 은행 창구에 5번 더 집어넣었습니다.
4. **은행원의 착각과 대참사**:
   - 은행원은 "어? 우리 은행 특수 암호 봉투가 맞네!"라며 5번의 복사본을 모두 진짜로 믿고 **총 6번(600만 원)을 송금**해 고객의 계좌를 털어버립니다!

---

## 2. TLS 1.2 vs TLS 1.3과 0-RTT의 탄생

웹 브라우저가 HTTPS 사이트에 접속할 때 거치는 핸드셰이크 지연시간(RTT: Round-Trip Time)의 진화 과정입니다:

```
[TLS 1.2] (2-RTT)
Client ---------- ClientHello -------------> Server
Client <--------- ServerHello, Cert, Key --- Server
Client ---------- ClientKeyExchange, Fin --> Server
Client <--------- SessionTicket, Fin ------- Server
Client ---------- HTTP GET /index.html ----> Server  (2번 왕복 후 첫 데이터!)

[TLS 1.3 일반] (1-RTT)
Client ---------- ClientHello + KeyShare --> Server
Client <--------- ServerHello + KeyShare --- Server
Client ---------- HTTP GET /index.html ----> Server  (1번 왕복 후 첫 데이터!)

[TLS 1.3 재연결] (0-RTT Early Data)
Client ---------- ClientHello + PSK + HTTP EarlyData ---> Server  (왕복 0번! 첫 패킷에 데이터 동시 전송!)
Client <--------- ServerHello + HTTP 200 OK ------------- Server
```

TLS 1.3의 **0-RTT (Zero Round-Trip Time)**는 이전에 발급받은 세션 티켓(PSK: Pre-Shared Key)을 사용하여, **TCP 연결의 맨 첫 번째 패킷(ClientHello)에 암호화된 HTTP 요청(Early Data)을 함께 실어 보내는 혁신적인 고속 기술**입니다. 지연시간이 0ms로 줄어들어 모바일 환경에서 체감 로딩 속도가 극적으로 빨라집니다.

---

## 3. 0-RTT의 아킬레스건: 재전송 공격 (Replay Attack)

하지만 RFC 8446 규격서에서도 엄중히 경고하듯, 0-RTT Early Data에는 치명적인 약점이 있습니다:

1. **전방향 비밀성(Forward Secrecy) 결여**:
   - 세션 티켓 키가 미래에 유출되면, 과거 캡처된 0-RTT 데이터가 사후 복호화될 수 있습니다.
2. **중간자 재전송(Replay) 공격에 무방비**:
   - 네트워크 구간에 있는 악의적인 중간자(공공 와이파이 해커, 손상된 라우터, 프록시)는 패킷을 복호화하거나 변조할 수 없습니다.
   - 하지만 **그냥 캡처한 패킷을 그대로 서버에 복사해서 다시 전송(Replay)**할 수 있습니다.
   - 서버 입장에서는 클라이언트가 보낸 유효한 세션 티켓과 암호화 데이터이므로, 이것이 원본인지 복제본인지 구분할 방법이 없습니다!

만약 0-RTT Early Data에 담긴 요청이 상태를 변경하는 비멱등(Non-Idempotent) 요청이라면?
- `POST /api/pay amount=50000` $\rightarrow$ 결제가 2번, 3번 중복 승인됨
- `POST /api/transfer to=hacker amount=1000000` $\rightarrow$ 잔고가 거덜 날 때까지 송금됨

---

## 4. 실무 아키텍트의 3대 안티 리플레이 방어막

RFC 8446 및 RFC 8470에서는 0-RTT 재전송 공격을 막기 위해 **3계층 심층 방어(Defense-in-Depth)**를 규정합니다.

### 1) 티켓 나이 윈도우 검증 (Ticket Age Window)
- 세션 티켓에는 발급 시각($T_{issued}$)이 암호화되어 있습니다.
- 클라이언트는 ClientHello에 자신이 체감한 티켓 나이(`obfuscated_ticket_age`)를 기록합니다.
- 서버 시계와의 오차가 허용 윈도우(예: $\pm 5$초)를 벗어나면, 너무 오래되었거나 미래에서 온 조작 패킷으로 간주하고 0-RTT를 거부합니다.

### 2) 서버 측 Nonce 캐시 & 일회용 티켓 (Anti-Replay Cache)
- **일회용 티켓 (Single-Use Ticket)**: 세션 티켓은 0-RTT에 단 1회만 사용할 수 있으며, 한 번 사용되면 서버 저장소에서 즉시 소멸시킵니다.
- **슬라이딩 윈도우 Nonce 필터 (Client Hello Recording)**:
  - ClientHello에 포함된 32바이트 난수(`client_random`)를 메모리 캐시(Bloom Filter 또는 Redis)에 기록합니다.
  - 윈도우 시간 내에 동일한 `client_random`을 가진 패킷이 다시 도착하면 즉시 **`REJECT_EARLY_DATA`**를 선언하고 1-RTT 풀 핸드셰이크로 강제 다운그레이드합니다.

### 3) 애플리케이션 계층 방어: HTTP 멱등성 준수 및 `425 Too Early`
가장 강력하고 필수적인 방어막은 **애플리케이션 계층**에 있습니다:
- **안전한 메서드(Safe & Idempotent)만 0-RTT 허용**:
  - `GET`, `HEAD` 같은 조회 요청은 복제 전송되어도 서버 데이터가 변하지 않으므로 0-RTT 처리를 허용합니다.
- **상태 변경 메서드(POST, PUT, DELETE, 결제/송금)는 0-RTT 전면 차단**:
  - 만약 비멱등 요청이 Early Data로 들어오면, 서버는 요청을 실행하지 않고 **`HTTP 425 Too Early`** 에러를 반환합니다.
  - 브라우저는 1-RTT 핸드셰이크가 안전하게 끝난 후(리플레이 불가능한 상태) 해당 POST 요청을 비로소 안전하게 재전송합니다.
