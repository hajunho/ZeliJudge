# 리눅스 커널 Netfilter Conntrack TCP 상태 머신, Out-of-Window 검증 및 SYNPROXY 이론적 심층 분석

## 1. 개요 및 넷필터 연결 추적(Conntrack) 아키텍처

리눅스 커널의 **넷필터(Netfilter)** 프레임워크는 네트워크 스택의 5대 훅 포인트(`PREROUTING`, `INPUT`, `FORWARD`, `OUTPUT`, `POSTROUTING`)에서 패킷을 가로채어 필터링, 수정, 라우팅합니다. 여기서 **Conntrack (`nf_conntrack`)**은 상태 비보존형(Stateless) 패킷 흐름에 영속적인 세션(Session) 개념을 부여하는 핵심 계층입니다.

모든 유입 패킷은 5-튜플(프로토콜, 송신지 IP, 목적지 IP, 송신지 포트, 목적지 포트)을 기반으로 고유한 해시 키를 생성하며, 커널은 양방향 흐름을 추적합니다:
- **`IP_CT_DIR_ORIGINAL`**: 연결을 개시한 측(클라이언트 $\to$ 서버).
- **`IP_CT_DIR_REPLY`**: 응답을 전송하는 측(서버 $\to$ 클라이언트).

TCP의 경우, 단순한 L4 패킷 전달을 넘어 송수신자 간의 핸드셰이크, 윈도우 크기 공지, 순서 번호 동기화, 그리고 연결 종료 시퀀스를 정밀하게 추적하는 프로토콜 전용 상태 머신(`net/netfilter/nf_conntrack_proto_tcp.c`)이 동작합니다.

---

## 2. TCP 윈도우 추적 (Window Tracking) 수리 모델

TCP는 신뢰성 있는 바이트 스트림 전달을 위해 슬라이딩 윈도우 프로토콜을 사용합니다. 방화벽이 단순한 포트/플래그 검사만 수행할 경우, 공격자가 정상 연결의 IP/포트를 위조하여 임의의 페이로드를 세션 중간에 주입하는 **TCP 시퀀스 번호 추측 및 리셋 공격(Blind In-Window Data Injection / RST Attack, RFC 4987/5961)**에 취약해집니다.

이를 방지하기 위해 Conntrack은 방향별로 다음과 같은 상태 변수를 유지합니다:
- **`td_end`**: 해당 방향에서 지금까지 전송된 가장 높은 시퀀스 번호 끝점 (즉, $\text{seq} + \text{len}$).
- **`td_maxend`**: 상대방으로부터 수신된 가장 높은 확인 응답 번호에 공지된 수신 윈도우를 더한 최대 허용 시퀀스 상한 (즉, $\text{ack} + \text{rwin}$).
- **`td_maxwin`**: 세션 동안 관측된 최대 수신 윈도우 크기 (윈도우 스케일링 적용 후).

### 2.1 32비트 모듈러 시퀀스 번호 비교
32비트 TCP 시퀀스 번호의 오버플로우 순환을 안전하게 비교하기 위해 커널은 모듈러 부호 있는 차이를 계산합니다:
$$\text{seq\_diff}(a, b) = \text{int32}((a - b) \pmod{2^{32}})$$
$$a \le b \iff \text{seq\_diff}(a, b) \le 0$$
$$a > b \iff \text{seq\_diff}(a, b) > 0$$

### 2.2 `tcp_in_window` 3대 판정 조건
`ESTABLISHED` 상태에서 유입된 패킷이 정당한 윈도우 내 패킷인지 확인하기 위해 다음 3대 조건을 엄격히 검사합니다:

1. **상한 경계 검사 (Upper Bound Check)**:
   패킷의 시작 시퀀스 번호는 상대방이 수신 가능한 최대 윈도우 상한을 초과해서는 안 됩니다.
   $$\text{seq} \le \text{receiver.td\_maxend}$$
   위반 시 `OUT_OF_WINDOW_ABOVE_MAXEND`로 판정하여 패킷을 드롭합니다.

2. **하한 경계 검사 (Lower Bound Check)**:
   패킷의 끝점($\text{seq} + \text{len}$)은 송신자가 이미 보낸 데이터 끝점에서 상대방 최대 윈도우를 뺀 값보다 작아서는 안 됩니다.
   $$\text{seq} + \text{len} \ge \text{sender.td\_end} - \text{receiver.td\_maxwin}$$
   너무 오래된 구형 지연 패킷(Stale Packet)은 `OUT_OF_WINDOW_TOO_OLD`로 드롭합니다.

