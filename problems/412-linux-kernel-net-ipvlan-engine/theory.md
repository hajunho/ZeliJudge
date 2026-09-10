# 이론 문서 412: Linux 커널 IPVLAN 네트워크 가상화 및 클라우드 CNI 아키텍처 심층 분석

## 1. 개요 및 배경: 컨테이너 네트워크 가상화 기술의 진화

현대 클라우드 데이터센터와 쿠버네티스(Kubernetes) 환경에서 수만 개의 컨테이너 간 고속 통신을 지원하기 위해 리눅스 커널은 여러 세대에 걸쳐 네트워크 가상화 기술을 진화시켜 왔습니다:

```
+--------------------------------------------------------------------------------------------------+
| Evolution of Linux Container Network Virtualization                                             |
|                                                                                                  |
| [ 1세대: veth + Linux Bridge ]                                                                   |
|   Container eth0 <---> veth_pair <---> br0 (Linux Bridge) <---> Physical eth0                    |
|   * 한계: 2번의 sk_buff 복사/스택 횡단, 브릿지 FDB 락 경합, 높은 CPU 오버헤드                     |
|                                                                                                  |
| [ 2세대: Macvlan ]                                                                               |
|   Container eth0 (Unique MAC A) ----+                                                            |
|   Container eth1 (Unique MAC B) ----+---> Direct Multiplexing on Physical eth0                   |
|   Container eth2 (Unique MAC C) ----+                                                            |
|   * 한계: 수천 개 컨테이너 시 스위치 CAM 테이블 포화, 엔터프라이즈 포트 시큐리티 위반              |
|                                                                                                  |
| [ 3세대: IPVLAN (Linux 3.19+) ]                                                                  |
|   Container eth0 (IP A) ------------+                                                            |
|   Container eth1 (IP B) ------------+---> Shared Single Physical MAC on Physical eth0           |
|   Container eth2 (IP C) ------------+                                                            |
|   * 혁신: 외부 스위치는 오직 1개 MAC만 인지! 포트 시큐리티 완벽 통과, L3 패스트패스 라우팅!        |
+--------------------------------------------------------------------------------------------------+
```

### 1.1 Macvlan의 치명적 인프라 제약과 IPVLAN의 탄생
- **Macvlan**은 물리 NIC 위에 가상 서브인터페이스를 생성하고 각각에 새로운 무작위 MAC 주소를 부여합니다.
- 그러나 클라우드 공급자(AWS VPC, Google Cloud, Azure)의 가상 머신(EC2/GCE) 가상 인터페이스는 오직 VM에 할당된 1개의 MAC 주소만을 허용(MAC Anti-Spoofing 필터)하므로, Macvlan을 구동하면 패킷이 하이퍼바이저에서 즉시 드롭됩니다.
- 또한 기업용 물리 스위치는 802.1X 또는 포트 시큐리티(Port Security)에 의해 단일 포트에 허용되는 최대 MAC 개수를 1개~4개로 제한합니다.
- **IPVLAN (`drivers/net/ipvlan/`)**은 모든 가상 인터페이스가 물리 디바이스의 물리 MAC을 100% 동일하게 공유함으로써 이 모든 인프라 제약을 단숨에 해결하였습니다.

---

## 2. Linux 커널 IPVLAN 내부 자료구조 및 포트 디바이스 모델

커널 소스코드 `drivers/net/ipvlan/`에서 IPVLAN은 마스터 디바이스를 감싸는 **`struct ipvl_port`**와 각 슬레이브 인터페이스를 나타내는 **`struct ipvl_dev`**로 추상화됩니다:

```
    [ Physical net_device: eth0 ]
                  |
                  v
       [ struct ipvl_port ]  <--- Master Port Controller
         - mode: IPVLAN_MODE_L2 / L3 / L3S
         - master_mac: e.g. 02:42:ac:11:00:01
         - ip_hash_table [ 10.0.0.10 -> ipvl0, 10.0.0.20 -> ipvl1, ... ]
                  |
         +--------+--------+
         |                 |
         v                 v
   [ ipvl0 (ns_1) ]   [ ipvl1 (ns_2) ]   <--- struct ipvl_dev (Slave Interfaces)
     IP: 10.0.0.10      IP: 10.0.0.20
```

