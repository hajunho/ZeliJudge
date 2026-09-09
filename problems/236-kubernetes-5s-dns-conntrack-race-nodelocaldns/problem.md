# 문제 236: 쿠버네티스(Kubernetes) 5초 DNS 지연 참사: Netfilter conntrack UDP race condition과 A/AAAA 병렬 질의 충돌 vs NodeLocal DNSCache

## 1. 개요 및 배경 (Incident Scenario)

대규모 MSA(마이크로서비스 아키텍처) 기반 쿠버네티스 클러스터에서 실시간 결제 및 주문 API 호출 중 간헐적으로 요청 지연시간이 정확히 **5,000ms(5초)** 또는 **10,000ms(10초)**씩 튀어 오르는 기이한 P99 테일 레이턴시 스파이크 장애(`KUBERNETES_5S_DNS_CONNTRACK_RACE_DISASTER`)가 발생했습니다.

APM(Datadog, OpenTelemetry)으로 트레이싱한 결과, 비즈니스 로직이나 DB 쿼리는 2ms 만에 끝났으나 외부 결제 게이트웨이나 내부 서비스 도메인을 조회하는 **DNS 질의 과정에서 정확히 5.0초간 스톨(Stall)**이 발생하고 있었습니다.

이 현상은 쿠버네티스 커뮤니티의 전설적인 이슈인 **[kubernetes/kubernetes #56903](https://github.com/kubernetes/kubernetes/issues/56903)**으로 알려진 리눅스 커널 넷필터(Netfilter) 연결 추적(conntrack) 모듈과 GNU C 라이브러리(glibc) 간의 상호작용 결함입니다:

```
[The Kubernetes 5-Second DNS Delay Race Condition]

Glibc Resolver in Pod                       Linux Kernel Netfilter (kube-proxy IPTABLES)
+-------------------------+                 +---------------------------------------------+
| getaddrinfo() sends:    |                 | Core 1: Packet A (A record query)           |
| Packet 1: A Query       | ====(UDP)=====> | -> DNAT 10.96.0.10 -> CoreDNS Pod IP        |
| Packet 2: AAAA Query    |                 | -> __nf_conntrack_confirm: SUCCESS! INSERT  |
| (Same Port, Same Socket)|                 +---------------------------------------------+
|                         |                 | Core 2: Packet B (AAAA record query)        |
|                         | ====(UDP)=====> | -> DNAT to CoreDNS Pod IP                   |
|                         |                 | -> __nf_conntrack_confirm: COLLISION DROP!  |
+-------------------------+                 +---------------------------------------------+
            |                                                      |
            | (Silent Packet Drop: No response received)            v
            +---------------------------------------------- [Packet B Lost]
            |
            | ---> Glibc waits RES_TIMEOUT (Exactly 5.0 seconds!)
            v
    [5,005ms Latency Spike & SLA Violation!]
```

### 왜 정확히 5초가 걸리는가?
1. **glibc의 A / AAAA 병렬 질의**:
   - glibc의 표준 DNS 리졸버(`getaddrinfo`)는 IPv4 주소(`A` 레코드)와 IPv6 주소(`AAAA` 레코드)를 조회하기 위해 동일한 UDP 소켓(동일한 Source IP, Source Ephemeral Port)에서 2개의 패킷을 거의 동시에 발송합니다.
2. **Netfilter conntrack의 삽입 경쟁 (Insert Race)**:
   - kube-proxy iptables 모드에서 CoreDNS 서비스의 ClusterIP(`10.96.0.10:53`)로 향하는 두 패킷은 DNAT 직전까지 완벽히 동일한 5-튜플(`pod_ip:port -> 10.96.0.10:53 UDP`)을 가집니다.
   - 멀티코어 환경에서 두 패킷이 서로 다른 CPU 코어에서 병렬 처리될 때, 두 번째 패킷이 conntrack 해시 테이블에 진입하는 순간 `__nf_conntrack_confirm`에서 튜플 충돌(`NF_CT_CONFIRM_FAILED`)이 발생하여 커널이 두 번째 패킷을 **조용히 드롭(Silent Drop, NF_DROP)**합니다.
3. **glibc의 5초 재전송 타임아웃**:
   - 패킷이 유실되었으므로 응답이 오지 않고, Linux glibc의 `/etc/resolv.conf` 기본 타임아웃(`RES_TIMEOUT = 5s`)이 만료될 때까지 스레드가 5초 동안 블로킹됩니다.
   - 5초 후 glibc가 재전송을 수행하면 그제야 응답을 받아 요청이 완료되므로, 정확히 5,005ms의 지연시간 스파이크가 발생합니다.

### 해결책: NodeLocal DNSCache
- 노드마다 로컬 링크-로컬 더미 인터페이스(`169.254.20.10:53`)로 구동되는 경량 DNS 캐싱 데몬(`NodeLocal DNSCache`)을 배치합니다.
- 파드가 노드 로컬 IP로 질의하므로 iptables DNAT 및 conntrack을 완전히 우회(`conntrack_entries_created = 0`)하여 5초 레이스 컨디션을 100% 제거하고 DNS 지연시간을 0.4ms로 단축시킵니다(`OPTIMAL_NODELOCAL_DNSCACHE_DEFENSE`).

본 문제에서는 쿠버네티스 DNS 아키텍처, resolv.conf 옵션, 트래픽 동시성 및 conntrack 테이블 한도에 따른 DNS 지연시간과 패킷 드롭을 시뮬레이션하고 최적 아키텍처를 판정합니다.

---

## 2. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "dns_architecture": "CORE_DNS_CLUSTERIP",
    "resolv_options": "DEFAULT",
    "conntrack_max": 131072,
    "conntrack_count": 45000,
    "kube_proxy_mode": "IPTABLES",
    "dns_timeout_sec": 5.0
  },
  "workload": {
    "total_dns_lookups": 10000,
    "parallel_a_aaaa_queries": true,
    "traffic_concurrency": 250,
    "cache_hit_rate": 0.85
  }
}
```

### 필드 설명
- `config`:
  - `dns_architecture` (str): DNS 아키텍처 (`"CORE_DNS_CLUSTERIP"`, `"NODELOCAL_DNSCACHE"`)
  - `resolv_options` (str): `/etc/resolv.conf` 옵션 (`"DEFAULT"`, `"SINGLE_REQUEST_REOPEN"`)
  - `conntrack_max` (int): 노드의 최대 conntrack 테이블 용량 (`sysctl net.netfilter.nf_conntrack_max`)
  - `conntrack_count` (int): 현재 사용 중인 conntrack 엔트리 수
  - `kube_proxy_mode` (str): 프록시 모드 (`"IPTABLES"`, `"IPVS"`)
  - `dns_timeout_sec` (float): glibc 리졸버 재전송 타임아웃 (초, 기본 5.0)
- `workload`:
  - `total_dns_lookups` (int): 총 DNS 질의 요청 수
  - `parallel_a_aaaa_queries` (bool): A 및 AAAA 레코드 병렬 질의 여부 (기본 true)
  - `traffic_concurrency` (int): 동시 처리 트래픽 수 (동시성이 높을수록 멀티코어 넷필터 충돌 확률 증가)
  - `cache_hit_rate` (float): 캐시 적중률

---

## 3. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 JSON 구조를 반환해야 합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_NODELOCAL_DNSCACHE_DEFENSE",
  "metrics": {
    "conntrack_usage_pct": 34.3,
    "five_second_stalls_count": 0,
    "avg_dns_latency_ms": 0.4,
    "p99_dns_latency_ms": 0.8,
    "conntrack_entries_created": 0,
    "netfilter_race_drops": 0
  }
}
```

