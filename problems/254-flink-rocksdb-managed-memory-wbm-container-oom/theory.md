# 문제 254 이론: Apache Flink 오프힙 메모리 모델, RocksDB WriteBufferManager 및 Container Cgroup OOMKilled 메커니즘

---

## 1. Apache Flink TaskManager 메모리 아키텍처

Apache Flink는 JVM 위에서 구동되지만, 대규모 상태 저장과 네트워크 셔플을 위해 힙(Heap)과 오프힙(Off-heap)을 정교하게 분할한 메모리 모델을 갖추고 있습니다.

```
+--------------------------------------------------------------------+
| TaskManager Total Process Memory (e.g. 8GB Container Limit)        |
+--------------------------------------------------------------------+
| Flink Total Memory                                                 |
| ├─ JVM Heap Memory: Framework Heap + Task Heap                     |
| ├─ Total Off-Heap Memory: Framework Off-Heap + Task Direct Memory  |
| └─ Managed Memory (Managed Fraction: default 0.4)                  |
|     └── RocksDB State Backend (C++ Native LRUCache & WBM)          |
+--------------------------------------------------------------------+
| JVM Metaspace & JVM Overhead                                       |
+--------------------------------------------------------------------+
```

### Managed Memory의 역할:
- `state.backend: rocksdb`를 사용할 때, Flink의 `Managed Memory`는 임베디드 RocksDB가 C++ 네이티브 메모리를 할당하는 전체 예산(Budget) 역할을 수행합니다.

---

## 2. 비관리형 모드와 슬롯-연산자 조합 폭발 (Combinatorial Explosion)

과거 Flink 버전이나 `state.backend.rocksdb.memory.managed: false`인 환경에서는 치명적인 구조적 결함이 존재합니다:
- 각 태스크 슬롯에서 실행되는 모든 상태 기반 연산자 서브태스크가 **자신만의 독립된 RocksDB 인스턴스**를 생성합니다.
- 단일 TaskManager 내 총 인스턴스 수:
  $$N = 	ext{Slots} 	imes 	ext{Stateful Operators}$$
- 4개 슬롯에 8개 연산자가 배정되면 32개의 RocksDB 인스턴스가 뜹니다.
- 인스턴스마다 기본 MemTable(128MB)과 Block Cache(64MB)를 독립적으로 잡으면:
  $$32 	imes 192	ext{MB} = 6,144	ext{MB}$$
- JVM 힙(3GB) 및 메타스페이스와 합산하면 컨테이너 제한(8GB)을 즉시 초과하여 리눅스 커널 cgroup 메모리 컨트롤러가 TaskManager Pod를 `Exit Code 137 (OOMKilled)`로 강제 사살합니다.

---

## 3. Flink 관리형 메모리와 WriteBufferManager (WBM)

Flink 1.10부터 도입된 `RocksDBMemoryFactory`는 TaskManager 내의 모든 RocksDB 인스턴스가 단 하나의 **전역 공유 LRUCache**를 공유하도록 강제합니다.

```
 [ Managed Memory LRUCache (4096MB) ]
 ┌─────────────────────────────────────────────────────────────┐
 │ WriteBufferManager (WBM): write_buffer_ratio = 0.5 (2048MB) │
 │ ├─ Operator 1 MemTable                                      │
 │ ├─ Operator 2 MemTable                                      │
 │ └─ Flushes to SST when WBM limit is reached!                │
 ├─────────────────────────────────────────────────────────────┤
 │ High Priority Pool: high_priority_pool_ratio = 0.1 (410MB)  │
 │ └─ Pinned L0 Index & Bloom Filter Blocks                    │
 ├─────────────────────────────────────────────────────────────┤
 │ Data Block Cache: Remaining (1638MB)                        │
 │ └─ Point Lookups & Range Scan Uncompressed Blocks           │
 └─────────────────────────────────────────────────────────────┘
```

### WriteBufferManager의 마법:
- RocksDB의 MemTable(쓰기 버퍼)은 원래 캐시가 아니라 동적 힙 할당입니다.
- WBM은 MemTable이 메모리를 할당할 때마다 공유 LRUCache에 가상 더미 엔트리를 삽입하여 캐시 용량을 차감합니다.
- MemTable이 `write_buffer_ratio` 한도에 도달하면, RocksDB는 즉시 디스크로 플러시(Flush MemTable to L0 SST)를 단행하여 오프힙 메모리가 정해진 경계를 절대 넘지 못하도록 엄격히 통제합니다.

---

## 4. Block Cache 기아와 인덱스/필터 방출 (Eviction)

### (1) `write-buffer-ratio` 불균형으로 인한 Block Cache 기아
- `write_buffer_ratio`를 0.8 이상으로 과도하게 크게 잡으면:
  - 가용 캐시의 대부분이 MemTable 쓰기 버퍼에 묶입니다.
  - 데이터 블록을 캐싱할 공간이 부족해져 상태 조회(Point Get) 시 매번 SSD의 SSTable을 읽어야 하므로, 캐시 미스율이 85% 이상 치솟고 파이프라인 전체가 백프레셔에 갇힙니다.
  - **권장값**: `0.4 ~ 0.5`로 설정하여 쓰기와 읽기 캐시의 균형을 유지.

### (2) Index & Bloom Filter Pinning의 절대적 중요성
- RocksDB는 SSTable 내에서 키의 존재 유무를 확인하기 위해 Bloom Filter와 2단계 Index 블록을 사용합니다.
- 일반 데이터 블록의 턴오버가 빠를 때 인덱스와 필터 블록이 캐시에서 쫓겨나면(Eviction), 단 하나의 키를 읽기 위해 수차례의 I/O가 발생하여 읽기 증폭이 10배 이상 폭증합니다.
- **해결책**:
  ```yaml
  state.backend.rocksdb.memory.high-priority-pool-ratio: 0.1
  state.backend.rocksdb.memory.partitioned-index-filters: true
  ```
  `high-priority-pool-ratio`를 0.1 이상으로 설정하고 L0 인덱스/필터를 캐시에 고정(Pinning)하여 읽기 성능을 보장해야 합니다.

---

## 5. 프로덕션 Flink 튜닝 레시피 (`flink-conf.yaml`)

```yaml
# 1. RocksDB 오프힙 관리형 메모리 활성화 (필수)
state.backend.rocksdb.memory.managed: true

# 2. Managed Memory 할당 비율 (총 컨테이너의 40%)
taskmanager.memory.managed.fraction: 0.4

# 3. 쓰기 버퍼 및 고우선순위 인덱스 캐시 비율
state.backend.rocksdb.memory.write-buffer-ratio: 0.5
state.backend.rocksdb.memory.high-priority-pool-ratio: 0.1

# 4. 2단계 파티셔닝 인덱스/필터 활성화
state.backend.rocksdb.memory.partitioned-index-filters: true
```
