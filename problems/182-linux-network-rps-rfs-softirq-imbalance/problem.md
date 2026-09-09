# Problem 182: Linux 네트워크 멀티코어 스케일링: Receive Side Scaling (RSS), Receive Packet Steering (RPS/RFS), softirq 불균형과 패킷 역순(Out-of-Order) 재앙

## 문제 설명

글로벌 결제 처리망 및 대규모 분산 API 게이트웨이를 운영하는 핀테크 플랫폼 팀은 100Gbps 고속 NIC(Network Interface Card)와 64코어 최신 NUMA 서버를 도입한 후 심각한 성능 저하와 간헐적 응답 불능(Tail Latency Spikes) 현상을 마주했습니다.

초당 수백만 패킷(Mpps)이 쏟아지는 피크 타임에 다음과 같은 현상이 관측되었습니다:
1. **Core 0의 `ksoftirqd/0` CPU 점유율 100% 포화 및 대규모 패킷 드랍**: NIC의 단일 RX 링 버퍼 하드웨어 인터럽트(IRQ)가 특정 CPU 코어(Core 0)로만 집중되어 다른 코어들은 한가로운 반면 Core 0의 링 버퍼 백로그가 가득 차 패킷이 폐기되는 참사가 발생했습니다.
2. **단순 라운드로빈(Round-Robin) 패킷 분산의 역습**: 패킷을 전 코어에 단순히 균등 분배(Round-Robin)하자, 동일한 TCP 연결(플로우)의 패킷들이 서로 다른 코어에서 비동기 처리되면서 네트워크 레이어에서 **대규모 패킷 역순(Out-of-Order Delivery)**이 발생했습니다. 이로 인해 수신측 TCP 스택이 중복 ACK(Duplicate ACK) 폭풍을 일으키고 빠른 재전송(Fast Retransmit)과 윈도우 축소(Congestion Window Collapse)로 네트워크 처리량이 곤두박질쳤습니다.
3. **L1/L2 CPU 캐시 미스 및 인터-코어 캐시 라인 무효화(Cache Invalidation)**: 패킷의 소프트 인터럽트(softirq)를 처리하는 코어와 해당 소켓의 데이터를 읽는 유저스페이스 애플리케이션 스레드(Application Core)가 서로 다른 코어에 배치되어, L1/L2 캐시 미스와 코어 간 버스 트래픽으로 인해 요청당 처리 지연시간이 5배 이상 급증했습니다.

인프라 아키텍처 팀은 리눅스 커널의 4대 패킷 수신 조향 메커니즘을 정밀하게 시뮬레이션하고, 소프트웨어 패킷 조향(RPS)과 소켓 가속(RFS)의 동작 원리를 검증할 수 있는 진단 엔진을 구축하고자 합니다.

---

## 핵심 패킷 조향 모드 (Steering Modes)

### 1. `SINGLE_CORE_IRQ` (단일 코어 인터럽트 고정)
- 하드웨어 RSS가 지원되지 않거나 `/proc/irq/N/smp_affinity`가 1로 설정된 최악의 구성입니다.
- **모든 인바운드 패킷이 Core 0으로만 강제 라우팅**됩니다.
- Core 0의 softirq 처리 큐가 틱당 한도(`core_softirq_capacity_packets`)를 초과하면 즉시 **패킷 드랍(NET_RX_DROP)**이 발생합니다.
- 평가 판정(Verdict): `CORE_ZERO_SOFTIRQ_SATURATION_COLLAPSE`

### 2. `NAIVE_ROUND_ROBIN_RPS` (나이브 라운드로빈 조향)
- 플로우를 고려하지 않고 패킷이 도착하는 순서대로 CPU 코어에 번갈아 분배합니다 (`target_core = rr_index % num_cores`).
- 코어 간 연산 지터(Jitter) 및 병렬 처리 순서 왜곡으로 인해 동일 플로우 내의 패킷이 **역순(Out-of-Order, `seq < last_seq`)**으로 TCP 스택에 전달됩니다.
- 평가 판정(Verdict): `TCP_OUT_OF_ORDER_RETRANSMIT_STORM`

