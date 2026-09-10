# Problem #433: 리눅스 커널 네트워킹: TCP BBRv3 혼잡 제어 및 ECN 비례 감쇄·토큰 버킷 폴리서(Policer) 감지 & 패킷 손실 헤드룸(Loss Headroom) 엔진

## 🌟 개요 (Executive Summary)
구글과 리눅스 커널 네트워킹 팀이 주도하는 BBR(Bottleneck Bandwidth and RTT) 알고리즘은 패킷 유실을 유일한 혼잡 신호로 보던 레거시 손실 기반 알고리즘(Reno, CUBIC)의 패러다임을 전환했습니다. 그러나 기존 BBRv1과 BBRv2는 현실 세계의 상용 네트워크에서 두 가지 치명적인 결함을 노출했습니다:
1. **와이파이/이동통신 무작위 손실에 대한 과민 반응 또는 큐 팽창**: BBRv1은 패킷 손실을 거의 무시하여 얕은 버퍼(Shallow Buffer) 스위치에서 버퍼블로트를 일으켰고, BBRv2는 경미한 손실에도 대역폭 추정치를 급격히 삭감하여 무선망 처리량이 급락했습니다.
2. **ISP 토큰 버킷 폴리서(Token Bucket Policer) 트랩**: ISP 및 클라우드 게이트웨이가 토큰 버킷 속도 제한기(Policer)를 적용할 때, BBR이 한계 대역폭을 탐색(PROBE_BW)하려다 버킷 용량을 초과하는 패킷이 일괄 드롭되면서 톱니파형 지연 및 심각한 전송 속도 진동이 발생했습니다.

리눅스 커널 6.x 및 IETF 표준화로 제시된 **BBRv3 (`net/ipv4/tcp_bbr.c`)**는 이러한 한계를 극복하기 위해 설계된 현대 혼잡 제어의 정점입니다:
- **PROBE_BW 4단계 서브페이스 상태 머신**: `UP`(1.25x 가속 대역폭 탐색) $\to$ `DOWN`(0.75x 큐 드레인) $\to$ `CRUISE`(1.0x 안정 순항) $\to$ `REFILL`(파이프 리필) 주기를 순환합니다.
- **손실 헤드룸(Loss Headroom)**: 와이파이 무선 환경의 비혼잡성 무작위 패킷 손실을 수용하기 위해, 지정된 허용 한계($L \le L_{\text{headroom}}$, 기본 2%) 이내의 손실에 대해서는 대역폭 추정치를 깎지 않고 유지합니다.
- **ECN AccECN / L4S 비례 감쇄**: 스위치 큐가 차오를 때 발생하는 ECN CE 마킹 비율($F_{\text{ecn}}$)을 EWMA 스무딩 $\alpha$로 추적하여, RTT 급증 없이 선제적으로 `cwnd`를 비례 감쇄($1 - \alpha/2$)합니다.
- **토큰 버킷 폴리서 실시간 감지**: RTT 증가가 거의 없는 상태(최소 RTT의 1.15배 이내)에서 10% 이상의 주기적 손실이 격발되는 패턴을 감지하면, 이를 ISP 폴리서 한계로 확정(`policer_detected = true`)하고 허위 대역폭 탐색을 중단하여 안정적인 속도로 수렴합니다.

본 문제에서는 리눅스 커널 TCP BBRv3의 핵심 알고리즘, 손실 헤드룸 판정, ECN 스무딩, 폴리서 감지 및 페이싱 레이트/`cwnd` 산출 파이프라인을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
                       [ Incoming TCP ACK Event ]
                                    │
           (bytes_delivered, rtt_ms, loss_bytes, ecn_bytes)
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │ 1. Update min_rtt = min(min_rtt, rtt_ms)                │
       │ 2. Update max_bw = max(max_bw, bytes_del / rtt_ms)      │
       │ 3. Compute loss_rate = loss_bytes / total_bytes         │
       │ 4. Compute ecn_fraction = ecn_bytes / bytes_delivered   │
       └────────────────────────────┬────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
  [ Policer Detection ]                           [ Loss Headroom Check ]
  loss_rate > 10% &&                              loss_rate <= headroom (2%)?
  rtt_ms / min_rtt <= 1.15                        ┌─────────┴─────────┐
            │                                    Yes                  No
         Detected!                                │                   │
  policer_detected = true                         ▼                   ▼
  Clamp max_bw to policed_rate             No BW Penalty        Compute excess loss
                                                                Backoff max_bw
            │                                                         │
            └───────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
                    [ ECN EWMA Alpha Smoothing ]
                    α = (1 - g)*α + g * ecn_fraction
                                    │
                                    ▼
               [ Pacing Rate & Congestion Window Calculation ]
                    BDP = max_bw * min_rtt
                    pacing_rate = max_bw * pacing_gain
                    cwnd = max(4*MSS, BDP * cwnd_gain * (1 - α/2))
