# Theory: Linux Kernel Fair Queueing (sch_fq) and Earliest Departure Time (EDT) Pacing

## 1. 개요: 버퍼블로트와 현대 TCP의 패킷 페이싱 혁신

전통적인 인터넷 라우팅 및 호스트 운영체제(OS)의 패킷 스케줄링은 **FIFO(First-In, First-Out)** 또는 단순 드롭테일(Drop-tail) 큐잉에 의존해 왔습니다. 그러나 광대역 라우터의 거대한 버퍼는 TCP의 손실 기반 혼잡 제어(예: Reno, CUBIC)와 맞물려 패킷이 버퍼에 수백 밀리초 동안 갇혀 왕복 시간(RTT)을 폭증시키는 **버퍼블로트(Bufferbloat)** 문제를 야기했습니다.

이를 근본적으로 타파하기 위해 Van Jacobson과 Neal Cardwell 등 Google 네트워킹 팀은 **BBR(Bottleneck Bandwidth and RTT)** 알고리즘을 제안했으며, BBR이 실시간 병목 대역폭에 맞춰 패킷을 균등한 시간 간격으로 방출할 수 있도록 리눅스 커널 3.12부터 **`sch_fq` (Fair Queueing with Pacing)**를 도입했습니다. 리눅스 4.19 이후 커널은 소켓 수준에서 나노초 단위 출발 시각을 태깅하는 **EDT(Earliest Departure Time)** 아키텍처를 채택하여 하드웨어 NIC 링 버퍼와 소프트웨어 스케줄러 간의 오버헤드를 비약적으로 줄였습니다.

---

## 2. sch_fq의 구조적 아키텍처

리눅스 커널 소스 코드 `net/sched/sch_fq.c`에 구현된 `sch_fq`는 세 가지 핵심 서브시스템의 유기적 결합체입니다.

### 2.1 2단계 큐잉 리스트 (new_flows vs old_flows)
`sch_fq`는 M. Shreedhar와 G. Varghese가 제안한 **DRR(Deficit Round Robin)** 원리를 확장하여 두 개의 양방향 연결 리스트를 유지합니다:
1. `new_flows`: 유휴(idle) 상태에서 새로 패킷을 수신한 활성 흐름들이 진입하는 큐입니다. 대화형 트래픽(SSH, DNS 등)이나 새로운 TCP 핸드셰이크 흐름이 벌크(Bulk) 전송 흐름에 밀려 지연되는 것을 방지하기 위해 `old_flows`보다 엄격한 우선권을 갖습니다.
2. `old_flows`: 최초 할당된 퀀텀(Quantum, 통상 1개 MTU 크기인 1514 바이트)을 모두 소진한 지속적인 대용량 흐름들이 순환하는 라운드 로빈 큐입니다.

흐름이 패킷을 송출할 때마다 패킷의 바이트 수만큼 흐름의 `credit`이 차감됩니다:
$$\text{credit} \leftarrow \text{credit} - L_{\text{pkt}}$$
크레딧이 0 이하가 되면, 퀀텀만큼 크레딧을 보충(`credit += quantum`)받은 뒤 `old_flows`의 후미로 이동합니다.

### 2.2 EDT(Earliest Departure Time)와 쓰로틀링 트리 (Red-Black Tree)
소켓이 초당 대역폭 $R$ (bytes/sec)로 페이싱되도록 설정된 경우, 크기 $L$ 바이트의 패킷이 시각 $T$에 송출되면, 해당 소켓의 다음 패킷은 최소 다음 시각 이전에는 절대 물리 계층으로 방출될 수 없습니다:
$$T_{\text{next}} = T + \left\lfloor \frac{L \times 10^9}{R} \right\rfloor \quad (\text{ns})$$

만약 차기 패킷의 예정 출발 시각 $T_{\text{next}}$이 현재 시각 $T_{\text{now}}$보다 미래라면, 해당 흐름은 즉시 활성 리스트(`new_flows`/`old_flows`)에서 제거되어 **`throttled_flows`** 레드-블랙 트리(최소 힙)로 격리됩니다.
시계 인터럽트 또는 타이머 휠(`hrtimer`)에 의해 시각이 전진하여 $T_{\text{now}} \ge T_{\text{next}}$가 충족되는 순간, 흐름은 깨어나 `old_flows`로 복귀합니다.

```
       +-------------------------------------------------------------+
       |                  fq_dequeue() 알고리즘                      |
       +-------------------------------------------------------------+
                                      |
                           [new_flows 탐색]
                                      |
                         +------------+------------+
                         |                         |
                    (비어있음)                 (흐름 존재)
                         |                         |
                 [old_flows 탐색]           헤드 패킷 검사
                         |                         |
               +---------+---------+          +----+----+
               |                   |          |         |
          (비어있음)           (흐름 존재)   T_req > now   T_req <= now
               |                   |          |         |
          [송출 중단]          헤드 검사  [Throttled로] [패킷 방출]
                                              격리     credit 차감
```

---

## 3. 수학적 공정성 및 딜레이 분석

### 3.1 Max-Min Fairness 보장
$N$개의 흐름이 대역폭 $C$를 공유할 때, 각 흐름의 요구량이 $d_1, d_2, \dots, d_N$이라면, `sch_fq`의 DRR 기법은 대역폭 분배량 $a_i$가 다음 Max-Min 공정성 조건을 수렴하도록 보장합니다:
$$\sum_{i=1}^N a_i = \min\left( C, \sum_{i=1}^N d_i \right), \quad a_i = \min(d_i, \gamma)$$
여기서 임계값 $\gamma$는 사용 가능한 잔여 대역폭을 비제한 흐름들에게 동등하게 분배하는 수준에서 결정됩니다.

### 3.2 패킷 간 간격(Inter-Packet Gap)의 지터 최소화
기존의 버스트 전송 방식에서는 패킷 $K$개가 연속해서 송신되어 스위치 버퍼 큐 길이를 순간적으로 $K \times \text{MTU}$까지 급증시킵니다.
반면 EDT 페이싱을 적용하면 송출 간격 $\Delta t$가 정밀하게 조율되므로, 스위치 버퍼 점유율 $Q(t)$가 0에 가깝게 유지되어 큐잉 딜레이 $D_q \to 0$에 수렴하게 됩니다.

---

## 4. 커널 구현 디테일 및 최적화

1. **소켓 캐시 및 잠금 회피**: 리눅스 커널은 소켓 구조체(`struct sock`) 내에 `sk_pacing_rate`와 `sk_pacing_status`를 캐싱하여 스케줄러 진입 시 락 경합 없이 마이크로초 단위 페이싱 결정을 내립니다.
2. **하드웨어 EDT 오프로드**: 최신 스마트 NIC(Mellanox ConnectX-6 등)는 `skb->tstamp`를 직접 읽어 하드웨어 ASIC 타이머에서 패킷 출발을 통제함으로써 호스트 CPU 인터럽트 오버헤드를 0으로 축소합니다.
