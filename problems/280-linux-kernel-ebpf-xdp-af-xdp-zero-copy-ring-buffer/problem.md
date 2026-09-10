# 문제 #280: 커널 네트워크 스택의 100배 가속 마법, 패킷이 커널 버퍼를 스킵한다고?!: Linux Kernel eBPF XDP & AF_XDP 무복사(Zero-Copy) UMEM 4대 링버퍼(Fill/Rx/Tx/Completion) 상태 머신 엔진

## 1. 개요 (Story & Context)
현대 데이터센터의 네트워크 대역폭은 10GbE, 40GbE를 넘어 100GbE, 400GbE 시대로 진입했습니다. 100GbE 회선에서 최소 크기의 이더넷 패킷(64바이트)이 유입될 때, 초당 처리해야 하는 패킷 수(PPS, Packets Per Second)는 자그마치 **1억 4,880만 PPS(148.8 Mpps)**에 달합니다. 즉, 패킷 1개당 허용된 CPU 처리 시간은 단 **6.72 나노초(ns)**에 불과합니다.

그러나 전통적인 리눅스 커널 네트워크 스택(`AF_INET` 소켓, `sk_buff`)의 데이터 패스는 다음과 같은 치명적인 병목을 안고 있습니다:
1. **`sk_buff` 동적 메모리 할당 및 해제**: 패킷마다 커널 슬랩(`kmem_cache`)에서 수백 바이트 크기의 메타데이터 구조체를 할당하고 해제하는 데만 수십~수백 ns가 소요됩니다.
2. **소프트웨어 인터럽트(SoftIRQ) 및 컨텍스트 스위칭**: 하드웨어 인터럽트(`ksoftirqd/NET_RX_SOFTIRQ`)와 소켓 큐 동기화로 인한 CPU 캐시 오염(Cache Miss).
3. **사용자 공간 데이터 복사 (`copy_to_user`)**: 커널 메모리 버퍼에서 유저 공간 메모리 버퍼로 페이로드를 복사하면서 메모리 버스 대역폭을 고갈시킵니다.

이 병목을 해결하기 위해 과거에는 커널을 완전히 바이패스하는 DPDK(Data Plane Development Kit)를 사용했으나, DPDK는 리눅스 커널의 강력한 보안 정책, `iptables`/`nftables`, 컨테이너 네트워크 네임스페이스, `tcpdump`, `ethtool` 등의 표준 생태계를 전부 포기해야 했으며 전용 코어를 100% 폴링(Polling) 상태로 태워야 하는 단점이 있었습니다.

리눅스 커널 4.18부터 도입된 **eBPF XDP(eXpress Data Path)**와 **AF_XDP(XSK - XDP Sockets)**는 이 문제를 완벽하게 해결했습니다!
- **eBPF XDP**: NIC 드라이버의 최하단(Driver Level)에서 `sk_buff`가 할당되기도 전에 패킷을 가로채어 eBPF 바이트코드로 나노초 단위로 필터링/포워딩합니다 (`XDP_DROP`, `XDP_PASS`, `XDP_TX`, `XDP_REDIRECT`).
- **AF_XDP Zero-Copy UMEM**: `bpf_redirect_map()`을 통해 특정 패킷을 유저 공간과 커널이 공유하는 고정 청크(Chunk) 메모리 풀인 **UMEM**으로 직결합니다. 이때 패킷 데이터는 NIC 하드웨어 DMA를 통해 유저 메모리로 직접 전달되며(Zero-Copy), 커널 복사가 0회 발생합니다.

