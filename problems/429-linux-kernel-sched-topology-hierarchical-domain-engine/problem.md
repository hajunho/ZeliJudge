# 문제 429: 리눅스 커널 스케줄러: 계층형 스케줄 도메인(sched_domain) 및 캐시 친화도 기반 NUMA 로드 밸런싱 엔진

## 1. 개요 (Overview)

수십에서 수백 개의 물리 CPU 코어를 탑재한 현대 멀티소켓 NUMA 서버 아키텍처에서 모든 CPU 코어가 동일한 메모리 접근 지연 시간(Uniform Latency)을 갖지 않습니다.
하나의 물리 코어 내부에서 실행 파이프라인과 L1/L2 캐시를 공유하는 **하이퍼스레딩(SMT)**, 동일 다이(Die) 상에서 L3 캐시를 공유하는 **멀티코어(MC)**, 그리고 원격 소켓 간 초고속 인터커넥트(Intel UPI, AMD Infinity Fabric)를 통해 메모리에 접근하는 **NUMA** 계층은 각각 상이한 통신 비용과 캐시 손실(Cache Miss Penalty)을 수반합니다.

리눅스 커널 CFS(Completely Fair Scheduler)는 이러한 물리적 하드웨어 구조를 추상화하기 위해 **스케줄 도메인 계층 구조(`struct sched_domain` 및 `struct sched_group`, `kernel/sched/topology.c`, `kernel/sched/fair.c`)**를 구성합니다.
스케줄러의 부하 분산 엔진(`load_balance()`)은 다음 핵심 원칙에 따라 동작합니다:
1. **계층적 주기 분산**: SMT/MC 도메인은 캐시 공유 비용이 낮으므로 매우 짧은 주기(수 밀리초)로 빈번하게 밸런싱을 수행하지만, NUMA 도메인은 원격 메모리 접근 오버헤드를 줄이기 위해 긴 주기(수십~수백 밀리초)와 높은 불균형 임계값(`numa_imbalance_threshold`)을 적용합니다.
2. **캐시 친화도(Cache Affinity) 보존**: 최근에 CPU에서 실행되어 캐시가 뜨거운 상태(**Cache-Hot**)인 태스크는 다른 코어로 이주될 경우 막대한 L1/L2 캐시 미스를 유발하므로, 도메인의 불균형이 캐시 친화 마진(`cache_hot_timeout`)을 초과하거나 대상 CPU가 완전히 유휴(Idle) 상태가 아닌 한 이주를 억제합니다.
3. **SMT 스레드 확산(Spreading)**: 유휴 물리 코어가 존재하는 경우, 이미 실행 중인 코어의 형제 SMT 스레드로 태스크를 몰아넣는 패킹(Packing)을 피하고 새로운 물리 코어로 분산시킵니다.

본 과제에서는 리눅스 커널 `kernel/sched/topology.c` 및 `fair.c`의 SMT/MC/NUMA 3계층 스케줄 도메인 토폴로지, 도메인별 부하 계산 및 불균형 산출, 캐시 친화도 판정, 유휴 CPU 우선 이주, 그리고 NUMA 스레스홀드 필터링을 시뮬레이션하는 엔진을 구현합니다.

---

## 2. 시스템 아키텍처 및 스케줄 도메인 계층 구조

