# 이론 문서 419: Linux 커널 데이터센터 혼잡 제어(DCTCP) 수학적 모델 및 초저지연 버퍼 제어 내부 원리

## 1. 개요 및 배경 (Datacenter Networking & Motivation)

현대 데이터센터 네트워크는 인터넷 WAN 환경과 근본적으로 다른 요구사항을 갖습니다:
- **초저지연 (Ultra-Low Latency)**: 분산 스토리지(Ceph, NVMe-oF) 및 RPC 프레임워크(gRPC)는 99.9% 꼬리 지연 시간(Tail Latency)이 수십 마이크로초 이하로 유지되기를 요구합니다.
- **얕은 버퍼 스위치 (Shallow Buffer Switches)**: 100GbE~800GbE 고속 스위치 ASIC은 제조 비용과 전력 한계로 인해 포트당 수 메가바이트 수준의 극소 패킷 버퍼만을 탑재하고 있습니다.

### 1.1 레거시 ECN의 이진 반응 딜레마
RFC 3168 ECN은 단 1개의 패킷이라도 CE 비트가 마킹되면 $cwnd$를 50% 삭감하도록 규정했습니다.
이는 인터넷의 패킷 손실을 방지하는 데는 유용했으나, 데이터센터에서는 다음과 같은 문제를 초래했습니다:
$$\text{Cwnd}_{\text{new}} = \frac{1}{2} \cdot \text{Cwnd}_{\text{old}}$$
- 혼잡이 아주 가볍게 발생했음에도 대역폭을 50%나 버리게 되어 전송률이 급락하고 버퍼 점유율이 톱니파 형태로 극심하게 출렁입니다.

DCTCP(RFC 8257)는 이 문제를 해결하기 위해 **"혼잡의 강도(Severity)를 비트율로 측정하여 선형 비례 축소"**를 도입했습니다.

---

## 2. DCTCP 수학적 모델 및 상태 방정식

### 2.1 ECN 분율 $F$의 측정
하나의 RTT 관측 윈도우 내에서 수신된 총 바이트 수를 $S_{\text{total}}$, CE 마킹이 확인된 바이트 수를 $S_{\text{ce}}$라고 할 때, 순간 혼잡 비율 $F$는 다음과 같이 정의됩니다:

$$F = \frac{S_{\text{ce}}}{S_{\text{total}}} \quad (0.0 \le F \le 1.0)$$

### 2.2 지수 가중 이동 평균 (EWMA) 필터
순간적인 패킷 버스트로 인한 측정 잡음을 필터링하기 위해 감쇠 계수 $g$를 사용합니다 (리눅스 커널 표준 $g = \frac{1}{16} = 0.0625$):

$$\alpha_{k} = (1 - g) \cdot \alpha_{k-1} + g \cdot F_k$$

- 혼잡이 없는 상태($F=0$)가 지속되면 $\alpha$는 매 RTT마다 $(1 - g)$ 배율로 지수 감쇠(Exponential Decay)하여 0에 도달합니다.
- 혼잡이 100% 지속되면($F=1$) $\alpha$는 점진적으로 1.0으로 점근합니다.

### 2.3 비례 윈도우 축소 공식
혼잡 윈도우 $cwnd$의 축소율은 $\frac{\alpha}{2}$로 결정됩니다:

$$cwnd \leftarrow cwnd \cdot \left( 1 - \frac{\alpha}{2} \right)$$

- **경미한 혼잡 ($F = 0.05, \alpha \approx 0.05$)**:
  $$cwnd \leftarrow cwnd \cdot (1 - 0.025) = 0.975 \cdot cwnd \quad (\text{단 2.5\%만 축소})$$
- **중간 혼잡 ($F = 0.40, \alpha \approx 0.40$)**:
  $$cwnd \leftarrow cwnd \cdot (1 - 0.20) = 0.80 \cdot cwnd \quad (20\% \text{ 축소})$$
- **완전 혼잡 ($F = 1.00, \alpha \approx 1.00$)**:
  $$cwnd \leftarrow cwnd \cdot (1 - 0.50) = 0.50 \cdot cwnd \quad (\text{최대 50\% 축소})$$

---

## 3. 스위치 대기열 동역학 (Queue Dynamics)

스위치 임계치 $K$와 정상 상태 큐 길이 $Q$의 관계는 다음과 같이 분석됩니다:
- 큐 길이 $Q \le K$인 동안에는 패킷에 CE 마킹이 전혀 붙지 않습니다 ($F = 0$).
- 큐 길이 $Q > K$가 되면 스위치는 유입 패킷에 즉시 CE 비트를 마킹합니다.
- 송신자들은 $\alpha$ 비례 윈도우 조절을 통해 큐 유입 속도를 드레인(Drain) 속도와 정확히 일치하도록 미세 조정합니다.
- **결과**: 평균 큐 길이는 $K$ 주변에서 단 몇 마이크로초 편차로 정밀하게 안정화되며, 버퍼 오버플로우가 원천 차단됩니다.

---

## 4. 리눅스 커널 구현 세부사항 (`net/ipv4/tcp_dctcp.c`)

1. **`dctcp_update_alpha(struct sock *sk, u32 flags)`**:
   - RTT 완료 시점(`tcp_clean_rtx_queue`)에 호출되어 $F$를 계산하고 $\alpha$를 갱신합니다.
   - 고정소수점 연산(Fixed-point arithmetic)을 위해 커널은 $\alpha$를 1024 스케일(10-bit shift)로 관리합니다.

2. **`dctcp_ssthresh(struct sock *sk)`**:
   - 혼잡 통지가 들어왔을 때 슬로우 스타트 임계치(`ssthresh`)를 계산합니다:
     ```c
     u32 val = (tp->snd_cwnd * (1024 - (ca->dctcp_alpha >> 1))) >> 10;
     return max(val, 2U);
     ```

3. **Incast 방어 효과**:
   - 수백 개의 흐름이 동시에 유입되더라도 스위치 큐가 $K$를 넘는 순간 모든 흐름이 동시에 자신의 윈도우를 정밀하게 억제하므로 버퍼 고갈(Buffer Starvation)과 패킷 드롭이 발생하지 않습니다.
