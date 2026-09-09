# Problem 173: TCP BBR 혼잡 제어와 버퍼블로트(Bufferbloat) 탈출 시뮬레이터

## 문제 설명

대용량 영상 스트리밍 플랫폼을 운영하던 중, 사용자들의 다운로드 대역폭은 충분함에도 불구하고 중간 라우터의 거대한 버퍼로 인해 패킷 손실 없이 RTT만 20ms에서 수 초로 폭증하여 실시간 채팅과 영상 재생이 멈추는 **버퍼블로트(Bufferbloat)** 장애가 발생했습니다.

기존의 손실 기반(Loss-based) 알고리즘인 **CUBIC**은 라우터 버퍼가 넘쳐 패킷이 드랍될 때까지 윈도우를 팽창시켜 버퍼블로트를 유발하는 반면, 구글의 **BBR (Bottleneck Bandwidth and RTT)**은 병목 대역폭($\text{BtlBw}$)과 최소 왕복 시간($\text{RTprop}$)을 직접 측정하여 대역폭-지연 곱($\text{BDP}$)에 맞춘 속도 페이싱(Pacing Rate)으로 큐를 비우며 전송합니다.

당신은 차세대 전송 계층 프로토콜 엔지니어로서, **CUBIC**과 **BBR** 혼잡 제어 엔진을 정밀 시뮬레이션하여 버퍼블로트 발생 여부와 회선 안정성을 검증해야 합니다.

---

## 시뮬레이터 시스템 명세 및 동작 규칙

### 1. 네트워크 파이프 (`network`)
- `btl_bw_bytes_per_tick`: 병목 링크의 최대 물리 처리량 (틱당 배출 바이트 수).
- `rt_prop_ticks`: 큐 대기가 없을 때의 순수 물리적 왕복 전파 지연 (기본 지연).
- `router_buffer_max_bytes`: 중간 라우터의 최대 FIFO 버퍼 용량.
- 물리적 대역폭-지연 곱: $\text{BDP} = \text{btl\_bw} \times \text{rt\_prop}$
- 현재 시점의 실제 왕복 시간:
  $$\text{RTT} = \text{rt\_prop} + \frac{\text{router\_queue}}{\text{btl\_bw}}$$

### 2. 송신자 설정 (`sender`)
- `algorithm`: `"CUBIC"` 또는 `"BBR"`
- `initial_cwnd_bytes`: 초기 혼잡 윈도우 크기.
- `ssthresh_bytes` (CUBIC): 슬로우 스타트 임계치.
- `pacing_gain_cycle` (BBR): PROBE_BW 상태에서의 8단계 페이싱 게인 배열 (기본값: `[1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]`).

### 3. CUBIC 동작 규칙
1. **전송 가능 바이트 산출**:
   $$\text{can\_send} = \max(0, \text{cwnd} - \text{in\_flight})$$
   $$\text{to\_send} = \min(\text{app\_data\_bytes}, \text{can\_send})$$
2. **라우터 버퍼링 및 드랍**:
   - `router_queue + to_send > router_buffer_max`인 경우, 초과분은 드랍(`dropped`)되고 버퍼는 최대치로 채워집니다.
3. **목적지 배출**:
   $$\text{drained} = \min(\text{router\_queue}, \text{btl\_bw})$$
4. **혼잡 윈도우 갱신**:
   - 패킷 드랍 발생 시 (손실 감지):
     $$\text{ssthresh} \leftarrow \max(\text{BDP}, \text{cwnd} \times 0.7)$$
     $$\text{cwnd} \leftarrow \max(\text{btl\_bw}, \text{cwnd} \times 0.7)$$
   - 드랍이 없을 시:
     - `cwnd < ssthresh`이면 $\text{cwnd} \leftarrow \text{cwnd} + \min(\text{to\_send}, \text{btl\_bw})$ (Slow Start)
     - `cwnd >= ssthresh`이면 $\text{cwnd} \leftarrow \text{cwnd} + \max(100, \text{btl\_bw} \times 0.1)$ (Congestion Avoidance)

### 4. BBR 동작 규칙
1. **목표 윈도우 및 페이싱 레이트 산출**:
   $$\text{bdp\_est} = \text{btl\_bw\_est} \times \text{rt\_prop\_est}$$
   $$\text{cwnd} = \max(\text{bdp\_est} \times \text{cwnd\_gain}, \text{btl\_bw} \times 2.0)$$
   $$\text{pacing\_rate} = \text{int}(\text{btl\_bw\_est} \times \text{pacing\_gain})$$
   $$\text{can\_send} = \max(0, \min(\text{pacing\_rate}, \text{cwnd} - \text{in\_flight}))$$
   $$\text{to\_send} = \min(\text{app\_data\_bytes}, \text{can\_send})$$
2. **상태 머신 전이**:
   - `STARTUP`: 초기 `pacing_gain = 2.89`. 라우터 큐가 0을 초과(`router_queue > 0`)하면 즉시 `DRAIN`으로 전이.
   - `DRAIN`: `pacing_gain = 1/2.89`, `cwnd_gain = 1.0`. 라우터 큐가 0으로 비워지면(`router_queue == 0`) 즉시 `PROBE_BW`로 전이.
   - `PROBE_BW`: 매 `rt_prop_est` 틱마다 8단계 사이클(`[1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]`)을 순환하며 `pacing_gain` 조정.

### 5. 최종 판정 (Verdict)
- **`PACKET_LOSS_TAIL_DROP`**: 라우터 버퍼 초과로 패킷 드랍이 발생한 경우 (`total_dropped > 0`).
- **`SEVERE_BUFFERBLOAT_DETECTED`**: 패킷 손실은 없으나 최대 RTT가 기본 RTT의 2배 이상 치솟은 경우 ($\text{bufferbloat\_ratio} \ge 2.0$).
- **`OPTIMAL_BBR_RATE_PACING`**: BBR 알고리즘으로 손실 0건 및 $\text{bufferbloat\_ratio} < 1.8$을 달성한 경우.
- **`LINE_RATE_CONFORMANT`**: 트래픽이 회선 용량 이내로 흘러 지연 없이 전송된 경우.

---

## 입출력 예시

### 입력 (JSON)
```json
{
  "network": {
    "btl_bw_bytes_per_tick": 10000,
    "rt_prop_ticks": 5,
    "router_buffer_max_bytes": 150000
  },
  "sender": {
    "algorithm": "BBR",
    "initial_cwnd_bytes": 10000,
    "pacing_gain_cycle": [1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
  },
  "workload": [
    { "tick": 1, "app_data_bytes": 30000 },
    { "tick": 2, "app_data_bytes": 30000 }
  ]
}
```

### 출력 (JSON)
```json
{
  "status": "SUCCESS",
  "algorithm": "BBR",
  "summary": {
    "btl_bw_bytes_per_tick": 10000,
    "rt_prop_ticks": 5,
    "bdp_bytes": 50000,
    "router_buffer_max_bytes": 150000
  },
  "metrics": {
    "total_sent_bytes": 38900,
    "total_delivered_bytes": 20000,
    "total_dropped_bytes": 0,
    "peak_router_queue_bytes": 18900,
    "peak_rtt_ticks": 6.89,
    "average_rtt_ticks": 5.94,
    "bufferbloat_ratio": 1.38,
    "packet_loss_rate": 0.0,
    "verdict": "OPTIMAL_BBR_RATE_PACING"
  },
  "sample_timeline": [...]
}
```
