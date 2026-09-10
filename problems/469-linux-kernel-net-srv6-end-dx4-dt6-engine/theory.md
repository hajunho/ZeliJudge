# 리눅스 커널 SRv6(Segment Routing over IPv6) 및 네트워크 기능 가상화 이론

## 1. MPLS의 한계와 SRv6 패러다임 전환

전통적인 서비스 프로바이더 백본 망에서는 BGP/MPLS IP VPN(RFC 4364)이 표준이었습니다.
그러나 MPLS는 다음과 같은 구조적 복잡성을 내포합니다:
1. **프로토콜 스택 과밀화**: IGP(OSPF/IS-IS) 위에 LDP, RSVP-TE, BGP가 계층적으로 동작하며 제어 평면(Control Plane) 부하 가중.
2. **미드포인트 라우터의 상태 유지**: RSVP-TE 터널마다 각 라우터가 레이블 스위칭 테이블(ILM/FTN)을 유지해야 하여 확장성 한계.
3. **IPv6 친화성 부족**: MPLS 32비트 레이블 스택은 IPv6 네이티브 헤더와 분리되어 있어 방화벽, 로드밸런서 등 L4-L7 미들박스가 내부 패킷을 검사하기 어렵습니다.

**SRv6(Segment Routing over IPv6)**는 소스 라우팅(Source Routing) 개념을 부활시켜, 소스 노드가 전체 서비스 체이닝(Service Chaining) 및 트래픽 엔지니어링(TE) 경로를 128비트 IPv6 주소 배열(Segment List) 형태로 패킷에 직접 담아 송신합니다.

---

## 2. 세그먼트 라우팅 헤더 (SRH, RFC 8754)

SRH는 IPv6 라우팅 확장 헤더(Routing Type 4)로 인코딩됩니다:
```c
struct ipv6_sr_hdr {
    __u8    nexthdr;
    __u8    hdrlen;
    __u8    type;          /* 4 = Segment Routing Header */
    __u8    segments_left; /* 현재 활성 세그먼트의 인덱스 */
    __u8    first_segment; /* 세그먼트 목록의 마지막 인덱스 (Last Entry) */
    __u8    flags;
    __u16   tag;
    struct in6_addr segments[0]; /* 역순으로 저장된 IPv6 SIDs */
};
```

- `segments[]` 배열은 **역순**으로 저장됩니다:
  `segments[first_segment]`가 첫 번째 경유지이며, `segments[0]`이 최종 목적지입니다.
- 패킷의 외곽 IPv6 `daddr`는 항상 `segments[segments_left]`와 일치합니다.
- 패킷이 경유지에 도착할 때마다 `segments_left`가 1씩 감소하며, 다음 목적지가 `daddr`로 치환됩니다.

---

## 3. 리눅스 커널 `seg6_local` 서브시스템 및 동작(Behaviors)

리눅스 커널은 `ip route` 명령어를 통해 특정 IPv6 주소를 수신했을 때 실행할 액션을 `seg6_local` 모듈(`net/ipv6/seg6_local.c`)에 등록할 수 있습니다:

```bash
# End 동작 등록 (트랜짓 포워딩)
ip -6 route add 2001:db8:cafe:1:: encap seg6local action End dev eth0

# End.DX4 동작 등록 (IPv4 Decapsulation & Cross-connect)
ip -6 route add 2001:db8:cafe:dx4:: encap seg6local action End.DX4 nh4 192.168.10.1 dev eth1

# End.DT6 동작 등록 (IPv6 Decapsulation & VRF 100 테이블 조회)
ip -6 route add 2001:db8:cafe:dt6:: encap seg6local action End.DT6 table 100 dev eth0
```

### 3.1 End.DX4의 패킷 처리 파이프라인
1. `skb`의 외곽 IPv6 헤더 및 SRH 유효성 검증 (`segments_left == 0`).
2. `pskb_pull()`을 통해 외곽 IPv6 헤더(40바이트)와 가변 길이 SRH를 스트립.
3. 내부 페이로드가 유효한 IPv4 헤더(`version == 4`)인지 확인.
4. 패킷의 네트워크 프로토콜을 `ETH_P_IP`로 변경하고, 지정된 `nh4` 게이트웨이로 바로 송출.

### 3.2 End.DT6의 패킷 처리 파이프라인
1. 외곽 헤더 스트립 후 내부 IPv6 패킷 추출.
2. `fib6_table_lookup()` 함수를 호출하여 기본 라우팅 테이블(Main Table)이 아닌 테넌트 격리 테이블(`table 100`)에서 목적지 주소 조회.
3. 테넌트 전용 가상 인터페이스(veth / cilium_net)로 포워딩.

SRv6는 5G 모바일 백홀망의 네트워크 슬라이싱, 쿠버네티스(Cilium eBPF SRv6) 서비스 메시, 그리고 하이퍼스케일 클라우드 WAN 백본에서 미래 네트워킹의 핵심 기반 기술로 확고히 자리잡았습니다.
