# 문제 217: AI/NVMe-oF RoCEv2 무손실(Lossless) 네트워크의 PFC(Priority Flow Control) 데드락 및 PAUSE 프레임 폭풍 vs DCQCN 혼잡 제어

## 1. 개요 (Incident Scenario)

초거대 언어 모델(LLM) 및 대규모 분산 AI 딥러닝 클러스터를 운영하는 AI 인프라 엔지니어링 팀은 수천 대의 H100/A100 GPU 노드 간 **NCCL AllReduce 집단 통신(Collective Communication)** 및 **NVMe-oF 초고속 스토리지 패브릭** 환경에서 주기적으로 클러스터 전체 통신이 완전 마비(Hang)되는 비상 사태를 겪었습니다.

RoCEv2(RDMA over Converged Ethernet v2)는 패킷 손실이 발생할 경우 하드웨어 Go-Back-N 재전송으로 인한 심각한 처리량 붕괴(Goodput Collapse)를 겪기 때문에, 통상 네트워크 스위치와 호스트 NIC(Mellanox ConnectX 등)에 **IEEE 802.1Qbb PFC(Priority Flow Control)**를 활성화하여 특정 트래픽 클래스(주로 Priority 3)를 무손실(Lossless)로 운용합니다.

그러나 무손실 패브릭에서 다음과 같은 치명적인 장애들이 관측되었습니다:
1. **순환 버퍼 의존성(Cyclic Buffer Dependency, CBD)과 PFC 데드락**:
   다중 경로(ECMP) 비대칭 라우팅 또는 링/메시 토폴로지에서 인캐스트(Incast) 버스트가 발생했을 때, 스위치 큐가 임계치(`pfc_pause_thresh_kb`)를 초과하여 상류(Upstream) 스위치로 PFC PAUSE 프레임을 전송합니다. 이 PAUSE 신호가 순환 고리($SW_1 \to SW_2 \to SW_3 \to SW_1$)를 형성하면서 모든 스위치가 서로의 송신을 영구적으로 차단하는 **PFC 데드락(PFC Deadlock)**이 발생했습니다. 결과적으로 클러스터 통신 처리량이 0 Gbps로 곤두박질치고 GPU 점유율이 0%로 추락했습니다.
2. **PFC PAUSE 폭풍(Storm)과 헤드오브라인 블로킹(Head-of-Line Blocking, HoL)**:
   특정 노드로 트래픽이 집중되는 인캐스트 상황에서 다운스트림 포트가 혼잡해지면 수십~수백 개의 PAUSE 프레임이 상류로 연쇄 전파(Pause Frame Propagation)됩니다. 이로 인해 동일한 업링크를 공유하던 무관한 저지연 RPC 및 헬스체크 트래픽까지 송신이 차단되는 광범위한 부수 피해(Collateral Damage)가 발생했습니다.
3. **PFC 워치독(PFC Watchdog / PDR, Deadlock Recovery)**:
   스위치 포트가 설정된 타임아웃(`watchdog_timeout_us`) 이상 지속적으로 PAUSE 상태에 머물 경우, 스위치 하드웨어가 데드락을 감지하고 정체된 큐의 패킷을 강제 폐기(Drain)하여 포트를 복구함으로써 순환 대기 고리를 깨뜨렸습니다.
4. **DCQCN(Data Center Quantized Congestion Notification) 종단 간 혼잡 제어**:
   스위치 큐가 PFC PAUSE 임계치에 도달하기 훨씬 전에 ECN(Explicit Congestion Notification) 마킹을 수행하고, 수신측 NIC가 CNP(Congestion Notification Packet)를 송신측으로 반환하여 송신율을 부드럽게 감속(Multiplicative Decrease / Additive Increase)시킴으로써, **PFC PAUSE 프레임을 단 1건도 유발하지 않고(Zero-PFC)** 패킷 손실 0%와 고대역폭 전송을 완벽하게 양립했습니다.

당신은 AI/HPC 고성능 네트워크 및 리눅스 RDMA 스택 엔지니어로서, RoCEv2 패브릭의 PFC 동작, 워치독 복구 메커니즘, DCQCN 혼잡 제어 및 패킷 흐름을 정밀하게 모의(Simulation)하고 정확한 네트워크 상태 판정 리포트를 도출하는 엔진을 구현해야 합니다.

---

## 2. 아키텍처 및 상태 머신 모델

