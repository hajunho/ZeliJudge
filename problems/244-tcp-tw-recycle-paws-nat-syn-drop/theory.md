# Problem 244 Theory: 리눅스 커널 TCP 트랜스포트 심층 분석 — `TIME_WAIT` 상태, RFC 7323 PAWS, `tcp_tw_recycle`의 태생적 결함 및 `tcp_tw_reuse`

인터넷 트래픽의 근간을 이루는 TCP(Transmission Control Protocol)에서 연결 종료 시 진입하는 **`TIME_WAIT` 상태**는 네트워크 안정성을 보장하기 위한 필수적인 안전장치입니다. 그러나 고성능 웹 서버 환경에서 과도하게 누적되는 `TIME_WAIT` 소켓을 성급하게 줄이려다 수많은 프로덕션 장애를 낳았던 대표적인 사례가 바로 **`net.ipv4.tcp_tw_recycle`**의 도입과 폐기 역사입니다.

본 문서에서는 RFC 793 및 RFC 7323(TCP Extensions for High Performance)의 PAWS 메커니즘, `tcp_tw_recycle`이 NAT 환경에서 필연적으로 실패할 수밖에 없는 커널 내부 원리, 그리고 안전한 대체 기법인 `tcp_tw_reuse`를 심층 분석합니다.

---

## 1. TCP `TIME_WAIT` 상태의 존재 이유 (RFC 793)

TCP 연결에서 능동적 종료(Active Close, 먼저 `close()` 호출)를 수행한 엔드포인트는 반드시 `TIME_WAIT` 상태로 전이되어 $2 \times \text{MSL}$ (Maximum Segment Lifetime, 리눅스 기본 60초) 동안 소켓을 보존합니다.

```
                    TCP 정상 4-Way Handshake 종료와 TIME_WAIT
                    
       Active Closer (Server)                      Passive Closer (Client)
             │                                               │
             │── 1. FIN (seq=u) ────────────────────────────►│
             │◄── 2. ACK (ack=u+1) ──────────────────────────┤
             │◄── 3. FIN (seq=v, ack=u+1) ───────────────────┤
             │                                               │
             │── 4. ACK (ack=v+1) ──────────────────────────►│
             ▼                                               ▼
      [TIME_WAIT 상태 진입]                                [CLOSED]
      (2 * MSL = 60초 타이머 대기)
```

### 1.1 `TIME_WAIT`의 두 가지 필수 목적
1. **마지막 ACK 유실 시의 안전한 재전송 보장**:
   - 서버가 보낸 마지막 ACK(4번)이 네트워크 장애로 유실되면, 클라이언트는 FIN(3번)을 재전송합니다.
   - 만약 서버가 즉시 소켓을 파기했다면 클라이언트의 재전송 FIN에 대해 `RST`를 반환하여 클라이언트 애플리케이션에 비정상 종료 에러(`Connection reset by peer`)가 발생합니다.
2. **지연 패킷(Old Duplicate Segment)에 의한 신규 연결 오염 방지**:
   - 네트워크 라우터 큐에 갇혀 지연되던 패킷이 뒤늦게 도착했을 때, 동일한 4-튜플(`src_ip, src_port, dst_ip, dst_port`)로 새로 맺어진 차세대 연결(Reincarnation)의 데이터로 오인되는 참사를 방지합니다.

---

## 2. RFC 7323 PAWS (Protection Against Wrapped Sequences)

10Gbps, 100Gbps 고속 네트워크에서는 TCP의 32비트 시퀀스 번호($2^{32} \approx 4.29\,\text{GB}$)가 불과 수 초 만에 한 바퀴를 돌아 재사용(Wrapping)됩니다.

이를 방지하기 위해 **TCP Timestamps 옵션(RFC 7323)**이 도입되었습니다:
- 모든 TCP 세그먼트 헤더에 32비트 타임스탬프 값(`TSval`)과 에코 응답값(`TSecr`)이 실려 전달됩니다.
- **PAWS 검사 알고리즘**:
  - 수신된 세그먼트의 시퀀스 번호가 수신 윈도우 내에 있더라도, 세그먼트의 타임스탬프가 최근 수신한 타임스탬프보다 과거의 것이라면($\text{SEG.TSval} < \text{TS.recent}$), 커널은 이를 **오래된 중복 패킷으로 간주하고 폐기(Drop)**합니다.

---

## 3. `tcp_tw_recycle`의 치명적 결함과 커널 내부 메커니즘

### 3.1 `tcp_tw_recycle`의 동작 원리
`tcp_tw_recycle = 1`을 켜면 커널은 `TIME_WAIT` 시간을 60초에서 $3.5 \times \text{RTO}$ (통상 $1\sim3$초)로 대폭 단축합니다.
이처럼 소켓을 빨리 닫아버리면 과거 패킷이 신규 연결로 유입될 위험이 생기므로, 커널은 이를 방어하기 위해 **`struct inet_peer` 전역 캐시**에 원격 IP 주소별로 마지막 타임스탬프를 기록해 둡니다.

