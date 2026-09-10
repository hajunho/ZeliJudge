# Theory: Linux Kernel eBPF Flow Dissector & RSS Hashing Architecture (`net/core/flow_dissector.c`)

## 1. 하드웨어 RSS의 태생적 한계와 수신 큐 편향 (Polarization)

현대 100GbE/400GbE 네트워크 어댑터는 여러 개의 수신 큐(RX Queues)를 활용하여 패킷을 여러 CPU 코어로 분산 처리합니다.
- **하드웨어 RSS (Receive Side Scaling)**: NIC ASIC이 수신된 패킷 헤더에서 IP와 TCP/UDP 포트를 추출하여 Toeplitz 해시를 계산합니다.
- **오버레이 터널의 수신 큐 편향 문제**:
  - Kubernetes Flannel/Calico, OpenStack Neutron 등 현대 클라우드는 **VXLAN (UDP 4789)** 또는 **GRE (Proto 47)** 오버레이 캡슐화를 광범위하게 사용합니다.
  - 레거시 NIC은 외부(Outer) IP(VTEP 노드 간 주소)와 외부 포트만을 검사하므로, 수천 개의 가상 머신/컨테이너 파드 간 트래픽이 모두 동일한 해시값을 갖게 되어 특정 단일 코어의 RX 링으로만 트래픽이 집중(Polarization)되고 패킷 드롭이 폭증합니다.

---

## 2. 리눅스 eBPF Flow Dissector (`BPF_PROG_TYPE_FLOW_DISSECTOR`)

Linux 4.20부터 도입된 eBPF Flow Dissector는 전통적인 C 커널 하드코딩 플로우 파서(`__skb_flow_dissect`)를 완전히 대체할 수 있는 고성능 프로그래머블 후크입니다:

```c
struct bpf_flow_keys {
    __u16 nhoff;
    __u16 thoff;
    __u16 addr_proto;
    __u8  is_encap;
    __u8  ip_proto;
    union {
        __be32 ipv4_src;
        __u32  ipv6_src[4];
    };
    union {
        __be32 ipv4_dst;
        __u32  ipv6_dst[4];
    };
    __be16 sport;
    __be16 dport;
    __u16  flags;
    __u32  flow_label;
};
```

### 2.1 주요 기능 및 장점
1. **깊은 패킷 검사 (Deep Packet Inspection)**:
   - 프로그래머블 eBPF 바이트코드가 임의의 깊이로 터널 헤더(VXLAN, Geneve, GRE, GTP-U)를 디캡슐화하여 실제 내부 컨테이너 파드의 소스/목적지 IP와 포트를 추출합니다.
2. **대칭 해싱 (Symmetric Flow Hashing)**:
   - 송신과 수신 방향이 동일한 5-튜플 해시를 갖도록 정규화(`min/max` 정렬)하여 전송 계층 소켓 캐시라인 및 연결 추적(conntrack)의 CPU 지역성을 보장합니다.
3. **네임스페이스 단위 안전한 격리**:
   - 컨테이너 네트워크 네임스페이스별로 상이한 터널링 정책과 파서를 동적으로 주입할 수 있습니다.
