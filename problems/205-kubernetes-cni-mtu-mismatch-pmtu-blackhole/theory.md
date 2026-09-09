# 쿠버네티스 CNI 네트워크: MTU 불일치, PMTU 블랙홀과 TCP MSS Clamping 심층 분석

## 1. 개요: 물리 이더넷과 오버레이 네트워크 캡슐화의 충돌

현대 클라우드 및 컨테이너 오케스트레이션(Kubernetes, OpenShift)에서 파드(Pod) 간 통신은 주로 **오버레이 네트워크(Overlay Network)**를 통해 이루어집니다.  
물리 네트워크 장비의 복잡한 BGP 라우팅이나 L2 VLAN 설정 없이도 서로 다른 서브넷에 위치한 노드 간에 자유롭게 가상 L3 네트워크를 구축할 수 있기 때문입니다.

```
+-------------------------------------------------------------------------+
|                  Overlay Encapsulation Packet Structure                 |
|                                                                         |
|  [Outer Ethernet] [Outer IP] [Outer UDP] [VXLAN Header]                 |
|     (14 Bytes)      (20 Bytes)  (8 Bytes)   (8 Bytes)                   |
|  <---------------------- 50 Bytes Overhead -------------------------->  |
|                                                                         |
|  [Inner IP (Pod Source -> Pod Dest)] [Inner TCP] [User Payload (Data)]  |
|               (20 Bytes)               (20 Bytes)    (e.g. 1460 B)      |
+-------------------------------------------------------------------------+
```

### 캡슐화 오버헤드와 유효 경로 MTU (Effective Path MTU)
- **표준 물리 이더넷 MTU**: **1500 바이트**
- **주요 오버레이 CNI 캡슐화 오버헤드**:
  - **VXLAN (RFC 7348)**: 50 바이트 (14B Outer Eth + 20B Outer IP + 8B UDP + 8B VXLAN)
  - **Geneve (RFC 8926)**: 기본 50 바이트 (가변 옵션 추가 가능)
  - **WireGuard**: IPv4 기준 60 바이트, IPv6 기준 80 바이트
  - **IPSec ESP**: 암호화 알고리즘에 따라 50~70 바이트
- **결과**: 물리 네트워크가 1500바이트를 지원할 때, 터널 내부를 통과할 수 있는 파드의 유효 MTU는 **1450 바이트**(1500 - 50)로 줄어듭니다.

---

## 2. Path MTU Discovery(RFC 1191)와 PMTU 블랙홀 참사

