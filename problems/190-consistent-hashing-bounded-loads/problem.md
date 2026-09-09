# Problem 190: 분산 캐시 로드 밸런싱: Google Bounded Loads 일관된 해싱(Consistent Hashing with Bounded Loads)과 핫스팟 캐스케이딩 연쇄 붕괴 방어

## 문제 설명

글로벌 실시간 OTT 스트리밍 및 소셜 미디어 플랫폼(Vimeo, YouTube, Netflix 등)의 분산 캐시 인프라를 운영하는 플랫폼 엔지니어링 팀은 월드컵 결승전 라이브 중계 도중 전례 없는 대형 장애를 겪었습니다.

특정 인기 라이브 스트림 청크(`live_stream_final_match`)와 플래시 세일 상품에 초당 수십만 건의 폭발적인 트래픽(Zipfian Skew)이 집중되자, 기존의 캐시 라우팅 아키텍처가 차례로 붕괴했습니다:

1. **표준 일관된 해싱(`STANDARD_CONSISTENT_HASH`)의 핫스팟 캐스케이딩 붕괴**:
   - 가상 노드(Virtual Nodes)를 노드당 50개씩 링에 균일하게 배치했음에도, 특정 핫키(Hot Key)의 해시값은 오직 단 하나의 주 노드($S_{hot}$)로만 직격했습니다.
   - $S_{hot}$ 노드의 동시 요청량이 하드웨어 한계 용량(`node_max_capacity`)을 초과하여 OOM 및 CPU 100% 포화로 즉시 사망(Crash)했습니다.
   - 링에서 $S_{hot}$이 제거되자, 해시 링의 시계 방향 다음 노드($S_{next}$)로 수만 건의 핫키 트래픽이 폭포수처럼 전이(Failover)되었습니다.
   - $S_{next}$ 역시 1초 만에 용량을 초과하여 사망하고, 연쇄적으로 클러스터 내 모든 노드가 차례로 쓰러지는 **캐스케이딩 연쇄 붕괴(Cascading Cluster Collapse)**로 전체 서비스가 완전 마비되었습니다.
2. **무작위 2선택 기법(`POWER_OF_TWO_CHOICES`)의 캐시 지역성(Locality) 파괴**:
   - 단순 부하 분산을 위해 무작위 2개 노드 중 부하가 적은 곳으로 요청을 보내는 방식을 도입하자, 부하는 균등해졌으나 **동일한 키가 사방으로 흩어져 캐시 적중률(Cache Hit Rate)이 20%대로 폭락**했습니다.
   - 캐시 미스로 인한 트래픽이 원본 오리진 데이터베이스로 직격하여 DB가 폭사하는 2차 참사(`CACHE_LOCALITY_COLLAPSE`)가 발생했습니다.
3. **Google Research의 혁신: Bounded Loads Consistent Hashing (Mirrokni et al. 2017)**:
   - Google의 Vahab Mirrokni 연구팀은 일관된 해싱의 최소 키 이동 특성과 높은 캐시 적중률을 그대로 유지하면서, **어떤 노드도 평균 부하의 $(1 + \epsilon)$배를 초과하지 못하도록 수학적으로 보장**하는 알고리즘을 발표했습니다 (ICDCN 2017, Vimeo 및 Envoy Proxy 공식 채택).
   - 각 노드의 동적 상한선(Bounded Capacity):
     $$C = \max\left(1, \left\lceil (1 + \epsilon) \cdot \frac{M}{N} \right\rceil\right)$$
     (여기서 $M$은 총 활성 요청 수, $N$은 활성 노드 수, $\epsilon$은 허용 오차 계수, 예: $\epsilon = 0.25$)
   - 키의 1차 해시 노드가 상한선 $C$에 도달하면, 해시 링을 시계 방향으로 탐색하여 용량이 남은 다음 노드로 자연스럽게 **스필오버(Spillover)**시킵니다.
   - 결과적으로 핫키의 초과 트래픽만이 링의 인접 노드들로 완충 분산되어, **노드 크래시 0건, 캐스케이딩 장애 원천 방어, 최적의 캐시 지역성 보존**을 동시에 달성합니다!

당신은 Envoy 및 Vimeo의 L7 로드밸런서 핵심 코어를 모델링한 분산 캐시 라우팅 시뮬레이터를 구현해야 합니다.

---

## 핵심 라우팅 모드 및 알고리즘

