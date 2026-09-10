# Theory #440: 리눅스 커널 초고속 네트워킹: net/core/skbuff.c GSO/TSO 세그멘테이션 오프로드 및 skb_segment 프래그먼트 슬라이싱 이론

## 1. 패킷 처리의 계산 복잡도와 CPU 벽 (The Per-Packet Overhead Wall)

전통적인 네트워크 프로토콜 스택 이론에서 패킷 전송 비용 $C_{\text{tx}}$는 바이트당 비용(Byte-copy overhead)과 패킷당 고정 오버헤드(Per-packet fixed cost)의 합으로 표현됩니다:

$$C_{\text{tx}} = C_{\text{byte}} \cdot S_{\text{payload}} + C_{\text{packet}} \cdot N_{\text{packets}}$$

현대 제로-카피(Zero-Copy) 및 DMA 기법의 발전으로 $C_{\text{byte}}$는 거의 0에 가깝게 최적화되었습니다.
그러나 $C_{\text{packet}}$은 여전히 다음과 같은 고정 CPU 비용을 수반합니다:
1. **소켓 버퍼 메모리 할당**: `struct sk_buff`(약 256바이트) 및 `struct skb_shared_info`(약 320바이트) 슬랩 할당.
2. **프로토콜 스택 순회**: 소켓 레이어 -> TCP 상태 머신 -> IP 라우팅 테이블 조회 -> Netfilter/iptables 훅 체인(수백 개 규칙 매칭) -> Qdisc/TC 트래픽 셰이핑.
3. **디바이스 드라이버 링 버퍼 등록**: PCIe MMIO 레지스터 쓰기 및 도어벨(Doorbell) 링잉.

단일 패킷당 소요되는 CPU 사이클이 약 1,000사이클이라고 가정할 때, 100GbE 회선을 1500바이트 MTU 패킷으로 꽉 채우려면 초당 약 8,200,000개의 패킷(8.2 Mpps)을 처리해야 하며, 이는 **8.2 GHz 분량의 순수 CPU 파워(최신 고성능 코어 3~4개)**를 100% 소진시킵니다.

---

## 2. GSO / TSO (Segmentation Offload)의 아키텍처 혁신

**TSO (TCP Segmentation Offload)**와 **GSO (Generic Segmentation Offload)**는 이 패킷당 고정 오버헤드를 근본적으로 $1/45$로 압축합니다:

```
[ Application send(64KB) ]
             │
             ▼
[ Giant GSO Super-Packet ] (64KB payload, single sk_buff)
             │
 ┌───────────┴─────────────────────────────────────────┐
 │ Kernel Stack Traversal: ONLY 1 PASS!                │
 │ - TCP Congestion Window Update                      │
 │ - IP Route Lookup (FIB Cache Hit)                   │
 │ - Netfilter / eBPF TC Filter Evaluated ONCE         │
 └───────────────────────┬─────────────────────────────┘
                         │
                         ▼
        ┌────────────────┴────────────────┐
        │       Hardware Supports TSO?    │
        └────────────────┬────────────────┘
                ┌────────┴────────┐
               Yes                No
                ▼                 ▼
     [ Handoff to NIC ASIC ]  [ skb_segment() in Software ]
     - NIC cuts 45 packets    - CPU slices payload into MSS
     - 0 CPU Cycles!          - Adjusts SEQ & IP_ID
     - Wire: 45 x 1500B       - Masks PSH/FIN until end
```

### (1) `skb_shared_info`와 Scatter-Gather 페이징
대용량 슈퍼-패킷을 메모리에 저장할 때 64KB 연속 물리 메모리를 요구하면 버디 시스템의 고차 단편화로 인해 메모리 할당이 실패합니다.
리눅스 커널은 이를 **비연속 페이지 프래그먼트 배열(`skb_frag_t frags[MAX_SKB_FRAGS]`)**로 해결합니다:
- 선형 헤더(`skb->data`): L2/L3/L4 헤더(54바이트) 및 초기 소량 데이터.
- 프래그먼트 목록(`frags`): 가상 메모리 페이지(`struct page *`)와 오프셋, 길이를 담은 분산 배열로, 사용자 메모리나 페이지 캐시에서 직접 제로-카피 참조합니다.

---

## 3. `skb_segment()`의 핵심 불변식과 정밀 슬라이싱 메커니즘

소프트웨어 GSO를 담당하는 `net/core/skbuff.c`의 `skb_segment()`는 다음과 같은 엄밀한 네트워크 프로토콜 불변식을 준수해야 합니다:

### (1) TCP 시퀀스 번호(Sequence Number)의 단조 증가 보존
슈퍼-패킷의 초기 시퀀스 번호가 $S_0$이고, 각 분할 세그먼트의 페이로드 길이가 $L_0, L_1, \dots, L_{m-1}$일 때:
$$S_k = S_0 + \sum_{i=0}^{k-1} L_i$$
수신측 TCP 스택은 이 시퀀스 번호를 통해 패킷의 순서를 맞추고 재조합하므로, 단 1바이트의 오차도 허용되지 않습니다.

### (2) TCP 제어 플래그의 선택적 마스킹 (PSH & FIN Isolation)
- `ACK`: 원본 패킷에 설정된 수신 확인 번호(Acknowledgment)는 연결 상태를 유지해야 하므로 **모든 분할 세그먼트**에 동일하게 복제됩니다.
- `PSH (Push)`: 수신측 애플리케이션 버퍼에 즉각 데이터를 밀어 올리라는 신호입니다. 만약 중간 세그먼트에 PSH가 남아있으면 수신측 OS가 불완전한 데이터를 조기 플러시하여 버퍼링 효율이 급락합니다.
- `FIN (Finish)`: 연결 종료 신호입니다. 중간 세그먼트에 FIN이 들어가면 수신측은 남은 데이터가 도착하기도 전에 소켓을 닫아버려 데이터가 유실됩니다.
- **규칙**: 따라서 `PSH`와 `FIN` 플래그는 반드시 **마지막 세그먼트($k = m-1$)에만 부여**되고 나머지 중간 세그먼트에서는 엄격히 제거(Clear)되어야 합니다.

### (3) 프래그먼트 경계 분할 (Frag Slicing across Boundaries)
하나의 MSS(예: 1448바이트) 세그먼트가 단일 4KB 페이지 프래그먼트의 끝부분에 걸쳐 다음 페이지 프래그먼트의 시작 부분까지 이어지는 경우, `skb_segment()`는 첫 번째 페이지의 잔여 바이트와 두 번째 페이지의 시작 바이트를 결합하여 새 skb의 프래그먼트 리스트를 구성합니다. 이때 원본 페이지의 참조 카운트(`get_page()`)만 원자적으로 증가시킴으로써 데이터의 실제 메모리 복사(memcpy)를 0으로 유지합니다.
