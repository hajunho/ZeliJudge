# 리눅스 커널 Netfilter Conntrack TCP 상태 머신, Out-of-Window 패킷 필터링 및 SYNPROXY DDoS 방어 엔진

## 문제 설명

리눅스 커널의 네트워크 서브시스템에서 **넷필터 연결 추적(Netfilter Connection Tracking, Conntrack)**은 상태 기반 방화벽(`iptables`/`nftables`), NAT(Network Address Translation), L4 로드 밸런서의 핵심 뼈대입니다. 특히 TCP 프로토콜 추적 모듈(`net/netfilter/nf_conntrack_proto_tcp.c`)은 양방향(`ORIGINAL`: 클라이언트 $\to$ 서버, `REPLY`: 서버 $\to$ 클라이언트)의 모든 패킷을 검사하여 유효한 TCP 상태 전이를 추적하고, 시퀀스 번호(Sequence Number)와 확인 응답 번호(Acknowledgment Number)가 수신 윈도우 범위 내에 존재하는지 정밀하게 검증합니다.

정상적인 네트워크 트래픽 외에도 인터넷 환경에서는 패킷 순서 뒤바뀜, 지연 도착, 또는 공격자에 의한 **비정상 패킷 주입(Out-of-Window Packet Injection Attack)** 및 **SYN Flood 분산 서비스 거부(DDoS) 공격**이 빈번하게 발생합니다. 대규모 SYN Flood 공격 시 공격자는 위조된 소스 IP로 초당 수백만 개의 SYN 패킷을 전송하여 Conntrack 테이블(`nf_conntrack_max`)을 순식간에 고갈시키고 정상 연결 수립을 마비시킵니다.

리눅스 커널은 이를 방어하기 위해 다음과 같은 고도화된 엔진들을 탑재하고 있습니다:
1. **TCP 상태 머신 및 윈도우 추적 엔진 (`tcp_in_window`)**:
   - 32비트 모듈러 시퀀스 번호 순환 연산(`seq_diff`, `seq_le`, `seq_ge`)을 기반으로, 현재 수신측 윈도우 상한(`td_maxend`)을 초과하거나 지나치게 오래된 구형 패킷(`td_end - td_maxwin` 미만), 또는 아직 송신되지 않은 미래 데이터를 승인하는 유령 ACK(`ack > td_end`)를 가려내어 `INVALID`로 드롭합니다.
2. **SYNPROXY 무상태 핸드셰이크 엔진 (`nf_synproxy_core.c`)**:
   - SYN 패킷이 유입될 때 즉시 Conntrack 세션을 할당하지 않고, 암호학적 **SYN Cookie**를 계산하여 가상으로 SYN/ACK를 응답합니다.
   - 이후 클라이언트가 유효한 3번째 ACK(ACK 번호가 Cookie + 1)를 보낸 경우에만 정당한 클라이언트로 인증하여 비로소 Conntrack 세션을 수립하고 백엔드 서버와의 연결을 중재합니다.

본 과제에서는 리눅스 커널 Netfilter Conntrack의 TCP 상태 머신, 엄격한 Out-of-Window 검증 로직, 그리고 SYNPROXY DDoS 완화 알고리즘을 100% 수리·시스템적으로 정밀 구현합니다.

---

## 시스템 아키텍처 및 패킷 파이프라인

```
+-------------------------------------------------------------------------+
|                  Incoming Packet (ORIGINAL / REPLY)                     |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                    1. SYNPROXY Inspection (PREROUTING)                  |
|  - If synproxy_enabled and unestablished:                               |
|    * SYN received -> Compute SYN Cookie -> Reply SYN/ACK (0-alloc)      |
|    * ACK received -> Verify Cookie == ack - 1                           |
|      -> If Match: Establish Conntrack Session                           |
|      -> If Mismatch: DROP (Mitigate Spoofed SYN Flood)                  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                  2. TCP State Machine Transitions                       |
|  - NONE -> SYN_SENT -> SYN_RECV -> ESTABLISHED -> FIN_WAIT / CLOSE      |
|  - Flag verification: SYN, ACK, FIN, RST matching current state         |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|               3. Out-of-Window Packet Filtering (tcp_in_window)         |
|  - 32-bit Modular Sequence Bounds:                                      |
|    * seq <= receiver.td_maxend (Upper bound check)                      |
|    * seq + len >= sender.td_end - receiver.td_maxwin (Lower bound)      |
|    * ack <= sender.td_end (Ghost ACK defense)                           |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|             ACCEPT (Update conntrack window) or DROP (Invalid)          |
+-------------------------------------------------------------------------+
```

---

## 핵심 요구사항 및 동작 규칙

### 1. 32비트 모듈러 시퀀스 번호 연산
TCP 시퀀스 번호는 32비트 부호 없는 정수($0 \le \text{seq} < 2^{32}$)이며, $2^{32}-1$을 초과하면 0으로 순환(Wrapping)합니다. 시퀀스 비교는 부호 있는 32비트 정수 차이로 판정합니다:
$$\Delta = (a - b) \pmod{2^{32}}$$
$$\text{If } \Delta \ge 2^{31}, \quad \text{diff} = \Delta - 2^{32} \quad \text{Else } \text{diff} = \Delta$$
- $a \le b \iff \text{diff} \le 0$
- $a > b \iff \text{diff} > 0$

