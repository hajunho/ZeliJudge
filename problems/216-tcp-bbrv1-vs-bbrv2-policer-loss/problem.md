# 문제 216: TCP BBRv1 vs BBRv2와 얕은 버퍼(Shallow Buffer) 환경에서의 토큰 버킷 폴리서(Token Bucket Policer) 패킷 손실 및 처리량 붕괴 완화

## 1. 개요 (Incident Scenario)

글로벌 크로스-리전(Cross-Region) 대규모 미디어 스트리밍 및 클라우드 게이트웨이 인프라를 운영하는 플랫폼 엔지니어링 팀은 퍼블릭 클라우드 간 Direct Connect 및 통신사 전용선(Leased Line) 구간에서 심각한 네트워크 처리량 불일치 장애에 직면했습니다.

클라우드 사업자(CSP) 및 중간 ISP 네트워크 장비는 계약 대역폭(Committed Information Rate, CIR)을 강제하기 위해 하드웨어 기반 **토큰 버킷 트래픽 폴리서(Token Bucket Traffic Policer)**를 배포하고 있습니다. 일반적인 라우터의 큐잉 셰이퍼(Traffic Shaper)와 달리, 폴리서는 잉여 패킷을 버퍼링하여 지연(Queue Delay)을 생성하는 대신 버킷 버스트 용량(Committed Burst Size, CBS)을 초과하는 즉시 패킷을 무자비하게 폐기(Drop)하는 얕은 버퍼(Shallow Buffer) 특성을 지닙니다.

이 환경에서 각 호스트의 TCP 혼잡 제어 알고리즘(Congestion Control Algorithm, CCA)에 따라 극단적인 이상 징후가 관측되었습니다:
1. **기본 리눅스 커널 CUBIC 커넥션**: 1Gbps 대역폭이 할당되어 있음에도 불구하고 폴리서의 단발성 패킷 드롭이 발생할 때마다 혼잡 윈도우(`cwnd`)를 30%씩 삭감(Multiplicative Decrease)하여 실효 대역폭이 100~140Mbps 수준으로 처참하게 붕괴(Starvation & Sawtooth Collapse)되었습니다.
2. **BBRv1(Bottleneck Bandwidth and RTT v1) 커넥션**: CUBIC과 달리 손실을 무시하고 측정된 병목 대역폭(`BtlBw`) 기반 페이싱(Pacing)을 유지하여 높은 대역폭을 점유하지만, `PROBE_BW` 상태의 주기적인 1.25x 오버페이싱 사이클마다 얕은 토큰 버킷을 완전히 초과하여 2.5%~3.5%에 달하는 고정적인 패킷 손실을 유발했습니다. 이는 재전송 스톰과 QUIC/HTTP3 헤드오브라인 블로킹을 유발하여 실시간 스트리밍 재생 중단 사고를 야기했습니다.
3. **BBRv2(Bottleneck Bandwidth and RTT v2) 커넥션**: 손실률(Loss Rate) 임계치와 얕은 버퍼/폴리서 감지 메커니즘을 결합하여, 폴리서 감지 시 `PROBE_BW`의 1.25x 페이싱 게인을 즉시 1.0x로 억제하고 상한 인플라이트(`inflight_hi`)를 제한함으로써 95% 이상의 회선 이용률을 유지하면서도 패킷 손실률을 0.5% 미만으로 억제하는 데 성공했습니다.

당신은 리눅스 커널 네트워크 스택 및 혼잡 제어 전문가로서, 토큰 버킷 폴리서 환경에서 CUBIC, BBRv1, BBRv2의 패킷 송수신, 페이싱 레이트 조절, 윈도우/버킷 상태 전이 및 성능 메트릭을 정밀하게 모의(Simulation)하고 최종 진단 리포트를 생성하는 진단 엔진을 구현해야 합니다.

---

## 2. 아키텍처 및 상태 전이 모델

```
 [TCP 송신 소켓 (Sender)]
    ├── CUBIC  : 손실 발생 시 cwnd *= 0.7 삭감 (Loss-based CC)
    ├── BBRv1  : BtlBw 측정 기반 Pacing (PROBE_BW 1.25x 게인 고정 유지)
    └── BBRv2  : 손실 피드백 감지 시 Policer 플래그 활성화 및 Probe Gain 1.0x 캡핑
              │
              ▼ Pacing 및 송신 (In-Flight Packet)
┌────────────────────────────────────────────────────────┐
│            Token Bucket Policer (망 경계 라우터)            │
│  - Tokens Refill: CIR (policer_rate_mbps * time)       │
│  - Bucket Depth : CBS (policer_bucket_capacity_bytes)  │
│                                                        │
│  [Tokens >= Packet Size]  ──>  PASS (전송 성공, RTT 후 ACK) │
│  [Tokens <  Packet Size]  ──>  DROP (패킷 즉시 폐기)        │
└────────────────────────────────────────────────────────┘
              │
              ▼ RTT 지연 후 ACK / Drop 피드백
 [CCA 상태 머신 갱신 및 Throughput / Loss Rate 산출]
```

### 시뮬레이션 동작 규격

1. **시간 및 단위 모델**:
   - 시뮬레이션 시간은 마이크로초($\mu s$) 단위로 진행됩니다.
   - 대역폭($Mbps$)에서 바이트/$\mu s$ 환산: `bytes_per_us = (policer_rate_mbps * 1,000,000) / (8 * 1,000,000)`.
   - $BDP = bytes\_per\_us \times rtt\_prop\_us$.
   - 토큰 버킷은 경과 시간에 비례하여 `bytes_per_us * elapsed`만큼 충전되며, 최대 용량은 `policer_bucket_capacity_bytes`로 캡핑됩니다.