### 판정(Verdict) 및 상태(Status) 규칙
1. **conntrack 테이블 고갈 (`conntrack_count + new >= conntrack_max`)**:
   - `status`: `"FAILED"`, `verdict`: `"CONNTRACK_TABLE_EXHAUSTION_PACKET_DROP"`
2. **`dns_architecture == "NODELOCAL_DNSCACHE"`**:
   - conntrack 및 iptables NAT 우회, 로컬 캐시 직행
   - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_NODELOCAL_DNSCACHE_DEFENSE"`, `avg_dns_latency_ms`: 0.4, `p99_dns_latency_ms`: 0.8, `five_second_stalls_count`: 0
3. **`dns_architecture == "CORE_DNS_CLUSTERIP"`**:
   - `resolv_options == "SINGLE_REQUEST_REOPEN"`:
     - 소켓 분리로 5초 지연은 막으나 직렬화 지연 발생
     - `status`: `"WARNING"`, `verdict`: `"SINGLE_REQUEST_REOPEN_SERIAL_LATENCY_WORKAROUND"`, `p99_dns_latency_ms`: 14.5
   - `parallel_a_aaaa_queries == false`:
     - IPv4 전용으로 충돌 없음 (`status`: `"SUCCESS"`, `verdict`: `"IPV4_ONLY_NO_AAAA_COLLISION"`)
   - `kube_proxy_mode == "IPTABLES"`:
     - 넷필터 삽입 충돌로 인한 5초 지연 폭풍 발생
     - `status`: `"FAILED"`, `verdict`: `"KUBERNETES_5S_DNS_CONNTRACK_RACE_DISASTER"`, `p99_dns_latency_ms`: 5005.0
   - `kube_proxy_mode == "IPVS"`:
     - IPVS UDP 세션 추적 충돌로 인한 간헐적 스톨
     - `status`: `"FAILED"`, `verdict`: `"IPVS_UDP_CONNTRACK_RACE_INTERMITTENT_STALL"`

---

## 4. 예제 입출력

### 예제 1 (입력)
```json
{
  "config": {
    "dns_architecture": "CORE_DNS_CLUSTERIP",
    "resolv_options": "DEFAULT",
    "conntrack_max": 131072,
    "conntrack_count": 45000,
    "kube_proxy_mode": "IPTABLES",
    "dns_timeout_sec": 5.0
  },
  "workload": {
    "total_dns_lookups": 10000,
    "parallel_a_aaaa_queries": true,
    "traffic_concurrency": 250,
    "cache_hit_rate": 0.85
  }
}
```

### 예제 1 (출력)
```json
{
  "status": "FAILED",
  "verdict": "KUBERNETES_5S_DNS_CONNTRACK_RACE_DISASTER",
  "metrics": {
    "conntrack_usage_pct": 49.6,
    "five_second_stalls_count": 350,
    "avg_dns_latency_ms": 177.4,
    "p99_dns_latency_ms": 5005.0,
    "conntrack_entries_created": 20000,
    "netfilter_race_drops": 350
  }
}
```
