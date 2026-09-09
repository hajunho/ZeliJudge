# 문제 254: Distributed Stream Processing — Apache Flink RocksDB State Backend Managed Memory, WriteBufferManager 및 컨테이너 Cgroup OOMKilled

## 1. 개요 (Incident Scenario)

글로벌 스트리밍 데이터 플랫폼(Uber, Netflix, Stripe)에서는 수 테라바이트 규모의 키 기반 스트림 집계(Keyed State, Windowing, CEP, Stream-Stream Join)를 실시간으로 처리하기 위해 Kubernetes 클러스터 상에서 **Apache Flink**를 구동합니다. Flink는 대용량 상태(State)를 JVM 힙 메모리 한계를 넘어 효율적으로 다루기 위해 C++ 네이티브 임베디드 스토리지 엔진인 **RocksDB State Backend**를 표준으로 사용합니다.

그러나 정기 프로모션으로 유입 트래픽이 폭증하고 새로운 상태 기반 집계 연산자(Stateful Operators)가 추가 배포된 날, Flink TaskManager Pod들이 연쇄적으로 강제 종료되는 대규모 장애가 발생했습니다:
1. **Kubernetes Pod Cgroup OOMKilled 참사 (Exit Code 137)**: Flink 설정에서 RocksDB 메모리 제어(`state.backend.rocksdb.memory.managed`)가 비활성화(`false`)되어 있었습니다. 각 TaskManager는 4개의 슬롯(Slot)을 가지고 있었고, 파이프라인 내 8개의 상태 기반 연산자가 배치되어 있었습니다. 그 결과 단일 TaskManager 컨테이너 내에 **$4 	imes 8 = 32$개의 독립된 RocksDB C++ 인스턴스**가 생성되었습니다. 각 인스턴스가 독립적인 MemTable(128MB)과 Block Cache(64MB)를 네이티브 오프힙(Off-heap)에 할당하면서, 전체 메모리 사용량이 컨테이너 cgroup 메모리 제한(`8192MB`)을 훌쩍 넘겨 리눅스 커널 OOM Killer에 의해 `SIGKILL`로 즉사했습니다.
2. **Block Cache 기아로 인한 처리량 붕괴 (Cache Starvation by Excessive MemTables)**: 관리형 메모리(`managed: true`)를 켰음에도 불구하고, 쓰기 버퍼 비율(`write-buffer-ratio`)이 0.85로 과도하게 높게 설정되어 있어 가용 오프힙 캐시의 대부분을 MemTable이 잠식했습니다. 그 결과 키 조회를 위한 Data Block Cache 공간이 워킹 셋(Working Set)의 30% 미만으로 쪼그라들어 캐시 미스율이 85%까지 치솟고 디스크 I/O 병목으로 인해 심각한 백프레셔(Backpressure)가 발생했습니다.
3. **인덱스 및 블룸 필터 캐시 방출로 인한 읽기 증폭 (Index/Filter Eviction Spike)**: `pin_l0_index_and_filter: false` 및 `high_priority_pool_ratio: 0` 설정으로 인해, 빈번한 데이터 블록 교체가 일어날 때 필수적인 Level-0 인덱스 블록과 블룸 필터가 캐시에서 축출되어 상태 읽기 증폭(Read Amplification)이 12.5배로 폭증했습니다.

당신은 분산 스트림 처리 및 Flink 코어 플랫폼 엔지니어로서, TaskManager 메모리 모델, RocksDB 네이티브 할당, WriteBufferManager(WBM), Block Cache 분할 및 인덱스 핀 설정 상태 머신을 시뮬레이션하고, 장애 근본 원인(Root Cause)과 엔터프라이즈 메모리 최적화 방안을 도출해야 합니다.

---

## 2. 아키텍처 및 상태 머신 (System Architecture & State Machine)

```
 ┌─────────────────────────────────────────────────────────────┐
 │ TaskManager Container (cgroup limit: 8192MB)               │
 ├──────────────────────────────┬──────────────────────────────┤
 │ JVM Heap (3072MB)            │ Direct Off-Heap (512MB)      │
 │ (Framework & Task Heap)      │ JVM Metaspace & Overhead     │
 ├──────────────────────────────┴──────────────────────────────┤
 │ Managed Memory (4096MB) - Dedicated to RocksDB State Backend│
 └──────────────────────────────┬──────────────────────────────┘
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
 [ Mode A: Unmanaged (managed=false) ]   [ Mode B: Managed (managed=true) ]
 - Each Operator Subtask allocates      - Single Shared LRUCache (4096MB)
   isolated RocksDB Native Memory!      - WriteBufferManager (WBM) charges
 - Instances = Slots * Operators          MemTables to shared cache!
   = 4 * 8 = 32 instances!              - Strict Budget:
 - 32 * 192MB = 6144MB Off-heap!          * MemTable: wb_ratio (0.5)
 ==> Total: 10240MB > 8192MB!             * High-Prio: Index/Filters (0.1)
 ==> Container OOMKilled (Exit Code 137)! * Data Block Cache: Remaining (0.4)
                                        ==> Total stays <= 8192MB! STABLE!
```

### (1) 메모리 모델 및 컨테이너 OOM 판정 규칙
- 컨테이너 총 메모리 사용량:
  $$	ext{Total Memory} = 	ext{jvm\_heap} + 	ext{direct\_mem} + 	ext{jvm\_overhead} + 	ext{rocksdb\_total\_offheap}$$
