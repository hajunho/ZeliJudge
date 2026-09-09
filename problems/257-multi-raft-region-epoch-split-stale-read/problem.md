# #257 [데이터가 반으로 쪼개졌는데 왜 옛날 리더가 엉뚱한 노드에 덮어써요?!: 분산 SQL Multi-Raft 아키텍처의 리전 에포크(Region Epoch) 불일치, 동적 스플릿/머지 레이스 컨디션과 리전 리스(Range Lease) 만료 검증 (Distributed SQL: Multi-Raft Region Epoch Validation, Dynamic Split/Merge Race Conditions & Range Lease Linearizability)]

## 1. 장애 및 실무 시나리오

초대규모 글로벌 이커머스 포털의 분산 NewSQL 스토리지 팀은 TiKV 및 CockroachDB와 유사한 **Multi-Raft 아키텍처** 기반 분산 키-값 저장소 클러스터를 운영하고 있습니다.

이 시스템에서 전체 키스페이스(Global Keyspace)는 사전식 순서(Lexicographical order)로 정렬된 연속적인 키 범위인 **리전(Region / Range)**으로 수평 분할되며, 각 리전은 고유한 3~5개의 복제본 노드들로 구성된 독립적인 **Raft 합의 그룹(Raft Consensus Group)**을 형성합니다. 단일 물리 스토리지 노드에는 수천 개의 독립된 Raft 엔진 인스턴스가 병렬로 동작합니다(Multi-Raft).

```
[글로벌 키스페이스 분할 구조]
  ["a" ----------------------- "m" ----------------------- "z"]
     \                         /   \                         /
      +-----------------------+     +-----------------------+
      |  Region 1: ["a", "m")  |     |  Region 2: ["m", "z")  |
      |  (Raft Group 1)       |     |  (Raft Group 2)       |
      |  Leader: Node 1       |     |  Leader: Node 2       |
      |  Peers: Node 1, 2, 3  |     |  Peers: Node 1, 2, 3  |
      |  Epoch: ver=2, conf=1 |     |  Epoch: ver=1, conf=1 |
      +-----------------------+     +-----------------------+
```

그러나 블랙 프라이데이 자정 세일 이벤트 도중, 특정 상품 카테고리(`"orange"`, `"pear"` 등)에 초당 수만 건의 결제 쓰기 요청이 집중되는 핫스팟(Hotspot)이 발생하여 데이터 크기가 96MB 임계치를 초과했습니다.
이에 분산 스케줄러(Placement Driver, PD)는 부하를 분산하기 위해 **동적 리전 스플릿(Dynamic Region Split)**을 트리거했습니다:
- 기존 리전 1 `["a", "z")` (Epoch ver=1)이 `"m"`을 기준으로 분할되어,
  - 좌측 리전 1: `["a", "m")` (Epoch `version`이 1에서 2로 증가)
  - 우측 신규 리전 2: `["m", "z")` (신규 생성, Epoch `version=1`)로 분기되었습니다.

하지만 이 스플릿 직후, 전 세계 분산 클라이언트들에서 **데이터 덮어쓰기 오염과 선형성 위반(Linearizability Violation)**이라는 최악의 분산 버그가 터져 나왔습니다:
1. **클라이언트 라우팅 캐시와 Stale Epoch 버전 불일치**:
   - 일부 클라이언트는 로컬에 과거의 라우팅 캐시(`Region 1: ["a", "z"), version=1`)를 그대로 들고 있었습니다.
   - 클라이언트는 키 `"orange"`(현재 리전 2 소유)에 대한 쓰기 요청을 리전 1의 리더에게 보냈습니다.
   - 만약 스토리지 서버가 클라이언트의 `epoch.version`을 검증하지 않았다면, 리전 1의 리더가 이미 자신의 관리 영역을 벗어난 키를 멋대로 로컬에 기록하여 리전 2의 데이터와 충돌하고 트랜잭션 데이터가 영구 유실(Data Corruption)되는 참사가 발생합니다!
