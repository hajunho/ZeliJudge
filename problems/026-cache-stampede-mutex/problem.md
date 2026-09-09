# [ZeliJudge #026] 캐시가 만료된 그 1초, DB가 폭발했다: 캐시 스탬피드(Cache Stampede)와 뮤텍스 방어

## 📌 문제 배경 스토리
쇼핑몰 '젤리마켓'의 백엔드 개발자 젤리는 메인 페이지의 '실시간 인기 상품 TOP 10' 조회의 성능을 높이기 위해 캐시(Redis)를 도입했습니다.
인기 상품 계산은 수백만 건의 주문 테이블을 `JOIN`하고 `GROUP BY`로 정렬해야 하는 매우 무거운 쿼리(소요 시간 50ms)였습니다.
젤리는 쿼리 결과를 캐시에 넣고 만료 시간(TTL)을 100ms로 설정했습니다:

```python
# [젤리가 작성한 단순 캐시 로직]
data = redis.get("popular_products")
if not data:
    # ❌ 캐시 미스 발생 시 누구나 DB로 달려감!
    data = db.query_heavy_popular_products()  # 50ms 소요
    redis.set("popular_products", data, ex=100)
return data
```

젤리는 뿌듯해하며 퇴근했습니다:
*"캐시 TTL이 100ms니까 99%의 요청은 캐시에서 0.1ms 만에 응답되겠지? DB는 완전 안전해!"*

하지만 세일 이벤트가 시작된 저녁, **데이터베이스 CPU가 100%로 치솟으며 커넥션 풀이 고갈되어 DB 서버가 영구 사망**했습니다!
1. 초당 수천 명의 사용자가 메인 페이지를 새로고침하고 있었습니다.
2. 캐시가 채워져 있는 동안에는 평화로웠으나, 정확히 **TTL이 만료된 바로 그 순간** 대참사가 터졌습니다:
3. 1번 사용자가 캐시가 없는 것을 보고 DB 쿼리를 시작했습니다 (이 쿼리는 50ms 동안 실행됩니다).
4. 문제는 **그 50ms 동안 도착한 수백 명의 다른 사용자들**이었습니다!
   - 아직 1번 사용자의 쿼리가 끝나지 않아 캐시는 여전히 텅 비어 있었습니다.
   - 뒤따라온 수백 명의 스레드가 일제히 *"어? 캐시 없네? 내가 DB 가서 계산해 와야지!"* 하고 동시에 무거운 DB 쿼리를 날렸습니다!
5. 수백 개의 무거운 `JOIN` 쿼리가 DB 엔진을 동시에 강타하면서 DB가 뻗어버리는 **캐시 스탬피드(Cache Stampede / Dogpiling)** 현상이 터진 것입니다!

CTO는 긴급 회의실에서 화이트보드를 두드리며 외쳤습니다:
*"젤리 씨! 캐시가 비었을 때 모두가 우르르 DB로 달려가면 캐시가 무슨 소용입니까!"*
*"캐시 미스가 발생했을 때는 **가장 먼저 온 딱 1개의 요청만 분산 락(Mutex Lock)을 획득하여 DB로 가고, 나머지 요청들은 락이 풀릴 때까지 잠시 대기(Singleflight)**하도록 만들어야 합니다!"*
*"첫 번째 요청이 50ms 뒤에 캐시를 채우고 락을 풀면, 대기하던 수백 명은 DB에 쿼리를 1번도 안 날리고 방금 채워진 캐시를 즉시 읽어서(Wait & Hit) 나갈 수 있다고요!"*

CTO는 캐시 스탬피드의 치명성을 검증하고 뮤텍스 기반 싱글플라이트 방어 효과를 입증하기 위해, **캐시 스탬피드 시뮬레이터**를 개발하라고 지시했습니다.

---

## ⚙️ 시스템 동작 규칙

### 1. 시스템 환경 설정 (`CONFIG TTL:<ttl_ms> QUERY_COST:<cost_ms>`)
- `TTL:<ttl_ms>`: 캐시 데이터가 유효하게 유지되는 시간 (밀리초, $1 \le ttl\_ms \le 10^9$)
- `QUERY_COST:<cost_ms>`: DB에서 무거운 쿼리를 실행하여 캐시를 채우는 데 소요되는 시간 (밀리초, $1 \le cost\_ms \le 10^9$)
- 시스템 시작 시점($t=0$) 이전에 캐시는 완전히 비어 있습니다.
- 쿼리가 $t_{start}$에 시작되면, 캐시는 $t_{ready} = t_{start} + cost\_ms$ 시점에 준비되며, 그 캐시의 유효 구간은 반열린구간 $[t_{ready}, t_{ready} + ttl\_ms)$ 입니다.  
  (즉 $t_{ready} \le t < t_{ready} + ttl\_ms$ 일 때 유효함)

---

### 2. 엔진별 동작 알고리즘

각 요청은 도착 시각 $t$ (밀리초) 오름차순으로 주어집니다: `REQ <t>`

