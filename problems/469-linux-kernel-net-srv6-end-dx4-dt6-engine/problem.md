# 리눅스 커널 SRv6 (Segment Routing IPv6) End.DX4 / End.DT6 전송 및 캡슐화 해제 엔진

## 1. 개요 및 배경

기존 통신사 코어망과 대규모 데이터센터에서 널리 쓰이던 MPLS(Multiprotocol Label Switching)는 경로상의 모든 라우터가 LDP/RSVP-TE 프로토콜을 통해 레이블 상태(State)를 분배하고 유지해야 했습니다. 이로 인해 5G 네트워크 슬라이싱(Network Slicing) 및 초대규모 클라우드 오버레이 네트워크에서 **상태 폭발(State Explosion)**과 프로토콜 복잡성 문제가 심각해졌습니다.

IETF 표준(RFC 8986, RFC 8754)과 리눅스 커널 4.10부터 도입된 **SRv6(Segment Routing over IPv6, `net/ipv6/seg6.c`, `net/ipv6/seg6_local.c`)**는 MPLS 레이블을 완전히 폐기하고, 표준 IPv6 확장 헤더인 **세그먼트 라우팅 헤더(Segment Routing Header, SRH)**에 소스 라우팅 지시자를 직접 인코딩합니다:
1. **상태 없는 소스 라우팅(Stateless Source Routing)**: 중간 노드는 흐름(Flow)별 상태를 전혀 기억할 필요가 없으며, 패킷 헤더의 세그먼트 목록(Segment List)을 보고 다음 목적지를 판별합니다.
2. **세그먼트 식별자(SID, Segment Identifier)**: 128비트 표준 IPv6 주소 형태를 띠며, 패킷이 도달했을 때 수행할 동작(Action/Behavior)과 파라미터를 지정합니다.
3. **핵심 SRv6 동작(Behaviors)**:
   - **`End` (Transit)**: 중간 라우터 경유. `segments_left`를 1 감소시키고, 다음 세그먼트 SID를 IPv6 목적지 주소(`daddr`)에 복사하여 FIB 포워딩합니다.
   - **`End.DX4` (Decapsulation & IPv4 Cross-Connect)**: Egress PE(Provider Edge) 라우터에서 동작. 외곽 IPv6 헤더와 SRH를 벗겨내고(Decapsulation), 내부 IPv4 패킷을 추출하여 지정된 IPv4 차기 홉(`nh4`) 또는 인터페이스로 직결 포워딩합니다.
   - **`End.DT6` (Decapsulation & Specific IPv6 Table Lookup)**: Egress 라우터에서 외곽 헤더를 제거하고, 내부 IPv6 패킷을 특정 가상 라우팅 포워딩(VRF) 테이블(`vrf_table_id`)에서 조회하여 격리된 멀티테넌트 네트워크로 라우팅합니다.

본 과제에서는 리눅스 커널의 SRv6 로컬 SID 테이블 파싱, `End` 트랜짓 갱신, `End.DX4` IPv4 캡슐화 해제, `End.DT6` VRF 조회를 구현하고 홉 리밋(Hop Limit) 만료 및 헤더 오류 탐지를 완벽히 검증하는 SRv6 포워딩 엔진을 개발합니다.

---

## 2. 아키텍처 다이어그램

```
Incoming SRv6 Packet:
+-------------------+-----------------------------------+-----------------------+
| Outer IPv6 Header | Segment Routing Header (SRH)      | Inner Payload         |
| dst: Active SID   | segments: [SID0, SID1, SID2]      | IPv4 or IPv6 VPN Pkt  |
| hop_limit: N      | segments_left: L                  | data: ...             |
+-------------------+-----------------------------------+-----------------------+
                                    |
                                    v (Look up outer dst in local_sids table)
+-------------------------------------------------------------------------------+
|                       Linux Kernel seg6_local.c Actions                       |
|                                                                               |
|   [ Action: End ]              [ Action: End.DX4 ]      [ Action: End.DT6 ]   |
|   - segments_left -= 1         - Verify L == 0          - Verify L == 0       |
|   - dst = segments[L]          - Strip Outer IPv6+SRH   - Strip Outer IPv6+SRH|
|   - Forward via Global FIB     - Forward to nh4/out_if  - Lookup in VRF Table |
+-------------------------------------------------------------------------------+
           |                                  |                        |
           v (Next Hop)                       v (Egress IPv4)          v (Egress IPv6)
    [ Backbone Router ]                [ Customer Edge IPv4 ]   [ Tenant VRF Pod ]
```

