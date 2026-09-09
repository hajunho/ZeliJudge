# Problem 207: 원격 노드에 메모리가 64GB나 남았는데 왜 프로세스가 멈춰요?!: 리눅스 커널 NUMA: 원격 노드 접근 지연 vs zone_reclaim_mode 직접 회수 스톨과 numactl 메모리 정책 (Linux Kernel NUMA: Remote Node Access Latency vs zone_reclaim_mode Stalls & numactl Memory Policies)

## 문제 배경 및 개요

대규모 클라우드 및 온프레미스 인프라에서 멀티소켓(2-Socket / 4-Socket, Intel Xeon / AMD EPYC) 고성능 데이터베이스(Redis, MySQL InnoDB, PostgreSQL, Apache Cassandra, ScyllaDB)를 운영하는 SRE 및 데이터베이스 아키텍처 팀은 기이하고 파괴적인 **"원격 메모리 유휴 상태에서의 프로세스 영구 동결(Freezing while Remote RAM is Empty)"** 장애를 겪었습니다.

128GB의 RAM(소켓 0에 64GB, 소켓 1에 64GB)을 장착한 2소켓 서버에서 Redis/MySQL 데이터베이스가 40GB의 메모리를 추가로 할당하려던 순간, 시스템 모니터링에는 다음과 같은 기괴한 현상이 기록되었습니다:

```
[서버 전체 메모리 현황: 총 128 GB]
┌───────────────────────────────────────┬───────────────────────────────────────┐
│           NUMA Node 0 (소켓 0)        │           NUMA Node 1 (소켓 1)        │
│   Used: 63.5 GB / Cap: 64.0 GB        │   Used:  2.0 GB / Cap: 64.0 GB        │
│   (Page Cache: 20 GB, Anon: 43.5 GB)  │   (완전히 텅 빈 유휴 상태: 62 GB 여유!)│
└───────────────────┬───────────────────┴───────────────────────────────────────┘
                    │
                    ▼
[DB 스레드가 Node 0 CPU에서 메모리 4GB 추가 할당 요청]
                    │
     ┌──────────────┴──────────────┐
     │ zone_reclaim_mode = 1 설정? │
     └──────────────┬──────────────┘
                    │
         [YES: zone_reclaim_mode = 1]
         "원격 노드 메모리는 QPI/UPI 인터커넥트를 타야 하므로 느리다!
          Node 1에 62GB가 있든 말든 무조건 로컬 Node 0에서 페이지를 쥐어짜라!"
                    │
                    ▼
  [커널 직접 회수(Direct Reclaim) 발동]
  - Node 0의 20GB Page Cache를 디스크로 강제 플러시 & 제거
  - kswapd 대신 사용자 프로세스가 직접 커널 루프에 갇힘 (CPU %sys 100%)
  - 할당 스레드가 수백 ms ~ 수 초간 완전히 굳어버림 (Stop-the-World Stall)
  - 클라이언트 쿼리 타임아웃 폭풍 및 DB 헬스체크 실패로 강제 재부팅!
```

이 참사의 원인은 리눅스 커널의 **`vm.zone_reclaim_mode`**와 **NUMA 메모리 할당 정책(Memory Policy)** 간의 상호작용에 있었습니다:
1. **`zone_reclaim_mode = 1`의 참극**: 로컬 노드의 가용 메모리가 `low` 워터마크 이하로 떨어지면, 커널은 원격 노드(Node 1)에 수십 GB의 여유 메모리가 있더라도 원격 할당을 거부하고 **로컬 노드의 페이지 캐시를 동기식으로 회수(Direct Reclaim Stall)**합니다. 이 과정에서 프로세스는 무응답 상태에 빠집니다.
2. **`zone_reclaim_mode = 0`의 완화와 원격 접근 페널티**: `zone_reclaim_mode = 0`으로 설정하면 로컬 노드 고갈 시 즉시 원격 노드로 할당이 넘어가(Remote Spillover) 직접 회수 스톨을 피할 수 있습니다. 그러나 원격 노드에 배치된 메모리에 접근할 때는 QPI/UPI 인터커넥트 횡단으로 인해 로컬 접근 대비 2배 이상의 지연시간($60\,\text{ns} \rightarrow 140\,\text{ns}$)이 발생합니다.
3. **`numactl --interleave`를 통한 근본적 해결**: 대규모 공유 메모리를 사용하는 인메모리 캐시나 DB 버퍼 풀의 경우, `MPOL_INTERLEAVE` 정책을 통해 메모리 페이지를 모든 NUMA 노드에 라운드로빈으로 균등 분산시킴으로써 단일 노드의 워터마크 고갈을 방지하고 메모리 컨트롤러 대역폭을 2배로 집계(Aggregate)합니다.
4. **`MPOL_BIND`의 위험성**: 특정 노드에만 엄격하게 바인딩한 경우, 해당 노드가 고갈되면 원격 폴백이 원천 차단되어 OOM 킬러가 프로세스를 즉사시킵니다.
5. **AutoNUMA (`kernel.numa_balancing = 1`)**: 원격 노드에 할당된 페이지라도 로컬 CPU의 접근 빈도가 높으면 커널이 자동으로 힌팅 폴트(Hinting Fault)를 감지하여 페이지를 로컬 노드로 마이그레이션합니다.

