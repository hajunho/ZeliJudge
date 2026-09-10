# 리눅스 커널 TCP Fast Open (RFC 7413) 아키텍처와 0-RTT 통신 이론

## 1. 전통적인 TCP 3-Way Handshake의 지연 시간 병목

인터넷 트래픽의 대다수를 차지하는 HTTP/1.1, HTTP/2 및 수많은 마이크로서비스 RPC 프로토콜은 단기성 TCP 연결(Short-lived TCP Connections)을 빈번하게 생성합니다.

전통적인 TCP 전송 제어 프로토콜(RFC 793)은 신뢰성 있는 전이중 통신 수립을 위해 엄격한 3단계 악수(3-Way Handshake: SYN -> SYN-ACK -> ACK)를 필수로 요구합니다:
1. **클라이언트 $\implies$ 서버**: 초기 시퀀스 번호 $ISN_c$를 담은 `SYN` 패킷 전송.
2. **서버 $\implies$ 클라이언트**: $ISN_s$와 함께 $ISN_c + 1$을 확인하는 `SYN-ACK` 패킷 응답.
3. **클라이언트 $\implies$ 서버**: $ISN_s + 1$을 확인하는 `ACK` 패킷 전송 후, 비로소 최초의 애플리케이션 데이터(예: HTTP GET 요청) 전송.

이 과정에서 클라이언트와 서버 간의 물리적 거리(Round Trip Time, RTT)로 인해 **최소 1-RTT(수십~수백 밀리초)의 고정 지연**이 발생합니다. TLS 1.2 핸드셰이크까지 결합되면 데이터 전송 전 3-RTT(수백 밀리초) 이상의 심각한 왕복 지연이 누적되어 사용자 체감 성능을 저해합니다.

---

## 2. TCP Fast Open (RFC 7413)의 탄생과 0-RTT 패러다임

2014년 IETF에서 표준화된 **TCP Fast Open(TFO / RFC 7413)**은 안전한 사전 인증 메커니즘을 통해 **첫 번째 SYN 패킷 자체에 애플리케이션 페이로드를 포함시키는 0-RTT 데이터 교환**을 실현했습니다.

```
       [Client]                                              [Server]
          │                                                     │
          │ ─── 1. SYN [TFO Cookie Request (Kind 34, Len 0)] ──>│
          │                                                     │ (HMAC-SHA256 / SipHash
          │                                                     │  Cookie = H(K_srv, Client_IP))
          │ <── 2. SYN-ACK [TFO Cookie (16 hex)] ───────────────│
          │                                                     │
          │ ─── 3. ACK ────────────────────────────────────────>│
          │                                                     │
     [Cache Cookie]                                             │
          │                                                     │
          │ (차후 연결 수립)                                      │
          │                                                     │
          │ ─── 4. SYN [TFO Cookie] + Data (0-RTT Request) ────>│ (쿠키 즉시 검증)
          │                                                     │ (소켓 수신 큐에 데이터 즉시 전달!)
          │ <── 5. SYN-ACK [Acking SYN + Data] + Data Response ─│
          │                                                     │
```

TFO가 적용되면, 클라이언트 애플리케이션은 연결이 완전히 수립되기 전에 이미 서버로부터 응답 데이터를 수신할 수 있으므로, 웹 페이지 로딩 속도를 최대 40% 이상 향상시킵니다.

---

## 3. 보안 위협 모델과 방어 아키텍처

만약 임의의 클라이언트가 `SYN` 패킷에 대용량 데이터를 실어 보낼 수 있다면, 인터넷은 치명적인 보안 공격에 노출됩니다:

### 3.1 IP 스푸핑 및 반사/증폭 디도스(Reflection/Amplification DDoS)
- **위협**: 공격자가 피해자의 IP로 소스 IP를 위조(Spoofing)한 후, 서버에 대용량 데이터를 요구하는 `SYN`을 보내면, 서버는 피해자에게 거대한 응답을 쏟아붓게 됩니다.
- **TFO 방어**: 서버는 오직 **사전에 정상적인 3-Way Handshake를 완료하여 해당 IP의 소유권을 입증한 클라이언트에게만 암호화된 TFO 쿠키를 발급**합니다. 위조된 IP로는 클라이언트가 쿠키를 수신할 수 없으므로 스푸핑된 SYN+Data 공격은 원천 차단됩니다.