```
[호스트 NIC 송신] ──(Gbps)──► [스위치 큐 (Queue Depth)] ──(Egress)──► [다음 홉 / 목적지]
                                      │
               ┌──────────────────────┴──────────────────────┐
               ▼                                             ▼
        [PFC 임계치 감지]                               [DCQCN ECN 감지]
   Queue >= pfc_pause_thresh_kb                  k_min <= Queue < k_max
               │                                             │
               ▼                                             ▼
     PFC PAUSE 전송 (Upstream)                       ECN CE 비트 마킹
     Upstream Link / Host PAUSE                              │
               │                                             ▼
     ┌─────────┴──────────┐                      목적지 NIC CNP 반환
     ▼                    ▼                                  │
[순환 의존성]         [워치독 타이머]                          ▼
All Links Paused    Paused >= Watchdog_Timeout     송신측 NIC Rate Throttle
     │                    │                     (Queue < Pause_Thresh 유지)
     ▼                    ▼                                  │
PFC DEADLOCK!       Queue Drain & Drop                       ▼
Throughput = 0      Deadlock Resolved               Zero-PFC 무손실 전송!
```

### 시뮬레이션 동작 규격

1. **단위 및 대역폭 환산**:
   - 시간 단위는 마이크로초($\mu s$) 단위이며, `time_step_us` 간격으로 이산 이벤트 시뮬레이션이 진행됩니다.
   - 링크 대역폭($Gbps$)에서 $\mu s$당 $KB$ 환산:
     $$kb\_per\_us = \text{bandwidth\_gbps} \times \frac{1000}{8192} \approx \text{bandwidth\_gbps} \times 0.12207$$
   - 링크당 전송 가능 용량: $avail\_kb = kb\_per\_us \times time\_step\_us$.

2. **PFC (Priority Flow Control) 메커니즘**:
   - 스위치 포트의 잔여 큐 용량(`queue_capacity_kb`, 기본 512KB).
   - 링크의 `queue_kb >= pfc_pause_thresh_kb` (기본 256KB) 도달 시:
     - 해당 링크로 패킷을 유입시키는 모든 상류 링크(`upstream_links`) 및 호스트 송신 큐(`ingress_flows`)에 PFC PAUSE 신호를 전달합니다 (`is_paused = True`, `is_source_paused = True`).
     - `pfc_pause_sent_count`를 1 증가시킵니다.
   - 링크의 `queue_kb <= pfc_resume_thresh_kb` (기본 128KB) 하강 시:
     - 상류 링크 및 호스트에 RESUME 신호를 전달합니다. (단, 상류 링크가 다른 하류 링크로부터 여전히 PAUSE를 받고 있다면 PAUSE 유지).
   - 링크가 PAUSE 상태인 동안에는 하류로 패킷을 전송(Egress Drain)할 수 없습니다.

3. **PFC 워치독 (PFC Watchdog / PDR)**:
   - `mode == "PFC_WATCHDOG"` 모드에서, 링크가 PAUSE 상태로 머문 누적 시간(`current_time - paused_since_us`)이 `watchdog_timeout_us` 이상 지속되면 워치독이 트리거됩니다.
   - 워치독 동작:
     - `watchdog_triggered_count`를 1 증가시킵니다.
     - 해당 포트의 큐에 고여 있던 패킷 전체를 드롭(`queue_kb = 0`, `packet_queue.clear()`)하여 대기열을 강제 비웁니다.
     - 링크 및 상류의 PAUSE 상태를 해제하여 통신을 정상 재개합니다.

4. **순환 데드락 판정**:
   - 패브릭 내의 3개 이상의 링크가 동시에 PAUSE 상태에 진입하고, 이 상태가 $400\mu s$ 이상 지속되면 순환 버퍼 데드락(`deadlock_detected = True`)으로 판정합니다.
   - `mode == "PFC_ONLY"`인 경우 AllReduce 통신이 완전히 얼어붙습니다 (`allreduce_frozen = True`).

5. **DCQCN (Data Center Quantized Congestion Notification)**:
   - `mode == "DCQCN"` 모드에서는 패킷 전송 시 스위치 큐 깊이가 $k_{min} \le queue\_kb$일 경우 ECN 비트를 마킹합니다.
   - 패킷이 목적지에 도달했을 때 ECN이 마킹되어 있다면, 최소 `cnp_interval_us` 간격으로 송신 호스트에 CNP 패킷이 도착합니다.
   - CNP 수신 시 송신율 감소:
     $$Rate \leftarrow \max(10.0, Rate \times (1 - \alpha / 2))$$
     $$\alpha \leftarrow \min(1.0, (1 - g) \times \alpha + g) \quad (g = 0.25)$$
   - CNP가 도착하지 않는 회복 주기에는 타이머에 의해 덧셈적 증가(Additive Increase, $R_{AI}$)를 수행합니다:
     $$Rate \leftarrow \min(TargetRate, Rate + R_{AI} \times (time\_step\_us / 100))$$
     $$\alpha \leftarrow \max(0.01, \alpha \times (1 - g))$$

