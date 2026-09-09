# TCP 핸드셰이크와 리눅스 커널의 이중 큐(SYN Backlog vs Accept Queue)

> "플래시 세일 오픈 10초 만에 클라이언트 앱에서 결제 요청 연결 타임아웃(Connection Timeout)이 폭발했습니다!  
> 서버 모니터링을 확인해보니 CPU 사용률은 25%에 불과하고 메모리도 절반이나 남아있으며 네트워크 대역폭도 널널합니다.  
> 패킷 덤프를 떠보니 클라이언트는 TCP 3-Way Handshake(SYN -> SYN-ACK -> ACK)를 정상적으로 보냈는데,  
> **서버 커널이 클라이언트의 마지막 ACK를 말없이 버려버리고 1초 뒤에 SYN-ACK를 다시 보내며 클라이언트를 1초 동안 얼어붙게 만들고 있었습니다!**  
> 3-Way Handshake가 분명히 끝났는데, 왜 커널은 연결을 맺어주지 않고 무시해 버린 걸까요?!"

---

## 1. 리눅스 커널의 TCP 연결 수립 2단계 이중 큐 구조

많은 개발자들이 `socket() -> bind() -> listen() -> accept()` 흐름을 배울 때, 연결 큐가 1개만 존재한다고 오해합니다.  
하지만 리눅스 커널은 TCP 연결을 맺을 때 **서로 다른 상태의 연결을 관리하기 위해 2개의 독립된 큐**를 운용합니다.

```
[클라이언트 (Client)]                                [리눅스 커널 (Linux Kernel)]                     [애플리케이션 (Tomcat/Nginx)]
        │                                                         │                                                │
        │ 1. SYN ────────────────────────────────────────────────►│ (1) SYN Queue (Incomplete Connection Queue)   │
        │                                                         │     상태: SYN_RECV                             │
        │                                                         │     크기: net.ipv4.tcp_max_syn_backlog         │
        │◄── 2. SYN-ACK ──────────────────────────────────────────│                                                │
        │                                                         │                                                │
        │ 3. ACK (클라이언트는 ESTABLISHED 완료!) ────────────────►│ (2) Accept Queue (Complete Connection Queue) │
        │                                                         │     상태: ESTABLISHED                          │
        │                                                         │     크기: min(listen backlog, somaxconn)       │
        │                                                         │                                                │
        │                                                         │◄── accept() 시스템 콜 ─────────────────────────│
        │                                                         │    (완성된 소켓을 꺼내가 비즈니스 스레드 할당)   │
```

### (1) SYN Queue (반가설 큐 / Incomplete Connection Queue)
- **보관 대상**: 클라이언트의 `SYN`을 받고 서버가 `SYN-ACK`를 보낸 뒤, 마지막 `ACK`가 오기를 기다리는 **미완성 연결(`SYN_RECV` 상태)**.
- **크기 제어**: 커널 파라미터 `net.ipv4.tcp_max_syn_backlog` (기본값: 보통 128~1024).
- **SYN Flood 방어**: 해커가 가짜 IP로 `SYN`만 무한히 보내 SYN 큐를 고갈시키는 공격(SYN Flood)이 들어오면, `net.ipv4.tcp_syncookies = 1` 설정 시 암호화된 타임스탬프 쿠키(SYN Cookie)를 발행하여 큐에 소켓을 저장하지 않고도 핸드셰이크를 이어갑니다.

### (2) Accept Queue (완가설 큐 / Complete Connection Queue / Listen Backlog)
- **보관 대상**: 클라이언트의 3단계 `ACK`를 수신하여 **TCP 3-Way Handshake가 완벽하게 끝난 연결(`ESTABLISHED` 상태)**.
- 이 연결들은 애플리케이션(톰캣 워커 스레드나 Nginx 워커 프로세스)이 `accept()` 시스템 콜을 호출하여 가져가기 전까지 이 큐에서 대기합니다.
- **크기 결정 공식**:
  $$	ext{Effective Accept Queue Limit} = \min(	ext{backlog in } listen(fd, backlog), 	ext{net.core.somaxconn})$$

---

## 2. somaxconn 기본값(128)의 배신과 Accept 큐 오버플로우

이커머스 대규모 트래픽에서 참사가 터지는 지점은 바로 **Accept 큐의 크기 제한**입니다.

1. 개발자가 톰캣 `server.xml`의 `<Connector acceptCount="1024">`나 Nginx `nginx.conf`의 `listen 80 backlog=1024;`를 설정했습니다.
2. 하지만 리눅스 커널의 `net.core.somaxconn` 기본값이 과거 **`128`**로 잡혀 있다면:
   $$\min(1024, 128) = 128$$
