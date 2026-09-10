# 리눅스 커널 TCP CUBIC 혼잡 제어 엔진 (Linux Kernel TCP CUBIC Congestion Control Engine - RFC 8312 & net/ipv4/tcp_cubic.c)

## 문제 설명

리눅스 커널의 **TCP CUBIC(`net/ipv4/tcp_cubic.c` / RFC 8312)**은 리눅스 커널 2.6.19부터 기본 혼잡 제어(Default Congestion Control) 알고리즘으로 채택되어, 전 세계 수십억 대의 서버와 스마트폰에서 인터넷 트래픽의 중추를 담당해 온 알고리즘입니다.

과거 표준이었던 TCP Reno는 윈도우 증가율이 왕복 지연 시간($	ext{RTT}$)에 직접 반비례($1/	ext{RTT}$)하여, 대역폭-지연 곱(BDP)이 큰 고속 장거리 네트워크(Long-Fat Network, LFN: 예, 10Gbps 대역폭에 100ms 지연)에서 패킷 손실이 1회 발생한 뒤 이전 전송률을 복구하는 데 수십 분 이상이 소요되는 치명적인 결함이 있었습니다.

CUBIC은 혼잡 윈도우 증폭 곡선을 **실제 경과 시간($t$)에 기반한 3차 다항식(Cubic Polynomial Curve)** 함수로 설계함으로써, RTT의 크기에 종속되지 않는 고속 대역폭 회복과 극도의 네트워크 안정성을 동시에 달성하였습니다:

```
                  W_cubic(t) = C * (t - K)^3 + W_max
  Window (cwnd)
        ^                                            /  [CONVEX REGION]
        |                                           /   Rapid probe for
 W_max -+ - - - - - - -.- - - - - - - -.- - - - - -/    new capacity
        |             /  ` - . _ . - '          |            /    [EQUILIBRIUM]          |           /     Stable Plateau
        |          /
        |         / [CONCAVE REGION]
        |        /  Decelerating growth
        |       /   approaching W_max
        |      /
 beta*W -+----+---------------------------------------------> Time (t)
        0     |                         |
              +<---------- K ---------->+
              Epoch Start            Epoch Inflection
