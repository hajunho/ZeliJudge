# 심층 이론: Linux 커널 TCP RACK-TLP (RFC 8985) 아키텍처와 손실 복구의 수학적 원리

---

## 1. 전통적인 순서 번호 기반 손실 감지의 한계

전송 제어 프로토콜(TCP)의 고전적 손실 감지 메커니즘은 1980년대 반 제이콥슨(Van Jacobson)의 연구에 기반을 둔 **"3개의 중복 확인응답(3 Duplicate ACKs, Fast Retransmit)"**이었습니다.

수신측은 순서가 어긋난 패킷(Out-of-Order Packet)을 수신할 때마다 자신이 마지막으로 연속되게 받은 바이트 시퀀스를 가리키는 중복 ACK를 회신합니다. 송신측은 동일한 ACK가 3회 연속 도착하면 패킷 하나가 유실된 것으로 간주하고 RTO(Retransmission Timeout) 만료 전에 재전송을 감행했습니다.

### 1.1 치명적 결함 1: 비대칭 경로 및 패킷 역전(Packet Reordering)
현대 인터넷은 단일 FIFO 경로가 아닙니다:
- 멀티코어 네트워크 카드(NIC)의 RSS(Receive Side Scaling) 해시 불균형.
- 무선 링크(5G HARQ / Wi-Fi)의 MAC 계층 프레임 재전송.
- 패킷 기반 부하 분산 스위치(ECMP / Packet Spraying).

이러한 환경에서는 패킷 1, 2, 3이 송신되었을 때 패킷 3이 패킷 2보다 2ms 먼저 도착하는 역전 현상이 빈번하게 일어납니다. 만약 역전 깊이(Reordering Degree)가 3을 초과하면 레거시 TCP는 이를 패킷 유실로 오판하여:
1. 불필요한 패킷 재전송(Spurious Retransmit)을 수행하고,
2. 혼잡 제어 윈도우(`cwnd`)를 50% 강등시키며,
3. 네트워크 파이프라인의 처리량을 파괴합니다.

### 1.2 치명적 결함 2: 작은 윈도우 및 테일 드롭(Tail Loss)의 재앙
TCP 연결에서 전송 중인 패킷 수(`inflight`)가 3개 이하이거나, 수십 킬로바이트의 웹 객체를 전송한 마지막 1~2개 패킷(Tail)이 라우터 큐에서 드롭되면:
- 수신측은 중복 ACK를 1~2개밖에 생성할 수 없습니다.
- 중복 ACK 카운터가 3에 도달하지 못하므로 고속 재전송이 영원히 발동하지 않습니다.
- 송신측은 최소 200ms에서 1초 이상 소요되는 **RTO(Retransmission Timeout)**가 만료될 때까지 멍하니 대기하게 되며, 이는 현대 클라우드 마이크로서비스의 P99 응답 시간을 치명적으로 악화시킵니다.

---

## 2. 패러다임의 대전환: 시간 기반 손실 감지 (Time-Based Loss Detection)

RFC 8985로 표준화된 **RACK(Recent ACKs)**은 "시퀀스 번호의 차이"가 아닌 **"전송 시각의 물리적 인과성(Temporal Causality)"**을 손실 판단의 절대 기준으로 삼습니다.

```
   Sender Timeline:
   P1 (t=0ms) ------------> Lost!
   P2 (t=5ms) -----------------------------------> Received! -> ACK/SACK arrives at t=55ms
   
   At t=55ms (ACK for P2 arrives):
     - P1 was sent at t=0ms (prior to P2).
     - P2 (sent later) is ALREADY delivered!
     - Elapsed time for P1 = 55ms - 0ms = 55ms.
     - RACK Condition: Is 55ms >= RTT (50ms) + reo_wnd (2.5ms)?
       YES! 55ms >= 52.5ms.
     -> P1 CANNOT merely be reordered; it is mathematically LOST!
     -> Trigger Fast Retransmit IMMEDIATELY! (No need for 3 DupACKs!)
```

