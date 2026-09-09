# Problem 193: 분산 스토리지: DynamoDB/Cassandra 스타일 Gossip 안티-엔트로피, Vector Clock 인과적 충돌 해소 및 톰스톤(Tombstone) 좀비 부활 방어

## 문제 설명

글로벌 분산 키-값 NoSQL 스토리지(Amazon DynamoDB, Apache Cassandra, Riak 등)를 운영하는 대규모 클라우드 데이터 인프라 팀은 마스터리스(Masterless) 멀티 리전 클러스터에서 심각한 데이터 무결성 훼손 현상을 겪었습니다.

1. **톰스톤(Tombstone) 미사용 물리 삭제로 인한 좀비 데이터 부활 참사(Zombie Data Resurrection)**:
   - 사용자가 탈퇴하거나 삭제한 민감 개인정보 레코드를 특정 복제본 노드에서 즉시 물리적(`DELETE`/`del`)으로 제거했습니다.
   - 일시적으로 네트워크 단절(Network Partition)이나 재부팅 중이었던 노드가 다시 온라인으로 복귀한 뒤, 백그라운드 **가십 안티-엔트로피(Gossip Anti-Entropy)** 동기화가 실행되었습니다.
   - 단절되었던 노드는 과거 데이터를 그대로 갖고 있었고, 정상 노드는 데이터가 존재하지 않았기 때문에, 동기화 알고리즘은 삭제된 레코드를 '새로 삽입된 데이터'로 오인하여 정상 노드로 다시 복사했습니다!
   - 그 결과, 완전히 삭제되었던 사용자의 계정과 주문 내역이 며칠 뒤 갑자기 다시 나타나는 **좀비 데이터 부활(Zombie Resurrection)** 대형 사고가 터졌습니다.
2. **동시 분기 쓰기 인과성(Causality) 상실과 벡터 클록(Vector Clock) 불일치**:
   - 중앙 마스터나 단일 리더가 없는 환경에서 두 개 이상의 코디네이터 노드가 동시에 동일 키를 수정했을 때, 단순 타임스탬프만으로는 NTP 클록 드리프트로 인해 인과적 선후 관계를 추적할 수 없어 데이터가 덮어씌워지거나 클러스터 간 불일치가 발생했습니다.
   - 분산 스토리지 엔진은 **벡터 클록(Vector Clock, `{Node_ID: Counter}`)**을 통해 인과적 우위(Dominance)를 엄격히 판별하고, 동시 충돌(Concurrent Divergence) 시 LWW(Last-Write-Wins) 또는 Sibling 병합을 수행해야 합니다.
3. **쿼럼 읽기 복구(Read Repair)와 GC Grace Period**:
   - 삭제는 물리 삭제가 아닌 **삭제 마커인 톰스톤(Tombstone)**을 벡터 클록과 함께 기록하여 클러스터 전체에 전파해야 합니다.
   - 클러스터의 모든 복제본에 톰스톤이 충분히 복제될 수 있도록 **`gc_grace_seconds`** 동안 톰스톤을 유지한 뒤에만 안전하게 가비지 컬렉션(GC Purge)을 수행해야 합니다.
   - 또한 클라이언트가 쿼럼 읽기(Quorum Read)를 수행할 때 구버전을 반환하는 뒤처진 복제본을 발견하면 즉시 최신 버전(또는 톰스톤)으로 인라인 갱신하는 **Read Repair**를 작동시켜 최종 일관성(Eventual Consistency)을 보장해야 합니다.

엔지니어링 팀은 분산 가십 안티-엔트로피, 벡터 클록 인과성 추적, 톰스톤 수명 주기, 그리고 Read Repair를 시뮬레이션하여 무결점 분산 스토리지 엔진의 동작을 검증하고자 합니다.

---

## 핵심 시스템 파라미터 및 원리