모든 노드는 링 상에 `vnodes_per_node`개의 가상 노드를 배치하며, 32비트 MD5 해시(`stable_hash`)를 기준으로 정렬된 해시 링을 형성합니다.

### 1. `STANDARD_CONSISTENT_HASH` (표준 일관된 해싱)
- 키 $k$의 해시값 시계 방향 첫 번째 가상 노드의 물리 노드($S_{primary}$)에 무조건 할당합니다.
- 해당 노드의 현재 부하가 `node_max_capacity`를 초과하면 노드가 사망(`crashed_nodes`에 추가, 링에서 제거)합니다.
- 노드 사망 시 링이 재구성되고 시계 방향 다음 노드로 페일오버되며, 이 노드 역시 한계 초과 시 연쇄 사망합니다.
- 2개 이상의 노드가 사망하거나 클러스터가 전멸하면 `status: FAILED`, `verdict: "CASCADING_CLUSTER_COLLAPSE"`로 판정됩니다.

### 2. `POWER_OF_TWO_CHOICES` (무작위 2선택 로드 밸런싱)
- 키와 요청 ID를 조합한 해시로 활성 노드 중 2개의 후보 노드를 선택하고, 현재 부하가 더 적은 노드에 할당합니다.
- 부하는 고르게 분산되지만 캐시 지역성이 파괴되어 캐시 적중률(`cache_hit_rate`)이 50% 미만으로 떨어지면 `status: FAILED`, `verdict: "CACHE_LOCALITY_COLLAPSE"`로 판정됩니다.

### 3. `BOUNDED_LOADS` (Google Bounded Loads Consistent Hashing)
- 허용 상한 용량: $C_{bounded} = \max\left(1, \left\lceil (1 + \epsilon) \cdot \frac{M}{N} \right\rceil\right)$
  (여기서 $M$은 현재까지 투입된 전체 활성 요청량 또는 인플라이트 요청량, $N$은 활성 노드 수)
- 키 $k$의 시계 방향 1차 노드($S_{primary}$)부터 시작하여 링을 시계 방향으로 순회합니다:
  - 순회 중 만난 활성 노드의 현재 부하가 $C_{bounded}$ 미만이면 해당 노드에 즉시 할당합니다.
  - 1차 노드가 아닌 다른 노드에 할당된 경우 `spillover_count`를 1 증가시킵니다.
  - 모든 노드가 포화된 경우 부하가 가장 적은 노드에 할당합니다.
- 노드 사망 0건 및 안정적 캐시 분산을 보장하며 `status: SUCCESS`, `verdict: "OPTIMAL_BOUNDED_LOADS_CONSISTENT_HASH"`로 판정됩니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "mode": "BOUNDED_LOADS",
    "epsilon": 0.25,
    "vnodes_per_node": 50,
    "node_max_capacity": 60,
    "nodes": ["edge_cache_1", "edge_cache_2", "edge_cache_3", "edge_cache_4"]
  },
  "workload": [
    {"op": "ROUTE", "wallclock_ms": 0.0, "req_id": "c1_req_0", "key": "live_stream_final_match"},
    {"op": "ROUTE", "wallclock_ms": 10.0, "req_id": "c1_req_1", "key": "live_stream_final_match"},
    {"op": "NODE_DOWN", "wallclock_ms": 50.0, "node": "edge_cache_2"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "mode": "BOUNDED_LOADS",
    "total_requests": 80,
    "active_nodes_remaining": 4,
    "crashed_nodes": [],
    "spillover_count": 35,
    "cache_hit_rate": 0.562
  },
  "metrics": {
    "total_requests": 80,
    "primary_assignments": 45,
    "spillover_count": 35,
    "crashed_node_count": 0,
    "max_node_load": 25,
    "min_node_load": 15,
    "average_node_load": 20.0,
    "load_imbalance_ratio": 1.25,
    "cache_hit_rate": 0.562,
    "verdict": "OPTIMAL_BOUNDED_LOADS_CONSISTENT_HASH"
  },
  "node_loads": {
    "edge_cache_1": 25,
    "edge_cache_2": 20,
    "edge_cache_3": 15,
    "edge_cache_4": 20
  },
  "sample_events": [
    {
      "wallclock_ms": 0.0,
      "op": "ROUTE",
      "req_id": "c1_req_0",
      "key": "live_stream_final_match",
      "primary_node": "edge_cache_1",
      "assigned_node": "edge_cache_1",
      "spillover": false,
      "current_node_load": 1
    }
  ]
}
```
