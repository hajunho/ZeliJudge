# 이론 백서: AI 클러스터 RoCEv2 무손실(Lossless) 네트워크의 PFC 데드락, PAUSE 폭풍 및 DCQCN 혼잡 제어

## 1. 개요 및 배경 (Background)

현대 생성형 AI와 대규모 파운데이션 모델(LLM, Large Language Models)의 훈련은 수천~수만 개의 고성능 가속기(NVIDIA H100, B200 등)가 긴밀하게 통신하는 초거대 분산 컴퓨팅 환경에서 수행됩니다. 이러한 환경에서 분산 훈련 프레임워크(Megatron-LM, DeepSpeed)는 모델 가중치와 그래디언트를 동기화하기 위해 **NCCL(NVIDIA Collective Communications Library) AllReduce** 집단 통신을 지속적으로 수행합니다.

AllReduce 연산은 모든 GPU가 데이터를 교환하기 전까지 다음 연산으로 넘어갈 수 없는 **배리어 동기화(Barrier Synchronization)** 특성을 지닙니다. 따라서 단 하나의 통신 링크에서 발생하는 지연이나 패킷 손실이 클러스터 전체 훈련 속도를 지연시키는 극심한 스트래글러(Straggler) 효과를 초래합니다.

고대역폭(100Gbps~400Gbps)과 마이크로초 단위의 극저지연을 달성하기 위해, 오늘날의 AI 클러스터와 분산 NVMe-oF(NVMe over Fabrics) 스토리지는 OS 커널의 TCP/IP 스택을 완전히 우회(Kernel Bypass)하고 CPU 개입 없이 메모리 간 직접 데이터 복사를 수행하는 **RoCEv2(RDMA over Converged Ethernet v2)** 프로토콜을 표준으로 채택하고 있습니다.

---

## 2. RoCEv2와 무손실(Lossless) 네트워크의 필연성

### 2.1. RoCEv2의 패킷 구조 및 하드웨어 제약
RoCEv2는 전통적인 인피니밴드(InfiniBand) 전송 계층 패킷을 UDP/IP 프레임(목적지 UDP 포트 `4791`)으로 캡슐화하여 표준 이더넷 스위치 상에서 라우팅할 수 있도록 설계되었습니다.

```
+------------------+---------------+----------------+----------------+----------------+
| Ethernet Header  |  IPv4 Header  |   UDP Header   |  IB BTH Header | RDMA Payload & |
| (802.1Q PCP/VLAN)|  (DSCP/ECN)   |  (Dst Port 4791) (Opcode, QPN, PSN)|      ICRC      |
+------------------+---------------+----------------+----------------+----------------+
```

그러나 RoCEv2의 신뢰성 연결(RC, Reliable Connection)은 호스트 OS 커널이 아닌 **스마트 NIC(SmartNIC, Mellanox ConnectX ASIC) 하드웨어 로직**에 내장되어 있습니다. ASIC의 면적과 비용 제약으로 인해 NIC 내부 버퍼는 수십~수백 킬로바이트 수준으로 매우 제한적입니다.

### 2.2. Go-Back-N 재전송의 재앙
- 수신측 NIC는 도착한 패킷의 순서 번호(Packet Sequence Number, PSN)가 연속적이지 않으면(단 $1$개의 패킷이라도 유실되면) 이후 수신되는 모든 정상 패킷을 폐기(Out-of-Order 패킷 수용 불가)합니다.
- 송신측 NIC는 손실을 인지한 후 유실된 시점부터 모든 패킷을 다시 보내는 **Go-Back-N 재전송**을 수행합니다.
- 패킷 유실률이 $0.1\%$만 발생해도 RDMA 재전송 스톰이 발생하여 회선의 실효 처리량(Goodput)이 수십 Gbps에서 거의 $0$에 가깝게 곤두박질치는 **처리량 붕괴(Goodput Collapse)**가 일어납니다.
- 따라서 RoCEv2를 안정적으로 운용하기 위해서는 네트워크 패브릭이 패킷을 결코 버리지 않는 **무손실 이더넷(Lossless Ethernet)**이어야 합니다.

---

## 3. IEEE 802.1Qbb PFC (Priority-based Flow Control)

이더넷을 무손실 네트워크로 전환하기 위해 도입된 표준이 **PFC (Priority-based Flow Control)**입니다.

### 3.1. 홉 간(Hop-by-Hop) 흐름 제어 메커니즘
전통적인 이더넷 PAUSE(802.3x)가 링크 전체를 멈추는 것과 달리, PFC는 $8$개의 트래픽 우선순위(Priority 0~7)를 개별적으로 제어합니다. 통상 AI RDMA 트래픽은 **Priority 3**에 할당하여 무손실(Lossless)로 지정하고, 일반 관리/SSH 트래픽은 Priority 0에 할당하여 유손실(Lossy)로 분리합니다.

