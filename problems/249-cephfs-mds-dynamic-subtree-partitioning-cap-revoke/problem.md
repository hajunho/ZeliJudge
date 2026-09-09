# 문제 249: Distributed File Storage — CephFS 메타데이터 서버(MDS) 동적 서브트리 파티셔닝, 클라이언트 Capability(Caps) 회수 지연 및 Beacon Heartbeat 장애 조치 플래핑

## 1. 개요 (Incident Scenario)

대규모 프라이빗 클라우드 및 Kubernetes 컨테이너 플랫폼(OpenStack, CSI-CephFS)에서는 수천 대의 컴퓨팅 노드에 POSIX 호환 분산 공유 파일시스템을 제공하기 위해 **CephFS**를 운용합니다. CephFS는 파일 데이터는 수천 개의 OSD(RADOS)에 분산 저장하고, 파일 계층 디렉토리 구조와 메타데이터는 **메타데이터 서버(MDS, Metadata Server)** 클러스터가 전담 처리합니다. 메타데이터 부하를 분산하기 위해 여러 대의 MDS가 활성(Active) 상태로 구동되는 멀티 액티브 MDS(Multi-Active MDS) 아키텍처를 채택하고 있습니다.

그러나 대규모 분산 빌드(CI/CD) 및 AI 분산 학습 워크로드가 동시에 몰린 날, CephFS 클러스터에서 심각한 서비스 장애가 발생했습니다:
1. **서브트리 마이그레이션 중단 및 클라이언트 I/O 정지 (Subtree Migration Stuck & Client Freeze)**: MDS 로드 밸런서가 과부하된 랭크 0(MDS 0)에서 랭크 1(MDS 1)로 디렉토리 서브트리를 이전(Export)하려 했으나, 해당 디렉토리의 파일 Capability(Caps)를 쥐고 있던 워커 노드가 응답하지 않았습니다(`MDS_HEALTH_CLIENT_LATE`). 클라이언트 축출(Eviction)이 비활성화된 상태에서 메타데이터 락이 풀리지 않아 수백 개의 컨테이너 I/O가 영구 정지되었습니다.
2. **서브트리 핑퐁 플래핑 (Ping-Pong Subtree Flapping Freeze)**: 쿨다운(Cooldown) 감쇠 시간이 설정되지 않은 상태에서 두 디렉토리 간 부하가 시시각각 역전되자, 밸런서가 서브트리를 랭크 0과 랭크 1 사이에서 수십 초 간격으로 끊임없이 왕복 이전(Ping-Pong)시켰습니다. 이전할 때마다 디렉토리 트리가 동결(`freeze_tree`)되어 p99 지연 시간이 수십 초 이상 치솟았습니다.
3. **동기식 캐시 정리로 인한 Beacon 하트비트 타임아웃 및 MDS 플래핑 (MDS Beacon Timeout Failover Flapping)**: 단일 디렉토리에 수만 개의 임시 파일이 폭증하자 MDS 캐시 제한치(`max_cached_inodes`)를 초과했습니다. MDS가 동기식으로 수만 개의 아이노드를 한꺼번에 캐시에서 방출(Trim)하는 동안 메인 디스패처 루프가 잠식되었고, Ceph Monitor(`ceph-mon`)로 보내는 하트비트 비콘(`MDS_BEACON`)이 유예 시간(`beacon_grace_sec`)을 초과하여 모니터가 정상 작동 중인 MDS를 죽은 것으로 판단하고 강제 장애 조치(Failover)를 단행했습니다.

당신은 분산 스토리지 코어 엔지니어로서, 클러스터 구성, 초기 서브트리 배치 및 부하(Heat), 클라이언트 응답성, 이벤트 스트림을 바탕으로 CephFS MDS의 동적 서브트리 파티셔닝, Cap 회수, 캐시 트리밍 및 하트비트 상태 머신을 시뮬레이션하고, 장애 근본 원인(Root Cause)과 프로덕션 최적화 방안을 도출해야 합니다.