UMEM의 초고속 무복사 데이터 교환은 락(Lock)이 전혀 없는 4개의 단일 생산자-단일 소비자(SPSC) 원형 링 버퍼(Circular Ring Buffer)로 구동됩니다:
1. **Fill Ring (Rx 생산자: 유저, 소비자: 커널/NIC 드라이버)**: 유저 공간이 비어있는 UMEM 청크 주소(`chunk_addr`)를 커널에 미리 등록하여, NIC가 수신 패킷을 쓸 수 있도록 장전해 둡니다.
2. **Rx Ring (Rx 생산자: 커널/NIC 드라이버, 소비자: 유저)**: 패킷이 도착하여 UMEM 청크에 DMA 기록되면, 커널이 패킷 디스크립터(`chunk_addr`, `len`, `packet_id`)를 이 링에 넣어 유저 공간이 읽을 수 있게 통지합니다.
3. **Tx Ring (Tx 생산자: 유저, 소비자: 커널/NIC 드라이버)**: 유저 공간이 전송할 패킷의 UMEM 청크 주소 및 길이를 등록하여 NIC 전송을 요청합니다.
4. **Completion Ring (Tx 생산자: 커널/NIC 드라이버, 소비자: 유저)**: NIC가 하드웨어 전송을 완료하면 해당 청크 주소를 등록하여, 유저 공간이 안전하게 해당 UMEM 청크를 재사용(Reclaim)할 수 있도록 반환합니다.

여러분은 고성능 네트워크 가속 엔진의 코어 시스템 엔지니어로서, eBPF XDP 필터링 규칙과 AF_XDP UMEM 4대 링버퍼의 수명 주기 및 제약 조건을 모의하는 **Linux Kernel eBPF XDP & AF_XDP Zero-Copy 상태 머신 엔진**을 완벽히 구현해야 합니다!

---

## 2. 상태 머신 및 연산 규칙

### 2.1 eBPF XDP 드라이버 액션 규칙
수신된 패킷은 등록된 BPF 규칙 리스트(`bpf_rules`)를 순서대로 평가합니다:
1. `match`의 모든 키-값 쌍(예: `proto`, `dst_port`)이 패킷과 일치하면 해당 규칙의 `action`을 즉시 채택하고 탐색을 종료합니다.
2. 일치하는 규칙이 없으면 기본 액션(`default_action`)을 적용합니다.

액션의 종류 및 상태 전이:
- `XDP_DROP`: 패킷을 즉시 폐기합니다.
  - `status: "DROPPED"`
  - `xdp_drop` 카운터 $+1$.
- `XDP_PASS`: 패킷을 리눅스 전통 커널 스택(`sk_buff`)으로 전달합니다.
  - `status: "PASSED_TO_KERNEL_SKB"`
  - `xdp_pass` 카운터 $+1$.
- `XDP_TX`: 패킷을 수신된 동일 인터페이스로 즉시 되돌려 전송(Hairpin Bounce)합니다.
  - `status: "HAIRPIN_BOUNCE_TX"`
  - `xdp_tx` 카운터 $+1$.
- `XDP_REDIRECT`: 패킷을 AF_XDP 소켓의 UMEM으로 전달합니다:
  - **Fill Ring 고갈 검사**: `fill_ring`에 사용 가능한 빈 청크가 없는 경우 (`len(fill_ring) == 0`), 패킷을 폐기합니다 (`status: "DROPPED_FILL_RING_EMPTY"`). `fill_ring_empty_drops` 카운터 $+1$.
  - **Rx Ring 만류 검사**: `rx_ring`이 이미 가득 찬 경우 (`len(rx_ring) >= ring_size`), 패킷을 폐기합니다 (`status: "DROPPED_RX_RING_FULL"`). `rx_ring_full_drops` 카운터 $+1$.
  - **정상 전달**: `fill_ring`에서 청크 주소 하나를 `pop(0)`으로 꺼내어, 수신 디스크립터 `{"chunk_addr": addr, "packet_id": id, "len": len}`를 `rx_ring`에 추가합니다. `status: "ZERO_COPY_RX_DELIVERED"`, `xdp_redirect` 카운터 $+1$.

### 2.2 UMEM 링버퍼 연산 (`operations`)
시뮬레이션은 순서대로 입력된 연산(`op`)들을 순차 실행합니다:
1. `USER_FILL_RING_ENQUEUE`:
   - 유저 공간이 `chunk_addrs` 목록의 청크 주소들을 `fill_ring`에 삽입합니다.
   - 링의 최대 용량(`ring_size`)을 초과하지 않는 청크만 수락(`accepted`)되고, 초과분은 거절(`rejected`)됩니다.
