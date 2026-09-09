# [CS-107] 정상 종료(FIN)와 강제 단절(RST)의 차이?!: TCP 소켓 정상 종료(4-Way Handshake)와 비정상 리셋(RST)의 저주 (`SO_LINGER`)

> **"선생님! 클라이언트가 대용량 JSON을 보냈는데, 서버가 앞부분만 파싱하고 `socket.close()`를 불렀더니 클라이언트 화면에 `Connection reset by peer (ECONNRESET)` 에러가 터져요! 서버는 정상적으로 닫았는데 왜 연결이 폭파되죠?!"**
> 
> 결제 게이트웨이(PG) 연동 모듈을 개발하던 신입 개발자 지우는 이상한 간헐적 버그를 발견했습니다.
> 결제 요청 페이로드가 10KB였는데, 서버 로직에서 첫 줄의 토큰만 검증하고 "인증 실패"라며 곧바로 `socket.close()`를 호출했습니다.
> 그러자 클라이언트는 서버가 보낸 "인증 실패" 응답을 읽지도 못한 채, `java.io.IOException: Connection reset by peer` 에러를 맞고 크래시되었습니다!
> 
> "서버가 `close()`를 호출했는데 왜 FIN 정상 종료가 아니라 RST 강제 리셋이 날아갔을까요?!"
> 네트워크 시스템 아키텍트는 통신 패킷 캡처를 보여주며 설명했습니다.
> "지우 씨, 전화 통화할 때 상대방이 아직 말을 다 안 끝내고 계속 말하고 있는데(수신 버퍼 미처리 데이터), 듣기 싫다고 수화기를 바닥에 쾅! 패대기치고 전선을 가위로 잘라버린 꼴이에요. 그게 바로 TCP RST 패킷입니다."

---

## 1. 문제 배경과 현실 비유: 부드러운 작별 인사(FIN) vs 수화기 패대기(RST)

TCP 소켓의 종료 방식은 크게 두 가지로 나뉩니다.

### 1) 신사적인 작별 인사: FIN (4-Way Handshake)
- **과정**: 송신 종료(FIN) -> 상대방 확인(ACK) -> 상대방 송신 종료(FIN) -> 확인(ACK).
- **특징**: 버퍼에 남아있는 모든 데이터를 끝까지 전송/수신 완료(Drain)한 뒤 우아하게 종료합니다.
- **TIME_WAIT 상태**: Active Close(먼저 `close()`를 부른 주체)는 지연 패킷에 의한 신규 연결 오염을 막기 위해 2MSL(60초) 동안 `TIME_WAIT` 상태로 소켓을 유지합니다.

### 2) 일방적인 수화기 패대기: RST (Abrupt Reset & Hard Reset)
- **과정**: 핸드셰이크 없이 단 1개의 RST 플래그 패킷을 상대방에게 던져 연결을 즉시 폭파합니다.
- **특징**:
  - 송수신 버퍼의 모든 잔여 데이터를 즉시 폐기(Drop)합니다.
  - 상대방에게 즉시 `ECONNRESET (Connection reset by peer)` 에러를 발생시킵니다.
  - **`TIME_WAIT` 상태를 거치지 않고 소켓이 즉시 파기(`CLOSED`)**됩니다.

### 3) 실무에서 RST가 폭발하는 2대 원인
1. **수신 버퍼 미처리 데이터(Unread Data) 잔존 상태에서 `close()`**:
   - 상대방이 보낸 데이터를 애플리케이션이 다 읽지 않고 남겨둔 채 `close()`를 호출하면, 커널은 이를 **데이터 유실(Data Loss)**로 간주하여 FIN 대신 **즉시 RST**를 발송합니다!
2. **Zero Linger (`SO_LINGER = {onoff: 1, linger: 0}`)**:
   - TIME_WAIT 소켓 포트 고갈을 피하겠다고 linger를 0으로 강제 설정하면, 소켓을 닫을 때 버퍼를 버리고 강제로 RST를 날려 상대방에게 에러를 유발합니다.

---

## 2. 요구사항 및 명령어 사양

당신은 TCP 소켓 라이프사이클(FIN 4-Way Handshake vs RST Abrupt Reset)을 시뮬레이션하는 `TcpSocketSimulator` 엔진을 구현해야 합니다.
표준 입력(`stdin`)으로 들어오는 명령어들을 한 줄씩 파싱하여 정확한 형식으로 표준 출력(`stdout`)에 출력하십시오.

