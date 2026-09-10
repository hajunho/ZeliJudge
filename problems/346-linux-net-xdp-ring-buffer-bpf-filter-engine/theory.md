# 리눅스 커널 eXpress Data Path (XDP)와 AF_XDP 제로카피 아키텍처 이론 심화 백서

## 1. 커널 네트워크 데이터 플레인의 물리적 한계

현대 데이터센터의 네트워크 대역폭은 10GbE에서 100GbE, 400GbE, 나아가 800GbE로 비약적으로 발전했습니다. 그러나 CPU 클럭 속도는 무어의 법칙 한계와 전력 밀도 문제로 인해 3~4GHz 수준에 정체되어 있습니다.

$$T_{\text{packet}} = \frac{\text{Packet Size (bits)}}{\text{Bandwidth (bps)}}$$

64바이트(이더넷 프리앰블 및 IFG 포함 84바이트 = 672비트) 패킷 기준:
- **10 GbE**: 패킷당 약 **67.2 ns**
- **100 GbE**: 패킷당 약 **6.72 ns** (CPU 클럭 3.3GHz 기준 약 **22 사이클**)
- **400 GbE**: 패킷당 약 **1.68 ns** (약 **5 사이클**)

전통적인 리눅스 커널 네트워크 스택의 패킷 수신 경로는 다음과 같습니다:
1. 하드웨어 인터럽트(IRQ) 발생 및 Top-Half 핸들러 실행
2. Bottom-Half 소프트인터럽트(`ksoftirqd`/`NET_RX_SOFTIRQ`) 스케줄링
3. 드라이버 NAPI 폴링 루프 진입 (`napi_poll`)
4. 드라이버 링 버퍼에서 DMA된 원시 패킷을 추출하여 `struct sk_buff` 동적 할당 (`kmem_cache_alloc`)
5. L2 이더넷 헤더 파싱 및 `netif_receive_skb` 호출
6. TC(Traffic Control) 서브시스템 및 Netfilter(iptables/nftables) 훅 순회
7. L3 IP 라우팅 테이블 조회 및 L4 프로토콜(TCP/UDP) 소켓 버퍼 큐잉
8. 유저스페이스 시스템 콜(`recvmsg`) 시 커널 버퍼에서 유저 버퍼로 메모리 복사 (`copy_to_user`)

이 과정에서 발생하는 단 한 번의 L3 캐시 미스(약 40~60ns 지연)나 메모리 할당자 락 경합만으로도 100GbE의 6.72ns 예산은 산산조각 나며, 큐 오버플로우로 인한 대규모 패킷 드롭이 발생합니다.

---

## 2. eXpress Data Path (XDP)의 혁신적 설계

XDP는 커널 내부에서 패킷을 처리하되, **가장 이른 시점(Earliest Point)**에 개입합니다.

```
+-------------------------------------------------------------+
|                     물리 NIC 수신 DMA                      |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|         드라이버 RX Ring Buffer (struct xdp_buff)           |
+-------------------------------------------------------------+
                              |
                     [ eBPF XDP Program ]
                              |
         +----------+---------+---------+----------+
         |          |                   |          |
         v          v                   v          v
     XDP_DROP    XDP_TX           XDP_REDIRECT  XDP_PASS
   (즉시 재활용) (헤어핀 반환)       (AF_XDP/NIC)  (sk_buff 생성)
                                        |          |
                                        v          v
                                   [AF_XDP XSK]  [전통 커널 스택]
                                   (Zero-Copy)   (netif_receive_skb)
```

### 2.1 3대 동작 모드
1. **Offloaded XDP**: eBPF 바이트코드를 SmartNIC(Netronome, Mellanox 등)의 NPU에 직접 JIT 컴파일하여 탑재. CPU 개입 0%.
2. **Native (Driver) XDP**: NIC 디바이스 드라이버의 초기 RX 루프(`napi_gro_receive` 이전)에서 실행. 대부분의 고성능 엔터프라이즈 환경(`mlx5`, `ixgbe`, `i40e`, `virtio_net`)에서 기본 지원.
3. **Generic XDP**: 드라이버 지원 없이도 커널의 `netif_receive_generic_xdp` 위치에서 동작하는 소프트웨어 폴백 모드(테스트/개발용).

