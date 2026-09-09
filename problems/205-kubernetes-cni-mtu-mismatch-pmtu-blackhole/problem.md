# 쿠버네티스 CNI 네트워크: veth MTU 불일치, PMTU Discovery 블랙홀과 iptables TCP MSS Clamping

## 문제 배경 및 개요
글로벌 엔터프라이즈 하이브리드 클라우드 환경에서 운영되는 쿠버네티스(Kubernetes) 클러스터는 노드 간 파드 통신을 위해 오버레이 네트워크 CNI(Calico, Cilium, Flannel, VXLAN, Geneve)를 사용합니다.
오버레이 네트워크는 파드가 보낸 오리지널 IP 패킷에 외부 UDP 및 터널 헤더(VXLAN 50바이트, WireGuard/IPSec 60~80바이트)를 덧씌워 물리 언더레이(Underlay) 네트워크로 전송합니다.

물리 이더넷의 표준 MTU(Maximum Transmission Unit)는 1500바이트입니다.  
따라서 오버레이 터널을 통과할 수 있는 유효 경로 MTU(Effective Path MTU)는 **1450바이트**(1500 - 50바이트 터널 헤더)로 줄어듭니다.

그런데 클러스터에 배포된 파드의 가상 이더넷 인터페이스(`veth`)가 기본값인 **MTU 1500**으로 잘못 설정되어 있을 때, 클라우드 인프라 전역에서 기이하고 치명적인 네트워크 마비 현상이 발생했습니다:

