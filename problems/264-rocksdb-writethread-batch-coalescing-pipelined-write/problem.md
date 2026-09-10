# [LSM-Tree/스토리지 엔진] RocksDB WriteThread 리더-팔로워 배치 병합(Batch Grouping)과 파이프라인 쓰기(Pipelined Write) 및 동시성 멤테이블 삽입 엔진

## 문제 설명

RocksDB는 Meta(구 Facebook), TiKV, CockroachDB, Apache Flink, Kafka Streams 등 전 세계 수많은 대규모 고성능 분산 데이터베이스와 스트리밍 플랫폼의 스토리지 코어로 사용되는 산업 표준 LSM-Tree 임베디드 데이터베이스 엔진입니다.

수십~수백 개의 CPU 코어를 가진 최신 서버 환경에서 수만 개의 동시성 스레드가 동시에 `db->Put()`을 호출할 때, 각 스레드가 개별적으로 뮤텍스(Mutex)를 획득하고 WAL(Write-Ahead Log)에 디스크 쓰기 및 `fsync`를 수행한 뒤 멤테이블(MemTable / SkipList)에 삽입한다면 극심한 락 경합(Lock Contention)으로 인해 CPU 사용률은 10%대로 곤두박질치고 I/O 처리량은 바닥을 치게 됩니다.

이 병목을 해결하기 위해 RocksDB v5.5+에서 완성된 핵심 아키텍처가 바로 **`WriteThread` 리더-팔로워(Leader-Follower) 배치 그룹핑(Batch Grouping)**과 **파이프라인 쓰기(Pipelined Write)** 및 **동시성 멤테이블 쓰기(Concurrent MemTable Write)**입니다:
1. **락리스 큐 등록(Lock-Free Enqueue)**: 동시 쓰기를 요청한 스레드들은 원자적 CAS를 통해 `WriteThread` 대기 큐에 진입합니다.
2. **리더-팔로워 역할 분담**: 가장 먼저 큐를 획득한 스레드가 **리더(Leader)**가 되고, 뒤따라온 스레드들은 **팔로워(Follower)**가 되어 대기합니다.
3. **배치 그룹 병합(`JoinBatchGroup`)**: 리더 스레드는 큐에 쌓인 팔로워들의 `WriteBatch`를 하나의 거대한 메가 배치로 병합합니다. 그룹 내 단 하나의 스레드라도 `sync=true`를 요구했다면 단 1회의 순차 I/O 및 `fsync`로 전체 그룹의 쓰기 안전성을 한 번에 확보합니다 (동기화 비용 극적 분산!).
4. **글로벌 시퀀스 번호 원자적 할당**: 리더는 병합된 배치의 모든 키에 대해 중복 없는 단조 증가 시퀀스 번호(Sequence Number) 구간 $[S_{\text{start}}, S_{\text{end}}]$를 한 번에 할당합니다.
5. **파이프라인 병렬 멤테이블 쓰기**:
   - 전통 모드: 리더 혼자서 모든 팔로워의 배치를 멤테이블에 순차 삽입하느라 리더가 병목이 됨.
   - 파이프라인 모드(`enable_pipelined_write=true` + `allow_concurrent_memtable_write=true`): WAL 기록이 끝나자마자 모든 팔로워를 즉시 깨워, 각자 자신의 시퀀스 번호 구간을 들고 락리스 동시성 스킵리스트(Concurrent SkipList)에 **병렬(Parallel)로 동시 삽입**합니다!

RocksDB 스토리지 엔진 엔지니어가 되어, 동시성 쓰기 요청들의 도착 시간과 용량을 기반으로 배치 그룹을 결성하고, WAL 동기화 비용을 분산 상각하며, 파이프라인 동시성 멤테이블 삽입 및 쓰기 스톨(Write Stall)을 정밀 시뮬레이션하는 **RocksDB WriteThread 파이프라인 엔진**을 구현하십시오.

---

## 핵심 시스템 모델 및 규칙

### 1. 쓰기 스레드 배치 그룹핑 (`JoinBatchGroup`)
- 쓰기 요청(Request)은 `arrival_time_us`, `batch` (키-값 목록), `sync` (fsync 여부)로 구성됩니다.
- 아직 처리되지 않은 요청 중 가장 빠른 도착 시간을 가진 요청이 **리더(Leader)**로 선출됩니다.
- 리더의 도착 시간으로부터 `batch_window_us` 이내에 도착한 연속된 요청들이 **팔로워(Follower)**로 배치 그룹에 합류합니다:
  - 그룹 내 요청 수 한계: $\le \text{max\_batch\_group\_count}$
  - 그룹 총 바이트 수 한계: $\le \text{max\_batch\_group\_bytes}$ (키 길이 + 값 길이의 총합)
  - 한계를 초과하면 해당 요청은 그룹에 포함되지 않고 다음 그룹의 리더로 이월됩니다.
- 그룹 내 어떤 요청이라도 `sync == true`이면, 해당 그룹 전체의 `has_sync`는 `true`가 됩니다.

