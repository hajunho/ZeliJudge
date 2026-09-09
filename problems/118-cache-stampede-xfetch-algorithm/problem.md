# 118. 캐시를 걸었는데 왜 1초 만에 10만 명이 몰려와 DB가 폭사해요?!: 캐시 스탬피드(Cache Stampede / Dogpiling)와 뮤텍스 락 vs 확률적 조기 갱신(XFetch / PER Algorithm)

## 문제 설명

인기 온라인 쇼핑몰의 메인 상품 페이지를 빠르게 서빙하기 위해, 고성능 인메모리 저장소(Redis)에 캐시를 걸어두었습니다.  
TTL(Time-to-Live)을 60초로 설정해 둔 덕분에, 평소에는 초당 1만 건의 요청이 들어와도 원본 데이터베이스(DB) CPU 점유율은 5% 미만으로 평화로웠습니다.

그러나 60초가 지난 바로 그 찰나! **대참사**가 발생했습니다. 💥  
캐시 키가 만료된 1초 사이에 몰려든 **수천~수만 명의 동시 요청**이 일제히 Cache Miss 판정을 마주했습니다.  
그리고 모든 클라이언트가 약속이라도 한 듯:
> *"어? 캐시에 없네?! 내가 DB에서 직접 조회해서 캐시 채워 넣을게!"*

수만 개의 무거운 DB 쿼리가 원본 데이터베이스에 동시에 융단폭격처럼 쏟아졌고, 데이터베이스 커넥션 풀이 즉시 고갈되며 DB CPU가 100%를 찍고 폭사했습니다.  
이 현상을 컴퓨터 과학에서는 **캐시 스탬피드 (Cache Stampede, 또는 Dogpiling / Thundering Herd)**라고 부릅니다.

---

### 어떻게 해결할 것인가? 3대 방어 전략

1. **단순 방치 (`NAIVE`)**:
   - 캐시가 만료되면 모든 요청이 각자 DB를 조회하여 캐시를 갱신합니다.
   - 핫 키(Hot Key)가 만료되는 순간 동시 요청 수만큼 DB 쿼리가 폭발하여 전사 마비가 일어납니다.

2. **상호배제 락 (`MUTEX_LOCK`, Single-Flight / Distributed Lock)**:
   - 캐시가 만료되었을 때, 분산 락을 획득한 **단 1개의 요청만** DB를 조회하여 캐시를 갱신합니다.
   - 나머지 요청들은 락 획득에 실패하여 대기(Wait, 약 50ms)한 뒤, 갱신된 캐시를 읽습니다.
   - DB 쿼리는 1회로 극적으로 억제되지만, 락을 기다려야 하는 클라이언트들에게 **50ms의 응답 지연(Latency Spike)**이 발생합니다.

3. **XFetch 확률적 조기 갱신 (`XFETCH`, Probabilistic Early Expiration)**:
   - 2015년 VLDB 학술 논문(Vattani et al.)에서 발표되어 Redis 공식 문서에서 권고하는 최첨단 표준 해법입니다.
   - 캐시가 완전히 죽고 난 뒤 수습하는 것이 아니라, **캐시가 살아있는 동안 만료 시점에 가까워질수록 확률적으로 누군가가 백그라운드에서 미리 갱신**합니다!
   - **XFetch 판정 공식**:
     $$-	ext{compute\_ms} 	imes eta 	imes \ln(R) > (	ext{expiry} - 	ext{now}) 	imes 1000$$
     - $	ext{compute\_ms}$: 해당 데이터를 DB에서 계산/조회하는 데 걸린 시간 (ms)
     - $eta$: 조기 갱신 민감도 계수 ($eta > 0$, 기본값 1.0)
     - $R$: 0 초과 1 이하의 난수 ($R \in (0, 1]$)
     - $	ext{expiry} - 	ext{now}$: 캐시 만료까지 남은 시간 ($\delta$, 초)
   - 만료 직전($\delta 	o 0$)에 가까워질수록 조건이 참이 될 확률이 올라가며, 지나가던 단 한두 개의 요청이 비동기 조기 갱신(`XFETCH_EARLY_REFRESH`)을 발생시켜 캐시를 연장합니다.
   - **놀라운 결과**: 정작 사용자는 기다림 없이(지연시간 0ms) 기존 캐시를 즉시 돌려받고, 캐시가 비어있는 순간 자체가 영구히 소멸하여 스탬피드를 100% 방지합니다!

---

## 입력 형식

표준 입력(stdin)으로 한 줄에 하나씩 다음 명령어들이 주어집니다:

1. `CONFIG strategy=<NAIVE|MUTEX_LOCK|XFETCH> beta=<float> compute_ms=<int>`
   - 캐시 전략을 설정합니다.
   - 출력: `OK strategy=<strategy> beta=<beta:.2f> compute_ms=<compute_ms>`

