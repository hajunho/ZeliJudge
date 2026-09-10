# 문제 405: Linux 커널 TCP RACK-TLP (Recent ACKs & Tail Loss Probe, RFC 8985) 시간 기반 손실 복구 및 테일 프로브 엔진

## 문제 설명

인터넷 트래픽의 대다수를 지탱하는 전송 계층 프로토콜인 TCP는 지난 수십 년 동안 패킷 유실을 감지하기 위해 **"3개의 중복 확인응답(3 Duplicate ACKs, RFC 5681)"**에 전적으로 의존해 왔습니다.

그러나 이 전통적인 방식은 현대의 고속 모바일/셀룰러(5G/LTE), Wi-Fi, 다중 경로(Multi-path), 분산 데이터센터 네트워크 환경에서 치명적인 한계를 드러냈습니다:

1. **패킷 재정렬(Reordering)에 대한 취약성**:
   - 무선 간섭, 버퍼링, 다중 경로 라우팅으로 인해 패킷 순서가 3개 이상 뒤바뀌면, 송신측은 실제 패킷 유실이 없음에도 불구하고 불필요한 고속 재전송(Spurious Fast Retransmission)을 감행하고 혼잡 윈도우(`cwnd`)를 절반으로 깎아 대역폭을 낭비합니다.
2. **트랜잭션 꼬리 유실(Tail Drop) 및 짧은 전송(Short Flow)의 재앙**:
   - 웹 검색, RPC, REST API 요청과 같이 작은 윈도우(예: 1~4개 패킷)로 데이터를 전송하거나, 대규모 버스트의 마지막 패킷(Tail Packet)이 유실되는 경우, 수신측은 중복 ACK를 3개 생성할 수 없습니다.
   - 송신측은 최소 200ms에서 수 초에 달하는 **재전송 타임아웃(RTO, Retransmission Timeout)**이 만료될 때까지 완전히 멈춰서(Hang), P99 테일 레이턴시가 폭증합니다.

구글의 Yuchung Cheng, Neal Cardwell 등은 이 문제를 혁신적으로 해결하기 위해 **RFC 8985**로 표준화되어 리눅스 커널 4.4+의 기본 손실 복구 알고리즘으로 채택된 **RACK-TLP (Recent ACKs and Tail Loss Probe, `net/ipv4/tcp_rack.c`, `net/ipv4/tcp_recovery.c`)**를 설계했습니다.

RACK-TLP는 TCP의 패러다임을 **"순서 번호 기반(Sequence-based)"**에서 **"시간 기반(Time-based)"**으로 완전히 전환합니다:

1. **Tail Loss Probe (TLP)**:
   - 전송 중인 미확인 데이터가 존재할 때, 가동 중인 RTO 타이머보다 훨씬 앞선 **프로브 타임아웃(PTO, Probe Timeout, 보통 $2 \times \text{SRTT}$)**을 설정합니다.
   - PTO 만료 시 새로운 미전송 데이터 또는 가장 높은 시퀀스의 패킷을 프로브로 송신하여 수신측의 즉각적인 SACK을 유도합니다.
   - 꼬리 유실이 발생했더라도 긴 RTO 대기 없이 1 RTT 만에 고속 손실 복구(Fast Recovery)로 진입하여 재앙적인 지연 스파이크를 원천 차단합니다.
2. **Recent ACKs (RACK)**:
   - 송신측은 각 패킷의 송신 시각(`send_time`)과 최근 전달된 패킷의 RTT 샘플을 정밀하게 추적합니다.
   - **RACK 손실 판정 규칙**:
     어떤 패킷 $X$보다 나중에 전송된 패킷 $Y$가 수신측에 성공적으로 도달(SACK/ACK)되었고,
     $$t_{\text{now}} - \text{send\_time}(X) \ge \text{rack.rtt} + \text{rack.reo\_wnd}$$
     를 만족하면, 패킷 $X$는 단순한 역전(Reordering)이 아니라 **유실(LOST)**된 것으로 확정하고 즉시 재전송합니다.
3. **적응형 역전 윈도우 (Adaptive Reordering Window, `reo_wnd`)**:
   - 네트워크에서 패킷 역전이 관측되면 `reo_wnd`를 동적으로 확장($\min(\text{SRTT}, \text{reo\_wnd} + \text{min\_rtt}/4)$)하여 지연 도달 패킷에 유예 시간을 부여함으로써 불필요한 재전송을 완벽히 방지합니다.

여러분의 임무는 리눅스 커널의 TCP RACK-TLP 엔진의 이산 사건(Discrete-Event) 시뮬레이터를 구현하는 것입니다.

---

## 시스템 아키텍처 다이어그램

