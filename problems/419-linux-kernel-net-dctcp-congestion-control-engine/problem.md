# 문제 419: Linux 커널 데이터센터 전송 계층 DCTCP(Data Center TCP) ECN 분율 회계 및 알파 스무딩(α) 기반 비례 윈도우 축소 엔진

## 문제 설명

하이퍼스케일 클라우드 데이터센터(Microsoft Azure, AWS, Meta) 내부의 통신 환경은 초저지연(RTT 수십~수백 마이크로초), 고대역폭(100GbE~800GbE), 그리고 얕은 패킷 버퍼(Shallow Buffer, 수 메가바이트 스위치 온칩 SRAM)라는 독특한 특성을 갖습니다.

전통적인 인터넷 혼잡 제어 알고리즘인 CUBIC, Reno 등과 표준 ECN(Explicit Congestion Notification, RFC 3168)은 이러한 데이터센터 환경에서 심각한 병목을 유발합니다:
1. **이진 혼잡 반응 (Binary Reaction)**: 단 1개의 패킷이라도 스위치에서 CE(Congestion Experienced) 마킹을 받으면, 송신자는 실제 혼잡 정도와 무관하게 무조건 혼잡 윈도우를 절반($cwnd \leftarrow cwnd / 2$)으로 삭감합니다.
2. **처리량 톱니파 진동 (Throughput Oscillations)**: 과도한 윈도우 축소로 인해 스위치 큐가 비어 대역폭을 100% 활용하지 못하고, 다시 윈도우를 회복하는 과정에서 버퍼블로트(Bufferbloat)가 반복됩니다.
3. **TCP 인캐스트 붕괴 (TCP Incast Collapse)**: 맵리듀스(MapReduce)나 분산 검색 등 파티션-집계(Partition-Aggregate) 구조에서 수백 대의 워커 노드가 단일 집계 노드로 동시에 수십 KB의 응답을 전송할 때, 스위치 버퍼가 즉시 포화되어 대규모 패킷 드롭과 재전송 타임아웃(RTO 200ms)이 발생하여 전체 요청 지연 시간이 수천 배 폭증합니다.

이 문제를 해결하기 위해 2010년 Mohammad Alizadeh 등에 의해 제안되고 IETF RFC 8257로 표준화되어 리눅스 커널 3.18+에 공식 병합된 핵심 데이터센터 혼잡 제어 서브시스템이 바로 **DCTCP (Data Center TCP, `net/ipv4/tcp_dctcp.c`, `CONFIG_TCP_CONG_DCTCP`)**입니다.

---

### DCTCP 핵심 아키텍처 및 동작 메커니즘

DCTCP의 근본적인 혁신은 **"혼잡을 단순한 0 또는 1의 이진 신호가 아닌, 0.0부터 1.0까지의 연속적인 혼잡 비율(Extent of Congestion)로 정량화하여 정확히 그에 비례해서만 윈도우를 축소하는 것"**입니다.

1. **스위치 조기 마킹 임계치 ($K$)**:
   - 데이터센터 스위치는 큐 길이($Q$)가 매우 작은 임계치 $K$ (일반적으로 20~65KB, 약 15~40개 패킷)를 초과하면 즉시 유입 패킷의 IP TOS 필드에 CE 비트(0b11)를 마킹합니다.
   - 큐가 넘쳐 패킷이 드롭될 때까지 기다리지 않고, 큐가 미세하게 쌓이기 시작하는 순간 즉시 경고를 보냅니다.

2. **정밀 ECN 에코 및 바이트 분율 회계 ($F$)**:
   - 수신자는 CE 마킹을 수신할 때마다 ACK 패킷에 이를 즉각 반영합니다.
   - 송신자는 1 RTT 관측 윈도우 동안 전달된 총 바이트 수($B_{\text{total}}$)와 CE 마킹이 부착된 바이트 수($B_{\text{ce}}$)를 정밀 회계합니다:
     $$F = \frac{B_{\text{ce}}}{B_{\text{total}}}$$

3. **지수 이동 평균(EWMA) 스무딩 팩터 ($\alpha$)**:
   - 네트워크의 순간적인 노이즈를 완화하고 지속적인 혼잡도를 추적하기 위해 감쇠 계수 $g = \frac{1}{16} = 0.0625$를 사용하여 알파($\alpha$) 값을 갱신합니다:
     $$\alpha \leftarrow (1 - g) \cdot \alpha + g \cdot F$$
   - $\alpha \in [0.0, 1.0]$: 혼잡이 전혀 없으면 0.0으로 수렴하고, 극심한 혼잡이 지속되면 1.0으로 수렴합니다.

4. **비례 윈도우 축소 (Proportional Window Reduction)**:
   - 혼잡 윈도우를 무조건 50% 깎는 대신, 계산된 혼잡도 $\alpha$에 비례하여 부드럽게 감축합니다:
     $$cwnd \leftarrow cwnd \cdot \left( 1 - \frac{\alpha}{2} \right)$$
   - 예를 들어, 경미한 혼잡으로 패킷의 10%만 마킹되었다면($\alpha = 0.1$), $cwnd$는 겨우 5%만 축소됩니다.
   - 모든 패킷이 마킹된 극심한 혼잡($\alpha = 1.0$)일 때만 전통적인 50% 축소가 적용됩니다.
   - 이로 인해 스위치 버퍼 큐 깊이가 수 마이크로초(단일 자릿수 µs) 수준으로 극도로 얕게 유지되면서도 링크 대역폭은 상시 99.9% 포화 상태를 유지합니다.

