# 문제 234: 분산 빅데이터 Apache Spark AQE(Adaptive Query Execution): 스큐 조인(Skew Join) 분할, 셔플 파티션 동적 병합(Coalescing) 및 SMJ vs BHJ 동적 전환

## 1. 개요 및 배경 (Incident Scenario)

글로벌 이커머스 및 실시간 결제 로그를 집계하는 대규모 Apache Spark 클러스터에서 단 1개의 태스크(Task)가 40분 넘게 끝나지 않아 전체 배치 파이프라인의 SLA가 붕괴되는 전형적인 **롱테일 스트래글러(Straggler)** 장애가 발생했습니다.

10억 건의 주문 테이블과 고객 테이블을 조인할 때, 탈퇴 회원이나 비회원 주문(`user_id = NULL` 또는 `user_id = 0`)에 데이터가 비정상적으로 쏠려 있었습니다. 전통적인 정적 쿼리 플래너(Static Catalyst Optimizer) 환경에서는 다음과 같은 치명적 병목이 발생했습니다:

1. **데이터 편중(Data Skew)과 디스크 스필(Disk Spill) 지옥**:
   - `spark.sql.shuffle.partitions=200` 기본 설정 하에서 해시 파티셔닝을 거치면, 대다수 199개 파티션은 15~20MB에 불과하여 2초 만에 조인을 마칩니다.
   - 그러나 비회원 키가 몰린 1개 파티션은 **600MB 이상의 대용량**으로 팽창합니다.
   - 단일 익스큐터(Executor) 코어에서 정렬 병합 조인(Sort-Merge Join, SMJ)을 수행하던 중 메모리 한도를 초과하여 수백 MB의 데이터를 디스크로 쏟아내는 **메모리 스필(Disk Spill)**이 발생하고, I/O 병목으로 인해 해당 태스크만 40분 동안 클러스터를 점유(`SKEW_PARTITION_DISK_SPILL_STRAGGLER_STALL`)합니다.
2. **협소 데이터셋의 소형 파티션 오버헤드**:
   - 필터링 조건으로 인해 셔플 데이터가 총 15MB밖에 되지 않는 쿼리에서도 정적 설정 때문에 200개의 태스크가 생성되어, 데이터 처리 시간보다 태스크 스케줄링 및 RPC 오버헤드가 더 커지는 비효율(`SMALL_SHUFFLE_PARTITIONS_SCHEDULING_OVERHEAD`)이 발생합니다.
3. **런타임 크기 무시로 인한 브로드캐스트 OOM**:
   - 필터링 전에는 수 기가바이트였으나 필터링 후 메모리에 브로드캐스트할 수 있는 크기(10MB 이하)로 줄어들었음에도 정적 플래너는 무거운 셔플 기반 SMJ를 고집합니다. 반대로 드라이버 메모리를 고려하지 않고 무리하게 브로드캐스트를 시도하면 드라이버 OOM(`BROADCAST_JOIN_OOM_CRASH`)이 발생합니다.

이 문제를 해결하기 위해 Spark 3.0부터 런타임 셔플 통계(MapStatus)를 피드백받아 실행 계획을 동적으로 변경하는 **적응형 쿼리 실행(Adaptive Query Execution, AQE)** 엔진이 도입되었습니다.

```
[Spark 3.0+ Adaptive Query Execution (AQE) Architecture]

Stage 1 (Map/Shuffle Write) ---> [ Shuffle Files Materialized & MapStatus Reported ]
                                                       |
                                                       v
                                      [ AQE Runtime Plan Re-Optimizer ]
                                                       |
  +----------------------------------------------------+------------------------------------+
  |                                                    |                                    |
  v (Rule 1: Dynamic Coalescing)                       v (Rule 2: Dynamic Skew Join)        v (Rule 3: Dynamic Join Switch)
[ Merge adjacent tiny partitions ]       [ Split 600MB skewed partition into ]   [ Convert SMJ to BHJ if ]
[ 200 partitions -> 5 partitions ]       [ 10 x 60MB parallel sub-partitions ]   [ filtered table <= 10MB ]
```

본 문제에서는 Spark AQE의 핵심 3대 규칙(동적 파티션 병합, 스큐 조인 분할, 조인 전략 동적 전환)과 워크로드 특성에 따른 클러스터 파티션 수, 최대 태스크 실행 시간, 디스크 스필 발생 여부를 시뮬레이션하고 최적 실행을 도출하는 판정 프로그램을 작성합니다.

---

