# Problem 211: 같은 노드에 있는 파드끼리 통신하는데 왜 iptables와 conntrack을 다 타요?!: 리눅스 커널 eBPF sockops와 sk_msg: 로컬 컨테이너 간 TCP/IP 네트워크 스택 완전 바이패스와 소켓 직접 리다이렉션 (Linux eBPF sockops & sk_msg: Bypassing TCP/IP Stack for Local Pod-to-Pod Communication vs iptables & conntrack Overhead)

## 문제 배경 및 개요

대규모 쿠버네티스(Kubernetes) 클러스터에서 고밀도 마이크로서비스 및 서비스 메시(Istio / Envoy sidecar, Linkerd, Consul)를 운영하는 클라우드 인프라 플랫폼 팀은 동일한 워커 노드(Worker Node) 내부에서 실행 중인 파드-사이드카 간의 초고빈도 통신에서 심각한 **"로컬 컨테이너 네트워크 오버헤드 및 conntrack 테이블 고갈 참사"**를 겪었습니다.

동일 노드 내의 애플리케이션 파드와 Envoy 사이드카 프록시는 초당 수만 건의 로컬 HTTP/gRPC 호출을 주고받는데, 전통적인 리눅스 veth 페어(veth pair) 기반 CNI 네트워크 환경에서는 다음과 같은 극심한 낭비와 장애가 발생했습니다:

```
[레거시 방식: 동일 호스트 내 파드 간 통신인데도 TCP/IP 스택을 2번 왕복!]
App Pod (10.244.1.15)
  │
  ├── 1. TCP 계층: 세그먼트 분할, SEQ/ACK 생성, 체크섬 계산
  ├── 2. IP 계층: 라우팅 테이블 룩업, Netfilter iptables PREROUTING
  ├── 3. Conntrack: 튜플(Tuple) 해시 룩업 및 conntrack 테이블 항목 생성/갱신
  ├── 4. veth 드라이버: 커널 패킷 복사 및 호스트 네임스페이스 전달
  ├── 5. Linux Bridge / OVS: Netfilter FORWARD 및 iptables 체인 순회
  ├── 6. veth 드라이버: Envoy Pod 네임스페이스로 전달
  ├── 7. IP 계층: Netfilter INPUT 체인 평가
  └── 8. TCP 계층: 패킷 재조립, 소켓 수신 큐 버퍼링
Envoy Proxy Pod (10.244.1.16)

==> 왕복 지연시간: 33 ~ 55 us 소요!
==> 단시간에 70,000개의 단기 연결(Short-lived connections)이 쏟아지자,
    nf_conntrack 테이블(65,536 한도)이 가득 차며 "nf_conntrack: table full, dropping packet"
    커널 패닉 발생! 4,464개의 패킷이 증발하며 파드 헬스체크 올스톱!
```

이 참사의 근본 원인은 **"물리적으로 동일한 호스트 메모리에 상주하는 두 소켓 간의 통신임에도, 무거운 커널 네트워크 스택(TCP 세그먼테이션, IP 라우팅, Netfilter iptables 규칙 수백 개 평가, conntrack 상태 추적)을 패킷이 두 번이나 왕복한다"**는 데 있었습니다.

Cilium 등 차세대 eBPF 기반 CNI는 이를 해결하기 위해 **`sockops` (소켓 동작 가로채기)와 `sk_msg` (소켓 메시지 직접 리다이렉션)** 프로그램을 결합한 **호스트 소켓 직접 바이패스(eBPF Host Routing)** 기술을 도입했습니다:

```
[eBPF sockops & sk_msg 가속 경로: TCP/IP 스택 완전 바이패스!]
App Pod (Socket A) ──── sendmsg() 호출 ────┐
                                           │
  ┌────────────────────────────────────────┴────────────────────────────────────────┐
  │ BPF_PROG_TYPE_SOCK_OPS:                                                         │
  │ TCP 핸드셰이크 완료 시 두 소켓이 동일 노드임을 감지하고 BPF SOCKHASH 맵에 페어링 저장! │
  │                                                                                 │
  │ BPF_PROG_TYPE_SK_MSG (bpf_msg_redirect_hash):                                   │
  │ TCP/IP 스택, Netfilter/iptables, conntrack, veth 장치를 100% 바이패스!          │
  │ 소켓 A의 송신 버퍼 페이로드를 소켓 B의 수신 큐(sk_receive_queue)로 즉시 직결 주입!│
  └────────────────────────────────────────┬────────────────────────────────────────┘
                                           │
Envoy Proxy Pod (Socket B) ◄───────────────┘

==> 지연시간: 33.3 us ───> 4.2 us 로 8배 초저지연 달성!
==> conntrack 테이블 항목 생성 = 정확히 0건! (테이블 고갈 패킷 드롭 100% 영구 방어!)
==> iptables 규칙 수백 개 평가 오버헤드 = 정확히 0건!
```

