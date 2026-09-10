# 문제 #289: 리눅스 커널 AutoNUMA 밸런싱: NUMA Hinting Page Fault(#PF), task_numa_placement 및 무경합 양방향 태스크 스왑(Two-Way Task Swap) 시뮬레이터

## 실무 배경: 듀얼 소켓 128코어 DB 서버의 인터커넥트(UPI) 병목과 메모리 지연 시간 3배 폭증 참사
대규모 인메모리 분산 데이터베이스(Redis, SAP HANA, RocksDB)를 2소켓(128코어, NUMA Node 0 & Node 1) 서버에 마이그레이션한 직후, 초당 트랜잭션 처리량(TPS)이 싱글 소켓 대비 45% 하락하고 P99 쿼리 지연시간이 35ns에서 105ns(3배)로 폭증하는 치명적인 참사가 발생했습니다.

리눅스 커널 성능 분석 도구 `perf c2c` 및 `numastat` 분석 결과, Node 0에서 실행 중인 쿼리 워커 스레드들이 읽고 쓰는 힙 메모리의 82%가 물리적으로 Node 1의 DRAM에 상주하고 있었으며, 반대로 Node 1의 스레드들은 Node 0의 메모리를 원격 참조하고 있었습니다:
```text
  NUMA Node 0:
    numa_hit:        1,200,450
    numa_miss:       8,450,210  <-- 심각한 원격 메모리 참조!
  NUMA Node 1:
    numa_hit:        1,150,300
    numa_miss:       7,980,120  <-- 심각한 원격 메모리 참조!
  UPI Interconnect Saturation: 94.2% (Bus Congestion / Throttling)
```

인텔 UPI(Ultra Path Interconnect) 또는 AMD 인피니티 패브릭(Infinity Fabric)을 건너가는 **원격 메모리 접근(Remote Access)**은 로컬 DRAM 접근(약 30ns)에 비해 3배 이상의 물리적 지연시간(약 90~110ns)을 유발하며, 대역폭 포화 시 전체 시스템 버스를 마비시킵니다.

리눅스 커널 CFS 스케줄러(`kernel/sched/fair.c`)는 이를 해결하기 위해 **AutoNUMA (Automatic NUMA Balancing)** 하부시스템을 탑재했습니다.
AutoNUMA는 가상 메모리 영역의 PTE 권한을 주기적으로 제거(`_PAGE_PROTNONE`)하여 인위적인 경미한 페이지 폴트(**NUMA Hinting Fault**)를 유도하고, 어떤 태스크가 어떤 노드의 메모리를 얼마나 자주 접근하는지 프로파일링한 뒤, **페이지 마이그레이션(`migrate_misplaced_page`)**과 코어 간 부하 불균형 없이 태스크의 친화도를 맞교환하는 **양방향 태스크 스왑(`task_numa_compare / TASKS_SWAPPED`)**을 단행합니다.

커널 스케줄러 엔지니어로서, 리눅스 커널 AutoNUMA의 힌팅 폴트 감지, 메모리 친화도 계산, 페이지 마이그레이션 및 무경합 태스크 스왑 엔진을 구현하십시오.

---

## AutoNUMA 시뮬레이션 알고리즘 사양

### 1. 물리 토폴로지 및 메모리 접근 비용 모델
* 2개의 NUMA 노드: `Node 0`, `Node 1`.
* 로컬 메모리 접근 지연: `local_latency` (기본 30.0ns, `task.cpu_node == page.node`).
* 원격 메모리 접근 지연: `remote_latency` (기본 90.0ns, `task.cpu_node != page.node`).

---

### 2. AutoNUMA 3단계 파이프라인

#### 단계 1: 힌팅 스캔 (`ARM_SCAN(task_id, page_ids)`)
- 커널의 `task_numa_work()`가 태스크의 대상 페이지 PTE를 `_PAGE_PROTNONE`으로 마킹합니다.
- 해당 페이지들의 `armed_hinting = True`로 설정되어 다음 접근 시 힌팅 폴트가 격발될 준비를 마칩니다.

#### 단계 2: 메모리 접근 및 힌팅 폴트 격발 (`ACCESS(task_id, page_id)`)
1. 태스크의 현재 실행 코어(`cpu_node`)와 페이지의 물리 상주 노드(`page.node`)를 비교하여 지연 시간 누적.
2. 만약 `page.armed_hinting == True`인 경우:
   - `hinting_faults_count += 1`.
   - `page.armed_hinting = False` (권한 정상 복원).
   - 태스크의 NUMA 통계 갱신: `task.numa_faults[page.node] += 1`.
   - **페이지 마이그레이션 판정**:
     - 원격 접근인 경우, 해당 페이지에 대한 연속 원격 접근 횟수가 임계치(`page_migration_threshold`, 기본 2회)에 도달하면:
       - `page.node = task.cpu_node` (페이지를 태스크의 로컬 노드로 물리 이주).
       - `page_migrations_count += 1`.
       - 연속 카운터 초기화.