- `rocksdb_memory_managed == false` (비관리형 모드):
  - 인스턴스 수: $N = 	ext{num\_task\_slots} 	imes 	ext{num\_stateful\_operators}$.
  - 인스턴스당 기본 할당: MemTable 128MB + Block Cache 64MB = 192MB.
  - $	ext{rocksdb\_total\_offheap} = N 	imes 192	ext{MB}$.
  - $	ext{Total Memory} > 	ext{container\_memory\_limit\_mb}$인 경우 **`container_oomkilled = true`** 판정 (Exit Code 137).
- `rocksdb_memory_managed == true` (관리형 모드):
  - 모든 인스턴스가 `managed_memory_mb` 한도 내에서 공유 LRUCache를 사용하므로 오프힙 총량이 고정됨.

### (2) 관리형 캐시 분할 및 Block Cache 기아 규칙
- `managed_memory_mb`의 내부 분할:
  - $	ext{memtable\_budget} = 	ext{managed\_memory\_mb} 	imes 	ext{write\_buffer\_ratio}$
  - $	ext{high\_prio\_budget} = 	ext{managed\_memory\_mb} 	imes 	ext{high\_priority\_pool\_ratio}$
  - $	ext{data\_block\_budget} = \max(0, 	ext{managed\_memory\_mb} - 	ext{memtable\_budget} - 	ext{high\_prio\_budget})$
- **Block Cache 기아 판정**:
  - $	ext{data\_block\_budget} < 	ext{state\_working\_set\_mb} 	imes 0.3$인 경우:
    - 데이터 블록 캐시가 극심하게 고갈되어 **`block_cache_starvation = true`**, `cache_miss_rate = 0.85` 발생.

### (3) 인덱스 및 블룸 필터 핀(Pinning) 규칙
- `not pin_l0_index_and_filter`이거나 `high_priority_pool_ratio == 0`인 경우:
  - 잦은 데이터 블록 갱신 시 인덱스와 블룸 필터가 캐시에서 축출되어 **`index_filter_eviction_spike = true`**, `read_amplification = 12.5` 발생.
- 정상 핀 설정 시: `read_amplification = 1.1`, 안정적인 상태 조회 보장.

---

## 3. 입력 사양 (Input Specification)

표준 입력(`sys.stdin`)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "taskmanager_config": {
    "container_memory_limit_mb": 8192,
    "jvm_heap_mb": 3072,
    "direct_memory_mb": 512,
    "jvm_overhead_mb": 512,
    "managed_memory_mb": 4096,
    "rocksdb_memory_managed": false,
    "write_buffer_ratio": 0.5,
    "high_priority_pool_ratio": 0.1,
    "pin_l0_index_and_filter": true,
    "num_task_slots": 4,
    "num_stateful_operators": 8
  },
  "workload": {
    "write_throughput_mb_per_sec": 100,
    "read_query_rate_per_sec": 5000,
    "state_working_set_mb": 1500
  },
  "events": []
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(`sys.stdout`)으로 다음 필드를 포함하는 JSON 객체를 출력합니다:

```json
{
  "final_state": {
    "total_container_usage_mb": 10240,
    "rocksdb_total_offheap_mb": 6144,
    "data_block_budget_mb": 2048,
    "memtable_budget_mb": 4096,
    "num_rocksdb_instances": 32
  },
  "metrics": {
    "container_oomkilled": true,
    "block_cache_starvation": false,
    "index_filter_eviction_spike": false,
    "cache_miss_rate": 0.0,
    "read_amplification": 1.0
  },
  "root_cause": "TASKMANAGER_CONTAINER_CGROUP_OOMKILLED",
  "recommendations": [
    "ENABLE_ROCKSDB_MANAGED_MEMORY"
  ]
}
```

### 진단 규칙 (Root Cause Hierarchy)
1. `container_oomkilled == true` $ightarrow$ `"TASKMANAGER_CONTAINER_CGROUP_OOMKILLED"`
2. `block_cache_starvation == true` $ightarrow$ `"BLOCK_CACHE_STARVATION_BY_EXCESSIVE_MEMTABLES"`
3. `index_filter_eviction_spike == true` $ightarrow$ `"INDEX_FILTER_BLOCK_EVICTION_READ_AMPLIFICATION"`
4. 기타 정상 상태 $ightarrow$ `"STABLE_BALANCED_MANAGED_ROCKSDB_STATE"`

### 권고사항 도출 규칙
- `not rocksdb_memory_managed`: `"ENABLE_ROCKSDB_MANAGED_MEMORY"`
- `write_buffer_ratio > 0.6`: `"TUNE_WRITE_BUFFER_RATIO_TO_PRESERVE_BLOCK_CACHE"`
- `not pin_l0_index_and_filter` 또는 `high_priority_pool_ratio == 0`: `"PIN_L0_INDEX_FILTER_AND_SET_HIGH_PRIORITY_POOL"`
- `total_container_usage > container_limit * 0.9` (관리형 활성 시): `"INCREASE_TASKMANAGER_CONTAINER_MEMORY_LIMIT"`
- 해당 사항이 없으면: `["MAINTAIN_CURRENT_ROCKSDB_MANAGED_CONFIG"]`
