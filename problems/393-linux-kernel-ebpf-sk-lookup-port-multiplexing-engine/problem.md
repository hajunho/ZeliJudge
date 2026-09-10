# Problem #393: Linux Kernel eBPF sk_lookup & L4 Port Multiplexing Engine (`net/core/filter.c`, `BPF_PROG_TYPE_SK_LOOKUP`)

## 문제 설명

글로벌 엣지 프록시(Cloudflare, Envoy, Cilium) 및 대규모 멀티테넌트 PaaS 환경에서는 수백만 개의 가상 IP 주소(Anycast VIP)와 수만 개의 포트 범위(Port Ranges)로 유입되는 연결을 소수의 고성능 유저스페이스 리스닝 소켓으로 라우팅해야 합니다.

전통적인 리눅스 BSD 소켓 API에서는 특정 포트나 IP로 들어오는 트래픽을 수신하려면 각 IP:Port 쌍마다 별도의 `bind()` 시스템 콜을 호출해야 했습니다.
1. **커널 메모리 낭비**: 수십만 개의 리스닝 소켓이 생성되면 커널 해시 테이블(`inet_hashinfo`)이 비대해져 메모리 낭비가 발생합니다.
2. **소켓 조회 지연**: 수신 패킷마다 깊은 4-튜플 해시 버킷 체인을 순회해야 하므로 연결 수립(3-way Handshake) 지연 시간이 급증합니다.
3. **와일드카드 바인드 충돌**: 특정 IP 바인드와 와일드카드(`0.0.0.0`) 바인드 간 충돌로 인해 유연한 포트 공유가 불가능했습니다.

리눅스 커널 5.9는 네트워크 네임스페이스 레벨에서 소켓 매칭을 프로그래머블하게 오버라이드할 수 있는 **eBPF sk_lookup (`BPF_PROG_TYPE_SK_LOOKUP`, `net/core/filter.c`)** 훅을 도입했습니다:

```
+----------------------------------------------------------------------------------------------------+
|                                eBPF sk_lookup Execution Flow                                       |
+----------------------------------------------------------------------------------------------------+
| [ TCP SYN / UDP Ingress Packet: src_ip, src_port, dst_ip, dst_port, proto ]                        |
|   | 1. Intercept BEFORE standard inet_lookup_listener() hashtable traversal!                       |
|   | 2. Execute BPF Program (BPF_PROG_TYPE_SK_LOOKUP):                                              |
|   |    - Evaluates priority-ordered matching rules (IP prefix, port range, proto).                |
|   |    - Case A: Action ASSIGN (bpf_sk_assign)                                                     |
|   |        -> Directly assigns target listening socket!                                            |
|   |        -> COMPLETELY BYPASSES kernel inet_hashinfo hashtable lookup!                           |
|   |    - Case B: Action DROP                                                                       |
|   |        -> Silently drops packet (Anti-DDoS / Port Blacklisting without TCP RST).               |
|   |    - Case C: Action PASS / Unmatched                                                           |
|   |        -> Falls back to legacy kernel inet_lookup_listener() table.                            |
|   |           Found -> FALLBACK_ASSIGNED                                                           |
|   |           Not Found -> FALLBACK_RST (Connection Refused)                                       |
+----------------------------------------------------------------------------------------------------+
```

### 핵심 기능 및 동작 규칙

1. **소켓 등록 (`REGISTER_SOCKET`)**:
   - `sock_id`, `bind_ip`, `bind_port`, `is_listening` 속성을 가진 소켓을 등록합니다.
2. **eBPF 룰 체인 (`ADD_RULE`)**:
   - `priority` (낮을수록 우선순위 높음), `match` (`dst_ip`, `dst_ip_prefix`, `port_start`, `port_end`, `proto`), `action` (`ASSIGN`, `DROP`), `target_sock`을 등록합니다.
3. **패킷 인그레스 처리 (`PROCESS_PACKET`)**:
   - 룰 매칭 시 `ASSIGN`: 대상 소켓이 존재하고 리스닝 중인 경우 `BPF_ASSIGNED` 처리 및 커널 해시 테이블 바이패스 (`bypassed_kernel_hashtable: true`).
   - 룰 매칭 시 `DROP`: `BPF_DROP` 처리.
   - 룰 미매칭 또는 대상 소켓 비정상 시: 레거시 커널 바인드 테이블 조회. 일치하는 소켓 존재 시 `FALLBACK_ASSIGNED`, 부재 시 `FALLBACK_RST`.

당신은 리눅스 커널 eBPF sk_lookup 프로그램의 4-튜플 인터셉션, 포트 레인지 멀티플렉싱, 커널 해시 테이블 바이패스 및 레거시 폴백 엔진을 시뮬레이션하는 프로그램을 작성해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {},
  "commands": [
    { "op": "REGISTER_SOCKET", "sock_id": "proxy_1", "bind_ip": "127.0.0.1", "bind_port": 8080 },
    { "op": "ADD_RULE", "rule_id": "r1", "priority": 10, "match": { "dst_ip": "1.1.1.1", "port_start": 443, "port_end": 443, "proto": "TCP" }, "action": "ASSIGN", "target_sock": "proxy_1" },
    { "op": "PROCESS_PACKET", "pkt_id": "p1", "src_ip": "10.0.0.1", "src_port": 12345, "dst_ip": "1.1.1.1", "dst_port": 443, "proto": "TCP" }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "total_packets": 1,
  "bpf_assigned_count": 1,
  "bpf_dropped_count": 0,
  "fallback_assigned_count": 0,
  "fallback_rejected_count": 0,
  "active_sockets": 1,
  "active_rules": 1,
  "events": [ ... ]
}
```