2. **패킷 송신 및 폴리서 판정**:
   - 패킷 크기는 `mss_bytes` (기본 1500 바이트)입니다.
   - 송신기가 패킷을 전송할 때:
     - 토큰 버킷 잔여량(`tokens_bytes`) $\ge pkt\_size$이면: 토큰을 $pkt\_size$만큼 차감하고, `is_drop = False`로 인플라이트 큐에 삽입합니다.
     - 토큰 버킷 잔여량 < $pkt\_size$이면: 토큰을 차감하지 않고 패킷을 즉시 폐기하며, `is_drop = True`로 인플라이트 큐에 삽입합니다.
   - 패킷은 $rtt\_prop\_us$ 후에 도달(ACK 또는 손실 통지)하여 인플라이트에서 해제됩니다.

3. **혼잡 제어 알고리즘(CCA)별 윈도우 및 페이싱 동작**:
   - **CUBIC**:
     - 송신 가능 조건: `in_flight + mss_bytes <= cwnd`.
     - 페이싱 간격: `mss_bytes / (bytes_per_us * 1.5)`.
     - 손실 발생 시: `ssthresh = max(2 * mss, cwnd * 0.7)`, `cwnd = ssthresh`.
     - 정상 ACK 수신 시:
       - `cwnd < ssthresh`: 슬로우 스타트 (`cwnd += mss_bytes`).
       - `cwnd >= ssthresh`: 혼잡 회피 (`cwnd += (mss_bytes * mss_bytes) / cwnd`).
   - **BBRv1**:
     - `PROBE_BW` 페이싱 게인 사이클: `[1.25, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]` (매 RTT마다 사이클 인덱스 전이).
     - 페이싱 속도: `btlbw_bytes_per_us * gain`.
     - 페이싱 간격: `mss_bytes / current_rate`.
     - 손실 신호에 반응하지 않고 1.25x 프로빙을 무조건 수행.
   - **BBRv2**:
     - RTT 윈도우 단위로 손실률(`window_dropped_bytes / window_sent_bytes`)을 모니터링.
     - 손실률이 2.0%(`> 0.02`)를 초과하면 폴리서(Policer/Shallow Buffer)로 감지(`policer_detected = True`, `inflight_hi = max(bdp, in_flight)`).
     - 폴리서 감지 상태에서는 1.25x 게인 단계에서 게인을 1.0x로 강제 캡핑(`if gain > 1.0: gain = 1.0`)하여 토큰 버킷 오버플로우 드롭을 방지.

---

## 3. 입력 사양 (Input Specification)

JSON 형식으로 표준 입력(`sys.stdin`)을 통해 전달됩니다.

```json
{
  "config": {
    "algorithm": "BBRV2",
    "policer_rate_mbps": 100,
    "policer_bucket_capacity_bytes": 15000,
    "rtt_prop_ms": 20.0,
    "mss_bytes": 1500,
    "simulation_duration_ms": 1000.0,
    "initial_cwnd_bytes": 15000
  }
}
```

- `algorithm` (string): `"CUBIC"`, `"BBRV1"`, `"BBRV2"` 중 하나.
- `policer_rate_mbps` (number): 폴리서 토큰 리필 레이트 ($Mbps$, 예: 100, 1000).
- `policer_bucket_capacity_bytes` (number): 토큰 버킷 최대 버스트 크기 (Byte, 예: 15000, 4500).
- `rtt_prop_ms` (number): 물리적 왕복 전파 지연 시간 ($ms$).
- `mss_bytes` (number): TCP 최대 세그먼트 크기 (Byte, 기본 1500).
- `simulation_duration_ms` (number): 시뮬레이션 총 시간 ($ms$, 기본 1000.0).

---

## 4. 출력 사양 (Output Specification)

JSON 형식으로 표준 출력(`sys.stdout`)에 출력합니다.

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_BBRV2_POLICER_CONGESTION_CONTROL",
  "algorithm": "BBRV2",
  "metrics": {
    "total_packets_sent": 8092,
    "total_bytes_sent": 12138000,
    "total_bytes_delivered": 12088500,
    "total_bytes_dropped": 49500,
    "packet_loss_rate_pct": 0.41,
    "average_throughput_mbps": 96.71,
    "bandwidth_utilization_pct": 96.7,
    "final_cwnd_bytes": 15000,
    "policer_detected": true
  }
}
```

### 진단 판정(Verdict) 기준:
1. `CUBIC`:
   - `bandwidth_utilization_pct < 50.0`: `"CUBIC_LOSS_SENSITIVITY_THROUGHPUT_COLLAPSE"` (`status: "FAILED"`)
   - 그 외: `"NORMAL_CUBIC_FLOW"` (`status: "SUCCESS"`)
2. `BBRV1`:
   - `packet_loss_rate_pct >= 2.5`: `"BBRV1_POLICER_EXCESSIVE_LOSS_RATE"` (`status: "FAILED"`)
   - 그 외: `"NORMAL_BBRV1_FLOW"` (`status: "SUCCESS"`)
3. `BBRV2`:
   - `bandwidth_utilization_pct >= 85.0` 및 `packet_loss_rate_pct < 2.0`: `"OPTIMAL_BBRV2_POLICER_CONGESTION_CONTROL"` (`status: "SUCCESS"`)
   - 그 외: `"BBRV2_SUBOPTIMAL_FLOW"` (`status: "SUCCESS"`)
4. 알 수 없는 알고리즘: `"UNKNOWN_ALGORITHM"` (`status: "FAILED"`)
