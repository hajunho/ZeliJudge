# Problem 066: 데이터베이스 샤딩과 팬아웃 병목 (Database Sharding & Scatter-Gather Fan-out)

## 문제 설명

대규모 트래픽을 감당하기 위해 데이터베이스를 16대의 샤드(Shard)로 수평 분할(Sharding)한 당신의 이커머스 팀에서 심각한 병목 현상이 발생했습니다:
> "DB를 16대로 쪼개어 샤딩을 적용했는데, 단일 DB일 때보다 쿼리 응답 속도가 5배나 느려지고 전체 DB CPU가 100%로 마비되었습니다!  
> 고객이 마이페이지에서 '내 주문 내역'을 누를 때마다 16대 샤드 전체에 쿼리가 브로드캐스트되어 모든 샤드가 서랍을 뒤집어엎고 있습니다!"

원인은 데이터 접근 패턴(Query Access Pattern)을 고려하지 않고 단순 생성 날짜(`created_date`)로 샤드 키를 잡은 **스캐터-게더(Scatter-Gather / Fan-out)** 안티패턴이었습니다:
- 사용자의 주문 조회 쿼리(`WHERE user_id = ?`)가 들어올 때 날짜를 알지 못하므로, 샤딩 라우터는 쿼리를 16개 모든 샤드에 동시에 브로드캐스트(Scatter)한 뒤 취합(Gather)해야 합니다.
- 샤드가 16대라면 단 1건의 사용자 조회에 16배의 DB 리소스가 낭비되며, 16대 중 가장 느린 샤드의 속도가 전체 응답 지연(Long-tail Latency)을 결정합니다.

반면, 핵심 비즈니스 쿼리 조건인 `user_id`를 샤드 키로 채택하여 코로케이션(Co-sharding)을 적용하면, 동일 사용자의 모든 주문 데이터가 단 하나의 물리 샤드에 격리 저장되어 **단 1개의 샤드로 직행(Targeted Single-Shard Routing, Fan-out = 1)**합니다.

당신은 동일한 주문 데이터 및 쿼리 스트림에 대해 **Date-Based Sharding**과 **User-Based Sharding**의 샤드별 접근 횟수(Fan-out)와 데이터 일관성을 비교 시뮬레이션하는 엔진을 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정
- `SHARDS <num_shards>`: 총 샤드 개수 $S$ ($1 \le S \le 32$).
- 샤드 식별자는 `S0, S1, S2, ..., S(S-1)` 로 주어집니다.
- 해시 라우팅 함수:
  $$\text{get\_shard}(key, S) = \left( \sum_{i=0}^{L-1} (i + 1) \times \text{ord}(key[i]) \right) \pmod S$$
  - 여기서 $L$은 문자열 $key$의 길이, $\text{ord}(c)$는 문자의 아스키 코드 값입니다.

### 2. 두 가지 샤딩 전략

#### 1) Date-Based Sharding (Naive 전략)
- **저장 위치**: `shard_id = get_shard(created_date, S)`
- **쿼리 라우팅**:
  - `QUERY_BY_USER <user_id>`: 날짜를 모르므로 **전체 $S$개 샤드에 브로드캐스트 (Scatter-Gather, Fan-out = $S$)**.
  - `QUERY_BY_DATE <created_date>`: 날짜를 아므로 해당 1개 샤드로 직행 (Fan-out = 1).
  - `QUERY_BY_USER_AND_DATE <user_id> <created_date>`: 날짜 샤드로 직행 (Fan-out = 1).

#### 2) User-Based Sharding (Optimal OLTP 전략)
- **저장 위치**: `shard_id = get_shard(user_id, S)`
- **쿼리 라우팅**:
  - `QUERY_BY_USER <user_id>`: 유저 ID를 아므로 **해당 1개 샤드로 직행 (Targeted, Fan-out = 1)**.
  - `QUERY_BY_DATE <created_date>`: 유저 ID를 모르므로 전체 $S$개 샤드에 브로드캐스트 (Scatter-Gather, Fan-out = $S$).
  - `QUERY_BY_USER_AND_DATE <user_id> <created_date>`: 유저 ID 샤드로 직행 (Fan-out = 1).

---

## 입력 형식

```text
SYSTEM_CONFIG
SHARDS <num_shards>
ACTIONS
INSERT <order_id> <user_id> <created_date> <amount>
QUERY_BY_USER <user_id>
QUERY_BY_DATE <created_date>
QUERY_BY_USER_AND_DATE <user_id> <created_date>
...
```

---

## 출력 형식

1. `INSERT` 명령 출력 (1줄):
```text
ACT <idx> INSERT <order_id> DATE_SHARD:STORED_AT=S<id> USER_SHARD:STORED_AT=S<id>
```

2. `QUERY_*` 명령 출력 (3줄):
```text
ACT <idx> <QUERY_TYPE> <args...>
  DATE_SHARD: FANOUT:<cnt> TARGETS:[<targets>] MATCHES:<matched_count>
  USER_SHARD: FANOUT:<cnt> TARGETS:[<targets>] MATCHES:<matched_count>
```
- `TARGETS`: 접근한 샤드 ID 목록 (오름차순, 쉼표 구분: `S0,S1,S2...`)