### 2. SYNPROXY 핸드셰이크 메커니즘
- `synproxy_enabled`가 `true`이고 세션이 아직 수립되지 않은 경우:
  - 클라이언트(`ORIGINAL`)의 최초 순수 SYN 패킷 유입 시:
    - SYN Cookie 계산:
      $$\text{cookie} = ((\text{seq} \oplus \text{synproxy\_secret}) + (\text{win} \ll 8) + \text{0xCAFE}) \pmod{2^{32}}$$
    - `action = "SYNPROXY_SYN_ACK_SENT"`, `reason = "SYN_COOKIE_GENERATED"`, `synproxy_syn_cookies_generated` 1 증가. 상태는 `NONE` 유지.
  - 클라이언트(`ORIGINAL`)의 3번째 순수 ACK 패킷 유입 시:
    - 쿠키 검증: $\text{ack} == (\text{cookie} + 1) \pmod{2^{32}}$
    - 일치 시: `action = "SYNPROXY_HANDSHAKE_COMPLETED"`, `state = "ESTABLISHED"`, `synproxy_cookies_verified` 1 증가, Conntrack 윈도우 초기화 후 패킷 승인.
    - 불일치 시: `action = "DROP"`, `reason = "INVALID_SYN_COOKIE"`, `synproxy_spoofed_syns_dropped` 1 증가.

### 3. 표준 TCP 상태 머신 전이
- `RST` 수신 시: 세션이 활성 상태인 경우 `state = "CLOSE"`, 승인.
- `ORIGINAL`의 순수 `SYN`: `state = "SYN_SENT"`, `td_end = seq + 1`.
- `REPLY`의 `SYN/ACK`: `ack == receiver.td_end`인 경우 `state = "SYN_RECV"`, `td_end = seq + 1`.
- `ORIGINAL`의 `ACK`: `SYN_RECV` 상태에서 `state = "ESTABLISHED"`.
- `FIN`: `ESTABLISHED` $\to$ `FIN_WAIT` $\to$ `CLOSE_WAIT` $\to$ `LAST_ACK` $\to$ `TIME_WAIT`.

### 4. 윈도우 검증 (`tcp_in_window`)
`ESTABLISHED` 상태이고 `strict_window_tracking = true`인 경우 다음 3대 조건을 모두 만족해야 합니다:
1. **상한 검증**: $\text{seq} \le \text{receiver.td\_maxend}$ (불만족 시 `OUT_OF_WINDOW_ABOVE_MAXEND` 드롭)
2. **하한 검증**: $\text{seq} + \text{len} \ge \text{sender.td\_end} - \text{receiver.td\_maxwin}$ (불만족 시 `OUT_OF_WINDOW_TOO_OLD` 드롭)
3. **ACK 유효성 검증**: 패킷에 `ACK` 플래그가 있는 경우 $\text{ack} \le \text{sender.td\_end}$ (불만족 시 `INVALID_ACK_BEYOND_SENT` 드롭)
- 검증 통과 시 송수신자의 `td_end`, `td_maxend`, `td_maxwin`을 최신 값으로 확장 갱신합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "synproxy_enabled": true,
    "synproxy_secret": 933612497,
    "strict_window_tracking": true
  },
  "packets": [
    {"id": "PKT_01", "dir": "ORIGINAL", "flags": ["SYN"], "seq": 200000, "ack": 0, "len": 0, "win": 64240},
    {"id": "PKT_02", "dir": "ORIGINAL", "flags": ["ACK"], "seq": 200001, "ack": 2969966144, "len": 0, "win": 64240}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)을 출력합니다:
```json
{
  "final_state": "ESTABLISHED",
  "metrics": {
    "packets_processed": 2,
    "packets_accepted": 1,
    "packets_dropped_invalid": 0,
    "synproxy_syn_cookies_generated": 1,
    "synproxy_cookies_verified": 1,
    "synproxy_spoofed_syns_dropped": 0,
    "state_transitions": 1,
    "window_probes_accepted": 0
  },
  "packet_results": [
    {
      "pkt_id": "PKT_01",
      "action": "SYNPROXY_SYN_ACK_SENT",
      "reason": "SYN_COOKIE_GENERATED",
      "state": "NONE",
      "syn_cookie": 2969966143
    },
    {
      "pkt_id": "PKT_02",
      "action": "SYNPROXY_HANDSHAKE_COMPLETED",
      "reason": "COOKIE_VERIFIED",
      "state": "ESTABLISHED"
    }
  ],
  "conntrack_table": {
    "ORIGINAL": {"td_end": 200001, "td_maxend": 3034206144, "td_maxwin": 64240},
    "REPLY": {"td_end": 2969966144, "td_maxend": 265536, "td_maxwin": 65535}
  }
}
```

---

## 제약 사항

- $1 \le \text{len}(packets) \le 100$
- $0 \le \text{seq}, \text{ack} < 2^{32}$
- $0 \le \text{win} \le 65535$, $0 \le \text{len} \le 65535$
- 모든 시퀀스 번호 및 윈도우 계산은 32비트 모듈러 정수 연산으로 처리합니다.
