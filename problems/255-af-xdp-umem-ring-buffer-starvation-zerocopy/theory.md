# 핵심 CS 및 리눅스 커널 이론: AF_XDP (XSK) 고성능 제로카피 네트워킹과 UMEM 링 버퍼 아키텍처

---

## 1. 리눅스 커널 네트워크 스택의 병목과 커널 바이패스의 역사

### 1.1 전통적 `sk_buff` 기반 스택의 나노초(ns) 비용 한계
전통적인 리눅스 커널 네트워크 서브시스템은 범용성과 유연성을 극대화하도록 설계되었습니다. 패킷이 100GbE NIC에 도착하여 유저스페이스 `recv()` 소켓 버퍼로 전달되기까지 다음과 같은 무거운 오버헤드가 발생합니다:

1. **`sk_buff` 메모리 할당 및 초기화**:
   - 패킷당 약 200바이트 이상의 메타데이터 구조체(`struct sk_buff`)를 `kmem_cache`에서 슬랩 할당(`kmem_cache_alloc`).
   - L2/L3/L4 헤더 포인터, 타임스탬프, 체크섬 상태, Netfilter 메타데이터 초기화.
2. **소프트웨어 인터럽트(NAPI SoftIRQ) 컨텍스트 스위칭**:
   - 하드웨어 IRQ $\rightarrow$ NAPI 폴링 루틴 스케줄링 $\rightarrow$ CPU 코어 간 인터럽트 밸런싱 오버헤드.
3. **Netfilter / conntrack / 라우팅 룩업**:
   - `iptables`, `nftables`, conntrack 연결 추적 해시 테이블 조회, FIB(Forwarding Information Base) 트리 탐색.
4. **유저스페이스 메모리 복사 (`copy_to_user`)**:
   - 커널 소켓 수신 버퍼에서 유저 프로세스 버퍼로의 캐시 라인 플러시 및 데이터 복사.

> **100GbE 회선 속도(Line Rate)의 시간적 예산(Time Budget)**:
> 64바이트 이더넷 프레임(Preamble 8B + IFG 12B 포함 총 84바이트 = 672비트) 기준:
> $$\text{PPS} = \frac{100 \times 10^9 \text{ bps}}{672 \text{ bits}} \approx 148,809,523 \text{ pkts/sec (148.8 Mpps)}$$
> 즉, **패킷 1개당 처리 허용 시간은 단 6.72 나노초(ns)**에 불과합니다.
> 현대 3.0GHz CPU에서 6.72ns는 **약 20개의 CPU 사이클**에 불과하며, 한 번의 L3 캐시 미스(약 40~60ns)나 메모리 복사(memcpy)만으로도 회선 속도 유지가 물리적으로 불가능해집니다.

---

### 1.2 DPDK vs AF_XDP (XSK) 비교

| 비교 항목 | DPDK (Data Plane Development Kit) | AF_XDP (Address Family XDP / XSK) |
|---|---|---|
| **동작 계층** | 완전한 커널 바이패스 (UIO / VFIO-PCI) | 리눅스 커널 eBPF XDP 서브시스템 기반 |
| **NIC 소유권** | 유저 프로세스가 NIC 하드웨어를 독점 | 리눅스 커널 드라이버가 NIC 소유 유지 |
| **표준 도구 호환성** | `ethtool`, `tcpdump`, `ip route` 사용 불가 | 표준 리눅스 도구, 모니터링 및 IP 스택과 공존 |
| **프로그래밍 모델** | 독자적인 C 라이브러리 및 PMD 드라이버 | eBPF XDP 맵(`BPF_MAP_TYPE_XSKMAP`) + 표준 POSIX 소켓 |
| **보안 및 격리** | 유저 프로세스 충돌 시 NIC 리셋 필요 | 커널이 UMEM 가상 메모리 매핑 및 접근 권한 보호 |
| **성능 (Mpps/core)**| ~20 - 30 Mpps | ~15 - 25 Mpps (XDP_ZEROCOPY 기준) |

---

## 2. AF_XDP UMEM 아키텍처와 4대 락리스(Lockless) SPSC 링

AF_XDP의 핵심은 유저스페이스가 미리 할당한 물리 연속 메모리 풀인 **UMEM(User Memory)**과, 커널-유저 간 뮤텍스나 락 없이 원자적 메모리 배리어만으로 통신하는 **단일 생산자 단일 소비자(Single-Producer Single-Consumer, SPSC) 링 버퍼** 4개입니다.

```
       [ UMEM : 등록된 거대 연속 메모리 블록 (예: 4096 Chunks x 2048 Bytes) ]
       +---------+---------+---------+---------+---------+---------+
       | Chunk 0 | Chunk 1 | Chunk 2 | Chunk 3 | Chunk 4 | ...     |
       +---------+---------+---------+---------+---------+---------+
            ^                                       |
            | DMA Address 매핑                       | DMA Address 매핑
            v                                       v
    [ Fill Ring ] -> (드라이버가 청크 확보) -> [ Rx Ring ] -> (유저가 패킷 소비)
    (User Prod / Kernel Cons)             (Kernel Prod / User Cons)

    [ Tx Ring ]   -> (드라이버가 패킷 전송) -> [ Completion Ring ] -> (유저가 청크 회수)
    (User Prod / Kernel Cons)             (Kernel Prod / User Cons)
```

