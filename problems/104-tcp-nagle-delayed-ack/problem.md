# [CS-104] TCP 네이글 알고리즘(Nagle's Algorithm)과 지연된 ACK(Delayed ACK) 40ms 지연의 저주 (`TCP_NODELAY`)

> **"로컬 환경에서는 0.1ms 만에 끝나던 마이크로서비스 간 RPC 호출이, 패킷 2번 쪼개 보냈을 뿐인데 왜 칼같이 40ms씩 지연되죠?!"**
> 
> 결제 백엔드를 담당하는 주니어 개발자 준호는 마이크로서비스 간 통신을 위한 고성능 HTTP/1.1 클라이언트를 직접 개발했습니다.
> 코드를 모듈화한다는 생각으로 `socket.write(http_header)`를 호출한 직후 곧바로 `socket.write(json_body)`를 호출했습니다.
> 로컬 루프백 테스트에서는 0.1ms 만에 즉시 끝나던 이 코드가, 사내 내부망 서버로 배포되자마자 모든 결제 승인 API의 p99 지연시간이 정확히 **40.2ms**로 치솟았습니다.
> 
> "DB 쿼리도 0.5ms밖에 안 걸리고 네트워크 핑도 0.2ms인데, 왜 모든 요청이 귀신에 홀린 듯 정확히 40ms씩 멈춰 설까요?!"
> 네트워크 시스템 아키텍트는 Wireshark 패킷 캡처 로그를 가리키며 씩 웃었습니다.
> "준호 씨, 컴퓨터 네트워크 역사상 가장 유명한 '두 천재의 선의가 빚어낸 40ms 교착상태'에 걸리셨군요. 존 네이글의 알고리즘과 버클리 소켓의 Delayed ACK가 서로를 하염없이 기다리고 있습니다."

---

## 1. 문제 배경과 현실 비유: 우체부와 수취인의 눈치 게임

컴퓨터 네트워크 전송 계층(TCP)에는 네트워크 회선 대역폭을 아끼기 위한 두 가지 유명한 최적화 알고리즘이 존재합니다.

