# #255 [초당 1000만 패킷(10 Mpps)을 처리하는데 왜 패킷이 드롭되고 복사 모드로 떨어져요?!: 리눅스 고성능 네트워킹 AF_XDP(XSK) UMEM 링 버퍼 고갈(Starvation)과 XDP_ZEROCOPY 드라이버 바인딩 vs XDP_COPY 폴백 오버헤드 (Linux High-Performance Networking: AF_XDP (XSK) Zero-Copy Packet Processing, UMEM Fill/Rx Ring Starvation & Driver ZEROCOPY vs COPY Fallback)]

## 1. 장애 및 실무 시나리오

어느 글로벌 클라우드 핀테크 인프라 팀은 100GbE NIC 환경에서 실시간 외환/선물 거래 주문 패킷을 초당 1,000만 건(10 Mpps) 이상 나노초 단위로 필터링하고 라우팅하는 초저지연 L4 프록시 게이트웨이를 운영하고 있습니다.

과거에는 커널을 완전히 우회(Kernel Bypass)하는 **DPDK (Data Plane Development Kit)**를 사용했으나, 전용 드라이버(`vfio-pci`) 할당으로 인해 표준 리눅스 도구(`ethtool`, `tcpdump`, `iptables`, `ip route`)를 전혀 쓸 수 없고 유지보수가 극도로 어렵다는 치명적인 운영 단점이 있었습니다.

이에 엔지니어링 팀은 리눅스 커널 4.18부터 도입되고 5.4+에서 성숙된 **AF_XDP (XSK, XDP Sockets)**를 도입하기로 결정했습니다. AF_XDP는 표준 리눅스 NIC 드라이버와 eBPF 서브시스템을 그대로 사용하면서, eBPF XDP 훅에서 `bpf_redirect_map()`을 통해 유저스페이스가 등록한 연속 메모리 버퍼인 **UMEM(User Memory)**으로 패킷을 직접 DMA 전송하는 획기적인 기술입니다.

```
[전통적인 Linux 네트워크 스택]
  NIC RX -> DMA -> sk_buff 할당 -> Hard IRQ -> NAPI SoftIRQ
  -> netif_receive_skb -> Netfilter(iptables) -> TCP/IP 스택 -> 소켓 버퍼 -> 유저 memcpy(recv)
  (결과: 패킷당 수백 나노초 소요, 코어당 처리량 1~2 Mpps 한계)

[AF_XDP (XSK) Zero-Copy 고성능 스택]
  NIC RX -> DMA -> [UMEM Chunk (유저 등록 메모리)] -> eBPF XDP (bpf_redirect_map)
  -> XSK Rx Ring 알림 -> 유저스페이스 제로카피 직접 포인터 접근!
  (결과: sk_buff 할당 0건, 커널 메모리 복사 0건, 코어당 10M~20M+ Mpps 달성!)
```

그러나 프로덕션 트래픽이 폭증하는 선물 만기일 거래 시간에 시스템에 치명적인 장애가 발생했습니다:
1. **Fill Ring Starvation (버퍼 링 고갈)**:
   - 트래픽 버스트가 밀려오는 순간, NIC 하드웨어 레벨에서 `rx_dropped` 카운터가 수십만 건 치솟으며 고객사 주문 패킷이 30% 이상 유실되었습니다.
   - 분석 결과, 유저스페이스 프로세스가 Rx 링에서 패킷을 읽어 처리한 뒤 빈 UMEM 청크를 드라이버에 반환하는 **Fill Ring 보충(Replenishment)**을 너무 게으르게(Fill Ring이 거의 텅 빌 때까지 대기하거나 너무 작은 배치로) 수행하여, NIC DMA 컨트롤러가 패킷을 쓸 청크 주소를 찾지 못해 하드웨어 링에서 즉각 패킷을 폐기(Starvation Drop)한 것으로 밝혀졌습니다.
2. **Rx Ring Overflow (유저스페이스 배압 지연)**:
   - 복잡한 보안 룰 검사로 유저스페이스의 소비 속도가 저하되자, 커널이 채워 넣는 Rx 링이 가득 차서 신규 패킷이 드롭되는 배압(Backpressure) 현상이 발생했습니다.
3. **XDP_COPY 폴백 저하**:
   - 가상화 노드(`virtio_net`)나 제로카피를 미지원하는 드라이버에서 소켓을 생성할 때 `XDP_ZEROCOPY` 플래그 바인딩이 실패하거나 `XDP_COPY` 모드로 폴백되어, 패킷당 커널 `memcpy`가 발생하여 CPU가 100% 포화되고 처리량이 1/5로 곤두박질쳤습니다.