2. **리전 리스(Range Lease) 만료와 구 리더의 Stale Read 결함**:
   - Multi-Raft 아키텍처에서는 모든 읽기마다 Raft Quorum 왕복(Roundtrip)을 돌면 레이턴시가 폭증하므로, Raft 리더에게 시간 기반의 **Range Lease**를 부여하여 로컬 메모리에서 즉시 선형적 읽기(Local Linearizable Read)를 수행합니다.
   - 그러나 네트워크 일시 지연으로 리더의 리스 갱신 하트비트가 지연되어 리스 만료 시각(`lease_expire_time`)이 지났음에도 불구하고, 리더가 여전히 로컬 읽기를 처리하여 최신 쓰기가 반영되지 않은 과거 데이터를 반환하는 결함이 발생했습니다.
3. **리전 머지 후 삭제된 톰스톤(Tombstone) 접근**:
   - 데이터가 적은 두 인접 리전이 하나로 병합(Merge)된 후, 소멸된 우측 리전(Tombstone)으로 요청이 인입되어 에러가 발생했습니다.

당신은 분산 SQL 스토리지 엔진 코어 개발자로서, 클라이언트 요청의 리전 에포크(`version`, `conf_ver`), 키 범위 유효성, 리더 권한, 리전 리스 만료 여부를 100% 엄밀하게 검증하고 적절한 에러 핸들링과 라우팅 캐시 무효화를 지시하는 검증 엔진을 구현해야 합니다.

---

## 2. Multi-Raft 요청 검증 파이프라인 아키텍처

```
  [클라이언트 요청] : {region_id, epoch:{version, conf_ver}, key, op, value}
         |
         v
  [1. 리전 존재 검증] ---> 리전이 없거나 톰스톤(소멸)인가?
         |             └──> YES: TOMBSTONE_OR_INVALID_REGION_NOT_FOUND (PD 재조회)
         v
  [2. 키 범위 검증]   ---> key가 [start_key, end_key) 범위 밖인가?
         |             └──> YES: ROUTING_KEY_RANGE_MISMATCH (키스페이스 재매핑)
         v
  [3. 에포크 버전 검증] ---> req.version < server.version 인가? (Split/Merge 발생)
         |             └──> YES: STALE_REGION_EPOCH_SPLIT_MISMATCH (클라이언트 캐시 무효화)
         v
  [4. 에포크 멤버십 검증]-> req.conf_ver < server.conf_ver 인가? (Peer 변경)
         |             └──> YES: STALE_REGION_CONF_VER_MEMBERSHIP_MISMATCH
         v
  [5. 리더 여부 검증] ---> 대상 노드가 해당 리전의 현재 Raft 리더인가?
         |             └──> NO : NOT_LEADER_REDIRECT_REQUIRED (리더 노드로 리다이렉트)
         v
  [6. 리전 리스 검증] ---> op == "READ" 이고 current_time >= lease_expire_time 인가?
         |             └──> YES: RANGE_LEASE_EXPIRED_LINEARIZABILITY_RISK (하트비트 필요)
         v
  [7. 정상 연산 실행] ---> READ: 로컬 데이터 반환 / WRITE: 로컬 및 Raft 적용!
```

---

## 3. 입력 사양 (Input Specification)

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다:

```json
{
  "stores": [1, 2, 3],
  "initial_regions": [
    {
      "region_id": 1,
      "start_key": "a",
      "end_key": "z",
      "version": 1,
      "conf_ver": 1,
      "peers": [1, 2, 3],
      "leader_store_id": 1,
      "lease_expire_time": 1000,
      "initial_data": {"apple": "10", "banana": "20", "orange": "30"}
    }
  ],
  "initial_time": 100,
  "events": [
    {
      "event_type": "REGION_SPLIT",
      "timestamp": 120,
      "region_id": 1,
      "split_key": "m",
      "new_region_id": 2
    },
    {
      "event_type": "CLIENT_REQUEST",
      "timestamp": 130,
      "request_id": "c2-stale-write",
      "target_store_id": 1,
      "region_id": 1,
      "epoch": {"version": 1, "conf_ver": 1},
      "op": "WRITE",
      "key": "apple",
      "value": "99"
    }
  ]
}
```

