# [Pro #270] 리눅스 커널 eBPF BPF_MAP_TYPE_LPM_TRIE 최장 일치 접두사(LPM) 라우팅 및 ECMP 패킷 스티어링 엔진

## 문제 설명

클라우드 네이티브 쿠버네티스 CNI(Cilium, Calico eBPF) 및 하이퍼스케일 L4 로드 밸런서(Meta Katran, Cloudflare Unimog)에서는 초당 수천만 개(Mpps)의 고속 패킷을 지연 없이 라우팅하고 보안 정책(CIDR 인그레스/이그레스 방화벽)을 검사해야 합니다. 전통적인 리눅스 커널의 네트워크 스택(Netfilter / iptables)은 선형 탐색($O(N)$)으로 인해 수천 개의 룰이 등록되면 CPU 부하가 폭증하는 치명적인 한계를 지닙니다.

이를 극복하기 위해 리눅스 커널 4.11부터 도입된 핵심 인프라가 바로 **`BPF_MAP_TYPE_LPM_TRIE` (Longest Prefix Match Trie)**입니다. 이 자료구조는 이진 기수 트리(Binary Radix Tree / Patricia Tree)를 커널 메모리 공간에 구축하여, 임의의 IPv4/IPv6 목적지 주소에 대해 **최장 일치 접두사(LPM, Longest Prefix Match)** 라우팅 규칙을 $O(W)$ (IPv4의 경우 최대 32비트 깊이)의 결정론적 상한 시간 내에 탐색합니다:
1. **계층적 접두사 우선순위 (LPM Hierarchy)**:
   - 예를 들어 `0.0.0.0/0`(기본 게이트웨이), `192.168.0.0/16`(사설망), `192.168.1.0/24`(로컬 서브넷), `192.168.1.10/32`(단일 호스트)가 동시에 등록되어 있을 때, 목적지 IP `192.168.1.10`으로 향하는 패킷은 비트 길이가 가장 긴 `/32` 규칙과 가장 먼저 매칭되어야 합니다.
2. **등가 다중 경로(ECMP, Equal-Cost Multi-Path) 부하 분산**:
   - 동일한 서브넷에 대해 여러 개의 출구 인터페이스나 넥스트홉 게이트웨이가 존재하는 경우, 패킷의 5-튜플(출발지 IP, 목적지 IP, 출발지 포트, 목적지 포트, 프로토콜) 해시를 계산하여 특정 플로우(Flow)의 패킷들이 일관된 단일 경로로 흐르도록 보장(Flow Affinity)하면서 대역폭을 선형 분산합니다.
3. **블랙홀/드롭 정책(Policy Null-routing)**:
   - 특정 악성 서브넷이나 인가되지 않은 IP 대역(`ACTION: DROP`)에 대해 트래픽을 커널 드라이버 계층(XDP)에서 즉각 폐기하여 시스템 자원을 보호합니다.
4. **동적 갱신 및 트리 가지치기(Node Pruning)**:
   - 라우팅 엔트리가 삽입·삭제될 때, 자식이 없고 유효 라우트도 없는 불필요한 중간 노드들을 즉시 압축·해제하여 메모리 사용량(`trie_node_count`)과 최대 탐색 깊이(`max_depth`)를 최소로 유지해야 합니다.

당신은 eBPF 기반 클라우드 네이티브 네트워킹 및 데이터 플레인 가속 팀의 시니어 커널 엔지니어로서, 리눅스 커널의 `BPF_MAP_TYPE_LPM_TRIE` 사양을 완벽히 모사하는 **최장 일치 접두사 라우팅 및 ECMP 패킷 스티어링 시뮬레이션 엔진**을 구현해야 합니다.

---

## 시스템 사양 및 세부 처리 규칙

### 1. 설정 매개변수 (`config`)
- `max_entries` (정수, 기본값 1000): LPM 트라이에 저장 가능한 최대 고유 CIDR 라우트 수입니다. 트라이가 가득 찬 상태에서 새로운 라우트를 삽입하려고 하면 `"MAP_FULL"` 오류를 반환합니다 (단, 이미 존재하는 CIDR의 내용 덮어쓰기는 허용됩니다).
- `enable_ecmp` (불리언, 기본값 true): 다중 넥스트홉(`len(next_hops) > 1`)이 존재할 때 5-튜플 일관성 해시 기반 ECMP 경로 선택을 활성화합니다. `false`이면 항상 첫 번째 넥스트홉(`next_hops[0]`)을 선택합니다.

### 2. IP 및 CIDR 비트열 처리
- IPv4 주소는 점으로 구분된 4개의 옥텟 $A.B.C.D$ 형태이며, 32비트 부호 없는 정수 $\text{ip\_int} = (A \ll 24) | (B \ll 16) | (C \ll 8) | D$로 변환합니다.
- CIDR 표기법 `IP/P` (예: `192.168.1.0/24`):
  - 접두사 길이 $P \in [0, 32]$입니다 ($P=0$이면 기본 라우트 `0.0.0.0/0`).
  - 서브넷 마스크 $\text{mask} = (\text{0xFFFFFFFF} \ll (32 - P)) \& \text{0xFFFFFFFF}$ ($P=0$이면 0).
  - 유효 네트워크 주소는 $\text{network} = \text{ip\_int} \& \text{mask}$로 정규화됩니다.