당신은 리눅스 커널 메모리 관리자 아키텍트로서, NUMA 토폴로지, 존 워터마크, `zone_reclaim_mode`, 메모리 정책(`MPOL_*`), 그리고 AutoNUMA 마이그레이션을 완벽하게 모델링하는 시뮬레이터를 구축해야 합니다.

---

## 핵심 NUMA 정책 및 커널 파라미터 명세

### 1. 존 워터마크 (Zone Watermarks)
각 NUMA 노드는 3대 워터마크를 가집니다:
- `high_mb`: 여유 메모리가 이보다 많으면 안전 상태.
- `low_mb`: 여유 메모리가 이 이하로 떨어지면 kswapd 깨어남 및 메모리 회수/원격 폴백 판단 기준.
- `min_mb`: 긴급 상황(OOM 직전) 경계선.

### 2. `zone_reclaim_mode` 동작
- **`zone_reclaim_mode = 1`**:
  - 로컬 노드의 여유 메모리가 `low_mb` 미만이 되면, 원격 노드에 여유가 있더라도 즉시 로컬 노드의 재활용 가능 메모리(`page_cache_mb`)를 동기적으로 회수(`direct_reclaim_events += 1`)합니다.
  - 회수량에 비례하여 동기식 스톨 시간(`direct_reclaim_total_stall_ms`)이 발생하며, 스톨이 $50\,\text{ms}$ 이상 지속되면 `NUMA_ZONE_RECLAIM_DIRECT_STALL`로 판정됩니다.
- **`zone_reclaim_mode = 0`**:
  - 로컬 노드가 `low_mb`에 도달하면 즉시 여유가 있는 원격 노드로 여유 메모리를 할당(Remote Spillover)합니다.
  - 직접 회수 스톨이 발생하지 않으며(`stall = 0ms`), 판정은 `NUMA_REMOTE_SPILLOVER_NO_STALL`이 됩니다.

### 3. 메모리 할당 정책 (`memory_policy.mode`)
- **`MPOL_DEFAULT`**: 스레드가 현재 실행 중인 CPU의 로컬 노드에 우선 할당. `zone_reclaim_mode` 설정에 따라 로컬 직접 회수 또는 원격 폴백 수행.
- **`MPOL_INTERLEAVE`**: `target_nodes`에 지정된 모든 노드에 요청 메모리를 균등 분할(Round-Robin)하여 할당. 양 노드의 사용량이 대칭적으로 유지되며, 판정은 `OPTIMAL_NUMA_INTERLEAVED_BALANCED`.
- **`MPOL_BIND`**: 오직 `target_nodes`에서만 할당 허용. 여유 공간이 `min_mb` 이하로 떨어지면 원격 노드가 비어 있어도 즉시 `OOM_KILLED` (`NUMA_NODE_BIND_OOM`, `status: FAILED`).
- **`MPOL_PREFERRED`**: 지정된 우선 노드에 먼저 시도하고, 가용량이 부족하면 스톨 없이 다른 노드로 즉시 우회 할당.