3. **확인 응답 번호 유효성 검사 (Ghost ACK Defense)**:
   ACK 번호는 상대방이 이미 보낸 바이트 범위 내에 있어야 합니다. 아직 전송되지 않은 미래의 데이터를 승인하는 ACK는 허위 패킷입니다.
   $$\text{ack} \le \text{sender.td\_end}$$
   위반 시 `INVALID_ACK_BEYOND_SENT`로 드롭합니다.

---

## 3. SYN Flood 공격과 SYNPROXY (`nf_synproxy_core.c`)

### 3.1 SYN Flood와 Conntrack 테이블 고갈
일반적인 TCP 연결 수립 시, 최초 SYN 패킷이 도착하면 Conntrack은 즉시 메모리에 `nf_conn` 구조체를 할당하고 해시 테이블에 삽입합니다. 공격자가 수백만 대의 봇넷이나 위조된 무작위 소스 IP로 SYN 패킷만을 폭주시키면(SYN Flood), 서버의 Conntrack 테이블(`nf_conntrack_max`)이 수 초 만에 100% 가득 차며 커널 로그에 다음과 같은 재앙적 에러가 출력됩니다:
```text
nf_conntrack: table full, dropping packet
```
이 상태에서는 합법적인 사용자의 정상적인 신규 연결 요청이 전면 거부됩니다.

### 3.2 SYNPROXY의 무상태(Stateless) 완화 원리
리눅스 커널의 **SYNPROXY**는 패킷이 Conntrack에 도달하기 전 `PREROUTING` 단계에서 동작하여 메모리 할당 없이 SYN Flood를 원천 무력화합니다:

```
[Attacker / Client]                 [SYNPROXY (Firewall)]               [Backend Server]
        |                                     |                                 |
        |--- (1) SYN ------------------------>|                                 |
        |    (No Conntrack entry created!)    |                                 |
        |<-- (2) SYN/ACK (Cookie) ------------|                                 |
        |                                     |                                 |
        |--- (3) ACK (ack = Cookie + 1) ----->|                                 |
        |    (Cookie verified successfully!)  |                                 |
        |                                     |--- (4) SYN (Backend) ---------->|
        |                                     |<-- (5) SYN/ACK (Backend) -------|
        |                                     |--- (6) ACK (Backend) ---------->|
        |<========== (7) Established Session with Conntrack ===================>|
```

1. **무상태 SYN Cookie 생성**:
   클라이언트 SYN 도착 시 Conntrack 메모리를 일절 할당하지 않고, 클라이언트 시퀀스 번호, 윈도우, 타임스탬프, 그리고 암호학적 비밀키(`synproxy_secret`)를 해싱한 암호학적 **SYN Cookie**를 초기 시퀀스 번호(ISN)로 삼아 즉석에서 가상 SYN/ACK를 전송합니다.
2. **위조 ACK 차단**:
   공격자가 보낸 가짜 SYN이나 무작위 ACK는 쿠키 검증에 실패하여 즉각 드롭됩니다.
3. **정당한 3번째 ACK 검증 및 백엔드 스플라이싱**:
   정상적인 클라이언트만이 방화벽이 보낸 쿠키에 1을 더한 ACK 번호(`ack == cookie + 1`)를 반환할 수 있습니다. 유효한 쿠키가 확인된 순간, SYNPROXY는 비로소 정식 Conntrack 세션을 수립하고 백엔드 서버와 3-way 핸드셰이크를 완료한 뒤 클라이언트-서버 간 트래픽을 투명하게 포워딩합니다.

---

## 4. 결론 및 실무적 가치

Netfilter Conntrack TCP 엔진과 SYNPROXY의 유기적 결합은 고성능 리눅스 라우터, 클라우드 게이트웨이, Kubernetes Ingress 컨트롤러, 그리고 금융권 고신뢰 네트워크 인프라에서 수천만 PPS의 대규모 DDoS 공격 속에서도 0-Downtime으로 합법 트래픽을 완벽히 보호하는 커널 네트워크 엔지니어링의 최고봉입니다.
