# Linux 커널 네트워킹: eBPF sockmap & sk_msg Zero-Copy TCP 스택 바이패스 가속 엔진

## 문제 설명

대규모 클라우드 네이티브 쿠버네티스(Kubernetes) 환경과 마이크로서비스 아키텍처(MSA), 그리고 사이드카 프록시(Envoy / Istio Service Mesh) 기반 인프라에서는 수많은 컨테이너 파드(Pod)들이 **동일한 호스트(Co-located Host)** 위에서 실행됩니다.

그러나 전통적인 리눅스 커널 네트워킹 모델에서는同一 호스트 내 파드 간 통신이라 하더라도 다음과 같은 방대하고 비효율적인 전체 TCP/IP 스택을 통과해야 합니다:
1. `sendmsg()` 시스템 콜 $\rightarrow$ TCP 버퍼 할당 및 세그먼테이션 (`tcp_sendmsg_locked`)
2. TCP 혼잡 제어 알고리즘(BBR/CUBIC) 및 페이싱, 송신 윈도우 계산
3. L3 IP 계층 라우팅 테이블 룩업 (`ip_route_output_key`)
4. Netfilter / iptables / conntrack 상태 추적(Connection Tracking) 테이블 검색
5. 가상 이더넷(`veth`) 또는 루프백(`lo`) 인터페이스 드라이버 큐잉
6. 소프트웨어 인터럽트(SoftIRQ `NET_RX_SOFTIRQ`) 및 스케줄링 지연
7. 수신측 conntrack 역방향 룩업, IP 헤더 검증, TCP 재조립 버퍼링
8. 수신 확인을 위한 반대 방향 TCP ACK 패킷 전송 및 왕복 지연

이로 인해 로컬 통신임에도 패킷당 $25\sim 30\mu\text{s}$의 지연시간과 바이트당 10~15회의 불필요한 CPU 사이클이 낭비되며, 사이드카 프록시를 경유하는 경우 이 비효율이 2배로 증폭됩니다.

이 병목을 해결하기 위해 리눅스 커널 4.14+ (Daniel Borkmann, John Fastabend 등)부터 도입되고 Cilium Service Mesh의 핵심 가속 기술로 사용되는 **`eBPF sockmap`(`net/core/sock_map.c`, `kernel/bpf/sockmap.c`)** 아키텍처는 혁신적인 제로카피 바이패스(Zero-Copy TCP Bypass)를 실현합니다:

```
[ Traditional Path: Full TCP/IP Stack Traversal (28.5 us) ]
User Socket A ---> [TCP Seg] ---> [L3 Routing] ---> [Netfilter/conntrack] ---> [lo/veth] 
                                                                                   |
User Socket B <--- [TCP Rx Queue] <--- [conntrack] <--- [IP Recv] <--- [SoftIRQ] <-+
  + Round-trip TCP ACKs and softirq overhead!

[ eBPF sockmap / sk_msg Direct Redirection Path (4.2 us) ]
User Socket A ---> [BPF_PROG_TYPE_SK_MSG] 
                         |
                         | (Zero-Copy Splicing directly into target socket's sk_receive_queue!)
                         v
User Socket B ---> [Target Socket sk_receive_queue]  <--- Ready for immediate read()!
(Bypasses: TCP Segmentation, Congestion Control, IP Routing, Netfilter, Veth, SoftIRQ, TCP ACKs!)
```

### 서브시스템 구성 및 작동 원리:
1. **`BPF_PROG_TYPE_SOCK_OPS` (소켓 연결 추적 및 맵 등록)**:
   - cgroup 단위로 부착되어 소켓 상태 전이 이벤트(`ACTIVE_ESTABLISHED`, `PASSIVE_ESTABLISHED`)를 후킹합니다.
   - 소켓의 4-Tuple(`src_ip`, `src_port`, `dst_ip`, `dst_port`)을 검사하여 양쪽 엔드포인트가 모두 동일 호스트의 로컬 서브넷(`co_located_subnets`)에 속하는 경우, `bpf_sock_hash_update()`를 호출하여 커널 소켓 참조를 `sockmap`(`BPF_MAP_TYPE_SOCKMAP` 또는 `SOCKHASH`)에 등록합니다.
   - 소켓이 종료(`SOCK_CLOSED`)되면 맵에서 안전하게 제거합니다.
2. **`BPF_PROG_TYPE_SK_MSG` (송신 메시지 인터셉트 및 버딕트 결정)**:
   - 유저 공간 프로세스가 `sendmsg()`를 호출하는 즉시 TCP 계층 이전에 메시지 버퍼(`sk_msg`)를 가로챕니다.
   - 규칙(`sk_msg_rules`)에 따라 3가지 판정(Verdict)을 내립니다:
     - `SK_DROP`: 악성 패턴(SQL Injection, 익스플로잇 토큰 등)이 탐지되면 즉시 패킷을 폐기합니다 ($0.5\mu\text{s}$).
     - `REDIRECT`: 양쪽 소켓이 모두 `sockmap`에 등록된 동일 호스트 통신인 경우, `bpf_msg_redirect_hash()`를 통해 전체 TCP/IP 스택을 통째로 우회하여 수신 소켓의 `sk_receive_queue`로 데이터 페이지를 직접 연결(Splicing)합니다 ($4.2\mu\text{s}$).
     - `SK_PASS`: 외부 원격 IP 통신이거나 바이패스 대상이 아닌 경우 표준 커널 TCP/IP 스택으로 라우팅합니다 ($28.5\mu\text{s}$).