#### 단계 3: 태스크 재배치 및 양방향 스왑 (`EVALUATE_PLACEMENT(task_a, task_b)`)
- **단일 태스크 이주 (`task_b` 생략 시)**:
  - `task_a`의 총 폴트 중 원격 노드 폴트 비율이 `task_swap_threshold`(기본 60%) 이상이면:
    - `task_a.cpu_node = 1 - task_a.cpu_node`.
    - `task_swaps_count += 1`.
    - 결과: `{"action": "TASK_MIGRATED", "task": task_a, "new_node": ...}`.
- **양방향 태스크 스왑 (`task_a`, `task_b` 지정 시)**:
  - `task_a`와 `task_b`가 서로 다른 노드에 있고,
  - `task_a`는 상대방 노드의 메모리를 더 선호하며 (`faults_a[node_b] > faults_a[node_a]`),
  - `task_b` 또한 상대방 노드의 메모리를 더 선호하는 경우 (`faults_b[node_a] > faults_b[node_b]`):
    - 코어 간 런큐 부하 불균형(Load Imbalance)을 0으로 유지하면서 두 태스크의 코어 친화도를 즉시 맞교환!
    - `task_a.cpu_node, task_b.cpu_node = node_b, node_a`.
    - `task_swaps_count += 1`.
    - 결과: `{"action": "TASKS_SWAPPED", "task_a": task_a, "task_b": task_b}`.
  - 조건 미충족 시: `{"action": "NOOP"}`.

---

## 입력 형식
표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "local_latency": 30.0,
    "remote_latency": 90.0,
    "page_migration_threshold": 2,
    "task_swap_threshold": 0.6
  },
  "initial_tasks": [
    {"task_id": "worker_1", "cpu_node": 0, "pages": ["p1", "p2"], "page_initial_nodes": [1, 1]},
    {"task_id": "worker_2", "cpu_node": 1, "pages": ["p3", "p4"], "page_initial_nodes": [0, 0]}
  ],
  "operations": [
    {"op": "ARM_SCAN", "task_id": "worker_1", "page_ids": ["p1"]},
    {"op": "ARM_SCAN", "task_id": "worker_2", "page_ids": ["p3"]},
    {"op": "ACCESS", "task_id": "worker_1", "page_id": "p1"},
    {"op": "ACCESS", "task_id": "worker_2", "page_id": "p3"},
    {"op": "EVALUATE_PLACEMENT", "task_a": "worker_1", "task_b": "worker_2"},
    {"op": "ACCESS", "task_id": "worker_1", "page_id": "p1"}
  ]
}
```

## 출력 형식
표준 출력(stdout)으로 JSON 단일 라인으로 시뮬레이션 결과를 출력합니다:
```json
{
  "operations_count": 6,
  "history": [
    {"op": "ARM_SCAN", "task_id": "worker_1"},
    {"op": "ARM_SCAN", "task_id": "worker_2"},
    {"task": "worker_1", "page": "p1", "is_local": false, "latency_ns": 90.0, "hinting_fault": true, "page_migrated_to_node": null},
    {"task": "worker_2", "page": "p3", "is_local": false, "latency_ns": 90.0, "hinting_fault": true, "page_migrated_to_node": null},
    {"action": "TASKS_SWAPPED", "task_a": "worker_1", "task_b": "worker_2"},
    {"task": "worker_1", "page": "p1", "is_local": true, "latency_ns": 30.0, "hinting_fault": false, "page_migrated_to_node": null}
  ],
  "metrics": {
    "total_accesses": 3,
    "local_accesses": 1,
    "remote_accesses": 2,
    "local_access_ratio_pct": 33.33,
    "average_latency_ns": 70.0,
    "hinting_faults_count": 2,
    "page_migrations_count": 0,
    "task_swaps_count": 1,
    "tasks": {
      "worker_1": {"cpu_node": 1, "numa_faults": {"0": 0, "1": 1}},
      "worker_2": {"cpu_node": 0, "numa_faults": {"0": 1, "1": 0}}
    },
    "pages": {
      "p1": {"current_node": 1},
      "p2": {"current_node": 1},
      "p3": {"current_node": 0},
      "p4": {"current_node": 0}
    }
  }
}
```