### 2.1 4개 링의 역할과 동작 규약

1. **Fill Ring (생산자: 유저스페이스, 소비자: 커널/NIC 드라이버)**:
   - 유저스페이스가 NIC 드라이버에게 "패킷이 들어오면 UMEM의 이 청크 주소들에 DMA로 써라"고 빈 청크들의 주소를 제공하는 링입니다.
   - 드라이버는 패킷 수신 시 Fill Ring에서 주소를 꺼내 NIC RX 디스크립터에 등록합니다.
2. **Rx Ring (생산자: 커널/NIC 드라이버, 소비자: 유저스페이스)**:
   - NIC이 패킷을 UMEM 청크에 DMA 완료하면, 드라이버가 패킷의 청크 주소, 오프셋, 바이트 길이를 Rx Ring에 등록합니다.
   - 유저스페이스는 Rx Ring에서 이를 읽어 제로카피로 패킷 데이터를 직접 파싱합니다.
3. **Tx Ring (생산자: 유저스페이스, 소비자: 커널/NIC 드라이버)**:
   - 유저스페이스가 송신할 패킷의 UMEM 청크 주소와 길이를 등록하는 링입니다.
   - 드라이버는 이를 읽어 NIC TX 디스크립터에 큐잉하고 패킷을 방출합니다.
4. **Completion Ring (생산자: 커널/NIC 드라이버, 소비자: 유저스페이스)**:
   - NIC이 패킷 송신 DMA를 마치면 드라이버가 해당 청크 주소를 Completion Ring에 넣어 유저스페이스에게 메모리 재사용이 가능함을 알립니다.

---

## 3. 실무 장애 메커니즘과 트러블슈팅

### 3.1 Fill Ring Starvation (링 버퍼 고갈로 인한 하드웨어 드롭)
- **원인**:
  - 유저스페이스 폴링 루프가 Rx Ring에서 패킷을 처리하고 청크를 해제한 뒤, Fill Ring으로 되돌려주는 배치(Batch) 작업 주기가 너무 길거나 임계치(`replenish_watermark`)가 너무 낮을 때 발생합니다.
  - 마이크로버스트(Microburst) 트래픽이 인입될 때 Fill Ring에 사용 가능한 청크가 0이 되면, NIC 드라이버는 패킷을 저장할 UMEM 메모리가 없어 NIC 하드웨어 FIFO 버퍼에서 패킷을 즉시 드롭(`rx_dropped`)합니다.
- **방어 기법**:
  - `replenish_watermark`를 링 크기의 50% 이상으로 설정하여, 버스트 인입 전에 사전 보충(Eager Replenishment)을 수행합니다.
  - 리눅스 `libbpf` / `libxdp`의 `xsk_ring_prod__reserve()` 함수를 적극 호출하여 가용 슬롯이 생기는 즉시 보충합니다.

### 3.2 XDP_ZEROCOPY vs XDP_COPY 모드
- **Zero-Copy (`XDP_ZEROCOPY`)**:
  - NIC 드라이버가 UMEM의 물리 주소를 직접 하드웨어 RX/TX 디스크립터에 매핑합니다.
  - CPU 개입이 전혀 없이 패킷이 유저 메모리로 직행합니다.
  - Mellanox ConnectX (`mlx5`), Intel 40GbE/100GbE (`i40e`, `ice`), Intel 10GbE (`ixgbe`) 등 엔터프라이즈 NIC에서 지원됩니다.
- **Copy (`XDP_COPY`)**:
  - 가상 머신 가상 드라이버(`virtio_net`)나 구형 NIC(`e1000e`) 등 제로카피 미지원 환경에서 발생합니다.
  - 드라이버가 일반 SKB 버퍼로 패킷을 수신한 뒤, 커널이 UMEM 청크로 바이트 복사(`memcpy`)를 수행합니다.
  - 메모리 버스 대역폭 포화와 L3 캐시 오염으로 인해 레이턴시가 폭증합니다.

### 3.3 점보 프레임 MTU와 청크 헤드룸 정렬
- 기본 AF_XDP 청크 크기는 2048B 또는 4096B입니다.
- XDP 프로그램이 패킷 메타데이터나 커널 헤더를 조작할 수 있도록 통상 256바이트의 `XDP_PACKET_HEADROOM`이 차감됩니다.
- 단일 버퍼 AF_XDP 모드에서는 $\text{Packet Size} > \text{Chunk Size} - \text{Headroom}$인 경우 패킷을 수용할 수 없어 드롭됩니다.
- 9000바이트 점보 프레임을 처리하려면 4096B 청크를 사용하거나 Linux 6.x 이상의 Multi-Buffer AF_XDP(MB-XSK) 기능이 필수적입니다.