### 2.1 PMTUD의 본래 작동 메커니즘
IP 프로토콜은 패킷 단편화(Fragmentation)로 인한 라우터 부하를 막기 위해 **Path MTU Discovery (PMTUD, RFC 1191)**를 정의합니다:
1. 송신 호스트(파드 커널)는 모든 TCP 패킷의 IP 헤더에 **`DF=1` (Don't Fragment)** 플래그를 설정하여 전송합니다.
2. 중간 라우터/게이트웨이 노드가 자신의 다음 홉 MTU(1450B)보다 큰 패킷(1500B)을 만나면, `DF=1`이 켜져 있으므로 패킷을 쪼개지 못하고 즉시 폐기합니다.
3. 라우터는 송신자에게 **`ICMP Type 3, Code 4 (Destination Unreachable: Fragmentation Needed and DF set)`** 에러 메시지를 보냅니다.
4. 송신자는 이 ICMP 패킷에 적힌 `Next-Hop MTU (1450)`를 확인하고, 자신의 경로 MTU 캐시를 업데이트하여 MSS를 줄여서 재전송합니다.

### 2.2 클라우드 환경의 현실: ICMP 차단과 블랙홀 참사
```
[Pod A (veth: 1500)]                                     [Node B / Gateway]
         │                                                        │
         ├─── TCP SYN (60B) ────────────────────────────────────> │ (통과!)
         │<── TCP SYN-ACK (60B) ──────────────────────────────────┤ (통과!)
         ├─── TCP ACK (60B) ────────────────────────────────────> │ (연결 수립!)
         │                                                        │
         ├─── TLS ClientHello (1500B, DF=1) ────────────────────> ┼── [DROP!]
         │                                                        │ (1550B > 1500B)
         │                                                        │
         │    [Firewall / Cloud Security Group: ICMP DROP!]       │
         │    <xxx ICMP Type 3 Code 4 (Next-Hop MTU 1450) xxxxx──┤
         │                                                        │
         ├─── [재전송 1: 1500B] ────────────────────────────────> ┼── [DROP!]
         ├─── [재전송 2: 1500B] ────────────────────────────────> ┼── [DROP!]
         │    ... (15분간 무한 재전송 후 Socket Timeout 폭사) ... │
```

- **보안 장비의 무차별 ICMP 차단**: 대부분의 기업 사내 방화벽, 클라우드 Security Group, WAF는 "Ping 디도스 공격이나 네트워크 정찰을 막는다"는 명목으로 모든 ICMP 트래픽을 일괄 차단(Drop)합니다.
- **블랙홀의 탄생**:
  - `ICMP Type 3 Code 4`가 방화벽에서 증발하므로, 파드는 패킷이 버려졌다는 사실조차 알지 못합니다.
  - 파드는 패킷이 일시적으로 유실되었다고 오판하여 동일한 1500바이트 패킷을 지수 백오프(Exponential Backoff)로 계속 재전송합니다.
  - 패킷은 라우터에서 소리 없이 계속 버려지고, 결국 애플리케이션은 영구 타임아웃에 빠집니다.

### 2.3 실무 엔지니어가 마주하는 기괴한 증상
- `ping`은 잘 감 (패킷 크기 64~84바이트).
- `curl`로 연결 시 TCP 핸드셰이크(SYN-ACK)는 1ms 만에 체결됨.
- 소형 HTTP GET 요청은 정상 응답을 반환함.
- **그러나 대규모 JSON 응답, 대용량 파일 업로드, 또는 SSL/TLS 인증서 체인 교환(Handshake) 시점에 프로세스가 얼어붙고 영구 타임아웃 발생!**

---

## 3. 구원 아키텍처: iptables TCP MSS Clamping

이 문제를 근본적으로 해결하기 위해 리눅스 커널 넷필터(Netfilter)와 CNI는 **TCP MSS Clamping (MSS 클램핑)**을 제공합니다.

```
+-------------------------------------------------------------------------+
|                  iptables TCP MSS Clamping Architecture                 |
|                                                                         |
|  [Pod A]                                                  [Remote Pod]  |
|  Advertises MSS = 1460 (veth MTU 1500)                                  |
|         │                                                               |
|         ├─── TCP SYN (MSS=1460) ───┐                                    |
|                                    │                                    |
|     +------------------------------v------------------------------+     |
|     | Node Gateway: iptables -t mangle -A POSTROUTING             |     |
|     | -p tcp --tcp-flags SYN,RST SYN                              |     |
|     | -j TCPMSS --clamp-mss-to-pmtu                               |     |
|     | => SYN 헤더의 MSS 값을 1460에서 1410으로 강제 재작성!       |     |
|     +------------------------------┬------------------------------+     |
|                                    │                                    |
|         <─── TCP SYN-ACK (MSS=1410)┴─────────────────────────────────┤ |
|                                                                         |
|  ★ 결과: 양단이 MSS=1410으로 합의하므로,                                |
|    어떤 데이터 패킷도 1450B를 초과하지 않아 ICMP 없이도 100% 무손실 통신!|
+-------------------------------------------------------------------------+
```

### 3.1 작동 메커니즘
1. 클라이언트 파드가 보낸 TCP SYN 패킷이 호스트 노드의 `mangle` 테이블 `POSTROUTING` 체인을 통과할 때, 커널이 TCP 옵션 필드를 검사합니다.
2. 커널은 송신자가 광고한 `MSS` 값(1460)을 해당 인터페이스의 유효 MTU에서 IP/TCP 헤더(40바이트)를 뺀 값인 **1410**으로 강제 덮어씁니다.
3. 수신측 서버 역시 이 클램핑된 MSS(1410)를 받아들이고, 자신도 1410 이하의 크기로만 패킷을 전송합니다.
4. **결과**:
   - 최대 패킷 크기 = 1410 (Payload) + 40 (IP/TCP) = 1450 바이트.
   - 50바이트 터널 헤더가 붙어도 $1450 + 50 = 1500 \le 1500$ 물리 MTU.
   - 단 하나의 패킷도 MTU를 초과하지 않으므로 **ICMP 오류가 전혀 발생하지 않고, 방화벽 ICMP 차단과 무관하게 100% 완벽한 유선 속도 통신**이 보장됩니다.

---

## 4. 해결책 종합 비교 및 프로덕션 권장 설정

| 해결 방안 | 구현 방식 | 장점 | 단점 / 고려사항 |
|---|---|---|---|
| **iptables TCP MSS Clamping** | `iptables -t mangle -A POSTROUTING -j TCPMSS --clamp-mss-to-pmtu` | **파드 설정 무관, ICMP 차단 환경에서도 완벽 작동** | TCP에만 적용 가능 (UDP/QUIC는 적용 불가) |
| **CNI veth MTU 수동 정합** | CNI Config에 `veth_mtu: 1450` 명시 | 파드 인터페이스 자체가 1450으로 생성됨 | 기존 파드 재기동 필요, 멀티 클러스터 관리 부담 |
| **물리 언더레이 점보 프레임** | 스위치 및 물리 호스트 MTU 9000 적용 | 1500B 파드 패킷을 클램핑 없이 최고 속도 수용 | 데이터센터 전체 네트워크 장비 점보 프레임 지원 필수 |

### 프로덕션 실무 튜닝 명령어
```bash
# Calico / Flannel / Cilium 노드에서 자동 클램핑 적용
iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# 또는 안전 마진을 두어 명시적 1410 (또는 IPSec 시 1400) 고정 클램핑
iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1410
```