---

## 2. 아키텍처 및 상태 머신 (System Architecture & State Machine)

```
       [ Ceph Monitor Cluster (ceph-mon) ]
                ▲                     ▲
  mds_beacon    │                     │ mds_beacon (Timeout > 4s => Failover!)
                │                     │
       ┌────────┴──────┐       ┌──────┴────────┐
       │ MDS Rank 0    │       │ MDS Rank 1    │
       │ (Active)      │       │ (Active)      │
       └───────┬───────┘       └───────┬───────┘
               │                       │
               │◄─── Subtree Export ──►│
               │     (freeze_tree)     │
               ▼                       ▼
    ┌───────────────────────────────────────────────┐
    │          Distributed Directory Hierarchy      │
    │  / (Rank 0)   /data (Rank 0->1)   /home (R 1) │
    └───────────────────────────────────────────────┘
               ▲
               │ CEPH_CAP_OP_REVOKE
               │
    ┌──────────┴───────────────┐
    │ Unresponsive Client      │ ◄── (client_eviction_enabled: false)
    │ (Holding /data Inode Cap)│     ==> Migration STUCK! Client I/O Freeze!
    └──────────────────────────┘
```

### (1) 로드 밸런서 및 서브트리 이전 규칙
- 각 랭크 $r$의 총 부하: $	ext{Load}(r) = \sum 	ext{heat of subtrees auth to } r$.
- 불균형 비율: $	ext{ratio} = rac{\max(	ext{Load})}{\max(1, \min(	ext{Load}))}$.
- `ratio >= imbalance_threshold`인 경우, 가장 부하가 높은 랭크에서 **고정되지 않은(Unpinned) 가장 부하가 큰 서브트리**를 최저 부하 랭크로 이전을 시도합니다.
- **서브트리 핀(Pinning)**: `pinned_rank is not None`인 서브트리는 밸런서에 의해 절대 이전되지 않습니다.
- **쿨다운 감쇠(Cooldown)**: `migration_cooldown_sec > 0`인 경우, 이전 후 경과 시간이 쿨다운 미만이면 이전을 건너뜁니다.
- **플래핑 감지(Flapping)**: `migration_cooldown_sec == 0`인 상태에서 30초 이내에 동일 서브트리가 재이전되면 `subtree_flapping_freezes += 1` 및 플래핑이 감지됩니다.

### (2) 클라이언트 Capability(Caps) 회수 규칙
- 서브트리를 다른 랭크로 이전하기 위해 해당 서브트리 내의 아이노드에 대해 Capability를 보유한 클라이언트들에게 `REVOKE` 메시지를 전송합니다.
- 미응답 클라이언트(`is_responsive == false`)가 존재하는 경우:
  - `client_eviction_enabled == true`: 미응답 클라이언트를 즉시 강제 축출(`evicted = true`)하고 세션을 종료하여 이전을 정상 완료합니다.
  - `client_eviction_enabled == false`: Cap 회수가 타임아웃되어 이전이 영구 교착(Stuck) 상태에 빠집니다 (`migrations_stuck += 1`).

### (3) 아이노드 캐시 트리밍 및 하트비트 비콘 규칙
- 랭크에 캐시된 총 아이노드 수 > `max_cached_inodes`인 경우 초과분(`excess`)에 대해 트리밍을 수행합니다.
- `async_cache_trim == false` (동기식 트리밍):
  - 메인 루프 잠식 시간: $	ext{stall\_sec} = rac{	ext{excess}}{10000}$.
  - 만약 $	ext{stall\_sec} > 	ext{beacon\_grace\_sec}$이면 Ceph Monitor와의 통신이 두절되어 `beacon_heartbeat_timeouts += 1` 및 `mds_failovers += 1`이 발생합니다.
- `async_cache_trim == true` (비동기 청크 트리밍): 백그라운드 워커가 점진적으로 해제하므로 비콘 지연 없이 안전하게 완료됩니다.

