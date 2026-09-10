# 리눅스 커널 TCP BBR 혼잡 제어 상태 머신 및 페이싱 레이트 엔진 (Linux Kernel TCP BBR Congestion Control State Machine & Pacing Rate Engine)

## 문제 설명

리눅스 커널의 **TCP BBR(Bottleneck Bandwidth and Round-trip propagation time - `net/ipv4/tcp_bbr.c`)**은 구글이 개발하여 인터넷 전송 계층(Transport Layer)을 혁신한 모델 기반 혼잡 제어(Model-based Congestion Control) 알고리즘입니다.

기존의 Reno나 CUBIC 같은 손실 기반(Loss-based) 알고리즘은 패킷 드롭(Packet Drop)이 발생할 때까지 버퍼를 가득 채워 지연 시간(Bufferbloat)을 폭증시키거나, 패킷 손실률이 높은 무선/위성 네트워크에서 전송률이 급락하는 문제를 안고 있었습니다. 반면 BBR은 클라인록(Kleinrock)의 최적 제어 이론에 따라 **병목 대역폭(Bottleneck Bandwidth: `BtlBw`)**과 **최소 전파 지연 시간(Round-Trip Propagation Time: `RTprop`)**을 실시간으로 독립 측정하여 큐(Queue)가 비어 있는 최적 동작점(Optimal Operating Point)에서 패킷을 전송합니다.

본 문제에서는 실제 리눅스 커널 `net/ipv4/tcp_bbr.c`의 4대 핵심 상태 머신(`STARTUP`, `DRAIN`, `PROBE_BW`, `PROBE_RTT`), 이중 윈도우 필터링, 페이싱 이득(Pacing Gain), 혼잡 윈도우(`cwnd`) 및 대역폭-지연 곱(`BDP`) 계산 메커니즘을 충실히 모델링한 BBR 혼잡 제어 시뮬레이터를 구현합니다.

---

## BBR 4단계 상태 머신 (State Machine)

### 1. 시작 단계 (`STARTUP`)
- **목적**: 병목 대역폭(`BtlBw`)을 신속하게 탐색하기 위해 지수적으로 전송률을 증가시킵니다.
- **페이싱 게인**: $\text{pacing\_gain} = 2.89$ ($2 / \ln 2 \approx 2.885$).
- **종료 조건**: 대역폭 측정치가 이전 피크보다 1.25배 이상 증가하지 못하는 상태가 연속 3회 지속되면 파이프가 가득 찬 것으로 판단(`full_bw` 정체), `DRAIN` 상태로 전이합니다.

### 2. 드레인 단계 (`DRAIN`)
- **목적**: `STARTUP` 단계의 공격적인 램프업으로 인해 병목 라우터 버퍼에 쌓인 잉여 패킷 큐를 신속히 비웁니다.
- **페이싱 게인**: $\text{pacing\_gain} = 1.0 / 2.89 \approx 0.346$.
- **종료 조건**: 네트워크 내 비행 중인 패킷 양(`inflight_bytes`)이 측정된 $\text{BDP}$ 이하로 떨어지면 큐가 완전히 비워진 것으로 판단하여 `PROBE_BW`로 전이합니다.

### 3. 대역폭 탐색 단계 (`PROBE_BW`)
- **목적**: 새로운 대역폭 여유분을 탐색(Probe)하면서도 큐를 즉시 비우는 정상 정상 상태(Steady State)입니다.
- **8단계 페이싱 게인 순환**:
  $$[1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]$$
  - `1.25` (Probe Up): 1 RTT 동안 대역폭을 25% 초과 전송하여 용량 확장 탐색.
  - `0.75` (Drain Down): 1 RTT 동안 전송률을 25% 낮춰 방금 탐색으로 생긴 큐 드레인.
  - `1.0` (Cruise): 6 RTT 동안 파이프 용량에 딱 맞춰 전송.
- **종료 조건**: 만약 10초(`rtprop_win_ms`) 동안 더 낮은 RTT가 관측되지 않아 `RTprop` 필터가 만료되면 `PROBE_RTT`로 전이합니다.

### 4. RTT 탐색 단계 (`PROBE_RTT`)
- **목적**: 라우터 큐 지연을 완전히 제거하여 순수한 물리적 전파 지연(`RTprop`)을 정확히 재측정합니다.
- **혼잡 윈도우 축소**: $\text{cwnd} = 4 \times \text{MSS}$ (5840바이트).
- **종료 조건**: 최소 200ms 동안 윈도우를 극소화한 후 `probe_rtt_done` 신호를 받아 `PROBE_BW`로 복귀합니다.

---

## 핵심 계산 공식

1. **대역폭-지연 곱 (Bandwidth-Delay Product - BDP)**:
   $$\text{BDP} = \left\lfloor \frac{\text{BtlBw} \times (\text{RTprop\_ms} / 1000)}{8} \right\rfloor \quad (\text{단위: 바이트})$$
2. **페이싱 전송률 (Pacing Rate)**:
   $$\text{pacing\_rate\_bps} = \lfloor \text{pacing\_gain} \times \text{BtlBw} \rfloor$$
3. **혼잡 윈도우 (CWND)**:
   $$\text{cwnd} = \begin{cases} 4 \times \text{MSS} & (\text{PROBE\_RTT}) \\ \max(\lfloor \text{cwnd\_gain} \times \text{BDP} \rfloor, 4 \times \text{MSS}) & (\text{기타 상태}) \end{cases}$$

---

## 입력 형식

JSON 형식으로 표준 입력에 전달됩니다.

```json
{
  "config": {
    "mss": 1460,
    "bw_window": 10,
    "rtprop_win_ms": 10000
  },
  "samples": [
    {"time_ms": 100, "delivery_rate_bps": 10000000, "rtt_ms": 20.0},
    {"time_ms": 200, "delivery_rate_bps": 50000000, "rtt_ms": 20.0}
  ]
}
```

---

## 출력 형식

```json
{
  "history": [
    {
      "time_ms": 100,
      "state": "STARTUP",
      "pacing_gain": 2.89,
      "btlbw_bps": 10000000,
      "rtprop_ms": 20.0,
      "bdp_bytes": 25000,
      "pacing_rate_bps": 28900000,
      "cwnd_bytes": 72250
    }
  ],
  "stats": {
    "state_transitions": [],
    "samples_processed": 2,
    "bbr_cycles": 0
  },
  "final_state": {
    "state": "STARTUP",
    "btlbw_bps": 50000000,
    "rtprop_ms": 20.0,
    "pacing_gain": 2.89
  }
}
```
