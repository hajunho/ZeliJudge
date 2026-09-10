# 리눅스 커널 Bridge 포워딩 데이터베이스(FDB) 및 STP 아키텍처 이론 백서

## 1. 리눅스 커널 L2 브리지의 역할과 패킷 경로

리눅스 커널의 소프트웨어 브리지(`net/bridge/`)는 OSI 7계층 중 2계층(데이터 링크 계층)에서 복수의 네트워크 인터페이스를 단일 이더넷 스위치 세그먼트로 결합합니다.

### 1.1 커널 내부 패킷 처리 흐름 (`net/bridge/`)
1. NIC 디바이스 드라이버가 패킷을 수신하고 `netif_receive_skb`를 호출합니다.
2. 수신 인터페이스의 `rx_handler`가 브리지의 `br_handle_frame`(`net/bridge/br_input.c`)으로 바인딩되어 있습니다.
3. **STP 포트 상태 검사**:
   - 포트가 `BR_STATE_DISABLED` 또는 `BR_STATE_BLOCKING`이면 BPDU 패킷을 제외한 일반 데이터 프레임을 즉시 폐기합니다.
4. **FDB 출발지 MAC 학습 (`br_fdb_update`)**:
   - 포트가 `BR_STATE_LEARNING` 또는 `BR_STATE_FORWARDING`이면, 해시 테이블 기반의 FDB에 `(src_mac, vlan) -> port` 매핑을 갱신합니다.
5. **목적지 포워딩 판정 (`br_forward` / `br_flood`)**:
   - 목적지 주소가 브로드캐스트(`FF:FF:FF:FF:FF:FF`)이거나 FDB에 매핑되지 않은 '미등록 유니캐스트(Unknown Unicast)'인 경우, 입력 포트를 제외한 모든 활성 포트로 복제하여 플러딩합니다.
   - FDB에 등록된 유니캐스트이면 해당 포트로만 직접 포워딩합니다.
   - 단, 목적지 포트가 입력 포트와 동일한 경우(`dest_port == in_port`), 이미 로컬 링크에 전달된 패킷이므로 반사(Reflect)되지 않도록 필터링합니다.

---

## 2. 브로드캐스트 스톰과 STP (Spanning Tree Protocol)

이더넷 프레임은 IP 패킷과 달리 **TTL (Time to Live)** 필드가 존재하지 않습니다. 따라서 네트워크 장비 간에 폐쇄 루프(Loop)가 형성되면, 단 하나의 브로드캐스트(ARP Request 등) 패킷이 영원히 증폭 순환하며 네트워크 전체 대역폭을 100% 마비시키는 **브로드캐스트 스톰(Broadcast Storm)**이 발생합니다.

### 2.1 STP 5대 포트 상태 전이 모델 (IEEE 802.1D)
루프를 방지하기 위해 STP 알고리즘은 최적의 신장 트리(Spanning Tree)를 구성하고 여분의 경로를 차단합니다:

1. **Disabled**: 관리자에 의해 포트가 비활성화된 상태 (링크 다운).
2. **Blocking**: 루프를 방지하기 위해 일반 프레임을 차단하고 BPDU 제어 패킷만 수신하는 상태.
3. **Listening**: 루트 브리지 및 포트 역할을 결정하며, MAC 학습과 데이터 전송을 하지 않는 상태.
4. **Learning**: MAC 주소 테이블(FDB)을 학습하지만 데이터 프레임 전송은 아직 하지 않는 상태 (Forward Delay 대기).
5. **Forwarding**: 정상적으로 MAC을 학습하고 데이터 프레임을 포워딩하는 최종 상태.

### 2.2 토폴로지 변경 통지 (TCN)와 블랙홀 방어
네트워크 링크가 단절되거나 경로가 변경되면 기존 FDB 테이블의 포트 매핑은 일순간 유효하지 않게 됩니다.
- 정상 상태의 FDB Aging Time은 보통 **300초(5분)**입니다.
- 링크가 바뀐 뒤에도 300초 동안 구버전 포트로 계속 패킷을 보내면 수많은 패킷이 증발하는 **블랙홀(Blackhole)** 현상이 발생합니다.
- STP는 브리지 장애 발생 시 **TCN(Topology Change Notification)** BPDU를 전파하고, 모든 브리지의 FDB Aging Time을 **15초(Forward Delay)**로 급격히 단축(Fast Aging)하여 과거의 매핑을 즉시 쓸어내고 새로운 경로를 재학습하도록 강제합니다.

---

## 3. 컨테이너 및 클라우드 가상화에서의 실무적 함의

1. **Docker `docker0` 브리지와 veth pair**:
   - 컨테이너가 생성되면 호스트 네임스페이스의 veth 종단이 `docker0` 브리지의 포트로 바인딩됩니다.
   - 컨테이너 간 통신은 브리지의 FDB 학습을 통해 $O(1)$ 속도로 유니캐스트 스위칭됩니다.
2. **쿠버네티스 CNI와 `hairpin_mode`**:
   - 포드가 서비스 IP를 통해 자기 자신을 호출하는 경우(Hairpin NAT), 브리지는 기본적으로 동일 포트 프레임을 드롭(`FILTER_SAME_PORT`)하므로 패킷이 유실됩니다.
   - 이를 해결하기 위해 쿠버네티스는 해당 veth 포트에 `hairpin_mode 1` 플래그를 활성화하여 동일 포트 반사를 예외적으로 허용합니다.
3. **`br_netfilter`와 성능 트레이드오프**:
   - 브리지를 통과하는 L2 프레임을 호스트의 iptables/netfilter 규칙으로 검사(`sysctl net.bridge.bridge-nf-call-iptables=1`)하면 CPU 오버헤드가 급증합니다.
   - 고성능 환경에서는 Cilium(eBPF 기반 우회)이나 Macvlan/SR-IOV를 활용하여 브리지 스택 자체를 우회하는 아키텍처가 선호됩니다.
