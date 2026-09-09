# CS 백서: TCP TIME_WAIT 소켓 고갈과 HTTP 커넥션 풀링 (TCP TIME_WAIT & Connection Pool Starvation)

> **"외부 결제 API를 호출했을 뿐인데, 몇 분 뒤 서버의 모든 외부 통신이 마비되고 `Cannot assign requested address` 에러가 쏟아져요!"**  
> — Python `requests.get()` 또는 Node.js `fetch()`를 커넥션 풀 없이 반복 호출했다가 서버 소켓이 전멸한 백엔드 엔지니어의 절규

---

## 1. 현실 비유: 말 한마디 할 때마다 전화 끊고 다시 거는 철수의 비극

어느 무역 회사 사무실에 외부와 통화할 수 있는 전화 회선(임시 포트, Ephemeral Port)이 딱 50개 있습니다.  
신입사원 철수는 거래처에 100가지 질문을 해야 합니다.

```
[미련한 철수의 통화 방식: Connection: close]
1. 번호를 누르고 신호음이 가길 기다립니다 ──▶ (TCP 3-Way Handshake, 20ms 소요)
2. "물건 재고 있나요?" ──▶ 1초 만에 묻고 전화를 뚝 끊어버립니다!
3. 통신사 규정: "방금 끊긴 회선은 다른 통화와 섞이지 않도록 60초간 잠금 대기 상태(TIME_WAIT)로 둡니다."
4. 철수는 질문 50개를 묻자마자 사무실의 50개 회선을 모조리 잠가버렸습니다!
5. 51번째 전화를 걸려고 수화기를 들자: "삐- 뚜- 뚜- 지금은 사용 가능한 회선이 없습니다 (Cannot assign requested address)!"

[현명한 영희의 통화 방식: HTTP Keep-Alive & 커넥션 풀]
1. 거래처에 전화를 딱 1번 걸어 연결합니다 (최초 1회만 Handshake).
2. "재고 있나요?", "가격은 얼마인가요?", "배송은 언제 되나요?" ──▶ 전화를 끊지 않고 100개 질문을 연속으로 묻습니다!
3. 전화선은 단 1개만 사용되고, 통화가 끝난 후에도 회선이 잠기지 않아 수만 번의 대화도 거뜬히 처리합니다!
```

1. **미련한 단기 연결 (Short-lived Connection)**:
   - 매번 HTTP 요청을 보낼 때마다 TCP 연결을 새로 맺고 끊습니다 (`Connection: close`).
   - 연결할 때마다 3-Way Handshake(SYN $\to$ SYN-ACK $\to$ ACK)로 왕복 지연시간(RTT)이 낭비됩니다.
   - 더 무서운 것은 **연결을 끊을 때 발생**합니다!

2. **TCP의 수호신이자 저주: `TIME_WAIT`의 정체**:
   - TCP 프로토콜에서 **먼저 연결 종료(`FIN`)를 선언한 쪽(Active Closer)**은 마지막 `ACK`를 보낸 뒤 즉시 소켓을 파괴하지 않고, **`TIME_WAIT` 상태로 60초~120초(2MSL: Maximum Segment Lifetime) 동안 대기**합니다.
   - 왜 바로 닫지 않을까요?
     1. 마지막 `ACK`가 유실되었을 때 상대방이 `FIN`을 재전송하면 이를 수신하여 다시 `ACK`를 보내주기 위해.
     2. 네트워크 상을 떠돌던 이전 연결의 지연 패킷(Lost Segment)이 우연히 새로 열린 소켓에 침투하여 데이터를 오염시키는 것을 방지하기 위해.
   - 문제는 **이 60초 동안 해당 클라이언트의 포트 번호(Ephemeral Port)가 잠겨서 재사용될 수 없다**는 점입니다!

3. **임시 포트 고갈 (Port Exhaustion / EADDRNOTAVAIL)**:
   - 리눅스 OS의 클라이언트 가용 포트 수는 보통 32,768 ~ 60,999번 사이의 약 28,000개입니다.
   - 초당 수백 건의 외부 API 요청을 단기 연결로 호출하면, 60초 동안 수만 개의 소켓이 `TIME_WAIT`로 누적되어 **28,000개의 포트가 순식간에 바닥납니다.**
   - 새 요청을 보내려고 소켓을 열려 할 때 OS 커널이 포트를 할당하지 못해 `Cannot assign requested address (Errno 99)` 에러를 뿜으며 서버의 모든 외부 통신이 전면 중단됩니다!

---

## 2. 컴퓨터 과학 이론: TCP 상태 전이도와 커넥션 풀링

### 1) TCP 4-Way Teardown과 TIME_WAIT 상태
```
Client (Active Closer)                     Server (Passive Closer)
       │                                              │
       ├────────────── FIN (FIN_WAIT_1) ─────────────▶│ (CLOSE_WAIT)
       │◀───────────── ACK (FIN_WAIT_2) ──────────────┤
       │                                              │
       │◀───────────── FIN (TIME_WAIT) ───────────────┤ (LAST_ACK)
       ├────────────── ACK (2MSL 타이머 시작) ────────▶│ (CLOSED)
       │
   [TIME_WAIT 60초 대기]
   해당 포트 번호 재사용 불가!
       │
    (CLOSED)
```

### 2) 해결책: HTTP Keep-Alive & 커넥션 풀링 (Connection Pooling)
- **HTTP 1.1 기본 스펙인 `Connection: keep-alive`**를 활용합니다.
- 애플리케이션에 **HTTP 커넥션 풀(Connection Pool)**을 구성합니다:
  1. 요청이 오면 이미 열려 있는 기존 TCP 커넥션을 풀에서 꺼내 재사용합니다.
  2. 3-Way Handshake를 건너뛰므로 네트워크 RTT가 즉시 70% 이상 단축됩니다.
  3. 요청이 끝나도 연결을 끊지 않고(`FIN`을 보내지 않음) 풀의 유휴 목록(Idle List)에 보관합니다.
  4. **클라이언트가 `FIN`을 보내지 않으므로 `TIME_WAIT` 소켓이 생성되지 않습니다!**
  5. 단 20~50개의 커넥션만으로도 초당 수만 건의 트래픽을 임시 포트 고갈 없이 안정적으로 처리할 수 있습니다.
