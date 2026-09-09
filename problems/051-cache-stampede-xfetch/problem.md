# #051 캐시가 만료되는 순간 DB가 폭발했어요?!: 캐시 스탬피드(Cache Stampede / Thundering Herd)와 분산 락 vs stale-while-revalidate

---

## 1. 현실 세계 비유: 선착순 인기 빵집 매대와 1,000명의 빵돌이들

초인기 빵집의 갓 구운 단팥빵 매대를 상상해 보세요.

```text
❌ 무방비 캐시(Cache-Aside)의 최후 (Thundering Herd 재앙):
   매대(Redis 캐시)에 따뜻한 빵이 놓여있을 때는 손님들이 1초 만에 빵을 집어가며 평화롭습니다.
   하지만 매대의 빵 유효시간이 딱 끝나 빵이 떨어진 찰나의 1밀리초!
   뒤에서 대기하던 손님 1,000명이 동시에 "빵 내놔!"를 외치며 좁은 주방 문을 부수고 몰려듭니다.
   주방 안의 제빵사(DB)는 1,000명에게 멱살을 잡혀 깔려 질식사(DB 커넥션 풀 고갈 & CPU 100% 사망)하고,
   단팥빵 1개를 굽는 데 5초가 걸리는 동안 뒤이어 들어온 1만 명의 손님도 주방으로 돌진합니다!

✅ Mutex 분산 락 (Single-Flight 패턴):
   빵이 떨어지면 제빵사가 문을 잠그고 번호표 1번 손님(Lock 획득자) 단 1명만 주방으로 들여보냅니다.
   "이 손님이 빵을 구워 나올 때까지 나머지 999명은 매대 앞에서 조용히 줄 서서 기다리세요(LOCK_WAIT)!"
   제빵사는 평화롭게 빵을 딱 1개 구워 매대에 채우고, 대기하던 손님들은 갓 나온 빵을 순서대로 집어갑니다.
   DB 쿼리가 1,000개에서 단 1개로 급감합니다!

✅ stale-while-revalidate (CDN 및 RFC 5861 비동기 갱신):
   "기다리는 것도 싫다! 손님 대기시간 0ms 달성!"
   빵이 방금 막 유효기간이 지났더라도, 매대에 남아있던 빵(Stale Data)을 손님들에게 즉시 건네줍니다.
   동시에 빵집 조수 1명이 주방에 들어가서 조용히 다음 빵을 백그라운드로 구워옵니다.
   손님들은 단 1ms도 기다리지 않고 음식을 받아 가며, 제빵사(DB)는 쿼리 단 1개로 여유롭게 빵을 굽습니다!
```

수많은 주니어 개발자와 AI 바이브 코더들이 "DB 부하를 줄이자!"며 Redis 캐시를 도입하고 TTL을 10분으로 설정합니다.  
그리고 10분 동안 평화롭다가, **10분 00초 캐시 키가 딱 만료되는 찰나의 순간 동시 접속자 5,000명이 한꺼번에 DB로 몰려가  
동일한 쿼리를 동시에 실행하여 DB가 폭사하는 "캐시 스탬피드(Cache Stampede / Thundering Herd)"** 대형 참사를 겪습니다.

---

## 2. 문제 개요

당신은 초당 수만 건의 트래픽이 몰리는 대형 티켓팅/이커머스 플랫폼의 백엔드 성능 엔지니어입니다.  
캐시 만료 구간마다 DB를 마비시키는 캐시 스탬피드를 방어하기 위해,  
기존의 **무방비 캐시 모델(NAIVE)**, **Mutex 락 기반 단일 조회 모델(MUTEX)**, 그리고 **stale-while-revalidate 기반 즉시 반환 모델(STALE)**을 시뮬레이션하고,  
DB 쿼리 절감률(`DB_SAVED`)과 평균 지연시간(`AVG_LATENCY`)을 정밀 측정하세요.

### 시뮬레이션 상세 규칙

#### 1. 공통 환경
- `TTL_MS <ttl_ms>`: 캐시의 유효 시간 (ms, $1 \le ttl\_ms \le 100,000$).
- `DB_QUERY_MS <db_query_ms>`: DB에서 데이터를 조회/연산하여 캐시를 채우는 데 걸리는 시간 (ms, $1 \le db\_query\_ms \le 5,000$).
- 캐시 초기 상태: 데이터 없음 (`expire_ms = 0`, Cold Start).
- 캐시가 유효한 상태(`t < cached_until`)에서 들어오는 요청은 **순수 캐시 히트(`HIT`)** 처리되며, 지연시간은 `1ms`, DB 쿼리는 `0회`입니다.