```

---

## 🔢 수학적 공식 및 판정 기준 (Mathematical Formulations)

### 1. 손실 헤드룸 및 백오프 (Loss Headroom & Penalty)
패킷 손실률 $L = \frac{B_{\text{loss}}}{B_{\text{delivered}} + B_{\text{loss}}}$에 대해, 허용 헤드룸 $L_{\text{headroom}}$ 초과분 $L_{\text{excess}}$는:
$$L_{\text{excess}} = \max(0, L - L_{\text{headroom}})$$
손실 페널티 계수 $P_{\text{loss}}$와 대역폭 조정은:
$$P_{\text{loss}} = \min(0.5, L_{\text{excess}} \times 2.0), \quad \hat{BW}_{\text{max}} = BW_{\text{max}} \times \left(1.0 - \frac{P_{\text{loss}}}{2}\right)$$

### 2. 토큰 버킷 폴리서 감지 (Policer Detection Invariant)
스위치 큐 적체(Bufferbloat) 없이 ISP 레이트 리미터에 부딪힌 경우:
$$\text{IsPolicer} = (L > 0.10) \land \left(\frac{RTT_{\text{sample}}}{RTT_{\text{min}}} \le \Theta_{\text{rtt\_ratio}}\right)$$
감지 시 $\hat{BW}_{\text{max}} = \min(BW_{\text{max}}, R_{\text{sample}})$로 상한 고정.

### 3. ECN EWMA 지수 가중 이동 평균
$$F_{\text{ecn}} = \frac{B_{\text{ecn}}}{B_{\text{delivered}}}, \quad \alpha_{t} = (1 - g)\alpha_{t-1} + g \cdot F_{\text{ecn}} \quad (g = 0.0625)$$

### 4. BDP 및 동적 혼잡 윈도우(cwnd) 산출
$$BDP = BW_{\text{max}} \times RTT_{\text{min}}$$
$$PacingRate = BW_{\text{max}} \times Gain_{\text{pacing}}$$
$$CWND = \max\left(4 \times MSS, BDP \times Gain_{\text{cwnd}} \times \left(1.0 - \frac{\alpha}{2}\right)\right)$$

---

## 📥 입력 형식 (Input Specification)

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "mss": 1460,
    "initial_rtt_ms": 40.0,
    "initial_bw_bytes_per_ms": 2000.0,
    "loss_headroom": 0.02,
    "ecn_alpha_gain": 0.0625,
    "policer_rtt_ratio_thresh": 1.15
  },
  "trace": [
    {"op": "ACK_EVENT", "bytes_delivered": 100000, "rtt_ms": 40.0, "loss_bytes": 0, "ecn_bytes": 0},
    {"op": "ACK_EVENT", "bytes_delivered": 99000, "rtt_ms": 40.0, "loss_bytes": 1000, "ecn_bytes": 0},
    {"op": "PHASE_STEP"},
    {"op": "GET_STATUS"}
  ]
}
```

### 지원 명령어 (Supported Operations):
1. `ACK_EVENT`:
   - 파라미터: `bytes_delivered`, `rtt_ms`, `loss_bytes`, `ecn_bytes`
   - BBRv3 상태 업데이트, 손실 헤드룸 판정, ECN EWMA 갱신, pacing rate 및 cwnd 계산.
2. `PHASE_STEP`:
   - `PROBE_BW` 상태 내에서 `UP` $\to$ `DOWN` $\to$ `CRUISE` $\to$ `REFILL` $\to$ `UP` 단계 순환.
3. `FORCE_STATE`:
   - 파라미터: `state` (`STARTUP`, `DRAIN`, `PROBE_BW`, `PROBE_RTT`), `phase` (optional)
   - BBR 상위 상태 강제 전이 및 게인 업데이트.
4. `GET_STATUS`:
   - 현재 대역폭, 최소 RTT, BDP, ECN $\alpha$, 폴리서 감지 여부 반환.

---

## 📤 출력 형식 (Output Specification)

표준 출력(stdout)으로 공백이 없는 콤팩트 JSON 문자열을 단일 행으로 출력합니다:
```json
{"events":[{"op":"ACK_EVENT","state":"PROBE_BW","phase":"CRUISE","min_rtt_ms":40.0,"max_bw_kbps":20000.0,"pacing_rate":2500.0,"cwnd_bytes":200000,"loss_rate":0.0,"loss_penalty":0.0,"ecn_alpha":0.0,"policer_detected":false}],"summary":{"final_state":"PROBE_BW","final_min_rtt":40.0,"final_max_bw":2000.0,"policer_detected":false,"total_bytes_delivered":100000,"total_loss_bytes":0,"total_ecn_bytes":0,"bbr_state_transitions":0,"policer_events":0,"ecn_backoff_events":0,"loss_backoff_events":0}}
```

---

## 💡 제약 조건 (Constraints)
- 모든 연산은 단일 스레드 결정론적(Deterministic)으로 동작해야 합니다.
- 부동소수점 출력(`min_rtt_ms`, `max_bw_kbps`, `pacing_rate`, `loss_rate`, `ecn_alpha`)은 명시된 정밀도로 반올림(`round(..., 2)` 또는 `round(..., 4)`)합니다.
- `cwnd_bytes`는 정수형(`int`) 바이트 단위로 출력되며 최소 $4 \times MSS$를 보장합니다.