### 3. `HASHED_RPS` (Receive Packet Steering - 4-Tuple 해시 기반)
- 패킷의 4-튜플(플로우 ID)의 MD5 해시값을 기반으로 코어를 결정합니다:
  $$\text{target\_core} = \text{MD5}(\text{flow\_id}) \pmod{\text{num\_cores}}$$
- 동일 플로우의 패킷은 **항상 동일한 단일 코어로 라우팅**되므로 패킷 역순(Out-of-Order)이 0건으로 완벽히 억제됩니다.
- 단, 유저 애플리케이션 스레드가 위치한 코어와 일치하지 않을 수 있어 캐시 미스가 발생할 수 있습니다.
- 평가 판정(Verdict): `HASHED_RPS_IN_ORDER_BALANCED`

### 4. `RFS_AFFINITY` (Receive Flow Steering - 애플리케이션 친화적 조향)
- 리눅스 커널의 RFS(`rps_sock_flow_table`) 원리를 적용하여, 해당 소켓을 실제로 폴링/수신하는 **유저스페이스 애플리케이션 스레드가 실행 중인 코어로 직접 패킷을 조향**합니다.
- 동일 플로우 무결성 보장(역순 0건)과 더불어, softirq 처리 코어와 애플리케이션 코어가 100% 일치하여 **L1/L2 CPU 캐시 적중(Cache Hit)**을 달성하고 최소 지연시간($10\,\mu\text{s}$)을 보장합니다.
- 평가 판정(Verdict): `RFS_ZERO_COPY_CACHE_LOCALITY_OPTIMAL`

---

## 하드웨어 및 성능 수식

### 1. 코어 용량 및 패킷 드랍
- 각 코어는 틱당 처리 가능한 최대 패킷 수(`core_softirq_capacity_packets`)를 가집니다.
- 큐 인덱스가 용량을 초과하는 패킷은 큐 오버플로우로 폐기됩니다 (`dropped_packets += 1`).

### 2. 패킷 지연시간 및 캐시 적중
- 수신 패킷을 처리한 코어(`c_id`)가 해당 플로우의 애플리케이션 코어(`app_core`)와 동일한 경우:
  - **L1/L2 Cache Hit**: 패킷 처리 지연시간 $10\,\mu\text{s}$
- 수신 패킷 처리 코어와 애플리케이션 코어가 다른 경우:
  - **Cache Miss (Cross-Core Cache Invalidation)**: 패킷 처리 지연시간 $50\,\mu\text{s}$

### 3. 피크 코어 불균형 비율 (Peak Core Imbalance Ratio)
$$\text{Peak Imbalance Ratio} = \frac{\max(\text{core\_packet\_counts})}{\text{평균 코어당 패킷 수}}$$

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "num_cpu_cores": 4,
    "steering_mode": "RFS_AFFINITY",
    "core_softirq_capacity_packets": 500,
    "app_flow_core_map": {
      "flow-1": 0,
      "flow-2": 1,
      "flow-3": 2,
      "flow-4": 3
    }
  },
  "workload": [
    {
      "tick": 1,
      "packets": [
        {"flow_id": "flow-1", "seq": 100},
        {"flow_id": "flow-2", "seq": 100}
      ]
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "num_cpu_cores": 4,
    "steering_mode": "RFS_AFFINITY",
    "core_softirq_capacity": 500,
    "total_packets": 100
  },
  "metrics": {
    "total_packets": 100,
    "processed_packets": 100,
    "dropped_packets": 0,
    "drop_rate": 0.0,
    "out_of_order_packets": 0,
    "cache_hits": 100,
    "cache_misses": 0,
    "cache_hit_rate": 1.0,
    "peak_core_imbalance_ratio": 1.0,
    "average_latency_us": 10.0,
    "core_packet_distribution": [25, 25, 25, 25],
    "verdict": "RFS_ZERO_COPY_CACHE_LOCALITY_OPTIMAL"
  },
  "sample_timeline": [
    {
      "tick": 1,
      "packets_count": 2,
      "core_loads": [1, 1, 0, 0],
      "processed": 2,
      "dropped": 0,
      "out_of_order": 0,
      "cache_hits": 2,
      "cache_misses": 0
    }
  ]
}
```

> **성공 기준**: `dropped_packets == 0`이고 `out_of_order_packets == 0`일 때 `status: "SUCCESS"`, 그렇지 않으면 `status: "FAILED"`.