### 지원 명령어 목록

1. `OPEN_CONN <conn_id>`
   - 새로운 소켓 연결을 `ESTABLISHED` 상태로 생성합니다.
   - 출력: `OPEN_CONN id=<conn_id> state=ESTABLISHED`

2. `SET_SO_LINGER <conn_id> <onoff: 0|1> <linger_sec>`
   - 소켓의 `SO_LINGER` 옵션을 설정합니다.
   - 출력: `SET_SO_LINGER id=<conn_id> onoff=<onoff> linger=<linger_sec>`

3. `APP_SEND <conn_id> <from: CLIENT|SERVER> <bytes>`
   - 데이터를 상대방에게 전송하여 상대방의 수신 버퍼(`recv_buffer`)에 누적합니다.
   - `ESTABLISHED` 상태가 아니면 `ERROR id=<conn_id> reason=SOCKET_NOT_ESTABLISHED state=<state>`
   - 출력: `APP_SEND id=<conn_id> from=<from> bytes=<bytes> target_recv_buffer=<new_bytes>`

4. `APP_READ <conn_id> <role: CLIENT|SERVER> <bytes>`
   - 자신의 수신 버퍼에서 최대 `<bytes>`만큼 데이터를 읽어 비웁니다.
   - `read_bytes = min(bytes, recv_buffer)`
   - 출력: `APP_READ id=<conn_id> role=<role> requested=<bytes> read=<read_bytes> remaining_recv_buffer=<remaining>`

5. `CLOSE_SOCKET <conn_id> <initiator: CLIENT|SERVER>`
   - 해당 주체가 소켓 닫기를 실행합니다.
   - 이미 닫힌 상태(`TIME_WAIT`, `CLOSED`)이면 `ERROR id=<conn_id> reason=ALREADY_CLOSED state=<state>`
   - **종료 판단 로직**:
     - **Case A: Zero Linger (`so_linger_on == 1 and so_linger_sec == 0`)**:
       - 즉시 RST 발송 및 양쪽 버퍼 폐기, TIME_WAIT 생략!
       - 출력:
         - `CLOSE_INITIATED id=<conn_id> by=<initiator> mode=ZERO_LINGER_ABRUPT`
         - `RST_SENT id=<conn_id> from=<initiator> reason=ZERO_LINGER_HARD_RESET`
         - `RST_RECEIVED id=<conn_id> to=<peer> error=ECONNRESET_CONNECTION_RESET_BY_PEER`
         - `CONN_CLOSED id=<conn_id> state=CLOSED time_wait=SKIPPED`
     - **Case B: 수신 버퍼에 미처리 데이터 존재 (`recv_buffer > 0`)**:
       - 즉시 RST 발송 및 양쪽 버퍼 폐기, TIME_WAIT 생략!
       - 출력:
         - `CLOSE_INITIATED id=<conn_id> by=<initiator> mode=UNREAD_DATA_ABRUPT`
         - `RST_SENT id=<conn_id> from=<initiator> unread_bytes=<unread> reason=UNREAD_DATA_IN_RECV_BUFFER`
         - `RST_RECEIVED id=<conn_id> to=<peer> error=ECONNRESET_CONNECTION_RESET_BY_PEER`
         - `CONN_CLOSED id=<conn_id> state=CLOSED time_wait=SKIPPED`
     - **Case C: 정상 종료 (수신 버퍼 0, Zero Linger 아님)**:
       - 4-Way Handshake 수행 및 TIME_WAIT 진입!
       - 출력:
         - `CLOSE_INITIATED id=<conn_id> by=<initiator> mode=GRACEFUL_4WAY_HANDSHAKE`
         - `FIN_SENT id=<conn_id> from=<initiator> state=FIN_WAIT_1`
         - `ACK_RECEIVED id=<conn_id> by=<initiator> state=FIN_WAIT_2`
         - `FIN_SENT id=<conn_id> from=<peer> state=LAST_ACK`
         - `ACK_SENT id=<conn_id> from=<initiator> state=TIME_WAIT duration=60000ms`
         - `CONN_CLOSED id=<conn_id> state=TIME_WAIT time_wait=ACTIVE`

