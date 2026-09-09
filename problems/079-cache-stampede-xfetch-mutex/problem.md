# Problem 079: 캐시 스탬피드와 뮤텍스 락 & XFetch 확률적 조기 만료 (Cache Stampede & Mutex vs XFetch)

## 문제 설명

초당 수만 명의 사용자가 방문하는 포털 사이트의 실시간 급상승 검색어 및 메인 배너 서비스를 운영하던 팀에 초대형 서비스 장애가 발생했습니다:
> "평소에는 Redis 캐시 덕분에 DB CPU 사용률이 5% 미만으로 평화로웠는데, 캐시 유효 시간(TTL 60초)이 끝나는 바로 그 1초 동안 갑자기 수천 건의 요청이 일제히 DB로 몰려들었습니다!  
> 무거운 집계 쿼리 수천 개가 동시에 실행되면서 DB CPU가 100%로 치솟고 커넥션 풀이 폭사하여 전사 사이트가 완전히 다운되었습니다!"

이 장애의 정체는 대규모 분산 캐시 시스템의 가장 치명적인 재앙인 **캐시 스탬피드(Cache Stampede / Thundering Herd)** 현상이었습니다:
- **캐시 만료 순간의 쓰나미**:
  - 트래픽이 몰리는 인기 키(Hot Key)의 캐시 유효 기간(TTL)이 만료되면, 그 직후 도착한 수많은 동시 요청이 일제히 `CACHE_MISS`를 감지합니다.
  - 방패(캐시)가 사라진 무방비 상태에서 모든 요청이 동일한 무거운 DB 집계 쿼리를 실행하여 데이터베이스를 때려눕힙니다.
- **해결책 1: 뮤텍스 락 (Mutex Lock / Single-Flight)**:
  - 캐시 미스가 발생했을 때 분산 락(Redis `SETNX`)을 획득한 **단 1개의 요청만 DB로 보내어** 데이터를 새로 계산하고 캐시를 갱신하게 합니다.
  - 나머지 요청들은 락을 기다리거나(`MUTEX_BLOCKED_WAIT`) 기존 Stale 데이터를 임시 반환받음으로써 DB 쿼리를 1개로 억제합니다.
- **해결책 2: XFetch 확률적 조기 만료 (Optimal Probabilistic Cache Expiration - VLDB 2015)**:
  - 캐시가 완전히 만료된 후 대처하는 것은 늦습니다!
  - 2015년 VLDB 학회에서 발표된 Vitter 교수의 **XFetch 알고리즘**은 캐시를 읽을 때마다 다음 확률 공식을 평가합니다:
    $$-\beta \times \delta \times \ln(U) > (\text{expiry\_time} - \text{current\_time})$$
    (단, $\beta$는 가중치 계수, $\delta$는 DB 계산 비용, $U \sim \text{Uniform}(0, 1)$ 난수)
  - 유효 기간이 얼마 남지 않았을 때($\Delta t \to 0$), 트래픽 중 단 1개의 요청이 확률적으로 조건을 만족하여 **선제 조기 갱신(`XFETCH_EARLY_REFRESH`)**을 트리거합니다!
  - 진열대가 비어있는 시간(Zero TTL) 자체가 영구히 사라져 모든 클라이언트는 락 대기 없이 항상 0ms 캐시 히트율을 누리게 됩니다!

인기 베이커리에서 빵이 다 떨어지는 순간 손님 500명이 주방으로 난입해 제빵사를 덮치지 않도록, 도어락(Mutex)을 달아 1명만 들여보내거나, 빵이 떨어지기 직전에 미리 새 빵을 굽도록 주문(XFetch)하는 것과 같습니다!

당신은 동일한 요청 스트림에 대해 무방비로 스탬피드를 맞는 **Naive 캐시 엔진**, 락을 거는 **Mutex 엔진**, 선제 조기 갱신을 수행하는 **XFetch 엔진**의 DB 쿼리 수와 안정성을 비교 검증하는 캐시 시뮬레이터를 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정 (`SYSTEM_CONFIG`)
- `CACHE_TTL_TICKS <int>`: 캐시 기본 유효 기간 틱.
- `DB_QUERY_COST_TICKS <int>`: DB 쿼리 계산 비용 $\delta$ (틱).
- `DB_MAX_CONCURRENCY <int>`: 단일 틱 내 DB가 견딜 수 있는 최대 동시 쿼리 수. 이를 초과하면 `DB_STATUS:OVERLOAD_CRASHED`로 영구 전환!
- `XFETCH_BETA <float>`: XFetch 선제 갱신 가중치 계수 $\beta$ (기본값: 1.0).