### 2.2 5대 핵심 액션 코드
- `XDP_DROP` (1): 패킷을 즉시 폐기하고 RX 링 버퍼 디스크립터를 NIC 하드웨어에 즉각 반환. L4 DDoS 방어에 최적.
- `XDP_TX` (2): 인입된 패킷의 헤더를 메모리 상에서 직접 수정한 후 동일한 네트워크 인터페이스의 TX 링으로 즉시 송신(Hairpin Reflect).
- `XDP_REDIRECT` (3): 다른 네트워크 인터페이스(veth, 다른 물리 포트)나 다른 CPU(`cpumap`), 또는 **AF_XDP 소켓**으로 패킷을 고속 전달.
- `XDP_PASS` (4): 전통적인 리눅스 커널 네트워킹 스택으로 제어권을 넘김 (`build_skb` -> `napi_gro_receive`).
- `XDP_ABORTED` (0): BPF 프로그램 내부 오류 또는 경계 초과 시 패킷 폐기 및 `trace_xdp_exception` 트레이스포인트 트리거.

---

## 3. AF_XDP (XSK)와 제로카피 UMEM 아키텍처

전통적인 소켓 I/O는 `copy_to_user`로 인해 CPU가 메모리 버스를 통해 패킷 바이트를 일일이 복사해야 합니다. **AF_XDP (Address Family XDP)**는 이를 완전히 제거하는 진정한 **Zero-Copy Kernel Bypass** 인터페이스를 제공합니다.

### 3.1 UMEM (User Memory)
- 유저스페이스 애플리케이션이 `mmap`/`posix_memalign`으로 할당한 거대한 연속 메모리 풀입니다.
- 일정한 크기(`frame_size`: 2048바이트 또는 4096바이트)의 고정 청크로 분할 관리됩니다.
- NIC 하드웨어 DMA 컨트롤러는 유저스페이스의 UMEM 메모리 주소로 패킷 페이로드를 직접 기록(Direct DMA Write)합니다.

### 3.2 4대 단일 생산자-단일 소비자(SPSC) 락프리 링 버퍼
AF_XDP 통신은 4개의 환형 큐(Circular Ring Buffer)를 통해 락(Lock) 없이 원자적 메모리 배리어만으로 구동됩니다:

1. **Fill Ring (User -> Kernel)**:
   - 유저스페이스가 수신용으로 준비한 빈 UMEM 프레임의 오프셋/주소를 커널에 공급합니다.
   - 이 링이 비어있으면(Starvation) NIC는 제로카피 수신 버퍼를 찾지 못해 패킷을 드롭합니다.
2. **Rx Ring (Kernel -> User)**:
   - 커널 드라이버가 NIC로부터 패킷을 DMA 수신한 후, 패킷 길이와 해당 UMEM 프레임 위치를 유저스페이스에 통지합니다.
3. **Tx Ring (User -> Kernel)**:
   - 유저스페이스가 선로로 전송할 패킷 데이터가 담긴 UMEM 프레임의 위치와 길이를 커널 드라이버에 전달합니다.
4. **Completion Ring (Kernel -> User)**:
   - NIC가 송신을 완료(TX Complete Interrupt/NAPI)한 후, 전송된 UMEM 프레임이 유저스페이스에 의해 안전하게 재사용될 수 있음을 알립니다.

---

## 4. 실무 응용: Cloudflare L4Drop 및 Meta Katran 아키텍처

- **Cloudflare L4Drop**: 전 세계 엣지 PoP에서 초당 수억 패킷의 UDP/TCP SYN Flood DDoS 공격을 방어하기 위해 XDP를 사용합니다. BPF LPM Trie 맵으로 블랙리스트 서브넷을 초고속 조회하고 `XDP_DROP`을 수행하여, 초당 1억 패킷 이상의 공격 속에서도 웹서버 CPU 사용률을 1% 미만으로 유지합니다.
- **Meta Katran**: 메타(구 페이스북)의 차세대 L4 로드밸런서로, 인입 트래픽을 BPF 맵의 매귈레프(Maglev) 일관 해싱 알고리즘을 통해 백엔드 캐시 서버로 `XDP_TX`를 통해 헤어핀 포워딩합니다.
- **AF_XDP 기반 고성능 DNS / 쿼크(QUIC) 엔진**: 구글 Envoy, NGINX 및 코어DNS 등은 AF_XDP를 연동하여 유저스페이스 패킷 처리량을 기존 POSIX 소켓 대비 5배~10배 이상 향상시키고 있습니다.
