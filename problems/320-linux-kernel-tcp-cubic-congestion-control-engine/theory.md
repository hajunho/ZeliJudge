# TCP CUBIC 혼잡 제어의 수학적 원리와 리눅스 커널 아키텍처 (RFC 8312 & net/ipv4/tcp_cubic.c)

## 1. 인터넷 전송 계층과 LFN(Long-Fat Network)의 위기

1988년 반 제이콥슨(Van Jacobson)이 제안한 TCP Reno의 AIMD(Additive Increase Multiplicative Decrease) 알고리즘은 인터넷 붕괴를 막아낸 일등공신이었습니다. 그러나 2000년대 들어 기가비트 이더넷, 대륙 간 해저 광케이블 등 초고속·고지연 네트워크(Long-Fat Networks, LFNs)가 보편화되면서 Reno의 한계가 명백해졌습니다.

### 르노의 RTT 편향성과 확장성 한계
Reno의 윈도우 증가는 매 RTT마다 1 패킷(MSS)씩 증가합니다:
$$rac{d W}{d t} = rac{1}{	ext{RTT}}$$
이 수식은 두 가지 심각한 구조적 결함을 내포합니다:
1. **RTT 불공정성 (RTT Unfairness)**: RTT가 10ms인 로컬 플로우는 1초에 100 패킷의 윈도우를 늘리는 반면, 해저 광케이블을 거치는 RTT 200ms 플로우는 1초에 겨우 5 패킷만 증가시킵니다. RTT가 짧은 연결이 공유 링크의 대역폭을 독점합니다.
2. **고속 회복 불능 (Inability to Scale)**: 10Gbps 링크($BDP pprox 83,000$ 패킷, 100ms RTT)에서 패킷 손실이 1회 발생하여 윈도우가 절반($41,500$ 패킷)으로 줄어들었을 때, 이를 복구하려면 $41,500$ 번의 RTT, 즉 **약 69분(4,150초)** 동안 단 하나의 패킷 손실도 없이 선형 증가해야 합니다. 실제 네트워크에서 이는 불가능에 가깝습니다.

---

## 2. BIC-TCP에서 CUBIC으로의 진화

이 문제를 해결하기 위해 노스캐롤라이나 주립대 연구진(Injong Rhee, Lisong Xu, Sangtae Ha)은 2004년 **BIC-TCP(Binary Increase Congestion Control)**를 제안했습니다. BIC-TCP는 이전 패킷 손실 직전의 윈도우 $W_{max}$와 손실 후 축소된 윈도우 $W_{min}$ 사이에서 이진 탐색(Binary Search)을 수행하여 가용 대역폭을 신속히 찾는 획기적인 방식이었습니다.

그러나 BIC-TCP는 알고리즘 내부에 이진 탐색, 가법 증가, 최대 탐색의 여러 모드가 혼재되어 있어 커널 구현이 복잡하고 수학적 분석이 어려웠습니다. 이에 2008년, 연구진은 BIC-TCP의 오목-평형-볼록 거동을 단 하나의 우아한 3차 다항식(Cubic Function)으로 통합한 **TCP CUBIC (RFC 8312)**을 완성하였습니다.

---

## 3. CUBIC 3차 함수의 수학적 우아함

CUBIC의 핵심 함수는 다음과 같이 정의됩니다:

$$W_{cubic}(t) = C \cdot (t - K)^3 + W_{max}$$

여기서 $t$는 마지막 혼잡 사건 이후 흐른 **실제 물리적 시간(Real Elapsed Time, 초 단위)**이며, $K$는 윈도우가 손실 이전의 $W_{max}$에 도달하는 데 걸리는 시간입니다.

### $K$의 수학적 유도
손실 직후($t=0$) 혼잡 윈도우는 $W_{max} \cdot eta$로 줄어듭니다. 따라서 $W_{cubic}(0) = W_{max} \cdot eta$가 성립해야 합니다:
$$C \cdot (0 - K)^3 + W_{max} = W_{max} \cdot eta$$
$$-C \cdot K^3 = W_{max} \cdot (eta - 1) = -W_{max} \cdot (1 - eta)$$
$$K^3 = rac{W_{max} \cdot (1 - eta)}{C} \implies K = \sqrt[3]{rac{W_{max} \cdot (1 - eta)}{C}}$$

이 도출이 갖는 의미는 혁명적입니다:
- **도함수 분석**:
  $$rac{d W_{cubic}}{d t} = 3C \cdot (t - K)^2$$
  - $t = 0$: 기울기가 $3C \cdot K^2$로 커서 손실 직후 윈도우를 매우 빠르게 회복합니다.
  - $t 	o K$: 도함수가 0에 수렴합니다. 즉, 과거 병목 지점이었던 $W_{max}$에 도달할 때 윈도우 증가율이 0이 되어 버퍼를 자극하지 않고 안정적인 플래토(Plateau)를 형성합니다.
  - $t > K$: 도함수가 다시 급격히 증가합니다. 네트워크 용량이 증설되었거나 타 플로우가 종료된 경우, 볼록(Convex) 곡선을 그리며 초고속으로 새로운 대역폭을 획득합니다.
- **RTT 무관성 (RTT Independence)**:
  $W_{cubic}(t)$의 $t$는 패킷 왕복 횟수가 아니라 '초' 단위 시계입니다. 따라서 10ms RTT를 가진 연결이든 200ms RTT를 가진 연결이든 **동일한 시간 $K$초 만에 $W_{max}$로 복귀**하므로, RTT에 따른 불공정성이 완벽히 해소됩니다.

---

## 4. 리눅스 커널 `net/ipv4/tcp_cubic.c` 구현 심층

리눅스 커널 내부에서는 부동소수점(FPU) 연산을 사용할 수 없으므로, 커널 개발자들은 CUBIC의 3차 곡선과 세제곱근 연산을 고도로 최적화된 **고정소수점 비트 시프트(Fixed-point Bit-shifting)** 연산으로 구현했습니다:

- `BICTCP_HZ = 10`: 커널 jiffies 타이머 기반 에포크 추적
- `bictcp_update()`: 매 ACK 수신 시 경과 시간 $t$를 계산하고 윈도우 목표치를 갱신
- **HyStart(`hystart_update()`)**:
  대역폭이 매우 큰 네트워크에서 슬로우 스타트의 지수적 증가 속도는 기가비트 스위치의 버퍼를 순식간에 날려버릴 수 있습니다. HyStart는 왕복 지연의 미세한 지연 스파이크($\Delta \ge \min(\max(RTT_{min}/8, 2	ext{ms}), 16	ext{ms})$)를 포착하여 드롭 없이 부드럽게 CUBIC 혼잡 회피로 핸드오버합니다.
- **빠른 수렴 (Fast Convergence)**:
  여러 CUBIC 연결이 하나의 병목을 공유할 때, 기존 연결이 계속 $W_{max}$를 유지하면 신규 연결이 대역폭을 공평하게 확보하지 못합니다. CUBIC은 이전 $W_{last\_max}$보다 낮은 윈도우에서 손실이 발생하면 $W_{max}$를 $0.85 	imes cwnd$로 추가 하향 조정하여 신규 플로우에 대역폭 여유 공간을 양보합니다.

이와 같은 완벽한 수리적 균형 덕분에, CUBIC은 오늘날 전 세계 인터넷의 가장 신뢰받는 전송 알고리즘으로 군림하고 있습니다.