6. `EXPIRE_TIME_WAIT <conn_id>`
   - `TIME_WAIT` 상태인 소켓을 2MSL(60초) 경과로 완전히 `CLOSED` 처리합니다.
   - `TIME_WAIT` 상태가 아니면 `ERROR id=<conn_id> reason=NOT_IN_TIME_WAIT state=<state>`
   - 출력: `TIME_WAIT_EXPIRED id=<conn_id> state=CLOSED`

7. `STATS <conn_id>`
   - 연결 통계를 출력합니다.
   - 출력: `STATS id=<conn_id> state=<state> fin_sent=<fin> rst_sent=<rst> time_wait_count=<tw> econnreset_count=<err> client_unread=<c_buf> server_unread=<s_buf>`

---

## 3. 입출력 예시

### 예시 입력 1
```text
OPEN_CONN conn_graceful
APP_SEND conn_graceful CLIENT 1000
APP_READ conn_graceful SERVER 1000
CLOSE_SOCKET conn_graceful SERVER
STATS conn_graceful
EXPIRE_TIME_WAIT conn_graceful
STATS conn_graceful
OPEN_CONN conn_unread
APP_SEND conn_unread CLIENT 10000
APP_READ conn_unread SERVER 1000
CLOSE_SOCKET conn_unread SERVER
STATS conn_unread
```

### 예시 출력 1
```text
OPEN_CONN id=conn_graceful state=ESTABLISHED
APP_SEND id=conn_graceful from=CLIENT bytes=1000 target_recv_buffer=1000
APP_READ id=conn_graceful role=SERVER requested=1000 read=1000 remaining_recv_buffer=0
CLOSE_INITIATED id=conn_graceful by=SERVER mode=GRACEFUL_4WAY_HANDSHAKE
FIN_SENT id=conn_graceful from=SERVER state=FIN_WAIT_1
ACK_RECEIVED id=conn_graceful by=SERVER state=FIN_WAIT_2
FIN_SENT id=conn_graceful from=CLIENT state=LAST_ACK
ACK_SENT id=conn_graceful from=SERVER state=TIME_WAIT duration=60000ms
CONN_CLOSED id=conn_graceful state=TIME_WAIT time_wait=ACTIVE
STATS id=conn_graceful state=TIME_WAIT fin_sent=2 rst_sent=0 time_wait_count=1 econnreset_count=0 client_unread=0 server_unread=0
TIME_WAIT_EXPIRED id=conn_graceful state=CLOSED
STATS id=conn_graceful state=CLOSED fin_sent=2 rst_sent=0 time_wait_count=1 econnreset_count=0 client_unread=0 server_unread=0
OPEN_CONN id=conn_unread state=ESTABLISHED
APP_SEND id=conn_unread from=CLIENT bytes=10000 target_recv_buffer=10000
APP_READ id=conn_unread role=SERVER requested=1000 read=1000 remaining_recv_buffer=9000
CLOSE_INITIATED id=conn_unread by=SERVER mode=UNREAD_DATA_ABRUPT
RST_SENT id=conn_unread from=SERVER unread_bytes=9000 reason=UNREAD_DATA_IN_RECV_BUFFER
RST_RECEIVED id=conn_unread to=CLIENT error=ECONNRESET_CONNECTION_RESET_BY_PEER
CONN_CLOSED id=conn_unread state=CLOSED time_wait=SKIPPED
STATS id=conn_unread state=CLOSED fin_sent=0 rst_sent=1 time_wait_count=0 econnreset_count=1 client_unread=0 server_unread=0
```

---

## 4. 실무 핵심 요약 (Architecture Takeaway)

1. **소켓 종료 전 수신 버퍼 완전 배수(Drain)**:
   - 클라이언트의 요청 페이로드를 중간에 자르고 `close()`하면 커널이 즉시 RST를 날려 클라이언트에 500/ECONNRESET 에러가 터집니다. 반드시 EOF까지 데이터를 모두 비우거나 `shutdown(SHUT_WR)` Half-Close를 활용해야 합니다.
2. **`SO_LINGER` Zero Linger 안티패턴 회피**:
   - TIME_WAIT는 네트워크 패킷 혼선을 막기 위한 필수적인 안전장치입니다. 포트 고갈을 피하겠다고 강제 RST를 날리면 통신 신뢰성이 무너집니다. 커넥션 풀링(Keep-Alive)으로 해결해야 합니다.