```
 [Switch Ingress Buffer Architecture]
 ┌──────────────────────────────────────────────┐
 │ Headroom (비상 흡수 구역)                     │ ── Max Buffer Capacity
 ├──────────────────────────────────────────────┤
 │ XOFF Threshold (pfc_pause_thresh_kb)         │ ── PFC PAUSE 프레임 상류 송신!
 │                                              │
 ├──────────────────────────────────────────────┤
 │ XON Threshold (pfc_resume_thresh_kb)         │ ── PFC RESUME 프레임 상류 송신!
 │                                              │
 └──────────────────────────────────────────────┘ ── 0 KB
```

1. **PAUSE (XOFF) 전송**: 스위치 큐의 점유량이 `pfc_pause_thresh_kb`에 도달하면, 스위치는 상류(송신 노드 또는 이전 스위치)로 **PFC PAUSE 프레임**을 보냅니다.
2. **헤드룸(Headroom)의 역할**: 상류 노드가 PAUSE 프레임을 수신하고 송신을 완전히 중단하기까지는 왕복 전파 지연(RTT)과 하드웨어 파이프라인 지연이 소요됩니다. 이 동안 비행 중(In-Flight)인 패킷들이 버퍼를 넘치지 않도록 안전하게 흡수하는 여유 공간이 헤드룸입니다.
3. **RESUME (XON) 전송**: 하류 링크로 패킷이 배출(Drain)되어 큐 깊이가 `pfc_resume_thresh_kb` 이하로 떨어지면, 상류로 **PFC RESUME 프레임**을 보내 송신을 재개시킵니다.

---

## 4. PFC의 치명적 부작용

PFC는 패킷 손실을 방지하지만, 네트워크 전체에 걸쳐 심각한 연쇄 부작용을 야기합니다.

### 4.1. PAUSE 폭풍(Storm)과 헤드오브라인 블로킹(HoL Blocking)
다수의 노드가 특정 스위치 포트로 동시에 데이터를 쏟아붓는 인캐스트(Incast)가 발생하면, 해당 포트의 버퍼가 고갈되어 상류로 PAUSE를 발송합니다.
상류 스위치 역시 버퍼가 가득 차게 되며, PAUSE 신호는 2홉, 3홉, 5홉 뒤의 상류 스위치들로 연쇄 전파(Pause Frame Propagation)됩니다.

```
 [Server A (Incast Flow)] ──┐
                            ├──► [SW1] ──(L_agg)──► [SW2] ──► [Server D (혼잡 병목)]
 [Server B (Incast Flow)] ──┘             ▲           │
                                          │ PAUSE!    │ PAUSE! (L2 버퍼 고갈)
 [Server C (Low Latency RPC)] ────────────┘           ▼
   (F_victim: Server E로 향하는 정상 흐름)      [Server E (여유 있는 목적지)]
```

- **헤드오브라인 블로킹 (HoL Blocking)**:
  `Server C`에서 `Server E`로 향하는 가벼운 저지연 RPC 패킷은 목적지가 전혀 혼잡하지 않음에도 불구하고, `SW1`과 `SW2` 사이의 공유 링크(`L_agg`)가 PAUSE 상태에 걸림으로써 함께 멈추어 버립니다. 이로 인해 마이크로서비스 헬스체크 실패, 분산 DB 타임아웃 등의 광범위한 부수 피해가 발생합니다.

### 4.2. 순환 버퍼 의존성(CBD)과 PFC 데드락 (PFC Deadlock)
가장 파괴적인 장애는 패브릭 내에 순환 버퍼 의존성(Cyclic Buffer Dependency)이 형성될 때 발생합니다.
리프-스파인(Leaf-Spine) 구조에서 다중 경로 라우팅 루프, 링 토폴로지, 비대칭 경로가 결합되면 다음과 같은 순환 대기가 완성됩니다:

```
  [SW1] ─── (L12) ───► [SW2]
    ▲                    │
    │                    │ (L23)
  (L31)                  ▼
  [SW3] ◄────────────────┘
```

1. $L_{23}$의 혼잡으로 $SW_2$가 $L_{12}$를 PAUSE합니다.
2. $L_{31}$의 혼잡으로 $SW_3$가 $L_{23}$을 PAUSE합니다.
3. $L_{12}$의 혼잡으로 $SW_1$가 $L_{31}$을 PAUSE합니다.
4. 이제 $L_{12}$, $L_{23}$, $L_{31}$의 모든 송신 포트가 하류의 PAUSE에 의해 차단되었습니다.
5. 어떤 포트도 패킷을 보낼 수 없으므로 큐가 절대로 줄어들지 않고, 따라서 어떤 포트도 RESUME을 보내지 못합니다!
6. **결과**: 네트워크 패브릭의 모든 통신이 영구적으로 동결(Freeze)되며, GPU AllReduce 훈련 작업은 즉시 멈추고 복구되지 않습니다.