---

## 3. 핵심 규칙 및 상태 전이 모델

### 3.1 홉 리밋 검사
- 수신 시 `outer_ipv6.hop_limit <= 1`이면 `TIME_EXCEEDED_HOP_LIMIT`로 즉시 드롭(`DROP`).

### 3.2 동작별 세부 처리
1. **`End` (중간 세그먼트 전송)**:
   - `srh.segments_left <= 0`이면 드롭 (`INVALID_SRH_SEGMENTS_LEFT`).
   - `srh.segments_left -= 1`.
   - `new_dst = srh.segments[srh.segments_left]`.
   - `outer_ipv6.dst = new_dst`, `outer_ipv6.hop_limit -= 1`.
   - FIB 조회 후 다음 홉 인터페이스로 전송 (`status: "TRANSIT_END"`).

2. **`End.DX4` (IPv4 캡슐화 해제)**:
   - `srh.segments_left != 0`이면 드롭 (`DX4_SEGMENTS_LEFT_NOT_ZERO`).
   - `inner_payload.type != "IPV4"`이면 드롭 (`DX4_PAYLOAD_NOT_IPV4`).
   - 외곽 IPv6 및 SRH 제거 후, 내부 IPv4 패킷을 `nh4`와 `out_if`로 전달 (`status: "DECAP_DX4"`).

3. **`End.DT6` (IPv6 캡슐화 해제 및 VRF 조회)**:
   - `srh.segments_left != 0`이면 드롭 (`DT6_SEGMENTS_LEFT_NOT_ZERO`).
   - `inner_payload.type != "IPV6"`이면 드롭 (`DT6_PAYLOAD_NOT_IPV6`).
   - 외곽 IPv6 및 SRH 제거 후, 내부 IPv6 패킷의 `dst`를 지정된 `vrf_table`에서 검색.
   - 라우트 미발견 시 드롭 (`VRF_ROUTE_LOOKUP_FAILED`).
   - 발견 시 해당 다음 홉으로 전달 (`status: "DECAP_DT6"`).

4. **일반 IPv6 포워딩 (`IP_FORWARD`)**:
   - 목적지 주소가 `local_sids`에 등록되어 있지 않은 경우, SRH를 수정하지 않고 일반 FIB 조회를 거쳐 전송.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {
    "local_sids": {
      "2001:db8:cafe:1::": {"action": "End"},
      "2001:db8:cafe:dx4::": {"action": "End.DX4", "nh4": "192.168.10.1", "out_if": "eth1"},
      "2001:db8:cafe:dt6::": {"action": "End.DT6", "vrf_table": 100}
    },
    "fib": {
      "2001:db8:cafe:2::": {"next_hop": "fe80::router2", "out_if": "eth0"}
    },
    "vrf_tables": {
      "100": {
        "2001:db8:user:1::10": {"next_hop": "fe80::client10", "out_if": "vrf100-veth"}
      }
    }
  },
  "operations": [
    {
      "type": "ROUTE_PACKET",
      "packet": {
        "outer_ipv6": {"src": "2001:db8:src::1", "dst": "2001:db8:cafe:1::", "hop_limit": 64},
        "srh": {"segments": ["2001:db8:cafe:dx4::", "2001:db8:cafe:2::", "2001:db8:cafe:1::"], "segments_left": 2, "last_entry": 2},
        "inner_payload": {"type": "IPV4", "src": "10.0.0.1", "dst": "192.168.1.100"}
      }
    },
    {"type": "QUERY_STATS"}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "ROUTE_PACKET",
      "status": "TRANSIT_END",
      "new_dst": "2001:db8:cafe:2::",
      "segments_left": 1,
      "next_hop": "fe80::router2",
      "out_if": "eth0"
    },
    {
      "op_index": 1,
      "type": "QUERY_STATS",
      "stats": {
        "transit_end": 1,
        "decap_dx4": 0,
        "decap_dt6": 0,
        "ip_forward": 0,
        "dropped": 0
      }
    }
  ],
  "summary": {
    "total_operations": 2,
    "stats": {
      "transit_end": 1,
      "decap_dx4": 0,
      "decap_dt6": 0,
      "ip_forward": 0,
      "dropped": 0
    }
  }
}
```
