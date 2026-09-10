# 문제 449: 리눅스 커널 eBPF 최장 접두사 일치(LPM) 트라이 라우팅 및 ACL 필터링 엔진 (`kernel/bpf/lpm_trie.c`)

## 1. 개요 및 배경

클라우드 네이티브 쿠버네티스 CNI(Cilium, Calico) 및 메타(Meta)의 초고속 L4 로드 밸런서 카트란(Katran), 엔터프라이즈 BGP 라우터 환경에서는 수십만 개의 서브넷 CIDR 규칙(`0.0.0.0/0`, `/16`, `/24`, `/32` 등)에 대해 100Gbps 와이어스피드로 패킷의 목적지 IP를 검사하고 라우팅 결정을 내려야 합니다.

### 1) 평면 해시 테이블(Flat Hash Table)의 성능 한계
- 평면 해시 테이블은 완전 일치(Exact Match)만을 지원하므로, 최장 접두사 일치(Longest Prefix Match)를 수행하려면 IPv4의 경우 `/32`부터 `/0`까지 **최대 33개의 서로 다른 해시 테이블을 순환 탐색**해야 합니다 (IPv6의 경우 129개).
- 이는 엄청난 CPU 캐시라인 바운싱과 레이턴시 스파이크를 유발합니다.

```
[평면 해시 테이블 탐색: 33회 연속 해시 순회 병목]:
Query IP ──> [Table /32] (Miss) ──> [Table /31] (Miss) ──> ... ──> [Table /0] (33회 캐시 미스!)

[eBPF BPF_MAP_TYPE_LPM_TRIE 바이너리 래딕스 트라이: O(비트 길이) 단일 경로 탐색]:
Query IP (192.168.1.100)
    │
    ▼
  [Node /0: Default GW]
    │  bit 0=1
    ▼
  [Intermediate Node /16]
    │  bit 16=0
    ▼
  [Node /24: Pod Subnet]  <── (최장 일치 후보 추적)
    │  bit 24=1
    ▼
  [Node /32: Pod Host]    <── (최종 최장 일치! 단 1회 하향 순회)
```

리눅스 커널은 이를 해결하기 위해 `kernel/bpf/lpm_trie.c`에 **`BPF_MAP_TYPE_LPM_TRIE`**를 도입하였습니다.
이 맵은 비트 단위 경로 압축(Path Compression)을 지원하는 **이진 기수 트라이(Binary Radix/Patricia Trie)** 구조로 설계되어 있으며, 커널 네트워크 데이터 패스(XDP, tc-bpf)에서 `rcu_read_lock()`을 통한 **완전 무잠금(Lockless) O(K) 최장 접두사 매칭**을 실현합니다.

---

## 2. 핵심 메커니즘 및 상세 스펙

본 문제에서는 리눅스 커널 `kernel/bpf/lpm_trie.c`의 핵심 트라이 알고리즘(노드 분할, 공통 접두사 추출, 중간 분기 노드 생성, 최장 일치 탐색, 삭제 시 자동 축약)을 모델링하는 엔진을 구현합니다.

### 1) 노드 구조 및 키 정규화
- 각 트라이 노드는 `prefixlen` (0 ~ 32), 정규화된 IP 주소(`ip_val`), 값(`value`), 값 노드 여부(`is_value_node`), 그리고 2개의 자식 포인터(`child[0]`, `child[1]`)를 가집니다.
- **키 정규화 불변식**:
  `prefixlen` 범위를 벗어난 하위 호스트 비트는 반드시 0으로 마스킹되어야 합니다.
  $$\text{mask} = ((1 \ll \text{prefixlen}) - 1) \ll (32 - \text{prefixlen})$$
  예를 들어 `192.168.1.123/24`를 입력하면 내부적으로 `192.168.1.0/24`로 정규화되어 저장됩니다.

