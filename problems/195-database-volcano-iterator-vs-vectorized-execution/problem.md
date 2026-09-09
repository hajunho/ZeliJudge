# Problem 195: 데이터베이스 쿼리 실행 엔진: 화산 반복자(Volcano Iterator) 모델 vs 벡터화 실행(Vectorized Execution) 및 캐시 친화적 해시 조인

## 문제 설명

초대규모 정형 데이터 웨어하우스(ClickHouse, Snowflake, DuckDB) 및 실시간 분석(OLAP) 데이터베이스 엔진을 설계하는 데이터베이스 코어 엔지니어링 팀은 전통적인 RDBMS(PostgreSQL, MySQL) 쿼리 엔진 아키텍처가 최신 멀티코어 CPU 환경에서 극심한 성능 병목을 일으키는 원인을 분석하고 차세대 쿼리 실행 엔진으로 전면 개편하고자 합니다.

1. **화산 반복자(Volcano Iterator) 모델의 가상 함수 호출(Virtual Function Call) 병목**:
   - 1994년 Goetz Graefe 교수가 제안한 화산 모델(Tuple-at-a-time)은 각 연산자(Scan, Filter, HashJoin, Aggregate 등)가 `next()` 인터페이스를 구현하여 한 번에 단 1개의 튜플을 상위 연산자로 전달합니다.
   - 1,000만 건의 행을 처리하는 5단계 실행 계획에서 무려 **5,000만 번의 가상 함수 간접 호출(`vtable dispatch`)**이 발생합니다.
   - 이는 CPU 분기 예측(Branch Predictor)을 무력화하고, 명령어 캐시(I-Cache) 미스를 유발하며, 컴파일러의 루프 언롤링 및 SIMD(Single Instruction Multiple Data) 자동 벡터화를 원천 차단합니다.
2. **나이브 해시 조인(Naive Hash Join)의 L3 캐시 스래싱(Cache Thrashing) 참사**:
   - 조인할 빌드 테이블의 해시 테이블 크기가 CPU L3 캐시 용량(예: 32MB~64MB)을 초과할 때, 프로브(Probe) 단계의 랜덤 메모리 접근이 80% 이상의 L3 캐시 미스를 유발합니다.
   - CPU 연산 속도(GHz)에 비해 메인 메모리(DRAM) 접근 지연(약 50~100ns)이 수백 배 느리기 때문에, CPU 코어는 연산의 90% 이상을 메모리 버스 대기(Memory Stall)에 낭비하게 됩니다.
3. **차세대 솔루션: 벡터화 실행(Vectorized Execution)과 기수 분할(Radix Partitioning)**:
   - **벡터화 실행 (Peter Boncz 2005, MonetDB/X100 / DuckDB)**: `next()` 호출 시 1개의 튜플 대신 **1024개 단위의 값 벡터(Vector Batch)**를 반환합니다. 가상 함수 호출 횟수가 1024배로 급감하고, 연속된 메모리 배열 순회로 CPU AVX-512 / NEON SIMD 명령어 세트가 완벽하게 적용됩니다.
   - **캐시 의식적 기수 해시 조인 (Radix Partitioned Hash Join)**: 해시 키의 비트(Radix)를 기반으로 빌드와 프로브 테이블을 L1/L2 캐시 크기(수십 KB~수 MB)에 들어맞는 작은 파티션으로 분할한 뒤 조인하여 L3 캐시 미스를 2% 이하로 제거합니다.

---

## 핵심 시스템 파라미터 및 원리

### 1. 실행 엔진 모드 (`execution_engine`)
- `VOLCANO_ITERATOR`: 튜플당 1회씩 상위 연산자로 `next()` 호출. 가상 함수 오버헤드가 크고 SIMD 적용 불가.
- `VECTORIZED`: `vector_batch_size`(기본 1024) 단위로 일괄 처리. 가상 호출이 1/1024로 급감하며 SIMD 4배 가속 적용.

### 2. 조인 알고리즘 (`join_algorithm`)
- `NAIVE_HASH_JOIN`: 전체 빌드 테이블로 단일 거대 해시 테이블 구축. 테이블 크기가 L3 캐시 용량을 초과할 시 캐시 스래싱(85% 미스율) 및 메모리 지연 스톨 발생.
- `RADIX_PARTITIONED_HASH_JOIN`: 캐시 크기 이하의 서브 파티션으로 분할 조인하여 캐시 미스율을 2% 이하로 극소화.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "system": {
    "execution_engine": "VECTORIZED",
    "vector_batch_size": 1024,
    "join_algorithm": "RADIX_PARTITIONED_HASH_JOIN",
    "l3_cache_capacity_tuples": 50000
  },
  "query_plan": {
    "scan_tuples_count": 1000000,
    "filter_selectivity": 0.5,
    "build_table_tuples": 200000
  }
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 형식 결과를 출력합니다.

```json
{
  "status": "SUCCESS",
  "engine_config": {
    "execution_engine": "VECTORIZED",
    "vector_batch_size": 1024,
    "join_algorithm": "RADIX_PARTITIONED_HASH_JOIN",
    "simd_vectorization": true,
    "radix_partitioning": true
  },
  "metrics": {
    "total_tuples_processed": 1000000,
    "output_tuples": 400000,
    "total_virtual_calls": 4885,
    "virtual_call_overhead_ms": 0.073,
    "cache_misses": 10000,
    "cache_miss_stall_ms": 1.0,
    "total_execution_time_ms": 6.073,
    "verdict": "OPTIMAL_VECTORIZED_RADIX_JOIN"
  }
}
```

### 판정 규칙 (Verdict Rules)
1. 화산 모델이면서 나이브 해시 조인의 캐시 미스율이 50%를 초과한 경우:
   - `status = "FAILED"`, `verdict = "VOLCANO_ITERATOR_CACHE_THRASHING_COLLAPSE"`
2. 화산 모델로 인한 가상 함수 호출 병목인 경우:
   - `status = "FAILED"`, `verdict = "VOLCANO_ITERATOR_VIRTUAL_CALL_BOTTLENECK"`
3. 나이브 해시 조인으로 인한 캐시 미스 스톨인 경우:
   - `status = "FAILED"`, `verdict = "NAIVE_HASH_JOIN_CACHE_MISS_STALL"`
4. 벡터화 실행 및 캐시 친화적 조인이 성공한 경우:
   - `status = "SUCCESS"`, `verdict = "OPTIMAL_VECTORIZED_RADIX_JOIN"`