### 파라미터 제약조건:
- `stores`: 클러스터 내 스토어(노드) ID 정수 리스트.
- `initial_regions`: 초기 리전 정의 리스트:
  - `start_key`, `end_key`: 사전순 반열린 구간 $[\text{start\_key}, \text{end\_key})$. 빈 문자열 `end_key`는 무한대($+\infty$)를 의미.
  - `version`: 키 범위 변경 시 증가하는 에포크 버전 (기본 1).
  - `conf_ver`: Raft 멤버십 변경 시 증가하는 설정 에포크 (기본 1).
  - `leader_store_id`: 현재 Raft 리더 스토어 ID.
  - `lease_expire_time`: 리더의 리전 리스 만료 타임스탬프.
- `events`: 시간 순서대로 발생하는 이벤트 리스트:
  - `REGION_SPLIT`: `region_id`, `split_key`, `new_region_id`
    - 좌측 리전(기존 ID)의 `end_key`를 `split_key`로 축소, `version += 1`.
    - 우측 리전(`new_region_id`) 생성: `[split_key, old_end)`, `version = 1`, `conf_ver = parent.conf_ver`.
  - `REGION_MERGE`: `source_region_id`, `target_region_id`
    - 타겟 리전이 소스 리전의 데이터를 흡수하고 범위를 `source.end_key`까지 확장.
    - `target.version += max(source.version, target.version) + 1`. 소스 리전은 `tombstone = true`.
  - `TRANSFER_LEADER`: `region_id`, `new_leader_store_id`, `lease_duration`
    - 리더를 변경하고 `lease_expire_time = timestamp + lease_duration` 갱신.
  - `TIME_ADVANCE`: `new_time` (클러스터 시간 전진).
  - `CLIENT_REQUEST`: 클라이언트의 읽기/쓰기 요청:
    - `target_store_id`, `region_id`, `epoch: {version, conf_ver}`, `op: "READ" | "WRITE"`, `key`, `value`.

---

## 4. 시뮬레이션 규칙 및 판정 계층

모든 이벤트 수행 후 발생하는 에러들에 대해 다음 엄격한 우선순위에 따라 최종 `status`를 결정합니다:

1. `stale_version_errors > 0`: `"STALE_REGION_EPOCH_SPLIT_MISMATCH"`
   - 클라이언트의 `epoch.version`이 서버보다 낮아 거부됨. 클라이언트 라우팅 캐시 무효화 및 PD 재조회 필요.
2. `stale_conf_ver_errors > 0`: `"STALE_REGION_CONF_VER_MEMBERSHIP_MISMATCH"`
   - 피어 멤버십 에포크 불일치.
3. `lease_expired_errors > 0`: `"RANGE_LEASE_EXPIRED_LINEARIZABILITY_RISK"`
   - 리더의 Range Lease가 만료되어 선형적 읽기가 거부됨.
4. `not_leader_errors > 0`: `"NOT_LEADER_REDIRECT_REQUIRED"`
   - 비리더 팔로워 노드로 요청이 인입되어 리다이렉트 필요.
5. `region_not_found_errors > 0`: `"TOMBSTONE_OR_INVALID_REGION_NOT_FOUND"`
   - 머지되어 소멸된 톰스톤 리전 또는 존재하지 않는 리전 접근.
6. `key_not_in_region_errors > 0`: `"ROUTING_KEY_RANGE_MISMATCH"`
   - 요청 키가 리전의 키 범위 밖임.
7. 모든 요청이 무결하게 성공한 경우: `"HEALTHY_MULTI_RAFT_CONSISTENCY"`

---

## 5. 출력 사양 (Output Specification)

표준 출력(stdout)으로 다음 스키마의 JSON을 한 줄로 출력합니다:

```json
{
  "status": "HEALTHY_MULTI_RAFT_CONSISTENCY",
  "metrics": {
    "total_active_regions": 2,
    "successful_reads": 2,
    "successful_writes": 1,
    "stale_version_errors": 0,
    "stale_conf_ver_errors": 0,
    "not_leader_errors": 0,
    "key_not_in_region_errors": 0,
    "region_not_found_errors": 0,
    "lease_expired_errors": 0
  },
  "diagnostics": [
    "All Multi-Raft operations completed with linearizable consistency and matching epochs."
  ],
  "recommended_tuning": {
    "suggestion": "Optimal Multi-Raft cluster state maintained."
  }
}
```