- 패킷이 물리 인터페이스 `eth0`의 NAPI 폴링 루프로 수신되면, 커널의 `netif_receive_skb()`는 등록된 rx_handler인 `ipvlan_handle_frame()`을 호출합니다.
- `ipvlan_handle_frame()`은 목적지 IP 주소를 추출하여 해시 테이블 `ip_hash_table`을 O(1) 시간 복잡도로 조회하고, 해당하는 슬레이브 인터페이스의 수신 큐로 즉시 직송(Fast-path)합니다.

---

## 3. 3대 포워딩 모드 심층 비교: L2 vs L3 vs L3S

| 특성 비교 | L2 모드 (`IPVLAN_MODE_L2`) | L3 모드 (`IPVLAN_MODE_L3`) | L3S 대칭 모드 (`IPVLAN_MODE_L3S`) |
|:---|:---|:---|:---|
| **동작 계층** | Layer 2 브릿지 에뮬레이션 | Layer 3 순수 IP 라우터 | Layer 3 대칭형 네임스페이스 라우터 |
| **ARP / 브로드캐스트** | 전체 슬레이브로 복제 전달 | **엄격 차단 (Drop)** | **엄격 차단 (Drop)** |
| **MAC 주소 공유** | 마스터 MAC 단일 공유 | 마스터 MAC 단일 공유 | 마스터 MAC 단일 공유 |
| **동일 호스트 로컬 통신** | 커널 헤어핀 스위칭 | 커널 헤어핀 라우팅 | 양방향 Netfilter 체인 통과 헤어핀 |
| **Netfilter Ingress** | 미지원 (마스터 레벨만) | 미지원 | **슬레이브 netns `PRE_ROUTING` 주입** |
| **컨테이너 로컬 방화벽/DNAT** | 불가 | 불가 | **완벽 지원 (Kubernetes Service/NAT)** |

---

## 4. L3S 모드에서의 슬레이브 네트워크 네임스페이스 Netfilter 인젝션

L3S(L3 Symmetric) 모드는 리눅스 4.15에 추가된 가장 진보된 모드로, 컨테이너 가상화의 핵심 요구사항인 **"컨테이너별 독립적인 iptables/nftables 방화벽 및 서비스 프록시"**를 가능하게 만듭니다:

```
+--------------------------------------------------------------------------------------------------+
| L3S Mode Ingress & Hairpin Netfilter Traversal                                                   |
|                                                                                                  |
| [ Ingress Packet ]                                                                               |
|   eth0 rx_handler ---> Match dst_ip ---> Switch to Target Slave netns Context                    |
|                                                    |                                             |
|                                                    v                                             |
|                                     [ NF_HOOK: NF_INET_PRE_ROUTING ]                             |
|                                     - Check slave-specific iptables rules                        |
|                                     - Perform DNAT (ClusterIP -> Pod IP)                         |
|                                     - Verdict: ACCEPT ---> Deliver to Container Socket           |
|                                     - Verdict: DROP   ---> Drop packet immediately               |
|                                                                                                  |
| [ Local Hairpin: Pod A -> Pod B ]                                                                |
|   Pod A Socket ---> Egress [ Pod A netns POST_ROUTING ]                                          |
|                                    |                                                             |
|                                    v                                                             |
|                     Direct Kernel Switch (No Wire I/O!)                                          |
|                                    |                                                             |
|                                    v                                                             |
|                     Ingress [ Pod B netns PRE_ROUTING ] ---> Pod B Socket                        |
+--------------------------------------------------------------------------------------------------+
```

---

## 5. 실무 클라우드 및 텔코 인프라 적용 사례

1. **AWS VPC CNI (EKS)**:
   - AWS VPC 환경에서는 각 EC2 인스턴스의 ENI(Elastic Network Interface)에 보조 사설 IP(Secondary Private IPs)가 할당됩니다.
   - IPVLAN L2/L3S 드라이버를 활용하면, ENI의 물리 MAC 주소를 그대로 공유하면서 수십 개의 보조 IP를 파드에 1:1로 직접 매핑할 수 있어 오버레이 네트워크(VXLAN/Geneve) 없이 완벽한 VPC 네이티브 라우팅 성능을 제공합니다.
2. **초고성능 5G UPF (User Plane Function)**:
   - 텔코 5G 코어망에서는 패킷 지연 시간이 1ms 이하로 제한됩니다.
   - IPVLAN L3 모드를 사용하여 브로드캐스트 노이즈를 완벽히 소멸시키고, 커널 내부 락 경합 없이 물리 NIC 처리량에 근접하는 라인 레이트(Line-rate) 포워딩을 구현합니다.