### 1. 벡터 클록(Vector Clock) 비교 규칙
두 레코드 $A$와 $B$의 벡터 클록 $V_A, V_B$에 대해:
- **$A$가 $B$를 지배 ($A > B$, `A_DOMINATES`)**:
  - 모든 노드 $k$에 대해 $V_A[k] \ge V_B[k]$이고, 최소 하나의 노드 $j$에 대해 $V_A[j] > V_B[j]$인 경우.
  - $A$가 $B$의 확실한 인과적 후속 버전이므로 $A$를 선택.
- **동시 충돌 (`CONCURRENT`)**:
  - 어느 한쪽도 다른 쪽을 일방적으로 지배하지 못하는 경우 (예: $V_A = \{N_1: 2, N_2: 1\}$, $V_B = \{N_1: 1, N_2: 2\}$).
  - `conflict_resolution == "LWW"`인 경우 타임스탬프 기준 승자를 선택하고 벡터 클록을 $V_{merged}[k] = \max(V_A[k], V_B[k])$로 병합.
  - `conflict_resolution == "NONE"`인 경우 충돌 미해소 상태로 발산(`CONCURRENT_VECTOR_CLOCK_DIVERGENCE`).

### 2. 톰스톤(Tombstone) 라이프사이클
- `enable_tombstones == false`: 물리 삭제를 수행하여, 파티션 복구 노드와 가십 동기화 시 삭제된 데이터가 도로 살아나는 좀비 부활 재앙 발생(`ZOMBIE_DATA_RESURRECTION_DISASTER`).
- `enable_tombstones == true`: 삭제 시 `is_tombstone = true` 마커와 함께 새 벡터 클록을 발행하여 복제본들에 전파.
- `PURGE_TOMBSTONES`: 톰스톤 생성 후 `current_time - tombstone_time >= gc_grace_ms`가 경과한 경우에만 물리적으로 파기(GC)하여 영구 삭제 완수.

### 3. 쿼럼 읽기 및 Read Repair
- 읽기 요청 시 정해진 쿼럼 수(`read_quorum`)만큼 복제본들의 레코드를 수집.
- 복제본 간 버전 불일치가 감지되면 최신 지배 버전(또는 톰스톤)을 뒤처진 복제본에 즉시 다시 써넣는 Read Repair 수행.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "system": {
    "nodes": ["N1", "N2", "N3"],
    "replication_factor": 3,
    "read_quorum": 2,
    "write_quorum": 2,
    "gc_grace_ms": 50.0,
    "enable_tombstones": true,
    "conflict_resolution": "LWW"
  },
  "events": [
    {
      "timestamp_ms": 0.0,
      "type": "WRITE",
      "key": "user:100",
      "value": "Alice",
      "coordinator": "N1"
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 형식 결과를 출력합니다.

```json
{
  "status": "SUCCESS",
  "metrics": {
    "total_writes": 1,
    "total_reads": 0,
    "read_repairs_count": 0,
    "zombie_resurrections_count": 0,
    "conflicts_detected": 0,
    "tombstones_purged": 3,
    "verdict": "OPTIMAL_GOSSIP_VECTOR_CLOCK_REPAIR"
  },
  "nodes_state": {
    "N1": {},
    "N2": {},
    "N3": {}
  },
  "events_log": [
    {
      "time_ms": 0.0,
      "event": "WRITE_COMMITTED",
      "key": "user:100",
      "value": "Alice",
      "vector_clock": {
        "N1": 1
      },
      "replicas_written": 3
    }
  ]
}
```

### 판정 규칙 (Verdict Rules)
1. `zombie_resurrections_count > 0`:
   - `status = "FAILED"`, `verdict = "ZOMBIE_DATA_RESURRECTION_DISASTER"`
2. `conflicts_detected > 0`이고 `conflict_resolution == "NONE"`:
   - `status = "FAILED"`, `verdict = "CONCURRENT_VECTOR_CLOCK_DIVERGENCE"`
3. 좀비 부활이 없고 모든 벡터 클록과 톰스톤이 정상 수렴된 경우:
   - `status = "SUCCESS"`, `verdict = "OPTIMAL_GOSSIP_VECTOR_CLOCK_REPAIR"`