### 4. AutoNUMA (`numa_balancing = true`)
- 원격 노드에 존재하는 메모리에 대해 로컬 CPU가 빈번한 읽기/쓰기를 수행할 경우, 커널이 이를 감지하여 해당 페이지를 로컬 노드로 물리적 마이그레이션(Page Migration)합니다.
- 판정은 `NUMA_AUTONUMA_PAGE_MIGRATED`.

---

## 입력 형식

표준 입력(Standard Input)으로 단일 JSON 객체가 주어집니다:

```json
{
  "numa_topology": {
    "nodes": [0, 1],
    "memory_per_node_mb": 16384,
    "watermarks_mb": {
      "min_mb": 256.0,
      "low_mb": 512.0,
      "high_mb": 1024.0
    },
    "latencies_ns": {
      "local_access_ns": 60.0,
      "remote_access_ns": 140.0
    },
    "distance_matrix": [
      [10, 20],
      [20, 10]
    ],
    "initial_usage_mb": {
      "0": {"anon_mb": 10240, "page_cache_mb": 4096},
      "1": {"anon_mb": 1024, "page_cache_mb": 1024}
    }
  },
  "kernel_config": {
    "zone_reclaim_mode": 1,
    "memory_policy": {
      "mode": "MPOL_DEFAULT"
    },
    "numa_balancing": false
  },
  "workload": [
    {"op": "ALLOC", "alloc_id": "alloc_1", "size_mb": 3072, "node_id": 0},
    {"op": "ACCESS", "alloc_id": "alloc_1", "node_id": 0, "access_count": 100000}
  ]
}
```

---

## 출력 형식

표준 출력(Standard Output)으로 복제 시뮬레이션 결과 JSON을 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "NUMA_ZONE_RECLAIM_DIRECT_STALL",
  "policy_mode": "MPOL_DEFAULT",
  "metrics": {
    "total_alloc_requests": 1,
    "successful_allocations": 1,
    "oom_events": 0,
    "total_allocated_mb": 3072.0,
    "local_allocation_count": 1,
    "remote_allocation_count": 0,
    "direct_reclaim_events": 1,
    "direct_reclaim_total_stall_ms": 125.0,
    "total_access_ops": 100000,
    "local_access_ops": 100000,
    "remote_access_ops": 0,
    "remote_access_ratio_pct": 0.0,
    "average_access_latency_ns": 60.0,
    "page_migrations_count": 0
  },
  "node_states": {
    "node_0": {
      "capacity_mb": 16384.0,
      "used_mb": 15872.0,
      "free_mb": 512.0,
      "anon_mb": 13312.0,
      "page_cache_mb": 2560.0
    },
    "node_1": {
      "capacity_mb": 16384.0,
      "used_mb": 2048.0,
      "free_mb": 14336.0,
      "anon_mb": 1024.0,
      "page_cache_mb": 1024.0
    }
  }
}
```

---

## 판정 기준 (Verdict Rules)

1. **`NUMA_NODE_BIND_OOM`**: `MPOL_BIND` 등으로 바인딩된 노드의 메모리가 소진되어 OOM 이벤트(`oom_events > 0`)가 발생한 경우 (`status: FAILED`).
2. **`NUMA_ZONE_RECLAIM_DIRECT_STALL`**: `zone_reclaim_mode = 1` 상태에서 로컬 노드 페이지 캐시 회수로 인해 직접 회수 스톨(`direct_reclaim_total_stall_ms >= 50.0`)이 발생한 경우.
3. **`OPTIMAL_NUMA_INTERLEAVED_BALANCED`**: `MPOL_INTERLEAVE` 정책을 통해 모든 노드에 대칭적으로 분산 할당된 경우.
4. **`NUMA_AUTONUMA_PAGE_MIGRATED`**: AutoNUMA가 활성화되어 원격 페이지가 로컬 노드로 자동 마이그레이션된 경우.
5. **`NUMA_REMOTE_SPILLOVER_NO_STALL`**: `zone_reclaim_mode = 0`으로 직접 회수 스톨 없이 원격 노드로 원활히 스필오버 할당된 경우.
6. **`NUMA_LOCAL_OPTIMAL`**: 로컬 노드 범위 내에서 100% 로컬 접근으로 완료된 경우.