4. **점보 프레임 MTU 청크 불일치**:
   - UMEM 청크 크기(2048바이트)에서 헤드룸(256바이트)을 제외한 최대 가용 크기(1792바이트)를 초과하는 9000바이트 점보 프레임이 인입되자 패킷이 즉시 드롭되었습니다.

당신은 인프라 네트워킹 수석 엔지니어로서, AF_XDP 소켓 바인딩, UMEM 4개 링(Fill, Rx, Tx, Completion)의 상호작용, 제로카피 vs 카피 모드, 패킷 수신/송신 및 보충 워터마크 알고리즘을 완벽히 모델링하고 시스템 장애를 진단하는 시뮬레이터를 작성해야 합니다.

---

## 2. AF_XDP 4개 링 버퍼 상호작용 아키텍처

```
  +========================================================================+
  |                   유저스페이스 (Userspace Application)                  |
  +========================================================================+
         |                                                    ^
         | 1. 빈 Chunk 주소 푸시                                 | 3. 패킷 도착 알림 소비
         v (Producer)                                         | (Consumer)
  +------------------+                                 +-------------------+
  |    Fill Ring     |                                 |      Rx Ring      |
  | (Driver 가 DMA할  |                                 | (수신된 패킷 디스크립터|
  |  버퍼 주소 제공)  |                                 |  주소/길이 정보)   |
  +------------------+                                 +-------------------+
         |                                                    ^
         | (Consumer)                                         | (Producer)
         v                                                    |
  +========================================================================+
  |              커널 드라이버 & NIC 하드웨어 (Kernel / NIC DMA)             |
  +========================================================================+
         |                                                    ^
         | 4. 패킷 송신 디스크립터 등록                            | 6. 송신 완료 Chunk 반환
         v (Producer)                                         | (Consumer)
  +------------------+                                 +-------------------+
  |     Tx Ring      |                                 |  Completion Ring  |
  | (송신할 패킷 주소  |                                 | (NIC이 전송 완료한  |
  |  및 길이 정보)    |                                 |  Chunk 주소 회수)  |
  +------------------+                                 +-------------------+
         |                                                    ^
         | (Consumer)                                         | (Producer)
         v                                                    |
  +========================================================================+
  |                 유저 등록 메모리 풀: UMEM (Contiguous Chunks)            |
  +========================================================================+
```

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다:

```json
{
  "system_config": {
    "nic_driver": "mlx5_core",
    "driver_zerocopy_supported": true,
    "umem_total_chunks": 4096,
    "chunk_size_bytes": 2048,
    "headroom_bytes": 256,
    "fill_ring_size": 1024,
    "rx_ring_size": 1024,
    "tx_ring_size": 1024,
    "completion_ring_size": 1024,
    "bind_flags": ["XDP_ZEROCOPY"],
    "initial_fill_chunks": 1024,
    "replenish_batch_size": 128,
    "replenish_watermark": 256
  },
  "simulation_steps": [
    {
      "step_id": 1,
      "incoming_rx_packets": [
        {"packet_id": "pkt-1", "size_bytes": 64},
        {"packet_id": "pkt-2", "size_bytes": 1500}
      ],
      "userspace_rx_budget": 10,
      "outgoing_tx_packets": [
        {"packet_id": "tx-1", "size_bytes": 64}
      ],
      "driver_tx_completion_budget": 5
    }
  ]
}
```

### 파라미터 제약조건:
- `nic_driver`: NIC 드라이버 이름 문자열 (예: `"mlx5_core"`, `"i40e"`, `"ice"`, `"virtio_net"`, `"e1000e"`).
- `driver_zerocopy_supported`: 드라이버의 하드웨어 제로카피(`XDP_ZEROCOPY`) 지원 여부 (boolean).
- `umem_total_chunks`: UMEM 총 청크 개수 ($1024 \le N \le 65536$).
- `chunk_size_bytes`: 청크당 바이트 크기 ($2048$ 또는 $4096$).
- `headroom_bytes`: XDP 패킷 헤드룸 바이트 ($0 \le H \le 512$, 기본 $256$).
  - 최대 단일 패킷 페이로드 용량 = `chunk_size_bytes - headroom_bytes`.
