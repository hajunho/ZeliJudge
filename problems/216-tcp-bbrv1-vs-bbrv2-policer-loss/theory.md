# 이론 백서: TCP 혼잡 제어(CCA)의 진화와 얕은 버퍼(Shallow Buffer) 토큰 버킷 폴리서에서의 BBRv1 vs BBRv2 vs CUBIC

## 1. 개요 및 배경 (Background)

현대 인터넷과 클라우드 데이터센터 네트워크에서 대역폭은 기가비트(Gbps)에서 테라비트(Tbps) 단위로 확장되었지만, 패킷 전송을 규제하는 메커니즘은 매우 이질적인 두 패러다임 사이에서 갈등을 겪고 있습니다.

1. **송신측 혼잡 제어(Congestion Control)**: 단말 호스트(End-host) 커널 스택에서 네트워크 경로의 수용 능력을 추정하여 송신 속도와 인플라이트 윈도우를 동적으로 제어.
2. **망 경계 트래픽 규제(Traffic Policing & Shaping)**: 통신사(ISP) 및 클라우드 사업자(CSP, AWS Direct Connect, Azure ExpressRoute, GCP Cloud Interconnect)가 고객이 계약한 대역폭(CIR, Committed Information Rate)을 강제하기 위해 배치한 네트워크 장비의 하드웨어 필터.

네트워크 중간 경로에 배치된 장비가 넉넉한 큐(Deep Buffer)를 갖춘 **트래픽 셰이퍼(Shaper)**인 경우, 일시적인 트래픽 버스트는 버퍼에 대기열을 형성하여 지연(RTT 증가 및 버퍼블로트)을 유발하지만 패킷 손실은 발생하지 않습니다.
그러나 하드웨어 비용 절감 및 지연 시간 억제를 위해 통신사 및 클라우드 게이트웨이가 채택하는 **토큰 버킷 폴리서(Token Bucket Policer)**는 버퍼가 사실상 존재하지 않는 **극도로 얕은 버퍼(Zero/Shallow Buffer)** 환경입니다.

이러한 환경에서 리눅스 커널의 기본 혼잡 제어 알고리즘인 **CUBIC**과 구글이 제안한 **BBRv1**, 그리고 개선된 **BBRv2**는 완전히 상이한 병목 및 장애 양상을 유발합니다.

---

## 2. 토큰 버킷 폴리서(Token Bucket Policer)의 동작 원리

토큰 버킷 메커니즘은 다음 파라미터로 정의됩니다:

```
                  +-------------------------+
                  |  Token Arrival (CIR)    |  ==> policer_rate_mbps
                  +-------------------------+
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Token Bucket (CBS) │  ==> policer_bucket_capacity_bytes
                    │  [ o o o o o o o ]  │
                    └─────────────────────┘
                               │
            Packet Arrival     │  Tokens >= Packet Size ?
      ─────────────────────────┴───────────────
             │                                │
            YES                               NO
             │                                │
             ▼                                ▼
       [Token 차감]                      [Drop Packet]
     Forward Packet                     Immediate Drop
```

- **CIR (Committed Information Rate)**: 토큰이 버킷에 지속적으로 주입되는 속도 (예: 100 Mbps = 12.5 Byte/$\mu s$).
- **CBS (Committed Burst Size)**: 버킷이 담을 수 있는 최대 토큰 용량 (예: 15 KB = 10 MTU 패킷 분량, 또는 심한 경우 4.5 KB = 3 MTU).
- **판정 규칙**:
  - $t$ 시점에 도착한 크기 $S$ 바이트의 패킷에 대해, 버킷의 잔여 토큰 $T(t) \ge S$이면 $T(t) \leftarrow T(t) - S$를 수행하고 패킷을 즉시 통과시킵니다.
  - 만약 $T(t) < S$이면 버퍼링 없이 패킷을 **즉시 폐기(Tail Drop)**합니다.

셰이퍼(Shaper)와 달리 폴리서는 큐가 없으므로 지연이 발생하지 않는 대신, 허용된 버스트(CBS)를 단 $1$바이트라도 초과하는 트래픽은 가차 없이 손실 처리됩니다.

---

## 3. 손실 기반 CC (CUBIC)의 처리량 붕괴 (Sawtooth Collapse)

