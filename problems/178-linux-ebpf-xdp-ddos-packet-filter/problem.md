# Problem 178: Linux eBPF XDP(eXpress Data Path) 드라이버 레벨 패킷 필터링과 SYN Flood 커널 바이패스 방어

## 문제 설명

대규모 글로벌 핀테크 플랫폼의 L4 인그레스 게이트웨이 클러스터가 초당 수천만 개의 위조된 패킷이 쏟아지는 **대규모 분산 SYN Flood DDoS 공격**을 받았습니다.
전통적인 리눅스 커널 네트워크 스택(Netfilter / iptables)을 사용하던 서버들은 유입되는 모든 악성 패킷에 대해 무거운 `struct sk_buff` 메모리를 할당하고 커넥션 트래킹(`nf_conntrack`) 테이블을 갱신하느라, **CPU가 100% `ksoftirqd`에 묶여 서버가 마비되고 정상 고객의 결제 요청이 전량 드랍되는 대재앙**을 겪었습니다.

인프라 엔지니어링 팀은 NIC 드라이버 레벨에서 `sk_buff` 할당 전에 패킷을 검사하여 초고속 폐기할 수 있는 **Linux eBPF XDP (eXpress Data Path)** 엔진을 긴급 도입하기로 결정했습니다.

당신은 NIC 디바이스 드라이버 최하단에서 동작하는 eBPF XDP 필터 및 무상태 SYN Cookie 메커니즘을 시뮬레이션하고, 합법적 트래픽을 완벽하게 보호하면서 공격 패킷을 라인 레이트 속도로 격퇴하는 시스템을 구현해야 합니다.

---

## 핵심 처리 규칙

### 1. 2단계 패킷 처리 파이프라인

#### STAGE 1: Linux eBPF XDP 드라이버 훅 (Zero `sk_buff` Allocation)
`config.enable_xdp == True`인 경우, 물리 링 버퍼에서 수신된 패킷을 다음 순서로 즉시 평가합니다:
1. **화이트리스트 통과 (`whitelist_ips`)**:
   - 출발지 IP가 화이트리스트에 포함된 경우, 모든 검사를 건너뛰고 즉시 `XDP_PASS`로 상위 커널 스택에 승격합니다.
2. **블랙리스트 드랍 (`blacklist_ips`)**:
   - BPF 해시 맵에 등록된 악성 IP인 경우, 즉시 **`XDP_DROP`**을 반환하여 패킷을 폐기합니다 (`stage: "XDP_DRIVER"`, `reason: "BPF_MAP_BLACKLIST_MATCH"`).
3. **SYN Flood 속도 제한 (Rate Limiting via BPF Map)**:
   - 플래그가 `SYN`인 경우, 해당 출발지 IP의 틱당 수신 카운터를 1 증가시킵니다.
   - 누적 카운터가 `xdp_syn_rate_limit`을 초과한 경우:
     - `enable_syn_cookies == True`인 경우:
       - 결정론적 암호학적 쿠키(`cookie = (zlib.crc32(f"{src_ip}:{src_port}:{tick}".encode()) & 0x7FFFFFFF) + 1`)를 생성하고, 기대 ACK 값(`cookie + 1`)을 BPF 맵에 캐싱한 뒤 **`XDP_TX`**로 반사 전송합니다 (`stage: "XDP_DRIVER"`, `reason: f"SYN_COOKIE_TRANSMITTED_COOKIE_{cookie}"`).
     - `enable_syn_cookies == False`인 경우:
       - 즉시 **`XDP_DROP`**으로 폐기합니다 (`stage: "XDP_DRIVER"`, `reason: "BPF_SYN_RATE_LIMIT_EXCEEDED"`).
4. **SYN Cookie ACK 검증**:
   - 플래그가 `ACK`이고 BPF 쿠키 맵에 해당 IP가 대기 중인 경우:
     - 패킷의 `ack` 필드가 기대 ACK 값(`expected_ack`)과 정확히 일치하면 쿠키 캐시를 제거하고 `XDP_PASS`로 승격합니다 (`reason: "SYN_COOKIE_VERIFIED"`).
     - 불일치하면 즉시 **`XDP_DROP`**으로 폐기합니다 (`reason: "INVALID_SYN_COOKIE_ACK"`).