### 2.1 RACK 손실 판정의 수학적 부등식

송신측이 패킷 $Y$의 도달을 확인(ACK 또는 SACK)한 시각을 $t_{\text{now}}$, 해당 패킷의 실제 RTT를 $R_{\text{sample}}$이라 할 때:

$Y$보다 먼저(또는 같은 타임스탬프에 더 낮은 시퀀스로) 송신된 미확인 패킷 $X$에 대하여,

$$\Delta t(X) = t_{\text{now}} - t_{\text{send}}(X)$$

$$\Delta t(X) \ge R_{\text{sample}} + R_{\text{reo\_wnd}}$$

위 부등식이 성립하는 순간, 패킷 $X$는 네트워크 상에 남아 있을 물리적 확률이 0에 수렴하므로 즉시 손실로 확정됩니다.

---

## 3. Tail Loss Probe (TLP)의 동작 메커니즘

TLP는 꼬리 유실(Tail Drop)로 인해 후속 ACK가 전혀 유입되지 않는 상황을 해결하는 선제적 프로브 메커니즘입니다.

### 3.1 프로브 타임아웃 (PTO, Probe Timeout)의 계산
송신측에 미확인 데이터(`inflight > 0`)가 존재할 때 TLP 타이머가 가동됩니다:

$$\text{PTO} = \begin{cases} \max(2 \times \text{SRTT}, 10\text{ ms}), & \text{if } \text{inflight} > 1 \\ \max(2 \times \text{SRTT} + W_{\text{delay}}, 10\text{ ms}), & \text{if } \text{inflight} == 1 \end{cases}$$

여기서 $W_{\text{delay}}$는 수신측의 지연 ACK(Delayed ACK, 보통 40ms~200ms)로 인한 오탐을 방지하기 위한 유예 마진입니다.

### 3.2 TLP의 손실 복구 생명주기
1. PTO 만료 시 송신측은 작은 **TLP 프로브 패킷**을 디스패치합니다.
2. 미전송 데이터가 큐에 남아 있다면 다음 새로운 패킷을 보내고, 전송할 데이터가 없다면 가장 최근에 보냈던 미확인 패킷을 재전송합니다.
3. 수신측은 이 프로브를 수신하고 즉시 ACK/SACK을 회신합니다.
4. 송신측은 회신된 SACK 정보를 바탕으로 RACK 알고리즘을 즉시 구동하여 누락된 구멍(Hole)을 감지하고 고속 재전송을 수행합니다.
5. 결과: **수백 ms가 걸리던 RTO 타임아웃이 불과 $1 \times \text{PTO} + 1 \times \text{RTT}$ 만에 완전히 해결**됩니다!

---

## 4. 리눅스 커널 소스 코드 레벨 분석 (`net/ipv4/tcp_rack.c`)

리눅스 커널의 소켓 구조체 `struct tcp_sock` 내부에는 RACK 손실 감지를 위한 전용 필드가 내장되어 있습니다:

```c
struct rack_loss_info {
    u32 rtt_us;        /* 가장 최근 ACK에 기반한 RTT (마이크로초) */
    u32 reo_wnd;       /* 동적 패킷 역전 윈도우 시간 */
    u8  reord;         /* 역전 관측 여부 플래그 */
};
```

커널은 패킷이 도착할 때마다 `tcp_rack_detect_loss()`를 호출하여 송신 큐의 skb(소켓 버퍼) 리스트를 역방향으로 순회하면서 시간 임계값을 넘긴 skb를 찾아 즉시 `TCP_SKB_CB(skb)->sacked |= TCPCB_LOST` 마킹을 수행하고 `tcp_xmit_retransmit_queue()`를 트리거합니다.

이로 인해 현대 리눅스 서버는 대규모 패킷 역전이 발생하는 무선망에서도 불필요한 재전송 없이 최적의 쓰루풋을 유지하며, 찰나의 테일 유실에도 지체 없이 반응할 수 있습니다.