```c
// net/ipv4/tcp_ipv4.c: tcp_v4_conn_request() (커널 4.12 이전 소스 개념도)
if (tcp_tw_recycle && tcp_peer_is_proven(dst, skb)) {
    if (!tcp_peer_ts_is_valid(peer, skb)) {
        NET_INC_STATS_BH(sock_net(sk), LINUX_MIB_PAWSPASSIVEREJECTED);
        goto drop; // <-- SYN 패킷을 조용히 드롭!
    }
}
```

### 3.2 NAT(Network Address Translation) 환경에서의 대참사
- **커널의 잘못된 가정**: 리눅스 커널 개발 당시에는 "하나의 공인 IP 주소 = 하나의 물리적 호스트(단일 클록)"라는 가정을 전제로 설계되었습니다.
- **현대 인터넷 환경 (NAT & CGNAT)**:
  - 기업 전용선, 공유기, 이동통신망(LTE/5G) 기지국 뒤에서는 수천 대의 서로 다른 디바이스(노트북, 스마트폰)가 **단 1개의 동일한 공인 NAT IP**를 공유합니다.
  - 각 디바이스는 제각기 다른 시각에 부팅되었으므로 각자의 로컬 클록(`TSval`)이 완전히 제각각입니다.
- **재앙의 발생**:
  1. 기기 A(부팅 후 100일 경과, $\text{TSval} = 8,640,000$)가 접속 후 종료 $\to$ 서버는 `peer(203.0.113.50) = 8,640,000` 기록.
  2. 기기 B(방금 부팅됨, $\text{TSval} = 10,000$)가 동일 공인 IP에서 `SYN` 전송.
  3. 서버의 검사: $10,000 < 8,640,000$ (과거의 쓰레기 패킷으로 오판!).
  4. **결과**: 서버는 기기 B의 SYN 패킷을 사일런트 드롭하고 침묵합니다. 기기 B는 1초, 3초, 7초 재전송을 반복하다가 영구 연결 타임아웃에 빠집니다.

---

## 4. `tcp_tw_recycle`의 폐기와 올바른 대안 `tcp_tw_reuse`

### 4.1 리눅스 커널 4.12에서의 영구 삭제
커널 네트워크 서브시스템 메인테이너 Eric Dumazet은 NAT 환경에서 복구가 불가능한 이 근본적 결함으로 인해 **리눅스 커널 4.12에서 `tcp_tw_recycle` 파라미터를 완전히 제거**했습니다.

```
commit 4396e46187ca5070219b81773c3ca652486129d7
Author: Eric Dumazet <edumazet@google.com>
Date:   Wed May 17 07:44:03 2017 -0700
Subject: tcp: remove tcp_tw_recycle
```

### 4.2 `tcp_tw_reuse`는 왜 안전한가?
`net.ipv4.tcp_tw_reuse = 1` (또는 커널 4.12+에서 `2: loopback only`)은 `tcp_tw_recycle`과 이름만 비슷할 뿐 완전히 다르게 동작합니다.

| 비교 항목 | `tcp_tw_recycle` (위험/삭제됨) | `tcp_tw_reuse` (안전/권장) |
| :--- | :--- | :--- |
| **적용 대상** | 인바운드 서버 수신 연결 + 아웃바운드 | **오직 아웃바운드(Client) `connect()`에만 적용** |
| **타임스탬프 검증 단위** | 원격 IP 주소 단위 (전역 `inet_peer`) | **4-튜플 단위 (`src_ip, src_port, dst_ip, dst_port`)** |
| **NAT 환경 영향** | **외부 클라이언트의 SYN을 사일런트 드롭하여 접속 마비** | **인바운드 SYN 처리에 일체 관여하지 않으므로 무영향** |
| **커널 지원 여부** | Linux 4.12에서 완전 영구 삭제됨 | 최신 리눅스 커널 기본 활성화 권장 |

---

## 5. 실무 서버 튜닝 가이드

대규모 HTTP 프록시나 API 서버에서 `TIME_WAIT`이 수만 개 쌓일 때의 올바른 조치 방안:

1. **`tcp_tw_recycle` 절대 금지**: 만약 레거시 OS(CentOS 7 등)를 사용 중이라면 반드시 `net.ipv4.tcp_tw_recycle = 0`으로 설정.
2. **HTTP Keep-Alive 활성화**: 클라이언트와의 연결을 재사용하여 매 요청마다 TCP 연결을 맺고 끊는 오버헤드 원천 제거.
3. **로컬 포트 범위 확장**: 아웃바운드 요청이 많은 프록시 서버의 경우:
   ```bash
   sysctl -w net.ipv4.ip_local_port_range="1024 65535"
   sysctl -w net.ipv4.tcp_tw_reuse=1
   ```
4. **TIME_WAIT 버킷 한도 조절**:
   ```bash
   sysctl -w net.ipv4.tcp_max_tw_buckets=262144
   ```