5. 위의 모든 조건을 통과한 정상 패킷은 **`XDP_PASS`** 판정을 받고 리눅스 커널 네트워크 스택으로 전달됩니다.

#### STAGE 2: 리눅스 커널 네트워크 스택 (sk_buff 할당 & Conntrack)
XDP가 비활성화되어 있거나 XDP를 통과한(`XDP_PASS`) 패킷만 진입합니다:
1. **SKB 할당 버짓 검사 (`skb_allocation_budget_per_tick`)**:
   - 틱당 할당된 `skb` 수가 예산을 초과하면, SoftIRQ 포화로 인해 커널에서 패킷이 드랍됩니다 (`action: "KERNEL_DROP"`, `stage: "KERNEL_SOFTIRQ"`, `reason: "SKB_ALLOCATION_BUDGET_EXHAUSTED"`).
2. **Conntrack 테이블 등록 (`max_conntrack_entries`)**:
   - 패킷의 5-tuple(`src_ip:src_port->dst_port:protocol`)이 conntrack 테이블에 없으면 추가를 시도합니다.
   - 테이블이 가득 찬 경우 커널 드랍이 발생합니다 (`action: "KERNEL_DROP"`, `stage: "KERNEL_CONNTRACK"`, `reason: "CONNTRACK_TABLE_FULL"`).
3. 위의 모든 단계를 통과하면 최종 유저 소켓에 배달됩니다 (`action: "DELIVERED_TO_SOCKET"`, `stage: "USERSPACE_SOCKET"`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "enable_xdp": true,
    "enable_syn_cookies": false,
    "max_conntrack_entries": 100,
    "skb_allocation_budget_per_tick": 50,
    "xdp_syn_rate_limit": 20,
    "blacklist_ips": ["198.51.100.42"],
    "whitelist_ips": ["10.0.0.100"]
  },
  "traffic_events": [
    {
      "tick": 0,
      "packets": [
        {
          "pkt_id": "pkt_001",
          "src_ip": "10.0.1.1",
          "src_port": 20001,
          "dst_port": 80,
          "protocol": "TCP",
          "flags": "SYN",
          "is_attack": false
        }
      ]
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "COMPLETED",
  "metrics": {
    "total_packets_received": 20,
    "xdp_dropped": 0,
    "xdp_passed": 20,
    "xdp_tx_syn_cookies": 0,
    "skb_allocated": 20,
    "kernel_conntrack_drops": 0,
    "legitimate_delivered": 20,
    "attack_blocked": 0,
    "conntrack_usage": 20,
    "verdict": "CLEAN_TRAFFIC_UNFILTERED_PASS"
  },
  "sample_packet_logs": [
    {
      "pkt_id": "pkt_001",
      "src_ip": "10.0.1.1",
      "flags": "SYN",
      "is_attack": false,
      "action": "DELIVERED_TO_SOCKET",
      "stage": "USERSPACE_SOCKET",
      "reason": ""
    }
  ]
}
```

### 최종 판정 (Verdict) 규칙
1. `KERNEL_STACK_COLLAPSE_CONNTRACK_EXHAUSTION`:
   - `enable_xdp == false`이고, `kernel_conntrack_drops >= 20`인 경우 (전통 스택 마비).
2. `LINE_RATE_XDP_PACKET_FILTERING_SUCCESS`:
   - `enable_xdp == true`이고, `kernel_conntrack_drops == 0`이며, `xdp_dropped > 0` 또는 `xdp_tx_syn_cookies > 0`인 경우 (XDP 방어 성공).
3. `CLEAN_TRAFFIC_UNFILTERED_PASS`:
   - `kernel_conntrack_drops == 0`, `attack_blocked == 0`, `xdp_dropped == 0`인 경우 (공격 없는 정상 트래픽).
4. `PARTIAL_FILTERING_PERFORMANCE_DEGRADED`:
   - 그 외의 경우.