```
+-------------------------------------------------------------------------+
|                               NUMA Node 0                               |
|   +-----------------------------+     +-----------------------------+   |
|   |           Core 0            |     |           Core 1            |   |
|   |   [CPU 0]       [CPU 1]     |     |   [CPU 2]       [CPU 3]     |   |
|   | (SMT Siblings, Shared L1/2) |     | (SMT Siblings, Shared L1/2) |   |
|   +-----------------------------+     +-----------------------------+   |
|                  Shared L3 Cache (MC Domain)                            |
+------------------------------------+------------------------------------+
                                     |
               [Interconnect Bus: UPI / Infinity Fabric]
                     (Higher Migration Cost: NUMA)
                                     |
+------------------------------------+------------------------------------+
|                               NUMA Node 1                               |
|   +-----------------------------+     +-----------------------------+   |
|   |           Core 2            |     |           Core 3            |   |
|   |   [CPU 4]       [CPU 5]     |     |   [CPU 6]       [CPU 7]     |   |
|   +-----------------------------+     +-----------------------------+   |
|                  Shared L3 Cache (MC Domain)                            |
+-------------------------------------------------------------------------+

[Hierarchy & Migration Thresholds]
  SMT Level  : Fast Migration (Shared Core Pipeline & L1/L2)
  MC Level   : Medium Migration (Shared L3 Cache)
  NUMA Level : Restricted Migration (High Cache & Memory Penalty, Threshold Filtered)
```

---

## 3. 세부 동작 명세 (Operational Specifications)

### 3.1 엔진 구성 매개변수 (`config`)
- `cache_hot_timeout`: 태스크가 실행을 마친 후 캐시가 핫 상태로 유지되는 시간 윈도우 (기본값 `50`).
- `numa_imbalance_threshold`: NUMA 도메인 간 이주를 허용하기 위한 최소 불균형 수치 (기본값 `50`).

### 3.2 토폴로지 및 상태 모델
- 토폴로지는 노드 수(`num_nodes`), 노드당 코어 수(`cores_per_node`), 코어당 SMT 스레드 수(`smt_per_core`)로 정의됩니다.
- 각 CPU는 `cpu_id`, `node_id`, `core_id` 및 할당된 `tasks` 목록을 갖습니다.
- 각 태스크는 `task_id`, `load`(부하 가중치), `cpu_id`, `last_run_time`을 갖습니다.
- 특정 CPU의 총 부하(`total_load`)는 해당 CPU에 대기/실행 중인 모든 태스크의 `load` 합입니다.

### 3.3 이벤트 처리 규칙

1. **`INIT_TOPOLOGY` (`time`, `num_nodes`, `cores_per_node`, `smt_per_core`)**:
   - 시스템의 계층적 CPU 토폴로지를 생성합니다.
   - `cpu_id`는 0부터 순차적으로 부여되며, 코어와 노드에 순차 매핑됩니다.
   - `event_logs`에 `TOPOLOGY_INITIALIZED`를 기록합니다.

2. **`ENQUEUE_TASK` (`time`, `task_id`, `load`, `target_cpu`)**:
   - 지정된 `target_cpu`의 런큐에 신규 태스크를 삽입합니다 (`last_run_time = time`).
   - `event_logs`에 `TASK_ENQUEUED`를 기록합니다.

3. **`EXECUTE_TASK` (`time`, `task_id`, `duration`)**:
   - 태스크 실행을 모사합니다. `last_run_time = time + duration`으로 갱신합니다.
   - `event_logs`에 `TASK_EXECUTED`를 기록합니다.

4. **`DEQUEUE_TASK` (`time`, `task_id`)**:
   - 태스크가 완료되어 런큐에서 제거됩니다.
   - `event_logs`에 `TASK_DEQUEUED`를 기록합니다.