리눅스 커널의 표준 알고리즘인 **CUBIC**은 손실을 유일한 혼잡 신호로 간주하는 손실 기반(Loss-based) 알고리즘입니다.

```
 cwnd
  ▲        /\            /\            /\
  │       /  \          /  \          /  \
  │      /    \  Drop  /    \  Drop  /    \
  │     /      \      /      \      /      \
  │    /        \    /        \    /        \
  │   /          \  /          \  /          \
  └──┴────────────┴┴────────────┴┴────────────┴──► Time
```

1. **윈도우 감소 법칙**:
   패킷 손실이 단 한 건이라도 발생하면 CUBIC은 혼잡 윈도우를 곱셈적 삭감(Multiplicative Decrease)합니다:
   $$\text{ssthresh} = \max(2 \times \text{MSS}, \text{cwnd} \times \beta) \quad (\beta = 0.7)$$
   $$\text{cwnd} = \text{ssthresh}$$
2. **폴리서 환경에서의 비극**:
   - 송신기가 회선 대역폭에 도달하여 패킷을 버스트 전송하는 순간, 폴리서의 CBS(10개 미만의 패킷)를 순간적으로 초과하여 손실이 발생합니다.
   - CUBIC은 즉시 `cwnd`를 30% 삭감하고 슬로우 스타트 또는 3차 함수(Cubic curve) 혼잡 회피로 복구하려고 합니다.
   - 그러나 복구되어 다시 CIR 근처에 도달하자마자 또다시 폴리서 드롭이 발생합니다.
   - **Mathis Equation**:
     $$\text{Throughput} \le \frac{\text{MSS}}{\text{RTT} \times \sqrt{p}} \times C$$
     폴리서가 유발하는 주기적인 드롭($p$)으로 인해 CUBIC의 실효 처리량은 10%~20% 수준으로 영구적 기아(Starvation) 상태에 빠집니다.

---

## 4. BBRv1의 한계: 폴리서에서의 지속적 패킷 손실률 (Loss Storm)

구글이 설계한 **BBRv1 (Bottleneck Bandwidth and RTT)**은 패킷 손실이 아닌 물리적 병목 대역폭($\text{BtlBw}$)과 최소 왕복 시간($\text{RTprop}$)을 직접 모델링합니다.

### 4.1. BBRv1 PROBE_BW 사이클
BBRv1은 정상 상태(Steady-State)에서 8개 RTT 윈도우로 구성된 페이싱 게인 사이클을 순환합니다:
$$\text{Pacing Gain Cycle} = [1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]$$

```
 Cycle:   [0]    [1]    [2]    [3]    [4]    [5]    [6]    [7]
 Gain :   1.25   0.75   1.0    1.0    1.0    1.0    1.0    1.0
          ▲      ▲
          │      └─ 0.75x: 큐 비우기 (Drain)
          └─ 1.25x: 대역폭 프로빙 (Probe Bandwidth)
```

### 4.2. 폴리서와의 치명적 충돌
- **1.25x Pacing Phase**: BBRv1은 숨겨진 대역폭이 있는지 확인하기 위해 $1$ RTT 동안 $\text{BtlBw} \times 1.25$의 속도로 패킷을 전송합니다.
- 회선의 CIR이 100 Mbps라면 125 Mbps로 송신하게 됩니다.
- 100 Mbps 폴리서는 잉여 25 Mbps를 수용할 수 있는 큐가 없습니다. CBS(예: 15 KB)는 단 수 밀리초만에 고갈되며, 이후 1.25x 페이즈 동안 유입되는 초과 패킷은 모두 폐기됩니다.
- 이 단계에서 약 20%의 패킷이 폐기되며, 8개 RTT 사이클 평균으로 환산하면 **전체 전송량의 2.5% ~ 3.5%가 영구적으로 손실**됩니다.
- BBRv1은 손실을 혼잡 신호로 해석하지 않으므로, 이 1.25x 프로빙을 무한히 반복하여 심각한 재전송 오버헤드와 실시간 트래픽 왜곡을 유발합니다.

---

## 5. BBRv2의 해결책: 폴리서 감지 및 인플라이트 캡핑