2. `NIC_RECEIVE_PACKET`:
   - NIC 하드웨어로 패킷이 수신됩니다. 총 수신 카운터 `rx_total_packets` $+1$.
   - eBPF XDP 액션 규칙(2.1절)에 따라 패킷을 처리하고 로그를 기록합니다.
3. `USER_RX_RING_DEQUEUE`:
   - 유저 공간 애플리케이션이 `rx_ring`에서 최대 `batch_size`개의 디스크립터를 꺼내(`pop(0)`) 처리합니다.
4. `USER_TX_RING_ENQUEUE`:
   - 유저 공간이 전송할 패킷 디스크립터들(`tx_packets`)을 `tx_ring`에 등록합니다.
   - `ring_size` 한도 내에서 수락되며, 수락된 개수만큼 `tx_submitted` 카운터가 증가합니다.
5. `KERNEL_TX_COMPLETION`:
   - 커널/NIC 드라이버가 `tx_ring`에 대기 중인 패킷들을 하드웨어 DMA 전송 완료 처리합니다.
   - `completion_ring`의 용량(`ring_size`) 한도 내에서 `tx_ring`에서 `pop(0)`하여 패킷의 `chunk_addr`를 `completion_ring`에 기록합니다. `tx_completed` 카운터가 증가합니다.
6. `USER_COMPLETION_RING_DEQUEUE`:
   - 유저 공간이 `completion_ring`에서 최대 `batch_size`개의 청크 주소를 회수(`reclaimed`)하여 재사용 풀로 복귀시킵니다.

---

## 3. 입력 형식 (Input Specification)
표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "umem": {
    "chunk_size": 2048,
    "ring_size": 4
  },
  "xdp_program": {
    "default_action": "XDP_PASS",
    "bpf_rules": [
      {
        "match": {"proto": "TCP", "dst_port": 80},
        "action": "XDP_REDIRECT"
      },
      {
        "match": {"proto": "UDP", "dst_port": 53},
        "action": "XDP_DROP"
      }
    ]
  },
  "operations": [
    {
      "step": 1,
      "op": "USER_FILL_RING_ENQUEUE",
      "chunk_addrs": [0, 2048, 4096]
    },
    {
      "step": 2,
      "op": "NIC_RECEIVE_PACKET",
      "packet": {"id": "pkt1", "proto": "TCP", "dst_port": 80, "len": 128}
    },
    {
      "step": 3,
      "op": "USER_RX_RING_DEQUEUE",
      "batch_size": 1
    }
  ]
}
```

---

## 4. 출력 형식 (Output Specification)
표준 출력(stdout)으로 연산 진행 로그, 최종 링버퍼 상태, 집계 통계를 포함하는 JSON 객체를 한 줄로 출력합니다:
```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "USER_FILL_RING_ENQUEUE",
      "enqueued_count": 3,
      "enqueued_addrs": [0, 2048, 4096],
      "rejected_full_addrs": []
    },
    {
      "step": 2,
      "op": "NIC_RECEIVE_PACKET",
      "packet_id": "pkt1",
      "action": "XDP_REDIRECT",
      "status": "ZERO_COPY_RX_DELIVERED",
      "assigned_chunk_addr": 0
    },
    {
      "step": 3,
      "op": "USER_RX_RING_DEQUEUE",
      "dequeued_count": 1,
      "packets": [
        {
          "chunk_addr": 0,
          "packet_id": "pkt1",
          "len": 128
        }
      ]
    }
  ],
  "final_ring_states": {
    "fill_ring": [2048, 4096],
    "rx_ring": [],
    "tx_ring": [],
    "completion_ring": []
  },
  "statistics": {
    "rx_total_packets": 1,
    "xdp_drop": 0,
    "xdp_pass": 0,
    "xdp_tx": 0,
    "xdp_redirect": 1,
    "fill_ring_empty_drops": 0,
    "rx_ring_full_drops": 0,
    "tx_submitted": 0,
    "tx_completed": 0
  }
}
```
