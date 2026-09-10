# 이론적 배경: Linux Kernel eBPF XDP 및 AF_XDP 무복사(Zero-Copy) 아키텍처와 락프리(Lock-Free) 링버퍼 동기화

## 1. 커널 네트워크 스택의 근본 한계와 폰 노이만 병목

### 1.1 100GbE 네트워크와 시간 예산(Time Budget)
이더넷 표준에서 최소 프레임 크기는 64바이트(Preamble 7B + SFD 1B + Inter-Packet Gap 12B 포함 총 84바이트 전송 시간 소요)입니다.
100GbE 회선의 비트율은 $100 \times 10^9$ bps이므로, 초당 최대 패킷 전송량은:
$$PPS_{\max} = \frac{100 \times 10^9 \text{ bps}}{84 \times 8 \text{ bits}} \approx 148,809,524 \text{ PPS} \approx 148.8 \text{ Mpps}$$

패킷 1개가 유입될 때 다음 패킷이 도착할 때까지의 시간 간격(Inter-Arrival Time)은:
$$\Delta t = \frac{1}{148.8 \times 10^6} \approx 6.72 \text{ ns}$$

CPU 클록 주파수가 3.0 GHz인 최신 서버 프로세서에서 1 사이클(Cycle)의 시간은 $\approx 0.33$ ns입니다. 즉, CPU 코어 1개는 패킷 1개당 **단 20 사이클(Clock Cycles)** 만에 처리를 끝내야만 패킷 드롭(Drop)이 발생하지 않습니다!

### 1.2 전통적인 리눅스 커널 패킷 경로 (`AF_INET` / `sk_buff`)의 오버헤드
리눅스 표준 네트워크 스택에서 패킷이 NIC 하드웨어에서 사용자 애플리케이션에 도달하기까지의 과정은 다음과 같습니다:
1. **NIC DMA Rx**: NIC 컨트롤러가 패킷을 호스트 커널 메모리 버퍼로 DMA 전송합니다.
2. **하드웨어 인터럽트 (MSI-X)**: NIC가 CPU 코어에 인터럽트를 걸어 패킷 도착을 알립니다.
3. **NAPI 폴링 루프 & `sk_buff` 할당**: 드라이버의 NAPI(`napi_schedule`) 루틴이 실행되며, `kmem_cache_alloc`을 호출하여 200바이트가 넘는 거대한 메타데이터 구조체 `struct sk_buff`를 할당합니다 (약 50~150 사이클).
4. **프로토콜 스택 통과**: `netif_receive_skb()`를 통해 `tc`(Traffic Control), Netfilter/iptables, IP 포워딩, TCP 체크섬 검증 및 상태 머신을 통과합니다 (수백 사이클).
5. **소켓 큐 인큐**: 소켓 수신 큐(`sk_receive_queue`)에 뮤텍스/스핀락을 획득하고 `skb`를 링크합니다.
6. **컨텍스트 스위칭 및 `copy_to_user`**: 사용자 프로세스가 `recv()` / `read()` 시스템 콜을 호출하면, CPU는 커널 공간 버퍼의 페이로드를 사용자 공간 버퍼로 메모리 복사합니다 ($O(N)$ 메모리 버스 대역폭 소비 및 캐시 축출).

이 모든 과정을 합산하면 패킷당 수천 나노초(ns)가 소요되므로, 리눅스 표준 스택은 단일 코어 기준 기껏해야 1~2 Mpps를 넘기기 어렵습니다.

---

## 2. 패킷 처리 가속 기술의 진화: DPDK vs eBPF XDP vs AF_XDP

| 비교 항목 | Linux Naive Socket (`AF_INET`) | DPDK (Data Plane Dev Kit) | eBPF XDP (eXpress Data Path) | AF_XDP (XSK Zero-Copy) |
| :--- | :--- | :--- | :--- | :--- |
| **패킷 가로채기 위치** | 커널 상위 레이어 (`netif_receive_skb`) | 유저 공간 (PMD 드라이버) | NIC 드라이버 최하단 (`napi_poll`) | NIC 드라이버 최하단 + UMEM 직결 |
| **`sk_buff` 할당 여부** | 필수 (패킷당 1회) | 없음 (Bypass) | 없음 (`xdp_buff` 초경량 구조체) | 없음 (UMEM 청크 DMA) |
| **커널 메모리 복사** | 발생 (`copy_to_user`) | 없음 (사용자 풀 직접 DMA) | 없음 (커널 인라인 처리) | **완전 0회 (Zero-Copy DMA)** |
| **커널 기능 활용성** | 100% (iptables, routing 등) | **0% (완전 고립)** | 100% (eBPF helper, map 연계) | **100% (커널/네임스페이스 연계)** |
| **CPU 코어 점유** | 인터럽트 + SoftIRQ | **100% 비지 폴링 (Dedicated)** | 이벤트 구동 폴링 (NAPI 결합) | 인터럽트 폴링 하이브리드 |
| **처리 성능 (단일 코어)**| ~1.5 Mpps | ~20 - 30 Mpps | **~24 - 35 Mpps (Drop/TX)** | **~15 - 25 Mpps (User 전달)** |