#### A. NAIVE 엔진 (무방비 동시 DB 돌진)
- 현재 시각 $t$에 이미 계산이 완료되어 유효한 캐시가 존재하는지 확인합니다 ($t_{ready} \le t < t_{ready} + ttl\_ms$).
- **`HIT`**: 현재 시각 $t$에 유효한 캐시가 이미 준비되어 있다면, DB 쿼리 없이 즉시 완료됩니다.
- **`MISS_DB_QUERY`**: 현재 시각 $t$에 유효한 캐시가 없다면(아직 이전 쿼리가 진행 중이거나 만료됨):
  - 이 요청은 **즉시 새로운 DB 쿼리를 발송**합니다 (`naive_db_count += 1`).
  - 이 쿼리는 $t + cost\_ms$ 시점에 완료되어, $[t + cost\_ms, t + cost\_ms + ttl\_ms)$ 구간 동안 유효한 캐시를 생성합니다.
  - (주의: 쿼리가 진행 중인 $t \sim t + cost\_ms$ 사이에는 캐시가 아직 준비되지 않았으므로, 그 사이에 도착하는 모든 요청은 무조건 `MISS_DB_QUERY`가 됩니다!)

#### B. MUTEX 엔진 (싱글플라이트 락 방어)
- **`HIT`**: 현재 시각 $t$에 유효한 캐시가 존재한다면 즉시 히트 처리됩니다.
- 현재 유효한 캐시가 없는 경우:
  - **`LOCK_DB_QUERY`**: 현재 아무도 락을 잡고 있지 않다면:
    - 이 요청이 **뮤텍스 락을 획득**하고 유일하게 DB 쿼리를 실행합니다 (`mutex_db_count += 1`).
    - 락은 $t + cost\_ms$까지 유지되며, 완료되는 순간 $[t + cost\_ms, t + cost\_ms + ttl\_ms)$ 동안 유효한 캐시가 채워지고 락이 해제됩니다.
  - **`WAIT_HIT`**: 이미 다른 선행 요청이 락을 쥐고 쿼리를 수행 중이라면:
    - 이 요청은 **DB 쿼리를 절대 날리지 않고**, 선행 요청의 쿼리가 완료될 때까지 대기하다가 채워진 캐시를 읽고 완료됩니다.

---

## 📥 입력 형식 (Input)

- 첫째 줄에 캐시와 DB 쿼리 설정이 주어집니다:
  `CONFIG TTL:<ttl_ms> QUERY_COST:<cost_ms>`
- 둘째 줄에 총 요청의 개수 $Q$가 주어집니다. ($1 \le Q \le 100,000$)
- 셋째 줄부터 $Q$개의 줄에 걸쳐 각 요청의 도착 시각 $t$가 주어집니다:
  `REQ <t>` ($0 \le t \le 10^{12}$, $t$는 이전 요청 이상으로 단조 증가)

---

## 📤 출력 형식 (Output)

- 각 요청에 대해 두 엔진의 처리 결과를 한 줄씩 출력합니다:
  `REQ <t> NAIVE:<naive_res> MUTEX:<mutex_res>`
  - `<naive_res>`: `HIT` 또는 `MISS_DB_QUERY`
  - `<mutex_res>`: `HIT`, `LOCK_DB_QUERY`, 또는 `WAIT_HIT`
- 모든 요청이 끝난 후 마지막 줄에 종합 통계를 출력합니다:
  `SUMMARY TOTAL:<Q> NAIVE_DB:<naive_db> MUTEX_DB:<mutex_db> DB_SAVED:<saved>`
  - `<saved>`: 뮤텍스 락 덕분에 절약된 DB 쿼리 수 (`naive_db - mutex_db`).

---

## 💡 입출력 예시 (Example)

### 예시 입력 1
```text
CONFIG TTL:100 QUERY_COST:50
6
REQ 0
REQ 10
REQ 20
REQ 60
REQ 149
REQ 150
```

### 예시 출력 1
```text
REQ 0 NAIVE:MISS_DB_QUERY MUTEX:LOCK_DB_QUERY
REQ 10 NAIVE:MISS_DB_QUERY MUTEX:WAIT_HIT
REQ 20 NAIVE:MISS_DB_QUERY MUTEX:WAIT_HIT
REQ 60 NAIVE:HIT MUTEX:HIT
REQ 149 NAIVE:HIT MUTEX:HIT
REQ 150 NAIVE:MISS_DB_QUERY MUTEX:LOCK_DB_QUERY
SUMMARY TOTAL:6 NAIVE_DB:4 MUTEX_DB:2 DB_SAVED:2
```

### 예시 설명 1
- $t=0$: 캐시가 없으므로 NAIVE는 쿼리 발송, MUTEX는 락을 잡고 쿼리 시작. ($t=50$에 쿼리 완료되어 $50 \le t < 150$ 동안 유효한 캐시 생성 예정)
- $t=10, 20$: 아직 $t=50$ 이전이므로 캐시가 미완성 상태입니다.
  - NAIVE: 캐시가 없으므로 둘 다 각각 DB 쿼리를 중복 발송하여 총 3회 폭발!
  - MUTEX: 이미 $t=0$ 요청이 락을 쥐고 쿼리 중이므로 대기(`WAIT_HIT`)하여 DB 쿼리 0회!
- $t=60$: $t=50$에 캐시 생성이 완료되어 $150$ 미만까지 유효하므로 두 엔진 모두 `HIT`!
- $t=149$: $149 < 150$이므로 여전히 캐시 유효 (`HIT`)!
- $t=150$: $t \ge 150$이 되어 캐시가 정확히 만료되었으므로 다시 새로운 쿼리 발송!