3. 모든 액션 처리 후 최종 요약 (4줄):
```text
SUMMARY DATE_SHARD TOTAL_FANOUT_QUERIES:<cnt> AVG_FANOUT:<avg> MAX_FANOUT:<max>
SUMMARY USER_SHARD TOTAL_FANOUT_QUERIES:<cnt> AVG_FANOUT:<avg> MAX_FANOUT:<max>
SUMMARY FANOUT_SAVED:<diff> (EFFICIENCY:<pct>%)
SUMMARY DATA_CONSISTENCY_CHECK: 100% MATCHED
```
- `TOTAL_FANOUT_QUERIES`: 전체 조회 쿼리에서 접근한 샤드 수(`FANOUT`)의 총합.
- `AVG_FANOUT`: `TOTAL_FANOUT_QUERIES / 총_조회_쿼리수` (소수점 둘째 자리).
- `EFFICIENCY`: `(FANOUT_SAVED / DATE_SHARD_TOTAL) * 100` (소수점 둘째 자리).
- `DATA_CONSISTENCY_CHECK`: 모든 쿼리에서 양 전략의 검색 결과가 100% 일치하면 `100% MATCHED`.

---

## 입출력 예시

### 예시 1: 4개 샤드 환경 사용자별 주문 조회

**입력:**
```text
SYSTEM_CONFIG
SHARDS 4
ACTIONS
INSERT ord-1 user-1 2026-09-01 10000
INSERT ord-2 user-1 2026-09-02 15000
INSERT ord-3 user-2 2026-09-01 20000
INSERT ord-4 user-3 2026-09-03 30000
INSERT ord-5 user-2 2026-09-04 25000
INSERT ord-6 user-4 2026-09-05 50000
QUERY_BY_USER user-1
QUERY_BY_USER user-2
QUERY_BY_USER user-3
QUERY_BY_USER user-4
```

**출력:**
```text
ACT 1 INSERT ord-1 DATE_SHARD:STORED_AT=S3 USER_SHARD:STORED_AT=S0
ACT 2 INSERT ord-2 DATE_SHARD:STORED_AT=S1 USER_SHARD:STORED_AT=S0
ACT 3 INSERT ord-3 DATE_SHARD:STORED_AT=S3 USER_SHARD:STORED_AT=S1
ACT 4 INSERT ord-4 DATE_SHARD:STORED_AT=S3 USER_SHARD:STORED_AT=S2
ACT 5 INSERT ord-5 DATE_SHARD:STORED_AT=S3 USER_SHARD:STORED_AT=S1
ACT 6 INSERT ord-6 DATE_SHARD:STORED_AT=S1 USER_SHARD:STORED_AT=S3
ACT 7 QUERY_BY_USER user-1
  DATE_SHARD: FANOUT:4 TARGETS:[S0,S1,S2,S3] MATCHES:2
  USER_SHARD: FANOUT:1 TARGETS:[S0] MATCHES:2
ACT 8 QUERY_BY_USER user-2
  DATE_SHARD: FANOUT:4 TARGETS:[S0,S1,S2,S3] MATCHES:2
  USER_SHARD: FANOUT:1 TARGETS:[S1] MATCHES:2
ACT 9 QUERY_BY_USER user-3
  DATE_SHARD: FANOUT:4 TARGETS:[S0,S1,S2,S3] MATCHES:1
  USER_SHARD: FANOUT:1 TARGETS:[S2] MATCHES:1
ACT 10 QUERY_BY_USER user-4
  DATE_SHARD: FANOUT:4 TARGETS:[S0,S1,S2,S3] MATCHES:1
  USER_SHARD: FANOUT:1 TARGETS:[S3] MATCHES:1
SUMMARY DATE_SHARD TOTAL_FANOUT_QUERIES:16 AVG_FANOUT:4.00 MAX_FANOUT:4
SUMMARY USER_SHARD TOTAL_FANOUT_QUERIES:4 AVG_FANOUT:1.00 MAX_FANOUT:1
SUMMARY FANOUT_SAVED:12 (EFFICIENCY:75.00%)
SUMMARY DATA_CONSISTENCY_CHECK: 100% MATCHED
```

**설명:**
- Date-Based 샤딩은 사용자 주문을 조회할 때마다 4개 샤드 전체를 뒤져야 해서 총 16번의 샤드 쿼리가 발생했습니다 (`AVG_FANOUT: 4.00`).
- User-Based 샤딩은 해당 사용자가 저장된 단 1개의 샤드로만 직행하여 단 4번의 샤드 쿼리만으로 완벽하게 처리했습니다 (`EFFICIENCY: 75.00% 절감`).
- 두 전략 모두 조회된 주문 건수는 정확히 일치하여 100% 데이터 정합성을 유지했습니다!