---

## 3. AF_XDP의 UMEM 아키텍처 및 4대 락프리 링버퍼

### 3.1 UMEM 메모리 모델
UMEM은 사용자 공간 프로세스가 익명 메모리 매핑(`mmap(MAP_ANONYMOUS | MAP_SHARED)`) 또는 거대 페이지(Huge Pages, 2MB/1GB)로 할당한 연속된 메모리 영역입니다. 이 영역을 커널에 `setsockopt(fd, SOL_XDP, XDP_UMEM_REG, ...)` 시스템 콜을 통해 등록합니다.
- UMEM은 동일한 크기(예: 2048 또는 4096 바이트)의 청크(Chunk)들로 격자 분할됩니다.
- 패킷은 언제나 청크의 시작 오프셋 또는 지정된 헤드룸(Headroom) 오프셋에 직접 DMA 기록됩니다.

### 3.2 4대 단일 생산자-단일 소비자(SPSC) 링버퍼의 역할
AF_XDP는 동기화 오버헤드(Lock Contention)를 완전히 제거하기 위해 단일 생산자-단일 소비자 원형 큐(Circular Ring Buffer) 4개를 사용합니다:

```
[ 사용자 공간 (User Space App) ]
    │                      ▲
    │ (1) Fill Ring        │ (2) Rx Ring
    │  [Empty Chunks]      │  [Received Packets]
    ▼                      │
═══════════════════════════════════════════════════ UMEM 경계 (Zero-Copy DMA)
    │                      ▲
    ▼                      │
[ 커널 드라이버 / NIC 하드웨어 (Kernel / NIC DMA) ]
    │                      ▲
    │ (3) Tx Ring          │ (4) Completion Ring
    │  [Packets to Send]   │  [Transmitted Chunks]
    ▼                      │
[ 사용자 공간 (User Space App) ]
```

1. **Fill Ring (Rx 풀 장전)**:
   - 생산자: **유저 애플리케이션** / 소비자: **커널 드라이버/NIC**
   - 유저는 패킷을 수신할 빈 UMEM 청크 주소(`chunk_addr`)들을 채워 넣습니다.
   - 드라이버는 패킷이 도착하기 전에 이 주소를 꺼내어 NIC의 하드웨어 수신 디스크립터(Rx Descriptor Ring)에 프로그래밍합니다.
2. **Rx Ring (수신 패킷 인도)**:
   - 생산자: **커널 드라이버/NIC** / 소비자: **유저 애플리케이션**
   - NIC가 패킷을 UMEM 청크에 DMA로 성공적으로 기록하면, 드라이버는 패킷 메타데이터(`chunk_addr`, `len`)를 Rx Ring에 기록합니다.
   - 유저는 이 링에서 디스크립터를 꺼내 패킷 데이터를 읽습니다 (Zero-Copy).
3. **Tx Ring (전송 요청)**:
   - 생산자: **유저 애플리케이션** / 소비자: **커널 드라이버/NIC**
   - 유저는 전송하고자 하는 패킷 데이터가 담긴 UMEM 청크 주소와 길이를 기록하여 전송을 요청합니다.
   - 드라이버는 이 정보를 읽어 NIC 송신 디스크립터(Tx Descriptor Ring)에 등록합니다.
4. **Completion Ring (송신 완료 및 청크 회수)**:
   - 생산자: **커널 드라이버/NIC** / 소비자: **유저 애플리케이션**
   - NIC가 패킷 전송을 마치면 드라이버는 해당 청크 주소를 Completion Ring에 적재합니다.
   - 유저는 이 링에서 주소를 꺼내어 "이제 이 청크는 안전하게 다른 패킷에 재사용해도 된다"고 판단하고 Fill Ring 등으로 환원합니다.

### 3.3 메모리 배리어(Memory Barrier)와 인덱스 동기화
SPSC 링버퍼는 `producer` 인덱스와 `consumer` 인덱스를 분리하여 락 없이 동기화합니다:
- 생산자는 `cached_cons`와 `prod`를 비교하여 남은 빈 슬롯 개수를 계산합니다.
- 슬롯에 데이터를 쓴 후 **Write Memory Barrier (`smp_wmb()`)**를 호출하여 데이터 쓰기가 인덱스 갱신보다 먼저 글로벌 메모리에 가시화되도록 보장한 뒤 `prod` 인덱스를 올립니다.
- 소비자는 **Read Memory Barrier (`smp_rmb()`)**를 통해 최신 `prod` 인덱스를 확인하고 슬롯 데이터를 읽습니다.
- 이를 통해 원자적 CPU 인스트럭션(`LOCK CMPXCHG`)이나 스핀락 없이 완벽한 메모리 가시성과 최고 대역폭을 달성합니다.