6. **NO_FLOW_CONTROL (일반 이더넷)**:
   - 흐름 제어가 없으므로 큐가 `queue_capacity_kb`를 초과하면 초과 패킷을 테일 드롭(Tail Drop)합니다.

---

## 3. 입력 사양 (Input Specification)

JSON 형식으로 표준 입력(`sys.stdin`)을 통해 전달됩니다.

```json
{
  "config": {
    "mode": "PFC_ONLY",
    "simulation_duration_us": 5000.0,
    "time_step_us": 10.0,
    "queue_capacity_kb": 512,
    "pfc_pause_thresh_kb": 256,
    "pfc_resume_thresh_kb": 128,
    "watchdog_timeout_us": 1000.0,
    "dcqcn_k_min_kb": 80,
    "dcqcn_k_max_kb": 180,
    "dcqcn_cnp_interval_us": 50.0
  },
  "topology": {
    "links": [
      {"id": "L12", "src": "SW1", "dst": "SW2", "bandwidth_gbps": 100},
      {"id": "L23", "src": "SW2", "dst": "SW3", "bandwidth_gbps": 100},
      {"id": "L31", "src": "SW3", "dst": "SW1", "bandwidth_gbps": 100}
    ]
  },
  "flows": [
    {"id": "F1", "src": "SW1", "dst": "SW3", "path": ["L12", "L23"], "target_rate_gbps": 110.0},
    {"id": "F2", "src": "SW2", "dst": "SW1", "path": ["L23", "L31"], "target_rate_gbps": 110.0},
    {"id": "F3", "src": "SW3", "dst": "SW2", "path": ["L31", "L12"], "target_rate_gbps": 110.0}
  ]
}
```

- `mode` (string): `"PFC_ONLY"`, `"PFC_WATCHDOG"`, `"DCQCN"`, `"NO_FLOW_CONTROL"`.
- `simulation_duration_us` (number): 총 시뮬레이션 시간 ($\mu s$).
- `topology.links` (array): 네트워크 링크 목록 (`id`, `src`, `dst`, `bandwidth_gbps`).
- `flows` (array): 트래픽 플로우 목록 (`id`, `src`, `dst`, `path`, `target_rate_gbps`).

---

## 4. 출력 사양 (Output Specification)

JSON 형식으로 표준 출력(`sys.stdout`)에 출력합니다.

```json
{
  "status": "FAILED",
  "verdict": "PFC_DEADLOCK_DETECTED_ALLREDUCE_FREEZE",
  "mode": "PFC_ONLY",
  "metrics": {
    "total_sent_bytes": 825000,
    "total_delivered_bytes": 0,
    "total_dropped_bytes": 0,
    "packet_loss_rate_pct": 0.0,
    "effective_throughput_gbps": 0.0,
    "total_pfc_pause_frames": 3,
    "total_watchdog_recoveries": 0,
    "deadlock_detected": true,
    "allreduce_frozen": true
  }
}
```

### 진단 판정(Verdict) 기준:
1. `mode == "PFC_ONLY"`:
   - `allreduce_frozen == true`: `"PFC_DEADLOCK_DETECTED_ALLREDUCE_FREEZE"` (`status: "FAILED"`)
   - `total_pfc_pause_frames >= 20`: `"PFC_PAUSE_STORM_HOL_BLOCKING"` (`status: "FAILED"`)
   - 그 외: `"NORMAL_PFC_OPERATION"` (`status: "SUCCESS"`)
2. `mode == "PFC_WATCHDOG"`:
   - `total_watchdog_recoveries > 0`: `"PFC_DEADLOCK_RESOLVED_WATCHDOG_DRAIN"` (`status: "SUCCESS"`)
   - 그 외: `"NORMAL_PFC_WATCHDOG_MONITORING"` (`status: "SUCCESS"`)
3. `mode == "DCQCN"`:
   - `total_pfc_pause_frames == 0` 이고 `packet_loss_rate_pct == 0.0` 이며 `effective_throughput_gbps >= 35.0`: `"OPTIMAL_DCQCN_LOSSLESS_TRANSMISSION"` (`status: "SUCCESS"`)
   - 그 외: `"DCQCN_SUBOPTIMAL"` (`status: "SUCCESS"`)
4. `mode == "NO_FLOW_CONTROL"`:
   - `"NO_FLOW_CONTROL_PACKET_LOSS_STORM"` (`status: "FAILED"`)
5. 기타 알 수 없는 모드: `"UNKNOWN_MODE"` (`status: "FAILED"`)