### 3. 이진 라디어스 트라이(Binary Radix Trie) 구조 및 LPM 탐색
- 트라이의 루트 노드는 깊이 0에 위치합니다 (`0.0.0.0/0` 라우트가 존재하면 루트 노드에 저장됨).
- 각 노드는 좌측 자식(`child[0]`, 비트 0)과 우측 자식(`child[1]`, 비트 1)을 가집니다.
- **LPM 탐색 알고리즘**:
  - 패킷의 목적지 IP $\text{dst\_ip}$를 32비트 정수로 변환합니다.
  - 최상위 비트(비트 31)부터 최하위 비트(비트 0) 방향으로 트라이를 따라 내려갑니다.
  - 탐색 경로 상에서 유효한 라우트(`is_leaf == true`)를 갖는 노드를 만날 때마다 해당 노드를 **최선의 일치 후보(`best_match`)**로 갱신합니다.
  - 탐색이 분기 누락으로 종료되거나 32비트를 모두 소진했을 때, 최종 기록된 `best_match`가 최장 일치 접두사 매칭 결과가 됩니다.

### 4. 명령어 (`commands`) 명세
- `ROUTE_PACKET {"packet": {"id": str, "src_ip": str, "dst_ip": str, "src_port": int, "dst_port": int, "protocol": str}}`:
  - 트라이에서 `dst_ip`에 대한 LPM 라우트를 탐색합니다.
  - 일치하는 라우트가 전혀 없는 경우:
    `{"op": "ROUTE_PACKET", "packet_id": id, "status": "NO_ROUTE_TO_HOST", "matched_cidr": null, "action": "DROP"}`
  - 일치한 라우트의 `action == "DROP"`인 경우:
    `{"op": "ROUTE_PACKET", "packet_id": id, "status": "DROPPED_BY_POLICY", "matched_cidr": cidr, "action": "DROP"}`
  - 일치한 라우트의 `action == "FORWARD"`인 경우:
    - `next_hops`가 비어있으면 `status: "NO_NEXT_HOP"`, `action: "DROP"` 반환.
    - `enable_ecmp == true`이고 `len(next_hops) > 1`인 경우:
      5-튜플 문자열 `"{src_ip}:{dst_ip}:{src_port}:{dst_port}:{protocol}"`의 UTF-8 바이트에 대해 표준 CRC32 해시를 계산합니다:
      $$\text{hash\_val} = \text{crc32}(\text{tuple\_str}) \& \text{0xFFFFFFFF}$$
      $$\text{hop\_index} = \text{hash\_val} \pmod{\text{len(next\_hops)}}$$
      선택된 넥스트홉 = `next_hops[hop_index]`.
    - 그렇지 않으면 `next_hops[0]` 선택.
    - 결과 반환:
      `{"op": "ROUTE_PACKET", "packet_id": id, "status": "FORWARDED", "matched_cidr": cidr, "action": "FORWARD", "egress_interface": hop["interface"], "gateway": hop["gateway"], "metric": metric}`
- `INSERT_ROUTE {"route": {"cidr": str, "action": str, ...}}`:
  - 트라이에 라우트를 등록하거나 갱신합니다.
  - 신규 등록인데 `total_routes >= max_entries`이면 `{"op": "INSERT_ROUTE", "cidr": cidr, "status": "MAP_FULL"}` 반환.
  - 성공 시 `status: "SUCCESS"` 반환.
- `DELETE_ROUTE {"cidr": str}`:
  - 지정된 CIDR 라우트를 삭제하고, 유효 라우트가 없고 자식이 없는 불필요한 중간 노드들을 상향식으로 정리(Pruning)합니다.
  - 존재하면 `{"op": "DELETE_ROUTE", "cidr": cidr, "status": "DELETED"}`, 없으면 `{"op": "DELETE_ROUTE", "cidr": cidr, "status": "NOT_FOUND"}`.
- `GET_TRIE_STATS {}`:
  - 트라이 상태 요약 반환: `{"op": "GET_TRIE_STATS", "stats": {"total_routes": int, "trie_node_count": int, "max_depth": int}}`.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "max_entries": 100,
    "enable_ecmp": true
  },
  "routes": [
    {
      "cidr": "0.0.0.0/0",
      "action": "FORWARD",
      "next_hops": [{"gateway": "192.168.0.1", "interface": "wan0"}],
      "metric": 100
    },
    {
      "cidr": "10.0.0.0/8",
      "action": "FORWARD",
      "next_hops": [{"gateway": "10.0.0.1", "interface": "eth0"}],
      "metric": 20
    }
  ],
  "commands": [
    {
      "op": "ROUTE_PACKET",
      "packet": {
        "id": "p1",
        "src_ip": "1.1.1.1",
        "dst_ip": "10.0.5.99",
        "src_port": 1234,
        "dst_port": 80,
        "protocol": "TCP"
      }
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 단일 JSON 객체를 공백 없이(또는 표준 JSON 포맷) 한 줄로 출력합니다:
```json
{
  "summary": {
    "total_commands_executed": 1,
    "final_trie_stats": {
      "total_routes": 2,
      "trie_node_count": 9,
      "max_depth": 8
    }
  },
  "command_results": [
    {
      "op": "ROUTE_PACKET",
      "packet_id": "p1",
      "status": "FORWARDED",
      "matched_cidr": "10.0.0.0/8",
      "action": "FORWARD",
      "egress_interface": "eth0",
      "gateway": "10.0.0.1",
      "metric": 20
    }
  ]
}
```