---

### 2. 세 가지 캐시 엔진 메커니즘

#### 1) Naive Cache Engine (무방비 캐시)
- `GET_ITEM <req_id>`:
  - `current_tick < naive_expiry`: 캐시 히트 (`CACHE_HIT`).
  - `current_tick >= naive_expiry`:
    - 캐시 만료! 모든 요청이 DB로 몰려감 (`CACHE_MISS_DB_QUERY`).
    - `naive_queries += 1`, 이번 틱 쿼리 수 1 증가.
    - 이번 틱 쿼리 수가 `DB_MAX_CONCURRENCY`를 초과하면 즉시 `CRASH_DETECTED`!
    - 캐시는 틱 종료 시점에 갱신 예약됨.

#### 2) Mutex Lock Engine (상호 배제 락)
- `GET_ITEM <req_id>`:
  - `current_tick < mutex_expiry`: 캐시 히트 (`CACHE_HIT`).
  - `current_tick >= mutex_expiry`:
    - 락이 풀려있는 경우: 락 획득 성공 (`MUTEX_ACQUIRED_DB_QUERY`), DB 쿼리 1회 실행, 락 잠금.
    - 락이 이미 걸려있는 경우: 락 대기/Stale 서빙 (`MUTEX_BLOCKED_WAIT`), DB 쿼리 0회 방어!

#### 3) XFetch Engine (확률적 조기 만료)
- `GET_ITEM <req_id> [pseudo_u]`:
  - `rem_ttl = xfetch_expiry - current_tick`
  - `rem_ttl > 0`:
    - XFetch 조건 평가: $-\beta \times \delta \times \ln(u) > \text{rem\_ttl}$
    - 조건 참: 선제 조기 갱신 트리거 (`XFETCH_EARLY_REFRESH`), DB 쿼리 1회 실행, `xfetch_expiry = current_tick + CACHE_TTL_TICKS`, 클라이언트는 즉시 데이터 수신!
    - 조건 거짓: 일반 캐시 히트 (`CACHE_HIT`).
  - `rem_ttl <= 0`: 비상 갱신 (`CACHE_EXPIRED_DB_QUERY`).

---

### 3. 액션 명세

#### 1) `GET_ITEM <req_id> [pseudo_u]`
- 캐시 조회 요청.
- 출력 (4줄):
  ```text
  ACT <idx> GET_ITEM ID:<req_id> TICK:<cur_tick>
    NAIVE: STATUS:<CACHE_HIT|CACHE_MISS_DB_QUERY> DB_OVERLOAD:<NONE|CRASH_DETECTED>
    MUTEX: STATUS:<CACHE_HIT|MUTEX_ACQUIRED_DB_QUERY|MUTEX_BLOCKED_WAIT>
    XFETCH: STATUS:<CACHE_HIT|XFETCH_EARLY_REFRESH|CACHE_EXPIRED_DB_QUERY> REMAINING_TTL:<rem>
  ```

#### 2) `TICK <num_ticks>`
- 가상 시간 `<num_ticks>` 경과.
- 출력 (1줄):
  ```text
  ACT <idx> TICK <num_ticks> (CURRENT_TICK:<cur_tick>)
  ```