---

## 5. 완화 기술 1: PFC 워치독 (PFC Watchdog / PDR)

RFC 8333 및 엔터프라이즈 NOS(SONiC, Arista EOS, Cisco NX-OS)는 데드락을 감지하고 강제 해소하기 위한 **PFC 워치독(PFC Deadlock Recovery, PDR)**을 탑재합니다.

```
 [포트가 PAUSE 상태 진입] ──► [타이머 가동: watchdog_timeout_us]
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           ▼                                                         ▼
    정상 RESUME 수신 (Time < Timeout)                    타임아웃 초과 (Time >= Timeout)
    타이머 리셋 및 정상 동작 유지                         ┌─────────────────────────────────┐
                                                         │ 1. 데드락 상태 선언             │
                                                         │ 2. 대기 큐 패킷 강제 드롭(Drain)│
                                                         │ 3. PAUSE 해제 및 통신 강제 재개 │
                                                         └─────────────────────────────────┘
```

- **한계점**: 워치독은 데드락을 해소할 수 있지만, 패킷을 강제 폐기(Drop)함으로써 동작합니다. 이는 필연적으로 RoCEv2의 Go-Back-N 재전송을 유발하여 일시적인 지연 시간 스파이크와 성능 저하를 초래하는 사후적(Reactive) 치료책에 불과합니다.

---

## 6. 완화 기술 2: DCQCN (Data Center Quantized Congestion Notification)

**DCQCN**은 PFC가 트리거되기 전에 송신측의 전송 속도를 선제적으로 조절하여 무손실과 무데드락을 동시에 달성하는 종단 간(End-to-End) 혼잡 제어 메커니즘입니다 (SIGCOMM 2015).

```
 [송신측 NIC (NP)] ──► [스위치 (CP)] ──► [수신측 NIC (RP)]
        ▲               (ECN 마킹)               │
        │                                        │
        └───────── CNP 패킷 반환 (IP/UDP) ────────┘
```

### 6.1. 3개 엔티티 간의 협업 프로토콜
1. **혼잡 감지점 (CP, Congestion Point: 스위치)**:
   - 스위치 큐 깊이를 모니터링하여 WRED/RED 방식으로 IP 헤더의 ECN 필드에 **CE (Congestion Experienced, 11b)** 비트를 마킹합니다.
   - 마킹 임계치: $k_{min} \le Q < k_{max}$ 구간에서 확률적으로 마킹하며, $Q \ge k_{max}$이면 $100\%$ 마킹합니다.
   - **핵심**: $k_{max}$는 PFC의 `pfc_pause_thresh_kb`보다 훨씬 낮게 설정됩니다 ($k_{max} \ll pfc\_pause\_thresh$).
2. **반응점 (RP, Reaction Point: 수신측 NIC)**:
   - CE 비트가 마킹된 패킷을 수신한 목적지 NIC는 송신측으로 특별한 관리 패킷인 **CNP (Congestion Notification Packet, DSCP 48)**를 생성하여 보냅니다.
   - 플러딩을 방지하기 위해 CNP는 최소 `cnp_interval_us`(보통 50$\mu s$) 간격으로 최대 1개만 전송됩니다.
3. **알림점 (NP, Notification Point: 송신측 NIC)**:
   - CNP를 수신한 송신측 NIC의 레이트 리미터(Rate Limiter)는 현재 송신율을 곱셈적으로 삭감합니다:
     $$R_{current} \leftarrow \max(R_{min}, R_{current} \times (1 - \alpha / 2))$$
     $$\alpha \leftarrow (1 - g) \times \alpha + g \quad (g = 0.25)$$
   - CNP가 오지 않는 평화로운 구간에서는 타이머와 바이트 카운터에 의해 덧셈적/쌍곡선적 증가(Additive/Hyperbolic Increase)로 회선 대역폭을 다시 탐색합니다.

### 6.2. "Zero-PFC" 무손실 네트워크의 완성
DCQCN이 올바르게 튜닝되면, 스위치 큐 깊이는 항상 $k_{min} \sim k_{max}$ 사이에서 진동하며 결코 `pfc_pause_thresh_kb`에 도달하지 않습니다.
- **PFC PAUSE 프레임 발생 수 = 0**
- **패킷 손실률 = 0%**
- **PFC 데드락 발생 확률 = 0%**
- **회선 이용률 > 80%~90% 유지**

이것이 현대 초거대 AI GPU 데이터센터가 DCQCN(또는 차세대 수신자 주도 프로토콜인 HPCC, Swift)을 필수적으로 구성하는 이유입니다.