```
+========================================================================================+
|                       TCP RACK-TLP Loss Recovery Engine Architecture                   |
+========================================================================================+

    [ Application Layer: Data Transmission Request ]
                           |
                           v
+----------------------------------------------------------------------------------------+
|  TCP Sender Engine (net/ipv4/tcp_output.c, net/ipv4/tcp_rack.c)                         |
|   - Congestion Control State: cwnd, ssthresh, ca_state (Open, Recovery, Loss)          |
|   - Transmission Window: snd_una (oldest unacked), snd_nxt                             |
|   - Inflight Tracking: Segment(seq, send_time, is_retrans, sacked, acked, lost)       |
+----------------------------------------------------------------------------------------+
         |                                                       ^
    Transmit / Retransmit                                   Receive ACK / SACK
         v                                                       |
+----------------------------------------------------+   +-------------------------------+
|  Forward Network Link (delay + fault injection)    |   |  Reverse Network Link (delay) |
|   - Packet Drops: [seq1, seq2, ...]                |   +-------------------------------+
|   - Packet Delays: {seq: extra_ms} (Reordering)    |                   ^
+----------------------------------------------------+                   |
         |                                                               |
         v                                                               |
+----------------------------------------------------------------------------------------+
|  Receiver Engine (SACK Generation & Cumulative ACK Tracking)                            |
|   - Tracks rcv_nxt and Out-of-Order SACK Blocks [start, end]                           |
+----------------------------------------------------------------------------------------+

                             [ Sender Internal Timers ]
   +---------------------------------------+   +---------------------------------------+
   | RTO Timer: t_now + RTO                |   | TLP Timer: t_now + PTO (Probe Timeout)|
   | - Fallback when all else fails        |   | - PTO = 2 * SRTT (+ wdelay if inf==1) |
   | - cwnd = 1, enter TCP_CA_Loss         |   | - Transmit TLP Probe segment          |
   +---------------------------------------+   +---------------------------------------+
                                               
                             [ RACK Loss Detection Logic ]
   When ACK arrives delivering packet Y at t_now:
     rack_rtt = sample_rtt
     For each unacked packet X sent before Y:
       If (t_now - X.send_time >= rack_rtt + rack_reo_wnd):
         Mark X as LOST -> Enter TCP_CA_Recovery -> Fast Retransmit X!
```

---

## 입출력 형식 및 명세

### 입력 JSON 구조

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 전달됩니다:

```json
{
  "config": {
    "initial_cwnd": 8,
    "initial_ssthresh": 32,
    "initial_srtt_ms": 50,
    "min_rto_ms": 200,
    "max_rto_ms": 3000,
    "enable_rack": true,
    "enable_tlp": true,
    "dupthresh": 3,
    "one_way_delay_ms": 25,
    "wdelay_ms": 5
  },
  "workload": {
    "total_packets": 8,
    "drops": [8],
    "delays": {"2": 20}
  }
}
```

#### 설정 파라미터 필드 명세:
- `initial_cwnd` (int): 초기 혼잡 윈도우 크기 (패킷 단위).
- `initial_ssthresh` (int): 초기 슬로우 스타트 임계값.
- `initial_srtt_ms` (float/int): 초기 스무딩 RTT (ms).
- `min_rto_ms` (float/int): RTO 최소 하한 (ms).
- `max_rto_ms` (float/int): RTO 최대 상한 (ms).
- `enable_rack` (bool): RACK 시간 기반 손실 감지 활성화 여부 (false 시 레거시 중복 ACK 기반).
- `enable_tlp` (bool): TLP 테일 프로브 활성화 여부.
- `dupthresh` (int): 레거시 고속 재전송 중복 ACK 임계값 (기본 3).
- `one_way_delay_ms` (float/int): 단방향 기본 전송 지연 (ms).
- `wdelay_ms` (float/int): `inflight == 1`일 때 TLP 지연 ACK 회피 여유 시간 (ms).

#### 워크로드 필드 명세:
- `total_packets` (int): 송신할 총 패킷 수 (시퀀스 번호 $1 \dots N$).
- `drops` (list): 유실시킬 패킷 번호 목록 (정수 또는 `{"seq": 8, "instance": 1}`).
- `delays` (dict): 특정 패킷에 추가할 지연 시간(ms) 맵 (패킷 역전 시뮬레이션용).

---

### 출력 JSON 구조

표준 출력(`sys.stdout`)으로 공백 없이 압축된 단일 JSON 문자열을 출력합니다:

```json
{
  "summary": {
    "total_simulation_time": 205.0,
    "total_packets": 8,
    "total_transmissions": 9,
    "fast_retransmissions": 0,
    "rto_retransmissions": 0,
    "tlp_probes_sent": 1,
    "final_cwnd": 16,
    "final_ssthresh": 32,
    "final_srtt_ms": 50.0,
    "final_rto_ms": 200.0,
    "final_reo_wnd_ms": 12.5
  },
  "retransmissions": [
    {
      "time": 155.0,
      "seq": 8,
      "type": "TLP_PROBE",
      "cwnd": 15,
      "ssthresh": 32
    }
  ],
  "state_transitions": []
}
```

---

## 핵심 손실 복구 및 타이머 규칙

1. **RTT 및 RTO 갱신 (Jacobson/Karels 알고리즘)**:
   $$R = t_{\text{now}} - \text{orig\_send\_time}$$
   $$\text{RTTVAR} \leftarrow 0.75 \times \text{RTTVAR} + 0.25 \times |R - \text{SRTT}|$$
   $$\text{SRTT} \leftarrow 0.875 \times \text{SRTT} + 0.125 \times R$$
   $$\text{RTO} \leftarrow \max(\text{min\_rto}, \text{SRTT} + 4 \times \text{RTTVAR})$$
2. **RACK 손실 감지 규칙**:
   - `rack.rtt = R`.
   - 패킷 $X$의 미확인 경과 시간 $t_{\text{elapsed}} = t_{\text{now}} - \text{send\_time}(X)$.
   - $t_{\text{elapsed}} \ge \text{rack.rtt} + \text{rack.reo\_wnd}$ 이면 즉시 `lost = True`.
3. **TLP 1회 프로브 규칙**:
   - TLP 프로브는 새로운 ACK가 수신될 때까지 1회만 발주됩니다(`tlp_sent_without_ack`).
   - 발주된 프로브마저 유실될 경우 안전하게 RTO 타이머가 인계받아 지수 백오프로 복구합니다.