3. 커널은 애플리케이션이 요청한 1024를 무시하고 **128개로 강제 축소(Clamping)**해 버립니다!
4. 플래시 세일 오픈 순간 500개의 연결이 일시에 쏟아져 들어오면, 톰캣 워커 스레드가 미처 `accept()`를 호출해 꺼내가기도 전에 128개의 Accept 큐가 0.01초 만에 꽉 차버립니다!

---

## 3. Accept 큐가 꽉 찼을 때 커널의 행동: `tcp_abort_on_overflow`

Accept 큐가 꽉 찬 상태에서 클라이언트의 3단계 `ACK`가 도착하면 커널은 어떻게 반응할까요?  
이 동작은 커널 파라미터 **`net.ipv4.tcp_abort_on_overflow`**에 의해 결정됩니다.

```
+-----------------------------------------------------------------------------------+
| Accept 큐 포화 시 tcp_abort_on_overflow 동작 비교                                 |
+---------------------+-------------------------------+-----------------------------+
| 설정값              | 커널의 동작 방식              | 클라이언트가 겪는 증상      |
+---------------------+-------------------------------+-----------------------------+
| 0 (리눅스 기본값)   | 클라이언트의 마지막 ACK를     | 클라이언트는 연결된 줄 알고 |
|                     | 조용히 버림(Silent Drop)!     | 데이터를 보내려다 1초 정지. |
|                     | 서버는 SYN-ACK를 재전송함     | (1초, 3초 지연 및 타임아웃) |
+---------------------+-------------------------------+-----------------------------+
| 1                   | 클라이언트에게 즉시 RST       | 클라이언트 즉시 에러 발생   |
|                     | (Reset) 패킷을 날려 강제 종료 | Connection Reset by Peer    |
|                     |                               | (ECONNRESET 에러 즉시 발생) |
+---------------------+-------------------------------+-----------------------------+
```

### 왜 기본값(0)은 ACK를 버리고 SYN-ACK를 다시 보낼까?
- 리눅스 커널 설계자들의 철학:
  *"지금 서버의 톰캣이 과부하로 `accept()`가 밀렸지만, 1초 뒤에는 워커 스레드가 일을 끝내고 큐를 비울 수도 있잖아? 그러니 연결을 당장 폭파(RST)하지 말고, 클라이언트의 ACK를 버려두면 서버가 SYN-ACK를 다시 보낼 테고, 그 사이에 Accept 큐에 자리가 나면 연결을 구제할 수 있을 거야!"*
- **하지만 현실의 결과**:
  - 클라이언트는 이미 `connect()`가 성공했다고 믿고 HTTP 요청 바이트를 보내지만, 서버는 아직 소켓을 안 열었으므로 데이터를 받지 못합니다.
  - 클라이언트는 최소 RTO(보통 1초) 동안 멍하니 대기(Stall)하며 지연 시간이 1,000ms로 폭등하게 됩니다!

---

## 4. 실무 진단 명령어와 커널 튜닝

### (1) 소켓 상태 실시간 확인 (`ss -lnt`)
```bash
$ ss -lnt
State      Recv-Q Send-Q  Local Address:Port
LISTEN     129    128     0.0.0.0:8080
```
- **`Send-Q`**: 해당 포트에 설정된 Accept 큐의 최대 크기 ($\min(backlog, somaxconn)$).
- **`Recv-Q`**: 현재 Accept 큐에서 애플리케이션의 `accept()`를 기다리고 있는 완성된 소켓 개수.
- `Recv-Q > Send-Q`이면 Accept 큐가 100% 넘쳐서 패킷이 버려지고 있는 현장입니다!

### (2) 커널 통계 카운터 확인 (`netstat -s`)
```bash
$ netstat -s | grep -i listen
    14820 times the listen queue of a socket overflowed # Accept 큐 넘침!
    14820 SYNs to LISTEN sockets dropped                # 큐 포화로 버려진 패킷!
```

### (3) 완벽한 실무 인프라 해결책
```bash
# 1. 커널 파라미터 상향 (/etc/sysctl.conf)
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.tcp_syncookies = 1

# 2. 적용
$ sysctl -p

# 3. Nginx / Tomcat 설정 동기화
# nginx.conf: listen 80 backlog=4096;
# server.xml: <Connector port="8080" acceptCount="4096" ... />
```