```

본 문제에서는 리눅스 커널 `net/ipv4/tcp_cubic.c`의 핵심 메커니즘인 **CUBIC 3차 윈도우 곡선(오목·평형·볼록 3대 영역)**, 지연 스파이크 기반 조기 완화 기법인 **HyStart(Hybrid Slow Start)**, 패킷 손실 시 경쟁 플로우에 대역폭을 양보하는 **빠른 수렴(Fast Convergence)**, 소규모 RTT 환경을 위한 **TCP-Friendly Reno 모드 에뮬레이션** 및 **RTO 타임아웃 복구 상태 머신**을 완벽히 시뮬레이션하는 엔진을 구현합니다.

---

## 핵심 메커니즘 및 수리 모델

### 1. CUBIC 윈도우 증가 곡선 (Bicubic Window Growth)
혼잡 회피(`CONGESTION_AVOIDANCE`) 상태에서 마지막 혼잡 사건 이후 경과 시간 $t$초에 따른 목표 윈도우 $W_{cubic}(t)$는 다음과 같습니다:

$$K = \sqrt[3]{rac{W_{max} \cdot (1 - eta)}{C}} \quad (	ext{초 단위, } C=0.4, eta=0.7)$$

$$W_{cubic}(t) = C \cdot (t - K)^3 + W_{max}$$

- **오목 영역 (Concave Region, $t < K - 0.15$)**: 윈도우가 빠르게 증가하다가 이전 최대치 $W_{max}$에 가까워질수록 증가 속도가 완만하게 둔화(Deceleration)하여 네트워크 안정성을 확보합니다.
- **평형 영역 (Equilibrium Plateau, $|t - K| \le 0.15$)**: 변곡점 $t pprox K$ 부근에서 도함수가 0에 수렴하며 $W_{max}$ 부근을 안정적으로 유지(Plateau)합니다.
- **볼록 영역 (Convex Region, $t > K + 0.15$)**: 안정기를 지나 새로운 가용 대역폭을 찾기 위해 다시 가속 성장(Acceleration)하며 상향 탐색합니다.

### 2. TCP 친화적 르노 에뮬레이션 (TCP-Friendly Region)
저지연(RTT가 작은) 환경에서는 전통적인 Reno 선형 증가 모델이 CUBIC 3차 곡선보다 빠를 수 있습니다. CUBIC은 기존 Reno 플로우를 굶주리게 하지 않고 대등하게 경쟁하기 위해 다음 르노 근사식 $W_{est}(t)$를 계산합니다:

$$W_{est}(t) = W_{max} \cdot eta + rac{3(1 - eta)}{1 + eta} \cdot rac{t}{	ext{RTT}}$$

만약 $W_{cubic}(t) < W_{est}(t)$라면 CUBIC은 르노 친화 모드(`sub_mode = "RENO_FRIENDLY"`)로 전환하여 $W_{est}(t)$를 목표 윈도우로 사용합니다.

### 3. HyStart (하이브리드 슬로우 스타트)
지수적으로 윈도우가 2배씩 증가하는 `SLOW_START` 단계에서 버퍼오버플로우로 인한 대규모 패킷 드롭이 발생하기 전에, 큐 지연(Queueing Delay) 누적을 감지하여 조기에 `CONGESTION_AVOIDANCE`로 안전하게 전이합니다.
- 최소 관측 지연 $RTT_{min}$ 대비 지연 증가량 임계치:
  $$	ext{delay\_thresh} = \min\left(\max\left(rac{RTT_{min}}{8}, 2	ext{ms}ight), 16	ext{ms}ight)$$
- 샘플 패킷 수가 8개 이상 누적된 상태에서 $(RTT - RTT_{min}) \ge 	ext{delay\_thresh}$가 감지되면 즉시 `ssthresh = cwnd`, `w_max = cwnd`로 설정하고 혼잡 회피 단계로 전환합니다.

### 4. 패킷 손실 및 빠른 수렴 (Fast Convergence)
- 3 중복 ACK(`3_DUP_ACKS`) 등 패킷 손실 발생 시:
  - 만약 현재 $cwnd < W_{last\_max}$ (새로 유입된 플로우가 대역폭을 확보할 수 있도록 양보):
    $$W_{max} = 	ext{round}\left(cwnd 	imes rac{1 + eta}{2}, 4ight) = 	ext{round}(cwnd 	imes 0.85, 4)$$
  - 그렇지 않은 경우:
    $$W_{max} = 	ext{round}(cwnd, 4)$$
  - $ssthresh = \max(2.0, 	ext{round}(cwnd 	imes eta, 4))$, $cwnd = ssthresh$
  - 에포크 시간 $t$를 0으로 리셋하고 새로운 $K$를 재계산합니다.

### 5. RTO 타임아웃 (Retransmission Timeout)
- 심각한 네트워크 단절 시 $ssthresh = \max(2.0, 	ext{round}(cwnd 	imes eta, 4))$
- $cwnd = 1.0$, 상태를 `SLOW_START`로 강제 전이하고 에포크를 초기화합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "mss": 1460,
    "c_scale": 0.4,
    "beta": 0.7,
    "fast_convergence": true,
    "tcp_friendliness": true,
    "hystart": true,
    "init_cwnd": 10.0,
    "init_ssthresh": 30.0,
    "rtt_min_ms": 50.0
  },
  "operations": [
    {"op": "PROCESS_ACK", "acked_packets": 5, "rtt_ms": 50.0, "time_advance_ms": 50.0},
    {"op": "PROCESS_LOSS", "loss_type": "3_DUP_ACKS"},
    {"op": "PROCESS_TIMEOUT"},
    {"op": "GET_STATE"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 연산 결과 리스트와 최종 요약 메트릭을 JSON 형태로 출력합니다:

```json
{
  "results": [
    {
      "op": "PROCESS_ACK",
      "time": 0.05,
      "state": "SLOW_START",
      "cwnd": 15.0,
      "ssthresh": 30.0,
      "w_max": 0.0,
      "k": 0.0,
      "region": "NONE",
      "sub_mode": "NONE",
      "rtt_ms": 50.0
    }
  ],
  "final_summary": {
    "current_time": 10.5,
    "state": "CONGESTION_AVOIDANCE",
    "cwnd": 109.0227,
    "ssthresh": 35.0,
    "w_max": 50.0,
    "k": 3.3472,
    "rtt_min_ms": 50.0,
    "stats": {
      "loss_events": 1,
      "timeout_events": 0,
      "hystart_exits": 0,
      "max_cwnd": 109.02,
      "reno_friendly_count": 0,
      "convex_count": 0,
      "concave_count": 0,
      "equilibrium_count": 0
    },
    "event_count": 4
  }
}
```