1. **송신 측의 네이글 알고리즘 (Nagle's Algorithm, RFC 896, 1984)**:
   - "편지 한 통(작은 패킷 / Tinygram) 배달하러 굳이 우체부 차를 몰고 가지 않는다. 지난번에 보낸 편지의 수신 확인증(ACK)이 오기 전까지는, 우편 가방(MSS, 기본 1460B)이 꽉 찰 때까지 편지들을 우체통(버퍼)에 모아둔다!"
2. **수신 측의 지연된 ACK (Delayed ACK, RFC 1122)**:
   - "우체부가 편지 한 장 배달해줬다고 바로 빈 도장(빈 껍데기 ACK)을 찍어 답장 보내지 않는다. 어차피 40ms 이내에 보낼 답장 편지(응답 데이터)가 생기거나 다음 편지가 곧 도착할 수 있으니, 40ms 동안 기다렸다가 한 번에 묶어서 확인 도장(Piggybacked ACK)을 찍어준다!"

### 40ms 침묵 교착상태 (Interlock Deadlock)
하지만 클라이언트가 데이터를 두 번 나누어 쓰는 순간(**2-Write Pattern: 헤더 전송 후 곧바로 바디 전송**), 두 알고리즘의 선의는 재앙이 됩니다:
1. 클라이언트가 **헤더(50B)**를 씁니다. 아직 네트워크에 미확인(In-Flight) 패킷이 없으므로 Nagle 규칙이라도 첫 패킷은 즉시 전송됩니다.
2. 서버가 헤더를 수신합니다. "패킷이 1개 왔네? 응답 데이터나 다음 패킷이 올 때까지 40ms 기다렸다가 ACK 보내야지!" 하고 **40ms 타이머**를 켭니다.
3. 클라이언트가 곧바로 **바디(200B)**를 씁니다. 하지만 "아까 보낸 헤더(50B)의 ACK가 아직 안 왔고, 바디(200B)는 MSS(1460B)보다 작네? 기다려라!" 하고 **버퍼에 대기(BUFFERED)**시킵니다.
4. **침묵의 40ms**: 클라이언트는 서버의 ACK를 기다리고, 서버는 클라이언트의 2번째 패킷을 기다립니다!
5. 40ms 타이머가 만료되어서야 서버가 마지못해 빈 ACK를 보내고, 그제서야 클라이언트의 버퍼가 풀려 바디가 전송됩니다. 결과적으로 순수 연산/전송 시간과 무관하게 무조건 40ms의 인공 지연이 발생합니다!

---

## 2. 요구사항 및 명령어 사양

당신은 TCP 네이글 알고리즘과 지연된 ACK의 상호작용을 시뮬레이션하는 `TcpSimulator` 엔진을 구현해야 합니다.
표준 입력(`stdin`)으로 들어오는 명령어들을 한 줄씩 파싱하여 정확한 형식으로 표준 출력(`stdout`)에 출력하십시오.

### 지원 명령어 목록

1. `INIT_CONN <conn_id> <mss> <nagle: ON|OFF> <delayed_ack: ON|OFF>`
   - 지정된 식별자(`<conn_id>`), 세그먼트 최대 크기(`<mss>`), Nagle 활성화 여부, Delayed ACK 활성화 여부로 TCP 연결을 초기화합니다.
   - 출력: `INIT_CONN id=<conn_id> mss=<mss> nagle=<ON|OFF> delayed_ack=<ON|OFF>`

2. `APP_WRITE <conn_id> <time_ms> <bytes>`
   - 현재 시각 `<time_ms>`에 애플리케이션이 소켓에 `<bytes>` 크기의 데이터를 씁니다.
   - 먼저 경과 시간에 따른 타이머 만료 이벤트를 처리한 후, 데이터를 클라이언트 송신 버퍼에 추가합니다.
   - **송신 로직**:
     - **Nagle OFF (`TCP_NODELAY`)**:
       - 버퍼에 데이터가 있는 한, 최대 MSS 크기로 즉시 분할하여 패킷을 연속 전송합니다.
       - 출력: `PACKET_SENT id=<conn_id> time=<time_ms> size=<send_size> in_flight=<in_flight>`
       - 패킷 수신 시 서버 처리:
         - Delayed ACK OFF: 즉시 ACK 발송.
           - 출력: `ACK_SENT id=<conn_id> time=<time_ms> acked_packets=1 type=IMMEDIATE`
           - 출력: `ACK_RECEIVED id=<conn_id> time=<time_ms> in_flight=<in_flight>`
         - Delayed ACK ON: 2번째 패킷이 도착하면 즉시 누적 ACK 발송(`type=FULL_BURST`), 1번째 패킷이면 40ms 타이머 가동(`timer = time_ms + 40`).
     - **Nagle ON**:
       - 버퍼 크기 >= MSS 인 경우: MSS 단위로 즉시 전송하고 서버 수신을 처리합니다.
       - 0 < 버퍼 크기 < MSS 인 경우:
         - 만약 `in_flight == 0`이면 즉시 전송 허용.
         - 만약 `in_flight > 0`이면 송신을 보류하고 버퍼링 대기합니다.
         - 출력: `PACKET_BUFFERED id=<conn_id> time=<time_ms> buffered_bytes=<bytes> in_flight=<in_flight> reason=NAGLE_WAIT_ACK`

3. `ADVANCE_TIME <conn_id> <target_time_ms>`
   - 시간을 `<target_time_ms>`까지 전진시키며 만료된 타이머 이벤트를 처리합니다.
   - Delayed ACK 타이머(`timer <= target_time_ms`)가 만료되면:
     - 서버가 ACK를 전송:
       - 출력: `ACK_SENT id=<conn_id> time=<timer_time> acked_packets=<count> type=DELAYED_TIMER_EXPIRED`
       - 출력: `ACK_RECEIVED id=<conn_id> time=<timer_time> in_flight=<in_flight>`
     - 만약 버퍼에 대기 중이던 데이터가 있었다면, 40ms 지연시간을 누적(`total_interlock_delay_ms += 40`)하고 대기가 풀린 패킷을 즉시 송신합니다.

4. `STATS <conn_id>`
   - 연결 상태 및 통계를 출력합니다.
   - 출력: `STATS id=<conn_id> total_written=<bytes> total_packets_sent=<count> interlock_delay_ms=<delay_ms> nagle_buffered_count=<count> in_flight=<in_flight> buffered_bytes=<bytes>`

---

## 3. 입출력 예시

### 예시 입력 1
```text
INIT_CONN conn_nagle 1460 ON ON
APP_WRITE conn_nagle 0 50
APP_WRITE conn_nagle 0 200
ADVANCE_TIME conn_nagle 50
STATS conn_nagle
INIT_CONN conn_nodelay 1460 OFF ON
APP_WRITE conn_nodelay 0 50
APP_WRITE conn_nodelay 0 200
ADVANCE_TIME conn_nodelay 50
STATS conn_nodelay
```

### 예시 출력 1
```text
INIT_CONN id=conn_nagle mss=1460 nagle=ON delayed_ack=ON
PACKET_SENT id=conn_nagle time=0 size=50 in_flight=1
PACKET_BUFFERED id=conn_nagle time=0 buffered_bytes=200 in_flight=1 reason=NAGLE_WAIT_ACK
ACK_SENT id=conn_nagle time=40 acked_packets=1 type=DELAYED_TIMER_EXPIRED
ACK_RECEIVED id=conn_nagle time=40 in_flight=0
PACKET_SENT id=conn_nagle time=40 size=200 in_flight=1
STATS id=conn_nagle total_written=250 total_packets_sent=2 interlock_delay_ms=40 nagle_buffered_count=1 in_flight=1 buffered_bytes=0
INIT_CONN id=conn_nodelay mss=1460 nagle=OFF delayed_ack=ON
PACKET_SENT id=conn_nodelay time=0 size=50 in_flight=1
PACKET_SENT id=conn_nodelay time=0 size=200 in_flight=2
ACK_SENT id=conn_nodelay time=0 acked_packets=2 type=FULL_BURST
ACK_RECEIVED id=conn_nodelay time=0 in_flight=0
STATS id=conn_nodelay total_written=250 total_packets_sent=2 interlock_delay_ms=0 nagle_buffered_count=0 in_flight=0 buffered_bytes=0
```

---

## 4. 실무 핵심 요약 (Architecture Takeaway)

1. **`TCP_NODELAY`의 실무 기본값 채택**
   - Nginx, Netty, Redis, gRPC, Node.js 등 고성능 네트워크 소프트웨어는 지연시간(Latency) 단축을 위해 소켓 생성 시 무조건 `TCP_NODELAY = 1`을 기본값으로 활성화합니다.
2. **2-Write 안티패턴 지양**
   - 헤더와 바디를 따로따로 `write()`하는 대신, 단일 버퍼로 합쳐 1번의 시스템 콜(`write` 또는 `writev`)로 전송해야 소켓 버퍼링 및 패킷 단편화 오버헤드를 원천 차단할 수 있습니다.