당신은 클라우드 네이티브 네트워크 및 eBPF 코어 엔지니어로서, 레거시 veth/iptables/conntrack 경로와 eBPF sockops/sk_msg 직접 리다이렉션 경로를 정밀하게 모델링하고 성능과 안전성을 평가하는 시뮬레이션 진단 엔진을 완성해야 합니다.

---

## 2대 네트워크 처리 모드 명세

### 1. `LEGACY_TCP_STACK_VETH` (레거시 커널 스택 모드)
- 로컬 파드 간 통신이라 하더라도 veth 페어, IP 라우팅, iptables 규칙 체인, conntrack 튜플 테이블을 모두 거칩니다.
- 신규 연결마다 conntrack 테이블에 엔트리가 추가됩니다.
- 연결 수가 `conntrack_table_max`(예: 65,536개)를 초과하면 커널 테이블 오버플로우(`conntrack_table_overflow = True`)가 발생하여 초과 패킷들이 무차별 폐기(`dropped_packets > 0`)됩니다.
- 평가 판정(Verdict): 패킷 드롭 발생 시 `CONNTRACK_TABLE_EXHAUSTION_PACKET_DROP` (`status: FAILED`), 정상 범위 내인 경우 `LEGACY_STACK_IPTABLES_OVERHEAD`.

### 2. `EBPF_SOCKOPS_SK_MSG_BYPASS` (eBPF 소켓 직접 리다이렉션 모드)
- cgroup v2 기반 `BPF_PROG_TYPE_SOCK_OPS`가 TCP 3-way 핸드셰이크 시점에 소켓을 감지하여 `SOCKHASH` BPF 맵에 등록합니다.
- `BPF_PROG_TYPE_SK_MSG`가 `sendmsg()`를 가로채어 `bpf_msg_redirect_hash()`를 통해 상대방 소켓의 수신 큐로 데이터를 직접 주입합니다.
- **로컬 트래픽은 conntrack 테이블을 전혀 소비하지 않으며(`conntrack_entries = 0`), iptables 규칙도 전혀 평가하지 않습니다.**
- 로컬 파드 통신 지연시간은 $4.2\,\mu\text{s}$로 극단적으로 단축됩니다.
- 단, 원격 노드로 나가는 외부 트래픽은 eBPF 맵에 대상 소켓이 없으므로 표준 네트워크 라우팅 경로로 안전하게 폴백(Fallback)합니다.
- 평가 판정(Verdict): `OPTIMAL_EBPF_SOCKOPS_STACK_BYPASS`.

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "network_config": {
    "node_id": "worker-node-1",
    "conntrack_table_max": 65536,
    "iptables_rules_count": 500,
    "mode": "EBPF_SOCKOPS_SK_MSG_BYPASS",
    "base_costs": {
      "legacy_tcp_ip_stack_latency_us": 25.0,
      "ebpf_sockops_redirect_latency_us": 4.2,
      "iptables_traversal_penalty_per_100_rules_us": 1.5,
      "conntrack_lookup_penalty_us": 0.8
    }
  },
  "endpoints": [
    {"pod_id": "pod-auth", "ip": "10.244.1.15", "node": "worker-node-1"},
    {"pod_id": "envoy-sidecar", "ip": "10.244.1.16", "node": "worker-node-1"},
    {"pod_id": "pod-payments", "ip": "10.244.2.30", "node": "worker-node-2"}
  ],
  "workload": [
    {"src_ip": "10.244.1.15", "dst_ip": "10.244.1.16", "count": 70000, "is_new_connection": true}
  ]
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 진단 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_EBPF_SOCKOPS_STACK_BYPASS",
  "mode": "EBPF_SOCKOPS_SK_MSG_BYPASS",
  "metrics": {
    "total_messages": 70000,
    "successful_messages": 70000,
    "dropped_packets": 0,
    "local_traffic_count": 70000,
    "remote_traffic_count": 0,
    "ebpf_redirected_count": 70000,
    "tcp_ip_stack_bypassed_pct": 100.0,
    "conntrack_entries_created": 0,
    "conntrack_table_overflow": false,
    "average_latency_us": 4.2
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`CONNTRACK_TABLE_EXHAUSTION_PACKET_DROP`**: 레거시 모드에서 단기 연결 폭증으로 인해 `conntrack_table_overflow == True`가 발생하고 패킷이 드롭된 경우 (`status: FAILED`).
2. **`LEGACY_STACK_IPTABLES_OVERHEAD`**: 레거시 모드에서 드롭 없이 완료되었으나 iptables 규칙 순회 및 conntrack 룩업으로 인해 지연시간 오버헤드가 발생한 경우.
3. **`OPTIMAL_EBPF_SOCKOPS_STACK_BYPASS`**: eBPF sockops 및 sk_msg 리다이렉션을 통해 로컬 트래픽을 100% 스택 바이패스하고 conntrack 오염을 방지하여 초저지연을 달성한 경우.
