# 136. SQL에 변수만 넣었을 뿐인데 왜 DB CPU가 100% 찍고 커넥션이 폭사해요?!: 하드 파싱(Hard Parse) vs 소프트 파싱(Soft Parse)과 바인드 변수(Bind Variable) & 커서 캐시 공유

## 문제 설명

이커머스 플랫폼의 백엔드 주니어 개발자 젤리(Zeli)는 사용자의 주문 내역을 조회하는 API를 개발하면서, 파이썬 코드에서 아무런 의심 없이 f-string 문자열 포맷팅으로 SQL을 작성했습니다:

```python
# ❌ 리터럴 쿼리 (문자열 결합 방식)
def get_order(user_id, order_id):
    sql = f"SELECT * FROM orders WHERE user_id = {user_id} AND order_id = {order_id}"
    cursor.execute(sql)
    return cursor.fetchone()
```

*"개발용 로컬 DB에서 실행해 봤을 때 인덱스도 잘 타고 0.5ms 만에 초고속으로 조회되니, 운영 서버에서도 번개처럼 빠르겠지?!"* 😎

하지만 프로모션 이벤트가 시작되어 동시 접속자 수천 명이 각자 자기 계정으로 주문 조회를 요청하자마자 DB 서버 모니터링에 충격적인 비상벨이 울렸습니다! 🚨

```
[ALERT] Database CPU Usage: 100% (옵티마이저 CBO 연산 폭풍!)
[ALERT] Shared Pool / Library Cache Latch Contention 급증!
[ALERT] Library Cache Eviction / Churn 폭발!
[ERROR] ORA-04031: unable to allocate 4096 bytes of shared memory
[ERROR] HikariCP: Connection is not available, request timed out after 30000ms.
```

쿼리 자체는 인덱스를 타는 초간단 PK 조회인데도 불구하고, **DB 서버의 CPU가 100%로 치솟으며 수십 개의 DB 커넥션 풀이 모조리 고갈되어 전사 서비스가 마비**된 것입니다! 😱

---

### 원인: SQL 최적화(CBO)의 비용과 리터럴 SQL의 하드 파싱 폭풍

RDBMS 엔진(Oracle, MySQL, PostgreSQL)은 SQL 텍스트를 수신하면 결과를 내기까지 다음 단계를 거칩니다:

```
[클라이언트 SQL 전송] ──► [1. 문법/의미 검사] ──► [2. CBO 옵티마이저 최적화] ──► [3. 실행 계획 실행]
                                                      │
                                                      └── 수십 가지 실행 경로 비용 계산
                                                          (극심한 CPU 수학 연산 소모! 🔥)
```

1. **하드 파싱 (Hard Parse)**:
   - 라이브러리 캐시에 실행 계획이 없으면, 옵티마이저가 인덱스 스캔, 풀 테이블 스캔, 조인 방식 등의 비용을 계산하여 새로운 실행 계획을 컴파일합니다. 이 과정은 **엄청난 CPU 연산**을 소모합니다.
2. **소프트 파싱 (Soft Parse)**:
   - 라이브러리 캐시에 동일한 SQL 텍스트가 이미 컴파일되어 있으면, 최적화 단계를 통째로 건너뛰고 **0.01ms 만에 실행 계획을 재사용**합니다.
3. **리터럴 쿼리의 참사**:
   - DB 엔진은 SQL 텍스트의 해시값(SQL ID)을 키로 캐시를 검색합니다.
   - `WHERE user_id = 1001`과 `WHERE user_id = 1002`는 숫자가 다르므로 **완전히 다른 독립된 SQL**로 취급됩니다!
   - 1,000명의 유저가 조회하면 **1,000번의 하드 파싱**이 일어나며 DB CPU가 100% 포화되고, 1회용 플랜들이 캐시를 채우면서 기존 캐시를 쫓아내는 **캐시 축출(LRU Churn)**과 래치 경합이 발생합니다.

---

### 구원: 바인드 변수 (Bind Variable / PreparedStatement)

해결책은 쿼리 텍스트에 값을 직접 박지 않고 **바인드 변수(`?`)**를 사용하는 것입니다:

```sql
SELECT * FROM orders WHERE user_id = ? AND order_id = ?;
```

- 파라미터 값이 1001이든 1002든 SQL 텍스트 템플릿이 완벽히 동일하므로, **최초 1회만 하드 파싱**되고 이후 수만 건의 쿼리는 **100% 소프트 파싱(캐시 적중)**으로 즉시 실행됩니다!
- CPU 사용률 90% 이상 급감, 공유 풀 메모리 보존, 그리고 악명 높은 **SQL 인젝션(SQL Injection)**까지 원천 방어됩니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "use_bind_variables": false,                 // 바인드 변수 사용 여부 (boolean)
  "shared_pool_cursor_capacity": 50,           // 공유 풀에 캐싱 가능한 최대 실행 계획 수
  "hard_parse_cpu_cost_ms": 10.0,              // 하드 파싱 1회당 CPU 소요 시간 (ms)
  "soft_parse_cpu_cost_ms": 0.1,               // 소프트 파싱 1회당 CPU 소요 시간 (ms)
  "execution_cost_ms": 1.0,                    // 쿼리 실제 실행 시간 (ms)
  "queries": [
    {
      "query_id": "q_01",
      "raw_sql": "SELECT * FROM orders WHERE user_id = 1001"
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다:

```json
{
  "summary": {
    "use_bind_variables": false,
    "total_queries": 30,
    "total_hard_parses": 30,
    "total_soft_parses": 0,
    "hard_parse_ratio_pct": 100.0,
    "soft_parse_ratio_pct": 0.0,
    "cache_evictions": 0,
    "distinct_plans_cached": 30,
    "total_cpu_time_ms": 330.0,
    "overall_verdict": "HARD_PARSE_STORM_CPU_EXHAUSTION"
  },
  "sample_query_results": [
    {
      "query_id": "q_01",
      "sql_key": "SELECT * FROM orders WHERE user_id = 1001",
      "parse_type": "HARD_PARSE",
      "elapsed_ms": 11.0
    }
  ]
}
```

---

## 제약 사항 및 상태 판정 기준

- `use_bind_variables == true`일 때 SQL 내의 모든 따옴표 문자열(`'...'`)과 정수/실수 숫자 리터럴은 `?`로 치환되어 템플릿 키를 구성합니다.
- 공유 풀 용량(`shared_pool_cursor_capacity`) 초과 시 가장 오랫동안 재사용되지 않은 플랜(LRU)이 축출됩니다 (`cache_evictions += 1`).
- `overall_verdict` 판정 기준:
  - `hard_parse_ratio_pct >= 80.0`이고 `total_queries >= 20`: `"HARD_PARSE_STORM_CPU_EXHAUSTION"`
  - `cache_evictions > 10`: `"SHARED_POOL_THRASHING_LRU_CHURN"`
  - `soft_parse_ratio_pct >= 70.0`: `"OPTIMAL_BIND_VARIABLE_REUSE"`
  - 그 외: `"MODERATE_PARSE_OVERHEAD"`
