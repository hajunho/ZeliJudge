# Problem 196: 리눅스 TCP 네트워크 스택: SYN Flood 공격, SYN 반가상화 쿠키(SYN Cookies)와 리슨 백로그(Listen Backlog) 큐 드롭 방어

## 문제 설명

글로벌 결제 게이트웨이 및 금융 핀테크 인프라를 운영하는 네트워크 보안 SRE 엔지니어링 팀은 분산 서비스 거부(DDoS) 공격 상황에서 원인 불명의 대규모 서비스 불능 사태를 겪었습니다.

외부 공격자가 위조된 IP 주소(IP Spoofing)로 초당 수만 건의 TCP `SYN` 패킷을 전송하고 마지막 `ACK`를 보내지 않는 **TCP SYN Flood 공격**을 가했을 때, 정상적인 결제 고객들의 TCP 연결 수립이 전면 차단되며 타임아웃 오류가 빗발쳤습니다.

리눅스 커널 네트워크 스택 추적(`netstat -s`, `ss -lnt`, `/proc/net/netstat`) 결과, 커널의 **반연결 큐(SYN Queue / Incomplete Connection Queue)**가 고갈되어 신규 연결이 모두 폐기(Drop)되고 있었으며, 사용자 애플리케이션의 `accept()` 지연으로 인해 **완결 큐(Accept Queue)** 또한 오버플로우를 겪고 있었습니다.

---

## 핵심 시스템 배경 및 원리

### 1. 리눅스 TCP 3-Way Handshake의 2단계 큐 아키텍처
리눅스 커널 TCP 스택은 리슨 소켓(`listen_fd`)에 대해 독립적인 두 개의 큐를 운용합니다:

1. **SYN 큐 (반연결 큐 / Incomplete Connection Queue)**:
   - 클라이언트가 보낸 최초의 `SYN` 패킷을 수신하면, 커널은 `SYN-ACK`를 응답하고 `request_sock` 메모리 구조체를 생성하여 SYN 큐에 보관합니다(상태: `SYN_RECV`).
   - 큐 크기 상한: `net.ipv4.tcp_max_syn_backlog`.
2. **Accept 큐 (완결 큐 / Complete Connection Queue)**:
   - 클라이언트로부터 최종 `ACK`를 수신하면 3-Way Handshake가 완결되어 상태가 `ESTABLISHED`로 전이되고 Accept 큐로 이동합니다.
   - 사용자 공간 애플리케이션은 `accept()` 시스템 콜을 호출하여 이 큐에서 소켓을 꺼내갑니다.
   - 큐 크기 상한: $\min(\text{app\_listen\_backlog}, \text{net.core.somaxconn})$.

### 2. SYN Flood 공격과 큐 고갈 참사
- 공격자가 위조된 IP로 대량의 `SYN`을 보내고 `ACK`를 보내지 않으면, SYN 큐의 모든 슬롯이 응답 대기 상태로 가득 찹니다.
- 큐가 가득 차면, 이후 도착하는 정상 클라이언트의 `SYN` 패킷이 커널에 의해 무차별 폐기되어 서비스가 붕괴됩니다(`TCP_SYN_FLOOD_QUEUE_EXHAUSTION_COLLAPSE`).

### 3. 방어 기법: SYN Cookies (`net.ipv4.tcp_syncookies = 1`)
- SYN 큐가 가득 찼을 때, 커널은 `request_sock` 메모리를 할당하는 대신 **연결 상태 정보를 암호화 해시로 인코딩한 초기 시퀀스 번호(ISN, Initial Sequence Number)**를 생성하여 `SYN-ACK`에 실어 보냅니다.
  $$\text{ISN} = \text{Hash}(\text{src\_ip}, \text{src\_port}, \text{dst\_ip}, \text{dst\_port}, \text{secret}) + t + \text{MSS\_Index}$$
- **핵심**: 서버 메모리를 일절 소비하지 않는 완전 무상태(Stateless) 방식입니다!
- 스푸핑 공격자는 가짜 IP이므로 `ACK`를 보낼 수 없어 공격이 무력화됩니다.
- 정상 클라이언트가 `ack_seq = ISN + 1`을 포함한 최종 `ACK`를 보내오면, 커널은 쿠키를 무상태로 검증하여 즉시 Accept 큐에 연결을 생성합니다.

### 4. Accept 큐 오버플로우 방어
- 애플리케이션이 바빠서 `accept()`를 제때 호출하지 못하면 Accept 큐가 꽉 찹니다.
- `net.core.somaxconn`과 `listen(fd, backlog)` 파라미터를 시스템 규모에 맞게 상향하고 논블로킹 이벤트 루프를 구축해야 병목을 방지할 수 있습니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "system": {
    "tcp_max_syn_backlog": 20,
    "net_core_somaxconn": 128,
    "app_listen_backlog": 128,
    "tcp_syncookies": 1
  },
  "traffic": [
    {
      "timestamp_ms": 0.0,
      "type": "RECV_SYN",
      "client_id": "atk_0",
      "is_legitimate": false
    },
    {
      "timestamp_ms": 35.0,
      "type": "RECV_SYN",
      "client_id": "user_alice",
      "is_legitimate": true
    },
    {
      "timestamp_ms": 45.0,
      "type": "RECV_FINAL_ACK",
      "client_id": "user_alice",
      "is_legitimate": true
    },
    {
      "timestamp_ms": 50.0,
      "type": "APP_ACCEPT",
      "count": 1
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 형식 결과를 출력합니다.

```json
{
  "status": "SUCCESS",
  "kernel_config": {
    "tcp_max_syn_backlog": 20,
    "net_core_somaxconn": 128,
    "app_listen_backlog": 128,
    "effective_accept_limit": 128,
    "tcp_syncookies": 1
  },
  "metrics": {
    "total_syn_received": 31,
    "syn_floods_dropped": 0,
    "syn_cookies_generated": 11,
    "syn_cookies_validated": 1,
    "legitimate_connections_established": 1,
    "legitimate_connections_rejected": 0,
    "accept_queue_overflow_drops": 0,
    "verdict": "OPTIMAL_SYN_COOKIES_DEFENSE"
  }
}
```

### 판정 규칙 (Verdict Rules)
1. `legitimate_connections_rejected > 0`이고 `tcp_syncookies == 0`:
   - `status = "FAILED"`, `verdict = "TCP_SYN_FLOOD_QUEUE_EXHAUSTION_COLLAPSE"`
2. `accept_queue_overflow_drops > 0`이고 `effective_accept_limit < 64`:
   - `status = "FAILED"`, `verdict = "ACCEPT_QUEUE_OVERFLOW_BACKLOG_BOTTLENECK"`
3. 정상 사용자가 거절당한 경우:
   - `status = "FAILED"`, `verdict = "LEGITIMATE_CLIENT_HANDSHAKE_DROPPED"`
4. SYN Cookie 및 적정 백로그로 정상 연결이 100% 수립된 경우:
   - `status = "SUCCESS"`, `verdict = "OPTIMAL_SYN_COOKIES_DEFENSE"`