5. **패킷 손실 시 하드 폴백 (Loss Fallback)**:
   - ECN 기반 비례 조절을 넘어서 실제 물리적 패킷 유실(Drop)이 발생하면, 하드웨어 안전망으로서 표준 손실 복구 절차($ssthresh \leftarrow cwnd / 2$, $cwnd \leftarrow ssthresh$)로 폴백합니다.

여러분은 리눅스 커널 DCTCP의 바이트 수준 ECN 분율 회계, EWMA $\alpha$ 스무딩 필터, 비례 $cwnd$ 축소 및 인캐스트 억제 엔진을 정밀하게 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                        Linux Kernel DCTCP Architecture (RFC 8257)                                |
+==================================================================================================+

   [ Sender (DCTCP) ]                                       [ Datacenter Switch ]
          |                                                           |
          | Transmits Data Packets (MSS = 1460B)                      |
          +---------------------------------------------------------->| Switch Buffer Queue (Q)
                                                                      | Check Q > K (Threshold: 20KB)?
                                                                      |   - YES: Set CE Bit in IP TOS!
                                                                      |   - NO : Leave Clean
                                                                      v
                                                            [ Receiver (AccECN) ]
                                                                      |
                                                                      | Echoes CE status in ACK
                                                                      v
   [ Sender TCP Ingress (net/ipv4/tcp_dctcp.c) ] <--------------------+
          |
          | 1. On Every ACK:
          |      rtt_bytes_total += bytes_acked
          |      if (ce_marked) rtt_bytes_ce += bytes_acked
          |      Grow cwnd (Slow Start: +1 MSS, Congestion Avoidance: +1/cwnd)
          |
          | 2. On RTT Window Completed:
          |      F = rtt_bytes_ce / rtt_bytes_total
          |      alpha = (1 - g) * alpha + g * F   (where g = 1/16 = 0.0625)
          |
          |      if (rtt_bytes_ce > 0):
          |          reduction_factor = 1 - (alpha / 2)
          |          cwnd = max(min_cwnd, cwnd * reduction_factor)  <-- Proportional Cut!
          |          ssthresh = cwnd
          |          state = CONGESTION_AVOIDANCE
          v
   [ Zero-Queue Bufferbloat Control & Near-Zero Queue Delay Achieved! ]
```

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "g": 0.0625,
    "mss": 1460,
    "min_cwnd": 2
  },
  "trace": [
    {"time": 0, "type": "INIT_FLOW", "flow_id": 1, "initial_cwnd": 10, "initial_ssthresh": 20},
    {"time": 1, "type": "ACK_EVENT", "flow_id": 1, "bytes_acked": 1460, "ce_marked": false},
    {"time": 2, "type": "ACK_EVENT", "flow_id": 1, "bytes_acked": 1460, "ce_marked": true},
    {"time": 3, "type": "RTT_WINDOW_COMPLETED", "flow_id": 1}
  ]
}
```

- `config.g`: EWMA 감쇠 계수 (기본값 0.0625).
- `config.mss`: 최대 세그먼트 크기 (기본값 1460 바이트).
- `config.min_cwnd`: 혼잡 윈도우 하한선 (기본값 2 패킷).
- `trace`: 시간 순서대로 실행되는 이벤트 리스트:
  - `INIT_FLOW`: `{"time": t, "type": "INIT_FLOW", "flow_id": id, "initial_cwnd": c, "initial_ssthresh": s}`
  - `ACK_EVENT`: `{"time": t, "type": "ACK_EVENT", "flow_id": id, "bytes_acked": b, "ce_marked": bool}`
  - `RTT_WINDOW_COMPLETED`: `{"time": t, "type": "RTT_WINDOW_COMPLETED", "flow_id": id}`
  - `PACKET_LOSS_EVENT`: `{"time": t, "type": "PACKET_LOSS_EVENT", "flow_id": id}`

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다 (compact JSON, `ensure_ascii=False`):

```json
{
  "summary": {
    "active_flows": 1,
    "total_acks": 2,
    "total_ce_marked_acks": 1,
    "total_proportional_reductions": 1,
    "total_loss_events": 0
  },
  "flows": {
    "1": {
      "flow_id": 1,
      "final_cwnd": 10.8266,
      "final_ssthresh": 10.8266,
      "final_alpha": 0.0312,
      "state": "CONGESTION_AVOIDANCE",
      "total_acks": 2,
      "total_ce_marked_acks": 1,
      "rtt_cycles": 1,
      "proportional_reductions": 1,
      "loss_events": 0,
      "rtt_logs": [ ... ]
    }
  },
  "event_logs": [ ... ]
}
```