### 2) 노드 삽입 (`INSERT`)
- `ip`, `prefixlen`, `value`
- **동작**:
  1. 트라이가 비어 있으면 루트 노드로 즉시 생성.
  2. 루트부터 하향 순회하며 현재 노드와 삽입 키 간의 **공통 접두사 비트 수(`common_bits`)**를 계산:
     - `common_bits < node.prefixlen`인 경우:
       현재 노드를 분할해야 합니다! `common_bits` 길이를 갖는 **중간 분기 노드(Intermediate Branch Node, `is_value_node = false`)**를 생성하고, 기존 노드를 자식으로 붙입니다.
       만약 삽입할 `prefixlen == common_bits`라면 분기 노드 자체가 값 노드가 됩니다.
       그렇지 않다면 새 노드를 분기 노드의 반대편 자식으로 매달아 줍니다.
     - `node.prefixlen == prefixlen`인 경우:
       완전 일치! 기존 노드의 `value`를 갱신하고 `is_value_node = true`로 설정합니다.
     - `prefixlen > node.prefixlen`인 경우:
       삽입 키의 `node.prefixlen`번째 비트(0 또는 1)를 확인하여 자식 노드로 계속 전진합니다. 자식이 비어 있다면 새 리프 노드로 즉시 부착합니다.
- 반환: `{"status": "INSERTED", "prefixlen": prefixlen, "key": norm_ip}`.

### 3) 최장 접두사 일치 조회 (`LOOKUP`)
- `ip`: 쿼리할 대상 완전 IP 주소 (예: `"192.168.1.100"`)
- **동작**:
  1. 루트부터 순회를 시작하며, 현재 노드의 접두사가 쿼리 IP의 상위 비트와 일치하는지 검사합니다.
  2. 일치하고 해당 노드가 실제 값을 가진 노드(`is_value_node == true`)라면, 현재까지의 **최장 일치 노드(`best_match`)**로 기록합니다.
  3. 쿼리 IP의 `node.prefixlen`번째 비트에 따라 자식 노드로 이동합니다.
  4. 더 이상 자식이 없거나 비트 불일치가 발생하면 탐색을 종료합니다.
  5. 최종 `best_match`가 존재하면:
     - `lookup_hits` 1 증가.
     - 반환: `{"status": "MATCH", "matched_prefixlen": best_match.prefixlen, "matched_key": best_match_ip, "value": best_match.value}`.
  6. 없으면:
     - `lookup_misses` 1 증가.
     - 반환: `{"status": "NO_MATCH", "query_ip": ip}`.

### 4) 엔트리 삭제 및 트라이 축약 (`DELETE`)
- `ip`, `prefixlen`
- **동작**:
  1. `(ip, prefixlen)`과 정확히 일치하는 값 노드를 탐색합니다.
  2. 노드를 찾지 못하면 `{"status": "NOT_FOUND", "prefixlen": prefixlen, "key": norm_ip}` 반환.
  3. 노드를 찾으면 `is_value_node = false`, `value = None`으로 비활성화합니다.
  4. **트라이 축약(Trie Collapse)**:
     - 자식이 둘 다 없는 경우: 부모의 해당 자식 링크를 `None`으로 정리.
     - 자식이 1개뿐인 비-값 노드인 경우: 부모가 해당 단일 자식을 직접 가리키도록 부모-자식 링크를 바이패스 병합(축약).
  5. 반환: `{"status": "DELETED", "prefixlen": prefixlen, "key": norm_ip}`.

### 5) 통계 조회 (`QUERY_STATS`)
- 트리 전체를 순회하여 다음 메트릭을 반환합니다:
  - `total_nodes`: 실제 라우팅 값을 가진 유효 노드 수 (`is_value_node == true`).
  - `intermediate_nodes`: 단순 분기용 중간 노드 수 (`is_value_node == false`).
  - `tree_depth`: 루트부터 최장 리프까지의 깊이 (루트 노드만 있으면 깊이 1, 비어있으면 0).
  - `lookup_hits`: 누적 조회 성공 횟수.
  - `lookup_misses`: 누적 조회 실패 횟수.

---

## 3. 입력 및 출력 형식

### 입력 포맷 (표준 입력 JSON)
```json
{
  "config": {
    "max_entries": 1024
  },
  "operations": [
    {"op": "INSERT", "ip": "0.0.0.0", "prefixlen": 0, "value": {"action": "DEFAULT_GW"}},
    {"op": "INSERT", "ip": "192.168.1.0", "prefixlen": 24, "value": {"action": "POD_SUBNET"}},
    {"op": "LOOKUP", "ip": "192.168.1.100"},
    {"op": "DELETE", "ip": "192.168.1.0", "prefixlen": 24},
    {"op": "QUERY_STATS"}
  ]
}
```

### 출력 포맷 (표준 출력 단일 라인 JSON)
```json
{"results":[...]}
```
모든 키와 값은 공백 없는 압축 JSON(`separators=(',', ':')`) 형식으로 출력합니다.
