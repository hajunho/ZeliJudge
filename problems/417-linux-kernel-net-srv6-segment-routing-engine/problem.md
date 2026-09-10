# 문제 417: Linux 커널 5G/클라우드 통신망 SRv6(Segment Routing over IPv6) End/End.X/End.DT4 네트워크 슬라이싱 및 L3VPN 디캡슐화 엔진

## 문제 설명

현대 대규모 5G 코어 통신망, 하이퍼스케일 클라우드 데이터센터 인터커넥트(DCI), 그리고 글로벌 백본망에서 지난 20년간 표준으로 사용되어 온 기술은 **MPLS (Multiprotocol Label Switching)**였습니다.
그러나 MPLS는 다음과 같은 구조적 한계와 운영 복잡성을 안고 있습니다:
1. **복잡한 시그널링 제어 평면 (Control-Plane Bloat)**: 라벨 분배를 위해 LDP(Label Distribution Protocol), RSVP-TE, BGP-LU 등 다수의 이종 프로토콜을 네트워크의 모든 전송 노드(Transit Node)에서 유지해야 합니다.
2. **트래픽 엔지니어링 상태 유지 (Stateful Core)**: 수십만 개의 LSP(Label Switched Path) 상태를 코어 라우터가 모두 기억해야 하므로 코어 장비의 확장성 한계가 발생합니다.
3. **오버레이와 언더레이의 단절**: MPLS 라벨은 L2.5 계층으로 일반 IP 라우팅 인프라와 호환되지 않으며, 중간 네트워크 장비에서 패킷 가시성(Visibility)과 흐름 분석이 극도로 어렵습니다.

이 문제를 해결하고 통신망을 소프트웨어 정의 네트워크(SDN) 기반으로 통합하기 위해 IETF(RFC 8754, RFC 8986)에서 표준화하고, 리눅스 커널 4.10+부터 채택된 차세대 패킷 포워딩 아키텍처가 바로 **SRv6 (Segment Routing over IPv6, `net/ipv6/seg6.c`, `net/ipv6/seg6_local.c`, `CONFIG_IPV6_SEG6_LWTUNNEL`)**입니다.

---

### SRv6 핵심 아키텍처 및 동작 메커니즘

SRv6의 기본 철학은 **"출발지 노드가 패킷 헤더에 전체 전송 경로(세그먼트 리스트)를 프로그래밍하여 기록하고, 중간 코어 라우터는 어떠한 상태도 유지하지 않는 무상태(Stateless) 소스 라우팅"**입니다.

1. **SRH (Segment Routing Header, IPv6 Routing Type 4)**:
   - IPv6 확장 헤더(Extension Header)로 삽입되며, 128비트 IPv6 주소 형태의 세그먼트 식별자(**SID, Segment Identifier**) 배열을 저장합니다:
     $$\text{Segments}[0], \text{Segments}[1], \dots, \text{Segments}[n-1]$$
   - **`Segments Left (SL)`**: 현재 활성화되어 처리해야 할 세그먼트의 인덱스를 가리킵니다.
   - IPv6 패킷의 최종 목적지 주소(Destination Address, DA)는 항상 현재 활성 세그먼트인 `Segments[SL]`로 설정됩니다.

2. **표준 SRv6 엔드포인트 동작 (RFC 8986)**:
   - **`End` (기본 엔드포인트)**:
     - 패킷의 IPv6 DA가 노드의 로컬 SID와 일치하고 $SL > 0$이면:
       - $SL$을 1 감소시킵니다 ($SL \leftarrow SL - 1$).
       - IPv6 DA를 다음 세그먼트인 `Segments[SL]`로 갱신합니다.
       - 표준 IPv6 라우팅 테이블에 따라 다음 홉으로 패킷을 전송합니다.
     - $SL == 0$인 경우, 패킷이 최종 SRv6 목적지에 도달한 것이므로 상위 계층으로 전달합니다.
   - **`End.X` (Layer-3 크로스 커넥트 엔드포인트)**:
     - $SL$을 1 감소시키고 DA를 다음 세그먼트로 갱신한 후, 일반 라우팅 테이블 조회를 거치지 않고 **지정된 특정 L3 송신 인터페이스 및 다음 홉(`nexthop`)으로 직통 전달(Cross-Connect)**합니다.
     - 5G 초저지연(URLLC) 경로 제어나 대역폭 보장 트래픽 엔지니어링(TE)에 필수적으로 사용됩니다.
     - 만약 $SL == 0$인 상태에서 `End.X`가 호출되면 세그먼트 언더플로우로 패킷을 폐기(`END_X_SL_UNDERFLOW`)합니다.
   - **`End.DT4` (디캡슐화 및 IPv4 VRF 라우팅 테이블 전달)**:
     - 5G 네트워크 슬라이싱 및 엔터프라이즈 BGP L3VPN의 핵심 함수입니다.
     - 외부 IPv6 헤더와 SRH를 완전히 제거(Decapsulate)합니다.
     - 내부 IPv4 페이로드의 목적지 IP를 읽어, 격리된 가상 라우팅 포워딩 인스턴스(**VRF, Virtual Routing and Forwarding**) 테이블에서 경로를 조회하여 고객망으로 전달합니다.
   - **`End.DX6` (디캡슐화 및 IPv6 크로스 커넥트 전달)**:
     - 외부 IPv6/SRH 헤더를 제거하고 내부 IPv6 패킷을 지정된 전용 크로스 커넥트 인터페이스로 즉시 전달합니다.

