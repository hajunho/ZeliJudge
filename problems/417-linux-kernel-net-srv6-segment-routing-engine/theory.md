# 이론 문서 417: Linux 커널 5G/클라우드 통신망 SRv6 아키텍처 및 세그먼트 라우팅 내부 원리

## 1. 개요 및 배경 (Historical Context & Motivation)

인터넷과 대규모 통신 사업자 백본망은 수십 년간 IP 홉-바이-홉 라우팅(Hop-by-hop Routing)과 MPLS(Multiprotocol Label Switching)에 의존해 왔습니다.

### 1.1 레거시 MPLS의 구조적 위기
MPLS는 패킷 헤더에 고정 길이의 32비트 라벨을 부착하여 빠른 스위칭을 구현했으나, 다음과 같은 심각한 한계가 존재했습니다:
- **프로토콜 스택 복잡성 (Control-Plane Bloat)**: 라벨 분배를 위해 LDP, RSVP-TE, MP-BGP 등 서로 다른 제어 프로토콜을 네트워크의 모든 전송 노드에서 유지해야 했습니다.
- **코어 상태 폭증 (Stateful Core)**: 트래픽 엔지니어링(TE) 터널마다 중간 라우터가 터널의 예약 대역폭과 경로 상태를 메모리에 유지해야 하므로 수만 개 이상의 터널 운영 시 확장이 불가능했습니다.
- **클라우드 네이티브 호환성 부재**: 컨테이너 및 서버 가상화 환경에서는 MPLS 라벨을 직접 처리하기 어려워 VxLAN, GRE 등 별도의 오버레이 터널링을 이중으로 중첩해야 했습니다.

이 모든 복잡성을 단일한 IPv6 데이터 평면으로 통일하기 위해 탄생한 아키텍처가 바로 **SRv6 (Segment Routing over IPv6)**입니다.

---

## 2. SRv6 데이터 평면: RFC 8754 SRH 구조

SRv6는 IPv6 기본 명세(RFC 8200)에 정의된 확장 헤더(Extension Header) 메커니즘을 그대로 활용합니다.
라우팅 헤더 타입 4로 정의된 **SRH (Segment Routing Header)**의 패킷 레이아웃은 다음과 같습니다:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| Next Header   |  Hdr Ext Len  | Routing Type(4)| Segments Left |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Last Entry   |     Flags     |              Tag              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|            Segment List [0] (128-bit IPv6 Address)            |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|            Segment List [1] (128-bit IPv6 Address)            |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                              ...                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|           Segment List [n-1] (128-bit IPv6 Address)           |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 2.1 세그먼트 배열의 역순 인덱싱 원리
SRH 내부의 `Segment List`는 목적지로부터 역순으로 인덱싱됩니다:
- `Segment List[0]`: 최종 목적지 노드의 SID.
- `Segment List[Last Entry]`: 인그레스 노드가 출발할 때 가장 먼저 방문해야 할 첫 번째 중간 경유지 SID.
- `Segments Left (SL)`: 포인터 역할을 하며, 경유 노드를 통과할 때마다 1씩 감소($\text{SL} \leftarrow \text{SL} - 1$)합니다.
- IPv6 헤더의 목적지 주소(`DA`)는 항상 $\text{DA} = \text{Segment List}[\text{SL}]$로 동기화됩니다.

---

## 3. RFC 8986 SRv6 네트워크 프로그래밍 핵심 동작

리눅스 커널(`net/ipv6/seg6_local.c`)은 패킷의 목적지 주소가 로컬 인터페이스의 SID와 매칭될 때 사전 정의된 가상 네트워크 기능을 즉각 실행합니다:

### 3.1 `End` (Endpoint Function)
- 가장 기본적인 전송 노드 동작입니다.
- 조건: $\text{SL} > 0$
- 동작:
  $$\text{SL} \leftarrow \text{SL} - 1$$
  $$\text{IPv6.DA} \leftarrow \text{Segment List}[\text{SL}]$$
- 갱신된 DA를 기반으로 표준 FIB(Forwarding Information Base) 라우팅을 수행합니다.

### 3.2 `End.X` (Endpoint with Layer-3 Cross-Connect)
- 명시적 경로 제어(Strict Explicit Path Steering)를 수행합니다.
- 동작:
  - $\text{SL}$ 감소 및 DA 갱신 후, 라우팅 테이블 조회를 완전히 건너뛰고 SID 바인딩 시 사전에 지정된 **고정 송신 인터페이스 및 고정 다음 홉(`nexthop`)으로 패킷을 직통 바이패스**합니다.
  - 최단 경로(ECMP)와 무관하게 특정 저지연 전용 회선으로 트래픽을 강제 유도할 수 있습니다.

### 3.3 `End.DT4` (Decapsulation & IPv4 Table Lookup)
- 5G 코어 및 멀티테넌트 BGP L3VPN의 최종 이그레스 노드 동작입니다.
- 동작:
  1. 외부 IPv6 헤더 및 SRH를 완전히 벗겨냅니다(Pop).
  2. 노출된 내부 순수 IPv4 패킷의 목적지 IP를 확인합니다.
  3. 고객 전용 격리 공간인 **VRF (Virtual Routing and Forwarding)** 라우팅 테이블에서 경로를 조회하여 대상 가입자 인터페이스로 전달합니다.
  4. 다른 테넌트 간의 IP 주소 충돌(예: 동일한 `10.0.0.1` 사설망 사용)을 완벽하게 격리합니다.

---

## 4. 성능 및 패킷 오버헤드 수학적 모델

### 4.1 SRv6 캡슐화 패킷 크기 계산
인그레스 노드에서 $N$개의 세그먼트를 가진 SRH를 캡슐화할 때 추가되는 오버헤드는 다음과 같습니다:

$$\Delta L_{\text{SRv6}} = L_{\text{IPv6\_Header}} + L_{\text{SRH\_Base}} + (N \cdot L_{\text{Segment}})$$
여기서:
- $L_{\text{IPv6\_Header}} = 40 \text{ bytes}$
- $L_{\text{SRH\_Base}} = 8 \text{ bytes}$
- $L_{\text{Segment}} = 16 \text{ bytes (128-bit IPv6 SID)}$

따라서 $N=2$ (2개 홉 경유)일 때:
$$\Delta L = 40 + 8 + (2 \times 16) = 80 \text{ bytes}$$

### 4.2 MTU 제약 및 패킷 폐기 조건
원래 가입자 패킷의 크기를 $L_{\text{payload}}$, 송신 물리 인터페이스의 최대 전송 단위를 $\text{MTU}_{\text{out}}$이라 할 때:
$$L_{\text{total}} = L_{\text{payload}} + \Delta L_{\text{SRv6}}$$
$$\text{Drop Policy} = \begin{cases} \text{FORWARD} & \text{if } L_{\text{total}} \le \text{MTU}_{\text{out}} \\ \text{DROP (MTU\_EXCEEDED)} & \text{if } L_{\text{total}} > \text{MTU}_{\text{out}} \end{cases}$$

대규모 5G 백본망에서는 이 80바이트 이상의 오버헤드로 인한 단편화(Fragmentation) 및 패킷 손실을 방지하기 위해 네트워크 전반에 점보 프레임(Jumbo Frame, MTU 9000~9216바이트)을 필수적으로 구성해야 합니다.