- `fill_ring_size`, `rx_ring_size`, `tx_ring_size`, `completion_ring_size`: 각 링의 큐 슬롯 크기 ($256 \le \text{size} \le 4096$, 2의 거듭제곱).
- `bind_flags`: 소켓 바인딩 플래그 목록 (`"XDP_ZEROCOPY"`, `"XDP_COPY"`).
- `initial_fill_chunks`: 초기 기동 시 Fill Ring에 투입할 청크 개수.
- `replenish_batch_size`: Fill Ring 보충 시 1회 최대 투입 청크 개수.
- `replenish_watermark`: Fill Ring 내 잔여 청크가 이 값 이하로 떨어지면 보충 트리거.
- `simulation_steps`: 시뮬레이션 단계 리스트 ($1 \le \text{len} \le 100$).

---

## 4. 시뮬레이션 규칙 및 상태 전이 (State Machine)

### 1단계: 소켓 바인딩 및 동작 모드 판정
- `bind_flags`에 `"XDP_ZEROCOPY"`가 포함되어 있을 때:
  - `driver_zerocopy_supported == True`이면 동작 모드는 `"ZEROCOPY"`.
  - `driver_zerocopy_supported == False`인 경우:
    - 만약 `bind_flags`에 `"XDP_COPY"`도 허용되어 있지 않다면 즉시 바인딩 실패 (`status: "BIND_FAILURE_DRIVER_INCOMPATIBLE"`, `mode: "NONE"`).
    - 만약 `"XDP_COPY"`가 허용되어 있다면 `"COPY"` 모드로 폴백.
- `bind_flags`에 `"XDP_COPY"`만 지정된 경우 동작 모드는 `"COPY"`.
- 바인딩 플래그가 비어있을 경우 드라이버 제로카피 지원 시 `"ZEROCOPY"`, 미지원 시 `"COPY"`.

### 2단계: UMEM 및 링 초기화
- 총 `umem_total_chunks` 개의 청크 풀 생성 ($[0, 1, \dots, N-1]$).
- 초기 Fill Ring에 `min(initial_fill_chunks, fill_ring_size, len(free_chunks))` 개의 청크를 할당하여 적재.

### 3단계: 각 Step별 5단계 파이프라인 순차 실행
각 Step은 다음 5단계를 엄밀한 순서대로 실행합니다:

1. **Phase A: Driver Tx 완료 처리 (Completion)**:
   - Tx 링에 대기 중인 패킷 중 최대 `driver_tx_completion_budget` 개를 완료 처리.
   - 완료된 청크 주소는 Completion 링에 인큐(슬롯 여유 부족 시 프리 풀로 직접 반환).
   - 유저스페이스는 Completion 링의 모든 청크를 즉시 회수하여 UMEM 프리 풀(`free_chunks`)로 반환.
2. **Phase B: Driver Rx 패킷 인입 (NIC DMA 수신)**:
   - `incoming_rx_packets`의 각 패킷에 대해:
     - 패킷 크기가 최대 페이로드 용량(`chunk_size - headroom`)을 초과하면 즉시 드롭 (`mtu_exceeded_drops += 1`).
     - Fill 링에 사용 가능한 청크가 없으면 즉시 드롭 (`fill_ring_starvation_drops += 1`).
     - Rx 링이 가득 찼으면(`len(rx_ring) >= rx_ring_size`) 드롭 (`rx_ring_overflow_drops += 1`, Fill 링 청크는 소비되지 않음).
     - 위 검사를 모두 통과하면 Fill 링에서 청크 1개를 꺼내 Rx 링에 `(packet_id, size_bytes, chunk_addr)` 인큐.
     - `mode == "COPY"`인 경우 `total_copy_bytes += size_bytes`.
   - 패킷 인입 완료 직후 `min_fill_ring_occupancy`와 `max_rx_ring_occupancy`를 갱신.
3. **Phase C: Userspace Rx 패킷 소비**:
   - Rx 링에서 최대 `userspace_rx_budget` 개의 패킷을 디큐.
   - 소비된 청크는 유저스페이스 작업 완료 후 UMEM 프리 풀(`free_chunks`)로 반환.
   - `total_rx_processed` 누적.
4. **Phase D: Userspace Tx 패킷 큐잉**:
   - `outgoing_tx_packets`의 각 패킷에 대해:
     - 패킷 크기가 청크 용량을 초과하면 무시.
     - 프리 풀에 잔여 청크가 없으면 버퍼 고갈 드롭 (`tx_no_buffer_drops += 1`).
     - Tx 링이 가득 찼으면 오버플로우 드롭 (`tx_ring_overflow_drops += 1`).
     - 통과 시 프리 풀에서 청크를 꺼내 Tx 링에 인큐. `mode == "COPY"`이면 `total_copy_bytes += size_bytes`.