---

## 3. 입력 사양 (Input Specification)

표준 입력(`sys.stdin`)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "cluster_config": {
    "num_mds_ranks": 2,
    "balancer_interval_sec": 10,
    "imbalance_threshold": 1.5,
    "migration_cooldown_sec": 0,
    "cap_revoke_timeout_sec": 5,
    "client_eviction_enabled": false,
    "beacon_grace_sec": 4,
    "async_cache_trim": true,
    "max_cached_inodes": 50000
  },
  "subtrees": [
    {"path": "/", "auth_rank": 0, "heat": 100, "pinned_rank": null, "inode_count": 5000},
    {"path": "/export_vol", "auth_rank": 0, "heat": 1200, "pinned_rank": null, "inode_count": 20000},
    {"path": "/archive", "auth_rank": 1, "heat": 150, "pinned_rank": null, "inode_count": 10000}
  ],
  "clients": [
    {"client_id": "hung_k8s_worker", "holding_caps": ["/export_vol"], "is_responsive": false}
  ],
  "events": [
    {"time_sec": 10, "type": "TRIGGER_BALANCER"}
  ]
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(`sys.stdout`)으로 다음 필드를 포함하는 JSON 객체를 출력합니다:

```json
{
  "final_state": {
    "current_sec": 10,
    "rank_loads": {
      "0": 1300,
      "1": 150
    },
    "rank_inodes": {
      "0": 25000,
      "1": 10000
    },
    "subtrees": [
      {"path": "/", "auth_rank": 0, "heat": 100},
      {"path": "/export_vol", "auth_rank": 0, "heat": 1200},
      {"path": "/archive", "auth_rank": 1, "heat": 150}
    ]
  },
  "metrics": {
    "migrations_completed": 0,
    "migrations_stuck": 1,
    "subtree_flapping_freezes": 0,
    "client_evictions_count": 0,
    "evicted_clients": [],
    "beacon_heartbeat_timeouts": 0,
    "mds_failovers": 0
  },
  "root_cause": "SUBTREE_MIGRATION_STUCK_CLIENT_CAP_REVOKE_TIMEOUT",
  "recommendations": [
    "ENABLE_CLIENT_CAP_REVOKE_AUTO_EVICTION",
    "ENABLE_SUBTREE_MIGRATION_COOLDOWN_DAMPENING",
    "PIN_HIGH_HEAT_SUBTREES_TO_SPECIFIC_MDS"
  ]
}
```

### 진단 규칙 (Root Cause Hierarchy)
1. `beacon_timeout_occurred == true` $ightarrow$ `"MDS_BEACON_HEARTBEAT_TIMEOUT_CACHE_TRIM_FAILOVER"`
2. `stuck_migration_occurred == true` $ightarrow$ `"SUBTREE_MIGRATION_STUCK_CLIENT_CAP_REVOKE_TIMEOUT"`
3. `flapping_occurred == true` $ightarrow$ `"SUBTREE_MIGRATION_PING_PONG_FLAPPING_FREEZE"`
4. 기타 정상 상태 $ightarrow$ `"STABLE_MDS_CLUSTER_BALANCED"`

### 권고사항 도출 규칙
- `not client_eviction_enabled`: `"ENABLE_CLIENT_CAP_REVOKE_AUTO_EVICTION"`
- `migration_cooldown_sec == 0`: `"ENABLE_SUBTREE_MIGRATION_COOLDOWN_DAMPENING"`
- `not async_cache_trim`: `"ENABLE_ASYNC_CHUNKED_CACHE_TRIMMING"`
- 고정되지 않은 고부하 서브트리(`pinned_rank is None and heat >= 1000`): `"PIN_HIGH_HEAT_SUBTREES_TO_SPECIFIC_MDS"`
- 해당 사항이 없으면: `["MONITOR_MDS_BALANCER_AND_CAP_HEALTH"]`