3. **인그레스 캡슐화 (`seg6_encap`)**:
   - 가입자 망(Customer Network)에서 일반 패킷이 인그레스 PE(Provider Edge) 라우터로 유입되면:
     - 지정된 슬라이싱 정책에 따라 외부에 IPv6 헤더(40바이트)와 SRH 헤더($8 + 16 \times N$바이트)를 덧씌웁니다.
     - 초기 $SL = N - 1$로 설정되고, DA는 첫 번째 경유지인 `Segments[N-1]`로 지정됩니다.

4. **MTU 검증 및 패킷 크기 회계**:
   - SRv6 캡슐화로 인해 패킷 크기가 증가하므로, 송신 인터페이스의 MTU를 초과할 경우 하드웨어적으로 패킷이 폐기(`MTU_EXCEEDED`)됩니다.

여러분은 리눅스 커널 SRv6 서브시스템의 인그레스 `seg6_encap`, 엔드포인트 `End`, 크로스 커넥트 `End.X`, L3VPN 멀티테넌트 VRF 슬라이싱 `End.DT4`/`End.DX6`, MTU 검증 및 패킷 회계 엔진을 정밀하게 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                    Linux Kernel SRv6 (Segment Routing over IPv6) Architecture                    |
+==================================================================================================+

   [ Ingress PE Node (seg6_encap) ]
     Customer IPv4 Packet: [ IP Header | Payload ] (Size: 100B)
               |
               | Applies SRv6 Policy: Segments = [ fc00:3::100, fc00:2::10, fc00:1::1 ]
               v
     +---------------------------------------------------------------------------------------------+
     | Outer IPv6 Header (DA: fc00:1::1, SA: fc00:0::1)                                            |
     | SRH (Type 4, SL=2, Segments=[fc00:3::100 (End.DT4), fc00:2::10 (End.X), fc00:1::1 (End)])  |
     | Inner Payload: Customer Packet                                                              |
     +---------------------------------------------------------------------------------------------+
               |
               | Forward via eth1
               v
   [ Transit Node 1: Matches DA = fc00:1::1 (Action: End) ]
     - Segments Left (SL) > 0 ? (SL = 2 -> 1)
     - Update IPv6 DA = Segments[1] = fc00:2::10
     - Forward via eth1
               |
               v
   [ Transit Node 2: Matches DA = fc00:2::10 (Action: End.X) ]
     - Segments Left (SL) > 0 ? (SL = 1 -> 0)
     - Update IPv6 DA = Segments[0] = fc00:3::100
     - Explicit L3 Cross-Connect: Bypasses RIB lookup, forwards to nexthop via eth2
               |
               v
   [ Egress PE Node: Matches DA = fc00:3::100 (Action: End.DT4) ]
     - Strip Outer IPv6 + SRH Header (Decapsulation!)
     - Extract Inner IPv4 Packet (Dst IP: 10.10.1.50)
     - Lookup route in Tenant VRF Table (vrf_red)
     - Forward purely decapsulated packet to Customer Interface (eth0)
```

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "interfaces": {
      "eth0": {"mtu": 1500, "ip": "fc00:0::1"},
      "eth1": {"mtu": 1500, "ip": "fc00:1::1"}
    },
    "local_sids": {
      "fc00:1::1": {"action": "End", "out_iface": "eth1"},
      "fc00:2::10": {"action": "End.X", "nexthop": "fc00:2::2", "out_iface": "eth2"},
      "fc00:3::100": {"action": "End.DT4", "vrf": "vrf_red"}
    },
    "vrf_tables": {
      "vrf_red": [
        {"prefix": "10.10.1.", "out_iface": "eth0"}
      ]
    }
  },
  "trace": [
    {
      "time": 0,
      "type": "PROCESS_PACKET",
      "packet": {
        "id": 101,
        "in_iface": "eth0",
        "size": 100,
        "encap_policy": {
          "src": "fc00:0::1",
          "segments": ["fc00:final::1", "fc00:1::1"]
        },
        "payload": {"data": "ping"}
      }
    }
  ]
}
```

- `config.interfaces`: 네트워크 인터페이스 목록 및 MTU.
- `config.local_sids`: 로컬 노드가 처리할 SID 주소 및 매핑된 액션 (`End`, `End.X`, `End.DT4`, `End.DX6`).
- `config.vrf_tables`: L3VPN 테넌트별 가상 라우팅 테이블.
- `trace`: 패킷 처리 이벤트 목록 (`PROCESS_PACKET`).

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다 (compact JSON, `ensure_ascii=False`):

```json
{
  "summary": {
    "total_packets": 1,
    "packets_forwarded": 1,
    "packets_dropped": 0,
    "srv6_encapsulated": 1,
    "srv6_decapsulated": 0,
    "sl_decremented": 1,
    "vrf_routes_resolved": 0
  },
  "packet_logs": [
    {
      "time": 0,
      "pkt_id": 101,
      "status": "FORWARDED",
      "out_iface": "eth1",
      "detail": "End -> Next SID fc00:final::1",
      "size": 180
    }
  ],
  "event_logs": [ ... ]
}
```