3. **`sk_msg` 코킹 및 프레임 배치 최적화 (`cork_bytes`)**:
   - `cork_bytes`가 지정된 경우, 작은 패킷(예: gRPC 스트리밍 프레임)이 임계치 크기에 도달할 때까지 소켓 버퍼에 모았다가(Cork), 임계치 충족 시 단일 배치로 제로카피 리다이렉션을 수행하여 시스템 콜 및 컨텍스트 스위칭 오버헤드를 극소화합니다.

주어진 소켓 목록, `sockops` 연결 라이프사이클 이벤트, `sk_msg` 정책 규칙, 그리고 송신 메시지 시퀀스를 커널 명세에 따라 시뮬레이션하고, 상세 실행 이력(`history`)과 최종 네트워크 가속 및 CPU 절감 통계(`summary`)를 산출하는 고성능 커널 시뮬레이터를 구현하십시오.

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "map_type": "SOCKHASH",
    "map_capacity": 1024,
    "bypass_enabled": true,
    "co_located_subnets": ["10.244.0.0/16", "127.0.0.1/32"],
    "stack_metrics": {
      "tcp_ip_stack_latency_us": 28.5,
      "ebpf_bypass_latency_us": 4.2,
      "tcp_ip_cpu_cycles_per_byte": 12.0,
      "ebpf_bypass_cpu_cycles_per_byte": 1.8
    }
  },
  "sockets": [
    {"sock_id": "s_client", "family": "AF_INET", "src_ip": "10.244.1.10", "src_port": 45000, "dst_ip": "10.244.1.20", "dst_port": 8080},
    {"sock_id": "s_server", "family": "AF_INET", "src_ip": "10.244.1.20", "src_port": 8080, "dst_ip": "10.244.1.10", "dst_port": 45000}
  ],
  "sockops_events": [
    {"event": "ACTIVE_ESTABLISHED", "sock_id": "s_client", "timestamp": 100},
    {"event": "PASSIVE_ESTABLISHED", "sock_id": "s_server", "timestamp": 100}
  ],
  "sk_msg_rules": [
    {"rule_id": "drop_attack", "match": {"has_pattern": "ATTACK"}, "action": "SK_DROP"},
    {"rule_id": "cork_grpc", "match": {"protocol": "gRPC"}, "cork_bytes": 1024, "action": "REDIRECT"},
    {"rule_id": "redirect_local", "match": {"co_located": true}, "action": "REDIRECT"},
    {"rule_id": "default_pass", "match": {}, "action": "SK_PASS"}
  ],
  "messages": [
    {"msg_id": "m1", "from_sock": "s_client", "payload": "GET /api/v1 HTTP/1.1", "bytes": 28, "protocol": "HTTP", "timestamp": 150}
  ]
}
```

### 필드 상세 설명:
- `config`:
  - `map_type`: BPF 맵 타입 (`"SOCKMAP"` 또는 `"SOCKHASH"`).
  - `map_capacity`: 맵에 등록 가능한 최대 고유 소켓 수.
  - `bypass_enabled`: 제로카피 바이패스 기능 활성화 여부 (`true`/`false`).
  - `co_located_subnets`: 동일 노드 로컬 파드 서브넷 CIDR 목록.
  - `stack_metrics`: 지연시간($\mu\text{s}$) 및 바이트당 소비 CPU 사이클.
- `sockets`: 네트워크 소켓 정의 (ID, 4-Tuple).
- `sockops_events`: `ACTIVE_ESTABLISHED`, `PASSIVE_ESTABLISHED`, `SOCK_CLOSED` 이벤트.
- `sk_msg_rules`: 버딕트 규칙 목록 (`match` 조건: `has_pattern`, `protocol`, `co_located`, `action`: `SK_DROP`, `REDIRECT`, `SK_PASS`, `cork_bytes`).
- `messages`: 송신 메시지 목록 (`msg_id`, `from_sock`, `to_sock`(선택적), `payload`, `bytes`, `protocol`, `timestamp`).

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다 (`separators=(',', ':')`).
```json
{
  "history": [
    {
      "type": "SOCKOPS",
      "event": "ACTIVE_ESTABLISHED",
      "sock_id": "s_client",
      "status": "REGISTERED",
      "detail": "co-located socket registered in SOCKHASH (10.244.1.10:45000->10.244.1.20:8080)"
    },
    ...
  ],
  "summary": {
    "total_messages_processed": 5,
    "bypassed_messages_count": 3,
    "standard_stack_messages_count": 1,
    "dropped_messages_count": 1,
    "total_bytes_transferred": 1260,
    "bypassed_bytes": 1140,
    "average_latency_us": 10.28,
    "latency_reduction_pct": 63.93,
    "total_cpu_cycles_saved": 11628.0,
    "sockmap_active_entries": 2
  }
}
```

### 요약 필드 설명:
- `total_messages_processed`: 처리된 총 송신 메시지 수.
- `bypassed_messages_count`: eBPF zero-copy TCP 바이패스로 직통 전달된 메시지 수.
- `standard_stack_messages_count`: 전체 커널 TCP/IP 스택을 통과한 메시지 수.
- `dropped_messages_count`: `SK_DROP` 규칙으로 즉시 폐기된 악성 메시지 수.
- `total_bytes_transferred`: 실제 전달 성공한 총 전송 바이트 수.
- `bypassed_bytes`: 제로카피로 전송된 데이터 볼륨.
- `average_latency_us`: 전달 성공한 메시지들의 가중 평균 지연시간($\mu\text{s}$).
- `latency_reduction_pct`: 표준 스택 대비 평균 지연시간 절감률(%).
- `total_cpu_cycles_saved`: TCP/IP 스택 우회를 통해 절약된 총 CPU 사이클 수.
- `sockmap_active_entries`: 시뮬레이션 종료 시점에 `sockmap`에 남아있는 활성 소켓 엔트리 수.