BBRv2는 BBRv1의 치명적인 결함(CUBIC과의 불공정 경쟁, 폴리서에서의 높은 패킷 손실률, 얕은 버퍼에서의 취약성)을 극복하기 위해 설계되었습니다.

```
 [RTT 주기적 모니터링]
       │
       ▼
  Loss Rate > 2.0% (loss_thresh) ?
       ├── YES ──► Policer / Shallow Buffer 감지!
       │             ├── policer_detected = True
       │             ├── inflight_hi = max(BDP, in_flight)
       │             └── PROBE_BW 1.25x 게인 단계 차단:
       │                   if gain > 1.0: gain = 1.0
       └── NO  ──► 정상 BBRv2 모델 유지
```

### 5.1. 주요 메커니즘
1. **명시적 손실 및 ECN 피드백 반영**:
   단일 RTT 윈도우 동안의 패킷 손실률이 임계치(기본 $2\%$, `loss_thresh`)를 초과하면 네트워크가 얕은 버퍼 폴리서이거나 심각한 혼잡 상태임을 인지합니다.
2. **상한 인플라이트(`inflight_hi`) 설정**:
   손실이 발생한 시점의 패킷 전송량을 경로의 최대 안전 인플라이트로 기록하고, 이를 초과하지 않도록 윈도우를 클램핑합니다.
3. **폴리서 적응형 프로빙 억제 (Policer Probe Gain Suppression)**:
   토큰 버킷 폴리서가 감지되면, 버킷을 초과하여 드롭을 유발하는 $1.25\times$ 프로빙 게인을 $1.0\times$로 제한합니다. 이를 통해 폴리서 버킷을 고갈시키지 않으면서 계약 대역폭(CIR)의 95% 이상을 완벽하게 활용하고, 패킷 손실률을 $0.5\%$ 미만으로 급격히 안정화합니다.

---

## 6. 리눅스 커널 구현 매핑 (`net/ipv4/tcp_bbr2.c`)

리눅스 커널 BBRv2 소스 코드의 핵심 구조체 및 로직 매핑:

```c
struct bbr2 {
    u32 min_rtt_us;          /* min RTT over min_rtt_win_sec */
    u32 bw_hi[2];            /* max bw over min_rtt_win_sec */
    u32 inflight_hi;         /* upper bound on inflight data */
    u32 inflight_lo;         /* lower bound on inflight data */
    u8  policer_detected:1,  /* link seems to be policed */
        unused:7;
    u8  cycle_idx;           /* current index in pacing_gain[] */
};

/* 손실률 및 폴리서 여부 판정 함수 */
static void bbr2_check_loss_too_high(struct sock *sk, const struct rate_sample *rs)
{
    struct bbr2 *bbr = inet_csk_ca(sk);
    if (rs->losses > 0 && rs->tx_in_flight > 0) {
        u32 loss_rate = (rs->losses * 100) / rs->tx_in_flight;
        if (loss_rate > bbr2_loss_thresh) {
            bbr->policer_detected = 1;
            bbr->inflight_hi = max(bbr2_bdp(sk), rs->tx_in_flight);
        }
    }
}
```

---

## 7. 실무 프로덕션 트러블슈팅 및 튜닝 권장사항

1. **FQ (Fair Queueing) Pacing 강제**:
   - BBR은 커널의 페이싱 엔진(`sch_fq`)에 전적으로 의존합니다.
   - `tc qdisc replace dev eth0 root fq pacing` 설정을 통해 호스트 레벨에서 마이크로버스트(Microburst)를 완화하여 토큰 버킷 순간 고갈을 방지해야 합니다.
2. **CSP 전용선 연동 시 CBS 확장 요청**:
   - AWS Direct Connect, Azure ExpressRoute 등에서 폴리서 설정 시 CBS가 $15\text{KB}$ 이하로 지나치게 작게 설정되어 있다면 CSP 콘솔이나 티켓을 통해 CBS를 $\text{BDP} / 4$ 수준으로 완화할 것을 권고합니다.
3. **BBRv2 및 Hybrid CCA 채택**:
   - Linux 5.18+ 환경에서는 BBRv1 대신 폴리서 친화적이고 CUBIC과 공존 가능한 BBRv2를 우선 도입하여 처리량 붕괴와 패킷 손실 문제를 동시에 해결합니다.