5. **Phase E: Userspace Fill Ring 보충 (Replenishment)**:
   - Fill 링의 잔여 청크 수가 `replenish_watermark` 이하이고 프리 풀에 청크가 존재할 때:
     - 투입 청크 수 = `min(replenish_batch_size, fill_ring_size - len(fill_ring), len(free_chunks))`.
     - 프리 풀에서 꺼내 Fill 링에 인큐.
   - Fill 링 잔여량에 대해 `min_fill_ring_occupancy` 재갱신.

### 4단계: 최종 상태 판정 (Status Determination Hierarchy)
시뮬레이션 종료 후 다음 우선순위에 따라 최종 `status`를 결정합니다:
1. 소켓 바인딩 실패 시: `"BIND_FAILURE_DRIVER_INCOMPATIBLE"`
2. MTU 초과 드롭 발생 시: `"MTU_CHUNK_MISMATCH_TRUNCATION"`
3. Fill 링 고갈 드롭 발생 시: `"FILL_RING_STARVATION_COLLAPSE"`
4. Rx 링 오버플로우 발생 시: `"RX_RING_OVERFLOW_BACKPRESSURE"`
5. 정상 처리되었으나 COPY 모드로 동작한 경우: `"UNSUPPORTED_COPY_MODE_DEGRADED"`
6. 드롭 없이 ZEROCOPY 모드로 완벽히 완주한 경우: `"HEALTHY_ZEROCOPY_LINE_RATE"`

---

## 5. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "status": "HEALTHY_ZEROCOPY_LINE_RATE",
  "mode": "ZEROCOPY",
  "metrics": {
    "total_rx_ingress": 800,
    "rx_received": 800,
    "total_rx_processed": 800,
    "fill_ring_starvation_drops": 0,
    "rx_ring_overflow_drops": 0,
    "mtu_exceeded_drops": 0,
    "tx_queued": 0,
    "tx_completed": 0,
    "tx_ring_overflow_drops": 0,
    "tx_no_buffer_drops": 0,
    "total_copy_bytes": 0,
    "min_fill_ring_occupancy": 224,
    "max_rx_ring_occupancy": 400
  },
  "diagnostics": [
    "AF_XDP operating at healthy line rate with zero-copy DMA. No packet drops or ring starvation detected."
  ],
  "recommended_tuning": {
    "suggestion": "Optimal configuration maintained."
  }
}
```

---

## 6. 입출력 예시 (Example 1)

### 예시 입력:
```json
{
  "system_config": {
    "nic_driver": "i40e",
    "driver_zerocopy_supported": true,
    "umem_total_chunks": 2048,
    "chunk_size_bytes": 2048,
    "headroom_bytes": 256,
    "fill_ring_size": 512,
    "rx_ring_size": 1024,
    "tx_ring_size": 512,
    "completion_ring_size": 512,
    "bind_flags": ["XDP_ZEROCOPY"],
    "initial_fill_chunks": 512,
    "replenish_batch_size": 64,
    "replenish_watermark": 128
  },
  "simulation_steps": [
    {
      "step_id": 1,
      "incoming_rx_packets": [
        {"packet_id": "pkt-0", "size_bytes": 64}
      ],
      "userspace_rx_budget": 200,
      "outgoing_tx_packets": [],
      "driver_tx_completion_budget": 0
    }
  ]
}
```
*(위 입력에서 incoming_rx_packets가 1200개 인입되는 경우)*

### 예시 출력:
```json
{
  "status": "FILL_RING_STARVATION_COLLAPSE",
  "mode": "ZEROCOPY",
  "metrics": {
    "total_rx_ingress": 1200,
    "rx_received": 512,
    "total_rx_processed": 200,
    "fill_ring_starvation_drops": 688,
    "rx_ring_overflow_drops": 0,
    "mtu_exceeded_drops": 0,
    "tx_queued": 0,
    "tx_completed": 0,
    "tx_ring_overflow_drops": 0,
    "tx_no_buffer_drops": 0,
    "total_copy_bytes": 0,
    "min_fill_ring_occupancy": 0,
    "max_rx_ring_occupancy": 512
  },
  "diagnostics": [
    "688 packets dropped due to Fill Ring starvation (NIC driver ran out of receive chunks)."
  ],
  "recommended_tuning": {
    "replenish_watermark": 256,
    "replenish_batch_size": 256,
    "suggestion": "Raise replenish_watermark and increase replenish_batch_size to eagerly replenish Fill Ring before burst arrival."
  }
}
```