5. **`TRIGGER_LOAD_BALANCE` (`time`, `level` ["SMT" | "MC" | "NUMA"], `idle_cpu`)**:
   - `idle_cpu`가 유휴 상태일 때 특정 도메인 레벨에서 부하 분산을 시도합니다 (`balance_runs += 1`).
   - **후보 CPU 집합 선정 (`candidate_cpus`)**:
     - `"SMT"`: `idle_cpu`와 동일한 물리 코어(`core_id`)를 공유하는 형제 CPU들.
     - `"MC"`: 동일 NUMA 노드(`node_id`) 내에 있지만 다른 물리 코어에 속한 CPU들.
     - `"NUMA"`: 서로 다른 NUMA 노드에 속한 CPU들.
   - **가장 바쁜 CPU 탐색 (`busiest_cpu`)**:
     - 후보 CPU들 중 `_cpu_load`가 최대인 CPU를 선정합니다.
     - 만약 `busiest_load <= idle_load`이면 이주 없이 종료합니다.
   - **불균형 산출 및 NUMA 필터링**:
     - `imbalance = (busiest_load - idle_load) // 2`.
     - `level == "NUMA"`이고 `imbalance < numa_imbalance_threshold`이면 원격 메모리 보호를 위해 이주를 생략합니다.
   - **캐시 친화도 판정 및 태스크 선정**:
     - `busiest_cpu`의 태스크 목록에서 후보를 역순으로 탐색합니다.
     - `(time - t.last_run_time) >= cache_hot_timeout`인 비-캐시-핫 태스크가 발견되면 해당 태스크를 선택합니다.
     - 만약 모든 태스크가 캐시-핫 상태인 경우:
       - `idle_load == 0` (대상 CPU가 완전히 텅 빈 상태)이면 CPU 유휴 방지를 위해 캐시 친화도를 무시하고 가장 최근 태스크를 선택합니다.
       - 대상 CPU에 이미 다른 태스크가 있다면(`idle_load > 0`), 불필요한 캐시 손실을 방지하기 위해 이주를 거부하고 `MIGRATION_BLOCKED_CACHE_HOT` 이벤트를 기록하며 종료합니다 (`cache_hot_migrations_blocked += 1`).
   - **이주 실행**:
     - 선택된 태스크를 `busiest_cpu`에서 제거하여 `idle_cpu`로 이동합니다.
     - `tasks_migrated`를 1 증가시키고, `migration_logs` 및 `event_logs`에 `TASK_MIGRATED`를 기록합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 입력 형식 (Standard Input, JSON)
```json
{
  "config": {
    "cache_hot_timeout": 50,
    "numa_imbalance_threshold": 50
  },
  "trace": [
    {"time": 10, "type": "INIT_TOPOLOGY", "num_nodes": 1, "cores_per_node": 2, "smt_per_core": 2},
    {"time": 20, "type": "ENQUEUE_TASK", "task_id": "t1", "load": 100, "target_cpu": 0},
    {"time": 30, "type": "ENQUEUE_TASK", "task_id": "t2", "load": 100, "target_cpu": 0},
    {"time": 40, "type": "TRIGGER_LOAD_BALANCE", "level": "SMT", "idle_cpu": 1}
  ]
}
```

### 출력 형식 (Standard Output, Compact JSON)
공백 없는 단일 라인 JSON 문자열(`separators=(',', ':')`)로 출력합니다:
```json
{"summary":{"tasks_migrated":1,"cache_hot_migrations_blocked":0,"balance_runs":1,"total_cpus":4,"active_tasks":2},"cpus":{"cpu_0":{"node_id":0,"core_id":0,"total_load":100,"tasks":["t1"]},"cpu_1":{"node_id":0,"core_id":0,"total_load":100,"tasks":["t2"]},"cpu_2":{"node_id":0,"core_id":1,"total_load":0,"tasks":[]},"cpu_3":{"node_id":0,"core_id":1,"total_load":0,"tasks":[]}},"migration_logs":[{"time":40,"task_id":"t2","from_cpu":0,"to_cpu":1,"level":"SMT","imbalance_cleared":100}],"event_logs":[{"time":10,"event":"TOPOLOGY_INITIALIZED","total_cpus":4,"num_nodes":1},{"time":20,"event":"TASK_ENQUEUED","task_id":"t1","load":100,"cpu_id":0},{"time":30,"event":"TASK_ENQUEUED","task_id":"t2","load":100,"cpu_id":0},{"time":40,"event":"TASK_MIGRATED","task_id":"t2","from_cpu":0,"to_cpu":1,"level":"SMT"}]}
```