2. `SET_CACHE key=<str> val=<str> ttl=<int> compute_ms=<int> now=<float>`
   - 시각 `now`에 캐시에 데이터를 저장합니다. (`expiry = now + ttl`)
   - 출력: `CACHE_STORED key=<key> val=<val> expiry=<expiry:.1f> compute_ms=<compute_ms>`

3. `GET key=<str> now=<float> rand=<float>`
   - 시각 `now`에 `key`를 조회합니다. (`rand`는 XFetch 판정용 난수, 기본 0.5)
   - 키가 처음 로딩되는 경우:  
     `RESULT key=<key> val=db_<key> action=INITIAL_LOAD_DB latency_ms=<compute_ms>`
   - **`NAIVE` 모드**:
     - 만료 시: `RESULT key=<key> val=<val> action=CACHE_MISS_DB_QUERY latency_ms=<compute_ms>`
     - 적중 시: `RESULT key=<key> val=<val> action=CACHE_HIT latency_ms=0`
   - **`MUTEX_LOCK` 모드**:
     - 만료 시 락 획득: `RESULT key=<key> val=<val> action=MUTEX_ACQUIRED_DB_QUERY latency_ms=<compute_ms>`
     - 만료 시 락 대기: `RESULT key=<key> val=<val> action=MUTEX_WAIT_HIT latency_ms=50`
     - 적중 시: `RESULT key=<key> val=<val> action=CACHE_HIT latency_ms=0`
   - **`XFETCH` 모드**:
     - 조기 갱신 트리거 시: `RESULT key=<key> val=<val> action=XFETCH_EARLY_REFRESH latency_ms=0` (캐시 수명 연장!)
     - 적중 시: `RESULT key=<key> val=<val> action=CACHE_HIT latency_ms=0`

4. `STATS`
   - 누적 통계를 출력합니다:  
     `STATS cache_hits=<hits> db_queries=<queries> early_refreshes=<refreshes> lock_waits=<waits>`

5. `RESET`
   - 캐시, 락, 통계를 모두 초기화하고 `NAIVE` 기본값으로 복귀합니다.
   - 출력: `OK strategy=NAIVE beta=1.00 compute_ms=100`

---

## 출력 형식

각 명령어를 수행한 결과를 한 줄씩 표준 출력(stdout)으로 출력합니다.

---

## 예제 입력 1 (Naive 모드: 캐시 스탬피드 참사)

```text
CONFIG strategy=NAIVE beta=1.0 compute_ms=150
SET_CACHE key=hot_item val=concert_ticket ttl=60 compute_ms=150 now=0
GET key=hot_item now=60
GET key=hot_item now=60
GET key=hot_item now=60
STATS
```

## 예제 출력 1

```text
OK strategy=NAIVE beta=1.00 compute_ms=150
CACHE_STORED key=hot_item val=concert_ticket expiry=60.0 compute_ms=150
RESULT key=hot_item val=concert_ticket action=CACHE_MISS_DB_QUERY latency_ms=150
RESULT key=hot_item val=concert_ticket action=CACHE_MISS_DB_QUERY latency_ms=150
RESULT key=hot_item val=concert_ticket action=CACHE_MISS_DB_QUERY latency_ms=150
STATS cache_hits=0 db_queries=3 early_refreshes=0 lock_waits=0
```

---

## 예제 입력 2 (XFetch 모드: 확률적 조기 갱신과 스탬피드 소멸)

```text
CONFIG strategy=XFETCH beta=1.0 compute_ms=200
SET_CACHE key=hot_item val=concert_ticket ttl=60 compute_ms=200 now=0
GET key=hot_item now=50 rand=0.5
GET key=hot_item now=59.8 rand=0.3
GET key=hot_item now=60.0 rand=0.5
STATS
```

## 예제 출력 2

```text
OK strategy=XFETCH beta=1.00 compute_ms=200
CACHE_STORED key=hot_item val=concert_ticket expiry=60.0 compute_ms=200
RESULT key=hot_item val=concert_ticket action=CACHE_HIT latency_ms=0
RESULT key=hot_item val=concert_ticket action=XFETCH_EARLY_REFRESH latency_ms=0
RESULT key=hot_item val=concert_ticket action=CACHE_HIT latency_ms=0
STATS cache_hits=3 db_queries=1 early_refreshes=1 lock_waits=0
```

> **설명**:  
> `now=59.8`에 도착한 요청에서 XFetch 조건이 만족되어, 지연시간 0ms로 기존 캐시를 즉시 돌려주면서 백그라운드에서 캐시 만료 시점을 $59.8 + 60 = 119.8$초로 미리 연장했습니다.  
> 그 덕분에 원래 만료 시점이었던 `now=60.0`에 도착한 후속 요청도 DB 조회 없이 부드럽게 캐시 적중(`CACHE_HIT latency_ms=0`)되었습니다!\n