### 2. 글로벌 시퀀스 번호 할당 (Sequence Number Allocation)
- 그룹 시작 전의 현재 시퀀스 번호를 $S$라 할 때, 그룹 내 총 키의 개수 $K_{\text{total}}$에 대해:
  $$\text{group\_sequence\_range} = [S, S + K_{\text{total}} - 1]$$
- 그룹 내 각 요청 $i$는 자신이 가진 키 개수 $K_i$만큼 연속된 하위 구간 $[S_i, S_i + K_i - 1]$을 순차적으로 부여받습니다.

### 3. 지연시간 및 파이프라인 모델링
1. **WAL 기록 단계**:
   $$\text{wal\_write\_time} = \text{group\_bytes} \times \text{cost\_wal\_write\_per\_byte\_us} + (\text{cost\_wal\_fsync\_us if has\_sync else } 0)$$
2. **멤테이블 삽입 단계**:
   - **전통 모드 (`pipelined=false` 또는 `allow_concurrent_memtable=false`)**:
     - 리더가 모든 키를 혼자 순차 삽입: $\text{memtable\_time} = K_{\text{total}} \times \text{cost\_memtable\_insert\_per\_key\_us}$.
     - 모든 스레드의 지연시간 = $\text{queue\_overhead} + \text{wal\_write\_time} + \text{memtable\_time}$.
   - **파이프라인 동시성 모드 (`enable_pipelined_write=true` and `allow_concurrent_memtable_write=true`)**:
     - 모든 스레드가 락리스 스킵리스트에 병렬 동시 삽입:
       - 그룹 전체 완료 시간(Wall-clock)은 키가 가장 많은 스레드의 시간에 의해 결정: $\max_i(K_i) \times \text{cost\_memtable\_insert\_per\_key\_us}$.
       - 개별 스레드 $i$의 지연시간:
         $$\text{latency}_i = \text{queue\_overhead} + \text{wal\_write\_time} + K_i \times \text{cost\_memtable\_insert\_per\_key\_us}$$

### 4. 멤테이블 용량 및 쓰기 스톨 (Write Stall)
- 현재 멤테이블 사용량 누적치 $\text{current\_memtable\_usage} \ge \text{memtable\_capacity\_bytes}$인 경우, 신규 그룹 형성이 중단되고 해당 요청은 `"WRITE_STALL_MEMTABLE_FULL"` 상태(`latency_us = 0.0`)로 처리되며 `stalls_count`가 1 증가합니다.

---

## 입력 형식

표준 입력(`sys.stdin`)으로 시스템 설정 파라미터와 쓰기 요청 목록이 포함된 JSON이 주어집니다:
```json
{
  "config": {
    "enable_pipelined_write": true,
    "allow_concurrent_memtable_write": true,
    "max_batch_group_bytes": 1048576,
    "max_batch_group_count": 64,
    "memtable_capacity_bytes": 67108864,
    "batch_window_us": 2.0,
    "cost_queue_overhead_us": 0.5,
    "cost_wal_write_per_byte_us": 0.0001,
    "cost_wal_fsync_us": 50.0,
    "cost_memtable_insert_per_key_us": 0.8,
    "initial_sequence_number": 1000,
    "initial_memtable_usage_bytes": 0
  },
  "requests": [
    {
      "id": "REQ_01",
      "thread_id": "T1",
      "arrival_time_us": 10.0,
      "batch": [{"key": "user:1", "value": "Alice"}],
      "sync": false
    },
    {
      "id": "REQ_02",
      "thread_id": "T2",
      "arrival_time_us": 10.5,
      "batch": [{"key": "user:2", "value": "Bob"}],
      "sync": true
    }
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 통계 메트릭, 생성된 배치 그룹 상세 정보, 요청별 처리 결과가 포함된 단일 라인 JSON을 출력합니다:
```json
{
  "summary": {
    "total_requests": 2,
    "total_batch_groups": 1,
    "avg_writers_per_group": 2.0,
    "total_wal_bytes": 26,
    "final_sequence_number": 1001,
    "final_memtable_usage_bytes": 26,
    "stalls_count": 0,
    "avg_latency_us": 51.3,
    "p50_latency_us": 51.3,
    "p99_latency_us": 51.3,
    "max_latency_us": 51.3
  },
  "batch_groups": [
    {
      "group_id": "GROUP_001",
      "leader_id": "REQ_01",
      "followers_count": 1,
      "total_writers": 2,
      "total_bytes": 26,
      "total_keys": 2,
      "sequence_range": [1000, 1001],
      "has_sync": true,
      "pipelined_parallel": true,
      "group_latency_us": 51.3
    }
  ],
  "thread_results": [
    {
      "id": "REQ_01",
      "group_id": "GROUP_001",
      "role": "LEADER",
      "status": "OK",
      "batch_keys_count": 1,
      "sequence_range": [1000, 1000],
      "latency_us": 51.3
    },
    {
      "id": "REQ_02",
      "group_id": "GROUP_001",
      "role": "FOLLOWER",
      "status": "OK",
      "batch_keys_count": 1,
      "sequence_range": [1001, 1001],
      "latency_us": 51.3
    }
  ]
}
```