## 2. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "aqe_enabled": true,
    "coalesce_shuffle_partitions_enabled": true,
    "skew_join_enabled": true,
    "advisory_partition_size_mb": 64.0,
    "min_partition_size_mb": 1.0,
    "skew_partition_threshold_mb": 256.0,
    "skew_partition_factor": 5.0,
    "auto_broadcast_join_threshold_mb": 10.0
  },
  "workload": {
    "join_type": "SORT_MERGE_JOIN",
    "left_table_size_mb": 50.0,
    "right_table_partitions_mb": [15.0, 18.0, 20.0, 16.0, 600.0, 17.0, 19.0, 14.0],
    "driver_memory_mb": 4096.0,
    "executor_memory_mb": 2048.0
  }
}
```

### 필드 설명
- `config`:
  - `aqe_enabled` (bool): Spark AQE 전체 활성화 여부
  - `coalesce_shuffle_partitions_enabled` (bool): 셔플 파티션 동적 병합 활성화 여부
  - `skew_join_enabled` (bool): 스큐 조인 감지 및 분할 활성화 여부
  - `advisory_partition_size_mb` (float): 병합/분할 목표 권장 파티션 크기 (기본 64MB)
  - `min_partition_size_mb` (float): 소형 파티션 판정 기준 크기 (기본 1MB)
  - `skew_partition_threshold_mb` (float): 스큐 파티션 절대 크기 임계치 (기본 256MB)
  - `skew_partition_factor` (float): 중앙값 대비 스큐 배수 기준 (기본 5.0배)
  - `auto_broadcast_join_threshold_mb` (float): BHJ 동적 전환 임계치 (기본 10MB)
- `workload`:
  - `join_type` (str): 초기 계획된 조인 유형 (`"SORT_MERGE_JOIN"`)
  - `left_table_size_mb` (float): 런타임 필터링 후 좌측 테이블 크기 (MB)
  - `right_table_partitions_mb` (list[float]): 셔플된 우측 테이블 파티션별 크기 목록 (MB)
  - `driver_memory_mb` (float): 드라이버 노드 메모리 (MB)
  - `executor_memory_mb` (float): 익스큐터당 할당된 메모리 (MB)

---

## 3. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 JSON 구조를 반환해야 합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_AQE_SKEW_JOIN_PARALLEL_SPLIT",
  "metrics": {
    "final_join_type": "SORT_MERGE_JOIN",
    "final_num_partitions": 17,
    "skewed_partitions_detected": 1,
    "skew_splits_created": 10,
    "max_task_duration_sec": 6.0,
    "disk_spill_mb": 0.0,
    "straggler_ratio": 1.0
  }
}
```

### 판정(Verdict) 및 상태(Status) 규칙
1. **브로드캐스트 동적 전환 (Dynamic Join Strategy Switch)**:
   - `aqe_enabled == true`이고 `left_table_size_mb <= auto_broadcast_join_threshold_mb`인 경우:
     - 만약 `left_table_size_mb * 3.0 > driver_memory_mb` 또는 `* 2.0 > executor_memory_mb`:
       - `status`: `"FAILED"`, `verdict`: `"BROADCAST_JOIN_OOM_CRASH"`, `max_task_duration_sec`: 9999.0
     - 메모리가 안전한 경우:
       - 셔플 없이 우측 파티션을 스트리밍 스캔 (`max_task_duration_sec = max(part) / 30.0`)
       - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_AQE_DYNAMIC_BROADCAST_HASH_JOIN"`
2. **소형 파티션 스케줄링 오버헤드**:
   - 파티션 수가 50개 초과이고 평균 크기가 `min_partition_size_mb` 미만인데 동적 병합이 비활성화된 경우:
     - `status`: `"WARNING"`, `verdict`: `"SMALL_SHUFFLE_PARTITIONS_SCHEDULING_OVERHEAD"`, `max_task_duration_sec`: 45.0
3. **스큐 파티션 처리 (Skew Join Handling)**:
   - 스큐 조건: `size >= skew_partition_threshold_mb` AND `size >= median * skew_partition_factor`
   - 스큐가 감지되었으나 `skew_join_enabled == false` 또는 `aqe_enabled == false`인 경우:
     - 단일 태스크가 거대 파티션을 전담 처리하며 메모리 스필 발생
     - `status`: `"FAILED"`, `verdict`: `"SKEW_PARTITION_DISK_SPILL_STRAGGLER_STALL"`
   - 스큐가 감지되고 `skew_join_enabled == true`인 경우:
     - 스큐 파티션을 $\lceil \text{size} / \text{advisory\_size} \rceil$개의 서브 파티션으로 분할하여 병렬 실행
     - `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_AQE_SKEW_JOIN_PARALLEL_SPLIT"`, `disk_spill_mb`: 0.0
4. **일반 파티션 처리**:
   - 동적 병합 활성화 시: `status`: `"SUCCESS"`, `verdict`: `"OPTIMAL_AQE_SHUFFLE_PARTITION_COALESCED"`
   - 정적 기본 실행: `status`: `"SUCCESS"`, `verdict`: `"STATIC_SORT_MERGE_JOIN_BASELINE"`

---

## 4. 예제 입출력

### 예제 1 (입력)
```json
{
  "config": {
    "aqe_enabled": true,
    "coalesce_shuffle_partitions_enabled": true,
    "skew_join_enabled": true,
    "advisory_partition_size_mb": 64.0,
    "min_partition_size_mb": 1.0,
    "skew_partition_threshold_mb": 256.0,
    "skew_partition_factor": 5.0,
    "auto_broadcast_join_threshold_mb": 10.0
  },
  "workload": {
    "join_type": "SORT_MERGE_JOIN",
    "left_table_size_mb": 50.0,
    "right_table_partitions_mb": [15.0, 18.0, 20.0, 16.0, 600.0, 17.0, 19.0, 14.0],
    "driver_memory_mb": 4096.0,
    "executor_memory_mb": 2048.0
  }
}
```

### 예제 1 (출력)
```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_AQE_SKEW_JOIN_PARALLEL_SPLIT",
  "metrics": {
    "final_join_type": "SORT_MERGE_JOIN",
    "final_num_partitions": 17,
    "skewed_partitions_detected": 1,
    "skew_splits_created": 10,
    "max_task_duration_sec": 6.0,
    "disk_spill_mb": 0.0,
    "straggler_ratio": 1.0
  }
}
```
