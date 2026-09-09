# 134. TCP 핸드셰이크는 끝났는데 왜 백엔드 연결이 1초씩 멈추고 연결이 끊겨요?!: 리눅스 커널의 이중 큐(SYN Backlog vs Accept Queue)와 somaxconn / tcp_abort_on_overflow 참사

## 문제 설명

대규모 모바일 커머스 앱의 인프라/백엔드 엔지니어 젤리(Zeli)는 선착순 한정 수량 특가 세일 이벤트를 오픈했습니다.  
오픈 직후 10초 만에 수만 명의 모바일 앱 사용자가 몰려들면서 클라이언트 네트워크 모니터링 로그에 충격적인 에러가 빗발쳤습니다! 🚨

```
[Client Error] java.net.SocketTimeoutException: Connect timed out (1,000ms delay!)
[Client Error] Connection reset by peer (ECONNRESET)
[Client Error] SYN retransmission to server 203.0.113.10:8080 timed out
```

서버 엔지니어 젤리는 즉시 백엔드 API 서버(Spring Boot / Tomcat)의 리소스 상태를 확인했습니다:

```bash
$ top
%Cpu(s): 24.2 us,  4.1 sy,  0.0 ni, 71.7 id ...  # CPU 70% 이상 널널함!
MiB Mem :  16000.0 total,   8420.0 free ...      # 메모리 8GB 이상 여유!
```

*"서버 CPU도 25%밖에 안 쓰고, 메모리도 8GB나 넉넉하고 네트워크 대역폭도 충분한데, 도대체 왜 수천 명의 클라이언트가 연결(Connect)조차 맺지 못하고 1초, 3초씩 멈추거나 튕겨버린 걸까요?!"* 😱

---

### 원인: 리눅스 커널의 이중 큐(SYN Queue vs Accept Queue)와 somaxconn의 배신

TCP 연결 수립 과정에서 리눅스 커널은 **두 개의 독립적인 큐(Queue)**를 사용합니다:

```
[클라이언트]                                          [리눅스 커널]                                     [애플리케이션 (Tomcat/Nginx)]
    │                                                      │                                                  │
    │ 1. SYN ─────────────────────────────────────────────►│ (1) SYN Queue (Incomplete Connection Queue)     │
    │                                                      │     상태: SYN_RECV                               │
    │                                                      │     크기: net.ipv4.tcp_max_syn_backlog           │
    │◄── 2. SYN-ACK ───────────────────────────────────────│                                                  │
    │                                                      │                                                  │
    │ 3. ACK (3-Way Handshake 완료!) ─────────────────────►│ (2) Accept Queue (Complete Connection Queue)   │
    │                                                      │     상태: ESTABLISHED                            │
    │                                                      │     크기: min(listen backlog, somaxconn)         │
    │                                                      │                                                  │
    │                                                      │◄── accept() 시스템 콜 ───────────────────────────│
    │                                                      │    (완성된 소켓을 꺼내가 워커 스레드에 할당)     │
```

1. **SYN Queue (반가설 큐)**:
   - `SYN`을 수신하고 `SYN-ACK`를 보낸 뒤 클라이언트의 마지막 `ACK`를 기다리는 미완성 연결 보관.
   - 크기 한도: `tcp_max_syn_backlog`.
   - `tcp_syncookies = 1`이면 큐가 가득 차도 SYN 쿠키로 전환하여 패킷 드롭을 방어합니다.
2. **Accept Queue (완가설 큐 / Listen Backlog)**:
   - 클라이언트가 3단계 `ACK`를 전송하여 3-Way Handshake가 끝난 완성 소켓 보관.
   - 애플리케이션 프로세스가 `accept()` 시스템 콜을 호출하여 가져가기 전까지 대기.
   - **실제 큐 크기 한도**:
     $$	ext{Effective Limit} = \min(	ext{app\_listen\_backlog}, 	ext{somaxconn})$$
   - **somaxconn의 배신**: 톰캣이나 Nginx에 `backlog=1024`를 설정했더라도, 리눅스 커널 파라미터 `net.core.somaxconn`의 기본값이 **128**로 되어 있으면 커널이 128개로 강제 축소해 버립니다!

