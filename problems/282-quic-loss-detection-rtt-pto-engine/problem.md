# 문제 #282: TCP의 40년 묵은 재전송 모호성을 어떻게 없앴을까요?!: QUIC (RFC 9002) 단조 증가 패킷 번호, 패킷·시간 임계값 손실 감지(Loss Detection), RTT 추정기 및 탐색 타임아웃(PTO) 엔진

## 1. 개요 (Story & Context)
1981년 IETF RFC 793으로 정의된 전송 제어 프로토콜(TCP)은 40년 넘게 전 세계 인터넷 통신의 척추 역할을 해왔습니다. 그러나 고속 무선망(5G/LTE), 모바일 이동성, 클라우드 글로벌 CDN의 시대에 접어들며 전통적인 TCP는 치명적인 구조적 한계에 부딪혔습니다:

1. **재전송 모호성 문제 (Retransmission Ambiguity Problem)**:
   - TCP에서 재전송된 세그먼트는 원래 패킷과 동일한 시퀀스 번호(Sequence Number, `SEQ`)를 사용합니다.
   - 송신자가 세그먼트를 재전송한 후 수신자로부터 `ACK`를 받았을 때, **"이 ACK가 최초 전송 패킷에 대한 응답인가, 아니면 재전송된 패킷에 대한 응답인가?"**를 송신자가 원천적으로 구분할 수 없습니다!
   - 이로 인해 카른의 알고리즘(Karn's Algorithm)은 재전송된 패킷의 RTT 측정을 무조건 버려야만 했고, RTT 추정이 심각하게 왜곡되거나 지연되었습니다.
2. **헤드오브라인 블로킹 (HOL Blocking)과 불연속 ACK 표현 한계**:
   - TCP의 SACK(Selective ACK, RFC 2018) 옵션은 TCP 헤더 가용 공간(최대 40바이트)의 한계로 인해 최대 4개의 블록만 표현할 수 있어, 심한 패킷 손실 시 복구 효율이 급락합니다.
3. **타임아웃 시 극단적인 스톨 (RTO Stall)**:
   - TCP의 재전송 타임아웃(RTO)은 최소 200ms~1초 단위로 길며, 타임아웃 발생 시 혼잡 윈도우(`CWND`)를 1로 줄여 전송이 완전히 얼어붙습니다.

2021년 IETF가 정식 표준화한 **QUIC (RFC 9002: QUIC Loss Detection and Congestion Control)**은 TCP의 40년 묵은 문제를 완전히 뿌리뽑았습니다:
- **단조 증가 패킷 번호 (Strictly Monotonically Increasing Packet Numbers)**:
  - QUIC에서 송신되는 모든 패킷은 패킷 번호 공간 내에서 엄격하게 1씩 증가하는 고유한 번호(`Packet Number, PN: 0, 1, 2, ...`)를 부여받습니다.
  - **재전송되는 데이터라도 결코 기존 패킷 번호를 재사용하지 않으며, 항상 새로운 더 높은 패킷 번호에 실려 전송됩니다!**
  - 따라서 모든 ACK는 자신이 어떤 패킷 번호를 확인하는지 명확하므로, 재전송 모호성이 수학적으로 100% 제거됩니다.
- **다중 범위 ACK 프레임 (ACK Ranges)**:
  - 최대 패킷 수 한계 없이 수신된 패킷 번호의 연속 구간들을 `[start, end]` 배열로 정밀하게 보고합니다.
- **2단계 손실 감지 (Packet Threshold & Time Threshold)**:
  - **패킷 임계값 ($kPacketThreshold = 3$)**: 확인된 최대 패킷 번호(`largest_acked`)보다 $kPacketThreshold$ 이상 뒤처진 미수신 패킷은 즉시 손실(`LOST`)로 판정합니다.
  - **시간 임계값 ($kTimeThreshold = 9/8$)**: 패킷 번호 차이가 3 미만이더라도, 송신 후 경과 시간이 $	ext{loss\_delay} = 1.125 \times \max(SRTT, latest\_rtt)$를 초과하면 즉시 손실로 판정합니다.
- **탐색 타임아웃 (Probe Timeout, PTO)**:
  - 무작정 RTO를 기다려 연결을 끊는 대신, 네트워크 유휴 상태에서 능동적으로 새 패킷 번호로 탐색 패킷을 발송(`PTO_EXPIRED`)하고, 연속 실패 시 지수 백오프($2^{\text{pto\_count}}$)를 적용합니다.

여러분은 글로벌 빅테크 CDN의 L4/L7 전송 계층 코어 네트워크 엔지니어로서, RFC 9002 규격에 따라 패킷 번호 수명 주기, Jacobson RTT 추정, 패킷/시간 임계값 손실 감지 및 PTO 백오프 상태 머신을 구동하는 **QUIC RFC 9002 Loss Detection & RTT Engine**을 구현해야 합니다!

---

## 2. 상태 머신 및 연산 규칙

### 2.1 QUIC 매개변수 설정 (`quic_config`)
- `k_packet_threshold`: 재정렬 허용 패킷 갭 임계값 (기본 3).
- `k_time_threshold_mult`: 시간 기반 손실 지연 승수 (기본 $9/8 = 1.125$).
- `k_granularity`: 타이머 최소 분해능 단위 (기본 1.0ms).
- `max_ack_delay`: 수신자 최대 ACK 지연 한도 (기본 25.0ms).

### 2.2 RTT 추정 규칙 (RFC 9002 Section 5)
1. **최초 RTT 측정 (`smoothed_rtt is None`)**:
   - `min_rtt = latest_rtt`
   - `smoothed_rtt = latest_rtt`
   - `rttvar = latest_rtt / 2.0`
2. **이후 RTT 측정 (`smoothed_rtt is not None`)**:
   - `min_rtt = min(min_rtt, latest_rtt)`
   - `ack_delay = min(ack_delay, max_ack_delay)`
   - `adjusted_rtt = latest_rtt`
   - 만약 `latest_rtt >= min_rtt + ack_delay`이면:
     - `adjusted_rtt = latest_rtt - ack_delay`
   - `rttvar = 0.75 * rttvar + 0.25 * abs(smoothed_rtt - adjusted_rtt)`
   - `smoothed_rtt = 0.875 * smoothed_rtt + 0.125 * adjusted_rtt`
3. **탐색 타임아웃 계산 (`get_pto()`)**:
   - RTT 측정이 아직 없는 경우: $	ext{base\_pto} = 333.0$ ms.
   - RTT 측정이 있는 경우:
     $$\text{base\_pto} = \text{smoothed\_rtt} + \max(4.0 \times \text{rttvar}, k\_granularity) + max\_ack\_delay$$
   - 최종 PTO: $\text{PTO} = \text{base\_pto} \times 2^{\text{pto\_count}}$

### 2.3 연산 규칙 (`operations`)
1. `PACKET_SENT`:
   - 시간 `time`에 패킷 번호 `pn`, 바이트 크기 `bytes`인 패킷을 송신합니다. 미확인 패킷 맵(`sent_packets`)에 등록합니다. `packets_sent` $+1$.
2. `ACK_RECEIVED`:
   - 시간 `time`에 `largest_acked`, `ack_delay`, `ack_ranges`를 수신합니다:
   - `ack_ranges`는 `[[start_1, end_1], [start_2, end_2], ...]` 형태의 폐구간 목록입니다.
   - 해당 범위에 포함되는 미확인 패킷들을 `newly_acked` 목록으로 수집하고 `sent_packets`에서 제거합니다.
   - 만약 `largest_acked`가 `newly_acked`에 포함되어 있다면:
     - $	ext{latest\_rtt} = \text{time} - \text{time\_sent}(\text{largest\_acked})$를 계산하고 RTT를 갱신합니다.
     - `pto_count`를 0으로 리셋합니다.
   - **손실 감지 (`detect_lost_packets`)**:
     - 손실 지연 시간:
       $$\text{loss\_delay} = \max(k\_time\_threshold\_mult \times \max(latest\_rtt, smoothed\_rtt), k\_granularity)$$
     - `sent_packets`에 남아있는 패킷 $pn \le \text{largest\_acked}$ 중:
       - **조건 1 (패킷 임계값)**: $\text{largest\_acked} - pn \ge k\_packet\_threshold$
       - **조건 2 (시간 임계값)**: $\text{time} - \text{time\_sent}(pn) \ge \text{loss\_delay}$
       - 위 조건 중 하나라도 만족하면 해당 패킷을 즉시 손실(`newly_lost`)로 판정하고 `sent_packets`에서 제거합니다.
3. `PTO_EXPIRED`:
   - 시간 `time`에 PTO 타이머가 만료되었습니다.
   - `pto_count` $+1$, `pto_events` $+1$, 지수 백오프된 다음 PTO 시간을 산출합니다. `status: "PROBE_TRIGGERED"`.

---

## 3. 입력 형식 (Input Specification)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "quic_config": {
    "k_packet_threshold": 3,
    "k_time_threshold_mult": 1.125,
    "k_granularity": 1.0,
    "max_ack_delay": 25.0
  },
  "operations": [
    {"step": 1, "op": "PACKET_SENT", "time": 100.0, "pn": 0, "bytes": 1200},
    {"step": 2, "op": "PACKET_SENT", "time": 105.0, "pn": 1, "bytes": 1200},
    {"step": 3, "op": "ACK_RECEIVED", "time": 140.0, "largest_acked": 0, "ack_delay": 2.0, "ack_ranges": [[0, 0]]}
  ]
}
```

---

## 4. 출력 형식 (Output Specification)
표준 출력(stdout)으로 각 연산의 진행 로그, 통계 지표, 최종 RTT 및 미확인/손실 패킷 번호 목록을 포함하는 JSON 객체를 한 줄로 출력합니다:
```json
{
  "operations_log": [
    {"step": 1, "op": "PACKET_SENT", "time": 100.0, "pn": 0, "bytes": 1200, "in_flight_count": 1},
    {"step": 2, "op": "PACKET_SENT", "time": 105.0, "pn": 1, "bytes": 1200, "in_flight_count": 2},
    {"step": 3, "op": "ACK_RECEIVED", "time": 140.0, "largest_acked": 0, "newly_acked": [0], "newly_lost": [], "latest_rtt": 40.0, "smoothed_rtt": 40.0, "rttvar": 20.0, "pto": 145.0}
  ],
  "final_state": {
    "smoothed_rtt": 40.0,
    "rttvar": 20.0,
    "min_rtt": 40.0,
    "pto": 145.0,
    "unacked_pns": [1],
    "total_lost_pns": []
  },
  "statistics": {
    "packets_sent": 2,
    "packets_acked": 1,
    "packets_lost_threshold": 0,
    "packets_lost_time": 0,
    "pto_events": 0,
    "rtt_updates": 1
  }
}
```
모든 부동소수점 수치는 소수점 4자리까지 반올림(`round(val, 4)`)합니다.