#### 2. 모델 A: 무방비 Cache-Aside (NAIVE)
캐시가 만료된 시점($t \ge cached\_until$)에 들어온 모든 요청이 개별적으로 DB 쿼리를 직접 수행합니다:
- 상태: `DB_DIRECT`
- 지연시간: $db\_query\_ms$
- DB 쿼리 발생: `+1회`
- 완료 시각 $t + db\_query\_ms$에 캐시 만료 시각이 갱신됩니다:
  $$cached\_until = \max(cached\_until, (t + db\_query\_ms) + ttl\_ms)$$
- 주의: 쿼리가 수행되는 $db\_query\_ms$ 동안 뒤이어 도착하는 모든 요청도 캐시가 미스이므로, 제각기 독립적으로 DB 쿼리를 발행합니다! (Thundering Herd 발생)

#### 3. 모델 B: Mutex 분산 락 (MUTEX / Single-Flight)
캐시가 만료된 시점($t \ge cached\_until$)에 오직 1개의 요청만 락(Lock)을 획득하여 DB 조회를 수행합니다:
- 현재 진행 중인 DB 쿼리가 없다면 ($t \ge busy\_until$):
  - 락을 획득하고 DB 쿼리를 시작합니다.
  - 상태: `LOCK_FETCH`
  - 지연시간: $db\_query\_ms$
  - DB 쿼리 발생: `+1회`
  - 쿼리 완료 시각 $finish\_t = t + db\_query\_ms$까지 락이 점유됩니다 ($busy\_until = finish\_t$).
  - $finish\_t$에 캐시 만료 시각이 갱신됩니다: $cached\_until = \max(cached\_until, finish\_t + ttl\_ms)$.
- 현재 다른 요청이 락을 쥐고 DB를 조회 중이라면 ($t < busy\_until$):
  - 이 요청은 DB 쿼리를 발행하지 않고, 락이 풀릴 때까지 대기합니다.
  - 상태: `LOCK_WAIT`
  - 지연시간: $busy\_until - t$ (락 해제 및 갱신 캐시 즉시 수신)
  - DB 쿼리 발생: `0회` (추가 쿼리 원천 차단!)

#### 4. 모델 C: stale-while-revalidate (STALE)
캐시가 만료되었더라도, 이전에 캐시된 과거 데이터(Stale Data)가 있다면 대기 없이 즉시 응답하고 백그라운드로 갱신합니다:
- **콜드 스타트(Cold Start)** 구간 (이전에 캐시된 적이 한 번도 없는 경우):
  - 최초 요청 ($t \ge busy\_until$): 상태 `COLD_FETCH`, 지연시간 $db\_query\_ms$, DB 쿼리 `+1회`. 완료 시각에 캐시 갱신 및 `has_stale = True`.
  - 완료 전 대기 요청 ($t < busy\_until$): 상태 `COLD_WAIT`, 지연시간 $busy\_until - t$, DB 쿼리 `0회`.
- **과거 데이터(Stale Data)가 존재하는 경우**:
  - 만료 후 첫 요청 ($t \ge busy\_until$):
    - 백그라운드 비동기 갱신 트리거 (완료 시각 $finish\_t = t + db\_query\_ms$ 예약, $busy\_until = finish\_t$, DB 쿼리 `+1회`).
    - 자신은 쿼리를 기다리지 않고 과거 캐시를 즉시 반환!
    - 상태: `STALE_REVALIDATE`, 지연시간: `1ms`
  - 백그라운드 갱신 중 도착한 요청 ($t < busy\_until$):
    - 이미 갱신이 진행 중이므로 쿼리 없이 과거 캐시를 즉시 반환!
    - 상태: `STALE_HIT`, 지연시간: `1ms`, DB 쿼리 `0회`

---

## 3. 입력 형식

```text
TTL_MS <ttl_ms>
DB_QUERY_MS <db_query_ms>
EVENTS <E>
REQ <client_id> <timestamp_ms>
... (총 E개의 REQ 줄)
```

- `ttl_ms`: 캐시 유효 시간 ($1 \le ttl\_ms \le 100,000$)
- `db_query_ms`: DB 조회 연산 소요 시간 ($1 \le db\_query\_ms \le 5,000$)
- `E`: 요청 수 ($1 \le E \le 30,000$)
- `timestamp_ms`: 요청 도착 시각 (ms 정수, $1 \le timestamp\_ms \le 10,000,000$, 비내림차순 정렬)