#### 3) `CHECK_METRICS`
- 누적 메트릭 점검.
- 출력 (4줄):
  ```text
  ACT <idx> CHECK_METRICS
    NAIVE: TOTAL:<tot> HITS:<hits> DB_QUERIES:<q> DB_STATUS:<HEALTHY|OVERLOAD_CRASHED>
    MUTEX: TOTAL:<tot> HITS:<hits> DB_QUERIES:<q> DB_STATUS:HEALTHY
    XFETCH: TOTAL:<tot> HITS:<hits> DB_QUERIES:<q> EARLY_REFRESHES:<cnt> DB_STATUS:HEALTHY
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
CACHE_TTL_TICKS <ttl>
DB_QUERY_COST_TICKS <delta>
DB_MAX_CONCURRENCY <max_concurrency>
XFETCH_BETA <beta>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 실행 결과 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (6줄):
```text
SUMMARY TOTAL_GET_REQUESTS:<tot>
SUMMARY NAIVE HITS:<hits> DB_QUERIES:<q> DB_STATUS:<HEALTHY|OVERLOAD_CRASHED>
SUMMARY MUTEX HITS:<hits> DB_QUERIES:<q> DB_STATUS:HEALTHY
SUMMARY XFETCH HITS:<hits> DB_QUERIES:<q> EARLY_REFRESHES:<cnt> DB_STATUS:HEALTHY
SUMMARY DB_QUERY_REDUCTION:<pct:.2f>%
SUMMARY CACHE_VERDICT: MUTEX_AND_XFETCH_PREVENT_STAMPEDE_CRASH
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
CACHE_TTL_TICKS 10
DB_QUERY_COST_TICKS 3
DB_MAX_CONCURRENCY 2
XFETCH_BETA 1.0
ACTIONS
GET_ITEM R1 0.5
TICK 10
GET_ITEM R2 0.5
GET_ITEM R3 0.5
GET_ITEM R4 0.5
CHECK_METRICS
TICK 2
GET_ITEM R5 0.5
CHECK_METRICS
```

**출력:**
```text
ACT 1 GET_ITEM ID:R1 TICK:0
  NAIVE: STATUS:CACHE_HIT DB_OVERLOAD:NONE
  MUTEX: STATUS:CACHE_HIT
  XFETCH: STATUS:CACHE_HIT REMAINING_TTL:10
ACT 2 TICK 10 (CURRENT_TICK:10)
ACT 3 GET_ITEM ID:R2 TICK:10
  NAIVE: STATUS:CACHE_MISS_DB_QUERY DB_OVERLOAD:NONE
  MUTEX: STATUS:MUTEX_ACQUIRED_DB_QUERY
  XFETCH: STATUS:CACHE_EXPIRED_DB_QUERY REMAINING_TTL:0
ACT 4 GET_ITEM ID:R3 TICK:10
  NAIVE: STATUS:CACHE_MISS_DB_QUERY DB_OVERLOAD:NONE
  MUTEX: STATUS:MUTEX_BLOCKED_WAIT
  XFETCH: STATUS:CACHE_HIT REMAINING_TTL:10
ACT 5 GET_ITEM ID:R4 TICK:10
  NAIVE: STATUS:CACHE_MISS_DB_QUERY DB_OVERLOAD:CRASH_DETECTED
  MUTEX: STATUS:MUTEX_BLOCKED_WAIT
  XFETCH: STATUS:CACHE_HIT REMAINING_TTL:10
ACT 6 CHECK_METRICS
  NAIVE: TOTAL:4 HITS:1 DB_QUERIES:3 DB_STATUS:OVERLOAD_CRASHED
  MUTEX: TOTAL:4 HITS:3 DB_QUERIES:1 DB_STATUS:HEALTHY
  XFETCH: TOTAL:4 HITS:3 DB_QUERIES:1 EARLY_REFRESHES:0 DB_STATUS:HEALTHY
ACT 7 TICK 2 (CURRENT_TICK:12)
ACT 8 GET_ITEM ID:R5 TICK:12
  NAIVE: STATUS:CACHE_HIT DB_OVERLOAD:CRASH_DETECTED
  MUTEX: STATUS:CACHE_HIT
  XFETCH: STATUS:CACHE_HIT REMAINING_TTL:8
ACT 9 CHECK_METRICS
  NAIVE: TOTAL:5 HITS:2 DB_QUERIES:3 DB_STATUS:OVERLOAD_CRASHED
  MUTEX: TOTAL:5 HITS:4 DB_QUERIES:1 DB_STATUS:HEALTHY
  XFETCH: TOTAL:5 HITS:4 DB_QUERIES:1 EARLY_REFRESHES:0 DB_STATUS:HEALTHY
SUMMARY TOTAL_GET_REQUESTS:5
SUMMARY NAIVE HITS:2 DB_QUERIES:3 DB_STATUS:OVERLOAD_CRASHED
SUMMARY MUTEX HITS:4 DB_QUERIES:1 DB_STATUS:HEALTHY
SUMMARY XFETCH HITS:4 DB_QUERIES:1 EARLY_REFRESHES:0 DB_STATUS:HEALTHY
SUMMARY DB_QUERY_REDUCTION:66.67%
SUMMARY CACHE_VERDICT: MUTEX_AND_XFETCH_PREVENT_STAMPEDE_CRASH
```