1. **"핑도 가고 TCP 연결도 되는데, 데이터만 보내면 굳어버려요!" (MTU 블랙홀 참사)**:
   - `ping`이나 `curl -I`는 아주 작은 패킷(60~100바이트)만 주고받으므로 1450바이트 한도에 걸리지 않아 정상 통과합니다.
   - TCP 3-Way Handshake(SYN, SYN-ACK, ACK) 역시 옵션 포함 60바이트 내외이므로 즉각 수립됩니다.
   - 그러나 HTTPS 통신이 시작되어 서버가 **거대한 TLS 인증서 체인(2KB~4KB)**을 보내거나, 클라이언트가 대용량 JSON/파일을 업로드하는 순간:
     - 파드 커널은 MTU 1500에 맞춰 MSS 1460 크기의 거대한 TCP 세그먼트를 생성합니다.
     - 리눅스 TCP 스택은 기본적으로 IP 헤더에 **`DF=1` (Don't Fragment, 단편화 금지)** 플래그를 설정합니다.
     - 이 패킷이 게이트웨이 노드(터널 진입점)에 도착하면, 터널 헤더가 붙어 총 크기가 1550바이트가 되므로 물리 MTU 1500을 초과합니다.
     - 게이트웨이 라우터는 `DF=1` 때문에 패킷을 쪼개지 못하고 **전량 폐기(Drop)**합니다.
2. **방화벽의 ICMP 차단과 영구 타임아웃 (`PMTU_BLACKHOLE_PACKET_DROP`)**:
   - RFC 1191 Path MTU Discovery(PMTUD) 명세에 따르면, 라우터는 패킷을 버리면서 송신자에게 `ICMP Type 3 Code 4 (Destination Unreachable: Fragmentation Needed and DF set, Next-Hop MTU 1450)` 에러 패킷을 보내야 합니다.
   - 송신자 파드가 이 ICMP를 받으면 패킷 크기를 1450 이하로 줄여서 재전송합니다.
   - **하지만 대부분의 클라우드 Security Group, 엔터프라이즈 방화벽, 로드 밸런서는 "보안상 위험하다"는 맹목적 이유로 모든 ICMP 패킷을 무차별 차단(Drop)하고 있습니다!**
   - 송신 파드는 ICMP 오류를 영원히 받지 못하므로, 패킷이 왜 안 가는지 모른 채 동일한 1500바이트 패킷을 무한 재전송(TCP Retransmission)하다가 수십 초~수 분 뒤 영구 타임아웃으로 연결이 끊어집니다.

이를 해결하기 위해 쿠버네티스 CNI와 리눅스 커널은 **iptables TCP MSS Clamping**을 표준 해결책으로 채택했습니다:
- 노드의 라우팅 경계(`iptables -t mangle -A POSTROUTING`)에서 모든 TCP SYN 패킷의 옵션 헤더를 실시간 인터셉트합니다.
- 송신자가 광고한 `MSS=1460`을 터널 경로에 맞춰 강제로 **`MSS=1410` (1450 MTU - 40바이트 IP/TCP 헤더)**으로 하향 조정(Clamping)하여 재작성합니다.
- 양단 간에 MSS 1410으로 합의되므로, 애플리케이션은 처음부터 1450바이트를 초과하는 패킷을 절대 만들지 않아 **ICMP 차단 환경에서도 패킷 폐기 0건, 단편화 0건, 100% 무손실 유선 속도 통신**을 달성합니다 (`OPTIMAL_TCP_MSS_CLAMPING_PMTU_TUNED`).

당신은 CNI 네트워크 경로 시뮬레이터를 구현하여, MTU 불일치와 ICMP 차단으로 인한 PMTU 블랙홀 참사를 재현하고, TCP MSS Clamping을 통한 완벽한 구원 동작을 검증해야 합니다.

---

## 시스템 동작 규칙 및 상태 머신

### 1. 유효 경로 MTU (Effective Path MTU) 계산
- `effective_path_mtu = underlay_physical_mtu - tunnel_overhead_bytes`
- 예: 물리 MTU 1500, VXLAN 오버헤드 50 -> 유효 경로 MTU = 1450바이트.
- 표준 IPv4 + TCP 기본 헤더 크기: `IP_TCP_HEADER_SIZE = 40` 바이트.

### 2. TCP 핸드셰이크 및 MSS 협상 (MSS Negotiation)
- 클라이언트 파드는 자신의 veth MTU를 기준으로 `client_mss = pod_veth_mtu - 40` (기본 1460)을 광고합니다.
- **TCP MSS Clamping 미적용 (`tcp_mss_clamping_enabled == False`)**:
  - `negotiated_mss = client_mss` (1460)으로 유지됩니다.
- **TCP MSS Clamping 적용 (`tcp_mss_clamping_enabled == True`)**:
  - `clamped_mss_target`이 지정되어 있으면 해당 값으로, 없으면 `auto_clamp = effective_path_mtu - 40` (예: 1410)으로 강제 하향 조정(Clamping)됩니다.
  - `negotiated_mss = min(client_mss, target_or_auto)`

### 3. 패킷 전송 및 터널 통과 검사
- SYN 핸드셰이크 패킷은 항상 60바이트로 유효 MTU를 통과합니다.
- 데이터 패킷의 물리 유선 크기: `wire_packet_size = payload_bytes + 40`.
- **경로 판정**:
  - `wire_packet_size <= effective_path_mtu`:
    - 패킷이 손실 없이 정상 전달됩니다 (`packets_delivered_line_rate += 1`).
  - `wire_packet_size > effective_path_mtu`:
    - **`df_bit == True`인 경우**:
      - 라우터가 패킷을 즉시 폐기합니다 (`packets_dropped_mtu_exceeded += 1`, `icmp_frag_needed_sent += 1`).
      - `icmp_fragmentation_needed_blocked == False`:
        - ICMP Type 3 Code 4 패킷이 송신자에게 도달(`icmp_frag_needed_delivered += 1`)하여, 송신자가 자율적으로 MSS를 1410으로 축소 재전송합니다.
      - `icmp_fragmentation_needed_blocked == True`:
        - ICMP 패킷이 방화벽에 의해 증발합니다. 송신자는 원인을 알지 못한 채 재전송을 반복하며 연결이 영구 동결(Blackhole Hang)됩니다 (`pmtu_blackhole_hangs_detected += 1`).
    - **`df_bit == False`인 경우**:
      - 단편화(Fragmentation)가 허용되어 패킷이 쪼개져 전달되지만 심각한 라우터 CPU 부하 및 처리량 저하가 발생합니다.

---

## 판정 기준 (System Status)

1. `PMTU_BLACKHOLE_PACKET_DROP`:
   - `pmtu_blackhole_hangs_detected > 0`: veth MTU가 터널 MTU보다 큰 상태에서 `DF=1` 대형 패킷이 버려지고 ICMP까지 차단되어 연결이 영구 동결된 상태.
2. `IP_FRAGMENTATION_OVERHEAD_COLLAPSE`:
   - TCP MSS Clamping이 꺼져 있고, `DF=0`으로 인해 패킷 단편화 오버헤드가 발생한 상태.
3. `OPTIMAL_TCP_MSS_CLAMPING_PMTU_TUNED`:
   - TCP MSS Clamping이 정상 작동하여 SYN 단계에서 MSS가 터널 MTU 이하로 강제 정합되었거나, 점보 프레임 언더레이로 패킷 드롭 0건을 달성한 상태.

---

## 입력 형식
표준 입력(`sys.stdin`)으로 다음 필드를 갖는 단일 JSON 객체가 주어집니다:
- `network_config`: 네트워크 및 CNI 터널 환경 설정
  - `pod_veth_mtu`: 파드 veth 인터페이스 MTU (기본 1500)
  - `tunnel_overhead_bytes`: 오버레이 캡슐화 헤더 바이트 (정수, 예: 50 for VXLAN, 60 for IPSec)
  - `underlay_physical_mtu`: 언더레이 물리 네트워크 MTU (정수, 기본 1500)
  - `icmp_fragmentation_needed_blocked`: 방화벽의 ICMP Type 3 Code 4 차단 여부 (boolean)
  - `tcp_mss_clamping_enabled`: iptables TCP MSS Clamping 활성화 여부 (boolean)
  - `clamped_mss_target`: 수동 지정할 목표 MSS 크기 (선택적 정수, 생략 시 자동 계산)
- `tcp_connections`: 시뮬레이션할 TCP 연결 목록
  - `connection_id`: 연결 식별자 문자열
  - `client_advertised_mss`: 클라이언트가 최초 광고한 MSS (정수)
  - `packets`: 전송되는 패킷 목록
    - `type`: `"SYN"` 또는 `"DATA"`
    - `payload_bytes`: TCP 페이로드 바이트 수 (정수)
    - `df_bit`: IP Don't Fragment 비트 활성화 여부 (boolean, 기본 true)

---

## 출력 형식
표준 출력(`sys.stdout`)으로 다음 필드를 갖는 단일 JSON 객체를 인덴트 2칸(`indent=2`)으로 출력해야 합니다:
- `status`: 판정 결과 문자열 (`PMTU_BLACKHOLE_PACKET_DROP` | `IP_FRAGMENTATION_OVERHEAD_COLLAPSE` | `OPTIMAL_TCP_MSS_CLAMPING_PMTU_TUNED`)
- `metrics`:
  - `total_connections`: 총 TCP 세션 수
  - `total_packets_sent`: 전송 시도된 총 패킷 수
  - `packets_delivered_line_rate`: 정상 유선 속도로 전달된 패킷 수
  - `packets_dropped_mtu_exceeded`: MTU 초과로 폐기된 패킷 수
  - `icmp_frag_needed_sent`: 라우터가 발생시킨 ICMP Type 3 Code 4 패킷 수
  - `icmp_frag_needed_delivered`: 클라이언트에게 실제 도달한 ICMP 패킷 수
  - `pmtu_blackhole_hangs_detected`: ICMP 유실로 영구 타임아웃에 빠진 연결 수
  - `effective_mss_negotiated`: 최종 협상/클램핑된 유효 MSS 바이트
- `root_cause_analysis`: 한국어 원인 분석 및 아키텍처 진단 메시지