---

## 4. 출력 형식

각 `REQ`마다 한 줄씩 3대 모델의 판정 상태와 지연시간을 출력합니다:
```text
REQ <client_id> AT:<t> NAIVE:<status>,LAT:<lat>ms MUTEX:<status>,LAT:<lat>ms STALE:<status>,LAT:<lat>ms
```

모든 요청 처리 후 종합 성능 통계를 출력합니다:
```text
SUMMARY TOTAL_REQS:<total>
NAIVE DB_QUERIES:<n_db> AVG_LATENCY:<n_lat>ms
MUTEX DB_QUERIES:<m_db> AVG_LATENCY:<m_lat>ms DB_SAVED:<m_saved>%
STALE DB_QUERIES:<s_db> AVG_LATENCY:<s_lat>ms DB_SAVED:<s_saved>%
```

- `AVG_LATENCY`: 총 지연시간 / 총 요청 수 (소수점 둘째 자리까지 반올림, 예: `25.50ms`)
- `DB_SAVED`: `((n_db - x_db) / n_db) * 100.0` (소수점 둘째 자리까지 반올림, 예: `75.00%`, `n_db == 0`이면 `0.00%`)

---

## 5. 입출력 예시

### 입력
```text
TTL_MS 100
DB_QUERY_MS 30
EVENTS 8
REQ C1 10
REQ C2 50
REQ C3 80
REQ C1 150
REQ C2 155
REQ C3 160
REQ C4 165
REQ C5 190
```

### 출력
```text
REQ C1 AT:10 NAIVE:DB_DIRECT,LAT:30ms MUTEX:LOCK_FETCH,LAT:30ms STALE:COLD_FETCH,LAT:30ms
REQ C2 AT:50 NAIVE:HIT,LAT:1ms MUTEX:HIT,LAT:1ms STALE:HIT,LAT:1ms
REQ C3 AT:80 NAIVE:HIT,LAT:1ms MUTEX:HIT,LAT:1ms STALE:HIT,LAT:1ms
REQ C1 AT:150 NAIVE:DB_DIRECT,LAT:30ms MUTEX:LOCK_FETCH,LAT:30ms STALE:STALE_REVALIDATE,LAT:1ms
REQ C2 AT:155 NAIVE:DB_DIRECT,LAT:30ms MUTEX:LOCK_WAIT,LAT:25ms STALE:STALE_HIT,LAT:1ms
REQ C3 AT:160 NAIVE:DB_DIRECT,LAT:30ms MUTEX:LOCK_WAIT,LAT:20ms STALE:STALE_HIT,LAT:1ms
REQ C4 AT:165 NAIVE:DB_DIRECT,LAT:30ms MUTEX:LOCK_WAIT,LAT:15ms STALE:STALE_HIT,LAT:1ms
REQ C5 AT:190 NAIVE:HIT,LAT:1ms MUTEX:HIT,LAT:1ms STALE:HIT,LAT:1ms
SUMMARY TOTAL_REQS:8
NAIVE DB_QUERIES:5 AVG_LATENCY:15.50ms
MUTEX DB_QUERIES:2 AVG_LATENCY:15.25ms DB_SAVED:60.00%
STALE DB_QUERIES:2 AVG_LATENCY:4.50ms DB_SAVED:60.00%
```

#### 해설
- $t=10$: 초기 콜드 스타트로 세 모델 모두 DB 조회 발생 (지연 30ms, 만료시각 $10+30+100 = 140ms$).
- $t=50, 80$: 캐시 유효 구간($< 140ms$)이므로 모두 `HIT` (지연 1ms).
- $t=150$: 캐시 만료! C1, C2, C3, C4가 150~165ms 사이에 폭주합니다.
  - **NAIVE**: 4개 요청 모두 DB로 직행하여 4번의 중복 DB 쿼리 발생 (`DB_DIRECT`, 각 30ms).
  - **MUTEX**: C1만 락을 잡고 DB 쿼리를 수행하고, C2, C3, C4는 락 해제 시점(180ms)까지 안전하게 대기하여 DB 쿼리를 1개로 방어 (`LOCK_WAIT`).
  - **STALE**: C1이 백그라운드 갱신을 트리거하면서도 **자신과 뒤이은 요청들에게 과거 캐시를 1ms 만에 즉시 반환**! DB 쿼리 60% 절감과 평균 레이턴시 4.5ms의 경이로운 성능을 증명합니다.