---

### Accept 큐가 꽉 찼을 때의 참사: `tcp_abort_on_overflow`

Accept 큐가 128개로 꽉 찬 상태에서 클라이언트의 마지막 `ACK`가 도착하면 커널 파라미터 `tcp_abort_on_overflow`에 따라 비극이 벌어집니다:

- **`tcp_abort_on_overflow = 0` (리눅스 기본값)**:
  - 커널은 클라이언트의 마지막 `ACK`를 **조용히 무시하고 버려버립니다(Silent Drop)!**
  - 클라이언트는 `ACK`를 보냈으므로 자기는 `ESTABLISHED` 상태가 되었다고 착각하지만, 서버는 소켓을 열지 못했습니다.
  - 서버는 자신이 보낸 `SYN-ACK`가 유실된 줄 알고 **1초 뒤에 `SYN-ACK`를 재전송**합니다.
  - 클라이언트는 이미 요청 바이트를 보내려다가 최소 1초 동안 정지(Stall)하며 레이턴시가 폭발합니다!
- **`tcp_abort_on_overflow = 1`**:
  - 커널이 클라이언트에게 즉시 **RST(Reset)** 패킷을 쏘아 연결을 강제로 끊어버립니다 (`ECONNRESET`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "somaxconn": 128,                     // 커널 Accept 큐 상한선
  "tcp_max_syn_backlog": 128,           // 커널 SYN 큐 상한선
  "tcp_abort_on_overflow": 0,          // 0: Silent Drop & SYN-ACK 재전송, 1: 즉시 RST
  "tcp_syncookies": 1,                 // 1: SYN Flood 쿠키 활성화, 0: 비활성화
  "app_listen_backlog": 1024,          // 애플리케이션 listen(fd, backlog) 설정값
  "app_accept_interval_ms": 20,        // 애플리케이션 accept() 호출 주기 (ms)
  "app_accept_batch_size": 10,         // 1회 accept() 호출 시 꺼내가는 최대 소켓 수
  "connection_attempts": [
    {
      "client_id": "cli_01",
      "syn_time_ms": 0,
      "rtt_ms": 10                      // 왕복 시간 (SYN 전송 후 ACK 도착까지 걸리는 시간)
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다:

```json
{
  "summary": {
    "somaxconn": 128,
    "app_listen_backlog": 1024,
    "effective_accept_queue_limit": 128,
    "tcp_max_syn_backlog": 128,
    "tcp_abort_on_overflow": 0,
    "tcp_syncookies": 1,
    "total_attempts": 20,
    "successful_connections": 5,
    "syn_drops": 0,
    "syn_cookie_used": 0,
    "accept_queue_overflows": 15,
    "syn_ack_retransmits": 15,
    "rst_sent_count": 0,
    "peak_syn_queue": 20,
    "peak_accept_queue": 5,
    "overall_verdict": "ACCEPT_QUEUE_OVERFLOW_SILENT_DROP_STALL"
  },
  "client_results_sample": [
    {
      "client_id": "cli_01",
      "syn_time": 0,
      "status": "ACCEPTED",
      "accepted_at_ms": 20
    }
  ]
}
```

---

## 제약 사항 및 상태 판정 기준

- `effective_accept_queue_limit = min(app_listen_backlog, somaxconn)`
- `overall_verdict` 판정 기준:
  - `accept_queue_overflows > 0`:
    - `tcp_abort_on_overflow == 1`이면 `"ACCEPT_QUEUE_OVERFLOW_RST_STORM"`
    - `tcp_abort_on_overflow == 0`이면 `"ACCEPT_QUEUE_OVERFLOW_SILENT_DROP_STALL"`
  - `accept_queue_overflows == 0`이고 `syn_drops > 0`:
    - `"SYN_QUEUE_EXHAUSTION_DROP"`
  - `accept_queue_overflows == 0`이고 `syn_drops == 0`이며 `syn_cookie_used > 0`:
    - `"SYN_FLOOD_MITIGATED_BY_COOKIES"`
  - 모든 연결이 성공적으로 수립된 경우:
    - `"ALL_CONNECTIONS_HEALTHY"`