### 3.2 TFO 암호화 쿠키 생성 메커니즘
서버는 클라이언트 상태를 별도로 메모리에 유지(Stateless)하지 않기 위해 대칭키 암호화 함수를 사용합니다:
$$
\text{Cookie} = \text{Truncate}_{16}(\text{HMAC-SHA256}(K_{\text{server}}, \text{Client\_IP}))
$$
리눅스 커널 구현(`net/ipv4/tcp_fastopen.c`)에서는 CPU 부하를 최소화하기 위해 초고속 의사난수 함수인 **SipHash-2-4** 또는 **AES-128**을 사용합니다.

### 3.3 SYN 플러드 및 소켓 버퍼 고갈 공격 방어
- 검증된 쿠키를 탈취하거나 합법적인 IP를 가진 악의적 노드가 수천 개의 `SYN + Data`를 연속으로 전송하면, 서버의 소켓 수신 버퍼와 백로그 메모리가 고갈될 수 있습니다.
- **방어 메커니즘**:
  - 리눅스 커널은 리스너 소켓마다 `fastopenq.max_qlen`이라는 전용 TFO 백로그 상한을 설정합니다 (`setsockopt(..., TCP_FASTOPEN, qlen)`).
  - 현재 미완료 TFO 연결 수(`current_queue_len`)가 `max_qlen`에 도달하면, 커널은 들어오는 SYN의 데이터 처리를 즉시 거부하고 표준 TCP 3-Way Handshake로 폴백(`FALLBACK_QUEUE_FULL`)하여 커널 메모리를 보호합니다.

### 3.4 키 로테이션 (Key Rotation) 무중단 지원
서버 보안을 위해 마스터 키는 주기적으로 교체되어야 합니다.
- 새 키(`server_primary_key`)가 도입되면 기존 키는 `server_backup_key`로 강등되어 유지됩니다.
- 클라이언트가 이전 백업 키로 서명된 쿠키를 보내더라도 즉각 거절하지 않고 0-RTT 데이터를 처리하되, `SYN-ACK`에 신규 프라이머리 키로 서명된 새 쿠키를 동봉하여 클라이언트 캐시를 자연스럽게 갱신(Self-Healing)합니다.

### 3.5 미들박스(Middlebox) 비호환성과 블랙홀 복구
일부 구형 라우터, 침입 방지 시스템(IPS), 방화벽은 `SYN` 패킷에 데이터 페이로드가 포함된 것을 비정상 비정형 패킷으로 간주하여 조용히 폐기(Blackhole Drop)합니다.
- 클라이언트는 SYN+Data 재전송 타이머(RTO)가 만료되면 이를 감지합니다.
- 패킷 드롭이 연속 임계치(`blackhole_threshold`) 이상 발생하면 해당 경로에 대해 TFO를 일시 비활성화(`tfo_disabled = true`)하고 일반 순수 SYN 패킷으로 즉시 전환하여 연결 장애를 회피합니다.

---

## 4. 리눅스 커널 소켓 프로그래밍 API

리눅스 커널에서 TFO를 활성화하기 위한 사용자 공간(Userspace) 시스템 콜 인터페이스:

### 4.1 서버 측 활성화
```c
int qlen = 50; // 최대 TFO 대기 큐 길이
setsockopt(listen_fd, IPPROTO_TCP, TCP_FASTOPEN, &qlen, sizeof(qlen));
```
- 커널 `sysctl`: `net.ipv4.tcp_fastopen`
  - `0x1`: 클라이언트 활성화
  - `0x2`: 서버 활성화
  - `0x3`: 클라이언트 및 서버 모두 활성화

### 4.2 클라이언트 측 0-RTT 전송
- 전통적 방식: `sendto(fd, buf, len, MSG_FASTOPEN, (struct sockaddr*)&serv_addr, addrlen)`
- 최신 리눅스 4.11+ 방식: `TCP_FASTOPEN_CONNECT` 소켓 옵션 설정 후 일반 `connect()` 및 `write()` 호출.

이와 같은 고도의 통신 공학적 설계를 통해 TCP Fast Open은 신뢰성과 보안성을 손상시키지 않으면서도 인터넷 통신의 오랜 숙원이었던 0-RTT 레이턴시를 달성했습니다.
