# #159 핫딜 상품 캐시 만료되는 순간 왜 DB CPU가 100% 찍고 서버가 타버려요?!: 캐시 스탬피드(Cache Stampede / Dogpile Effect)와 확률적 조기 재계산 XFetch 알고리즘 (Cache Stampede & Probabilistic Early Expiration XFetch Algorithm)

## 1. 실무 장애 시나리오: "핫딜 캐시 만료 1초 만에 왜 DB CPU가 100% 찍고 서버가 뻗어요?!"

글로벌 이커머스/라이브쇼핑 플랫폼 '젤리마켓'의 백엔드 엔지니어 태호는 홈 화면 상단에 노출되는 '실시간 핫딜 특가 상품' 정보를 Redis에 캐싱하여 서비스하고 있었습니다.

이 데이터는 여러 테이블(상품, 쿠폰, 실시간 재고, 셀러 정보)을 무겁게 JOIN하고 할인율을 실시간 계산해야 하므로 DB 쿼리 연산에 약 **200ms**의 시간이 소요됩니다. 태호는 데이터 신선도를 위해 Redis TTL을 **60초(1분)**로 설정했습니다:

```java
// [일반적인 캐시-어사이드 패턴 (Naive Cache-Aside)]
public ProductDetail getHotDealProduct(Long productId) {
    String cacheKey = "product:hotdeal:" + productId;
    ProductDetail cached = redisTemplate.opsForValue().get(cacheKey);
    if (cached != null) {
        return cached; // 1ms 초고속 캐시 히트
    }

    // 캐시 미스! DB 조회 후 60초 TTL로 캐시 저장
    ProductDetail product = productRepository.fetchWithHeavyJoins(productId); // 200ms 소요!
    redisTemplate.opsForValue().set(cacheKey, product, 60, TimeUnit.SECONDS);
    return product;
}
```

평상시에는 캐시 히트율 99.9%를 유지하며 평화로웠습니다.  
하지만 동시 접속자가 10만 명이 몰린 '블랙 프라이데이 핫딜 오픈' 직후, **정확히 60초 주기로 DB가 폭사하는 기괴한 지옥**이 펼쳐졌습니다:

1. 핫딜 캐시가 생성된 지 정확히 60초가 지난 $t = 60.000$초, Redis의 TTL이 만료되어 키가 증발(Eviction)했습니다.
2. 바로 그 찰나(1초 미만)에 홈 화면을 보고 있던 **수천 명의 사용자가 동시에 캐시 미스(Cache Miss)**를 냈습니다!
3. 수천 개의 스레드가 일제히 `fetchWithHeavyJoins()`를 호출하며 데이터베이스로 무차별 쿼리 폭격을 쏟아부었습니다.
4. DB의 동시 커넥션 풀(Connection Pool)이 순식간에 100% 고갈되었고, CPU 점유율은 100%로 치솟았습니다.
5. 쿼리 응답 지연시간이 200ms에서 5초, 10초로 폭증하더니, 결국 `503 Service Unavailable` 에러와 함께 DB 서버가 완전히 뻗어버렸습니다!

긴급 소집된 데이터 아키텍트 민우 님이 화이트보드에 캐시 만료 타임라인을 그리며 원인을 설명해주었습니다:

> "태호 님! 이것이 바로 대규모 분산 캐시 시스템의 가장 치명적인 함정인 **'캐시 스탬피드(Cache Stampede / Dogpile Effect)'**입니다!  
> 캐시가 만료된 그 순간에 유입된 수천 개의 요청이 동시에 DB로 쏟아져 DB를 질식사시키는 것이죠!  
> 분산 락(Mutex Lock)을 걸면 DB는 살릴 수 있지만, 락을 얻지 못한 수천 명의 사용자가 200ms 이상 멈추는 지연시간 스파이크(Latency Spike)를 겪게 됩니다!  
> 이 문제를 완벽하게 해결하려면, VLDB 논문에서 검증된 **'확률적 조기 재계산(Probabilistic Early Expiration) XFetch 알고리즘'**을 도입해야 합니다!  
> 캐시가 실제로 만료되기 직전, 만료 임박 확률 공식($-\beta \times \delta \times \ln(U) > \text{expiry} - t$)을 검사하여 **수천 명 중 딱 1명만 조기 당첨**되어 백그라운드에서 캐시를 갱신하게 만듭니다!  
> 당첨된 사용자도 현재 캐시를 즉시 반환(1ms)받고, 물리적 만료 시점이 되었을 때는 이미 캐시가 최신화되어 있으므로 **캐시 미스 0건, 락 대기 0초, DB 부하 1건으로 100% 무중단 서비스**가 가능해집니다!"

태호는 민우 님의 조언에 따라 캐시 스탬피드 시뮬레이터를 구축하여, Naive, Mutex Lock, XFetch 세 가지 전략의 캐시 히트율, DB 쿼리 수, 과부하 에러, 그리고 응답 지연시간을 정밀 검증하기로 결심했습니다.

---

## 2. 핵심 이론: XFetch 확률적 조기 재계산 알고리즘

```
[Naive: 만료 즉시 수천 개 쿼리 폭격 (Cache Stampede)]
t=60s (만료): [REQ 1] ──> DB 쿼리 #1
              [REQ 2] ──> DB 쿼리 #2  ===> DB CPU 100% 포화 & 503 폭사!
              [REQ 3] ──> DB 쿼리 #3

[Mutex Lock: 1명만 DB 쿼리, 나머지는 락 대기]
t=60s (만료): [REQ 1] ──> 락 획득 ──> DB 쿼리 (200ms 소요)
              [REQ 2] ──> 락 대기 (200ms 지연 스파이크)
              [REQ 3] ──> 락 대기 (200ms 지연 스파이크)

[XFetch: 만료 전 확률적 1명 조기 비동기 갱신]
t=59.85s:     [REQ 1] ──> 확률 조건 충족! (조기 당첨)
                          - 기존 캐시 즉시 반환 (지연 1ms)
                          - 백그라운드에서 DB 쿼리 1건 실행
              [REQ 2] ──> 기존 캐시 즉시 반환 (지연 1ms)
t=60.05s:     새 캐시 갱신 완료! (캐시 미스 0건, 락 대기 0초!)
```

### XFetch 공식
$$\text{Recompute Condition: } -\beta \times \delta \times \ln(U) > (\text{expiry} - t)$$

* $U \in (0, 1)$: 균등 분포 난수
* $\delta$ (`compute_cost_ms`): DB 쿼리/연산에 소요되는 시간 (ms)
* $\beta$ (`beta`): 조기 갱신 적극성 계수 ($\beta > 0$, 기본값 1.0)
* $\text{expiry} - t$: 캐시 만료까지 남은 잔여 시간 (ms)

---

## 3. 문제 요구사항

입력으로 주어지는 캐시 전략(`strategy`: `"NAIVE"`, `"MUTEX_LOCK"`, `"XFETCH"`), 초기 TTL(`initial_ttl_ms`), DB 연산 비용(`compute_cost_ms`), $\beta$ 계수(`beta`), DB 동시 수용 용량(`db_capacity`), 요청 목록(`requests`)을 바탕으로 시뮬레이션을 수행하고, 종합 메트릭 및 요청별 응답 결과를 JSON 형식으로 출력하는 프로그램을 작성하세요.

### 상세 규칙
1. **캐시 상태 관리**:
   * 초기 캐시: `available_from = 0`, `expiry = initial_ttl_ms`, `value = "VALUE_V1"`, `delta = compute_cost_ms`.
   * DB 쿼리 완료 시점(`finish_t = t + compute_cost_ms`)에 새 버전(`VALUE_V2`, `VALUE_V3`...) 및 새 만료 시각이 활성화됨.
2. **전략별 동작 ($t$ 시점)**:
   * **NAIVE**:
     - 캐시 유효($t < \text{expiry}$): 캐시 히트 (지연 1ms).
     - 캐시 만료($t \ge \text{expiry}$): 캐시 미스!
       - 현재 실행 중인 DB 쿼리 수 + 1이 `db_capacity`를 초과하면: `DB_OVERLOAD_503` 에러 발생 (지연 5,000ms, 값 null).
       - 초과하지 않으면: DB 쿼리 실행 (지연 `compute_cost_ms`).
   * **MUTEX_LOCK**:
     - 캐시 유효($t < \text{expiry}$): 캐시 히트 (지연 1ms).
     - 캐시 만료($t \ge \text{expiry}$):
       - 락 미점유 시: 락 획득 후 DB 쿼리 실행 (지연 `compute_cost_ms`, 락 해제 시점은 $t + \text{compute\_cost\_ms}$).
       - 락 점유 중일 시: 락 해제 시점까지 대기 (지연시간 = $\text{locked\_until} - t$).
   * **XFETCH**:
     - 캐시 유효($t < \text{expiry}$):
       - $-\beta \times \delta \times \ln(u) > (\text{expiry} - t)$ 검사.
       - 조건 참이고 현재 백그라운드 쿼리가 진행 중이지 않다면:
         조기 재계산 트리거! 백그라운드 DB 쿼리 1건 실행, 사용자에게는 현재 캐시 즉시 반환 (`status = "XFETCH_EARLY_RECOMPUTE"`, 지연 1ms, `cache_hits += 1`).
       - 조건 거짓 또는 이미 쿼리 진행 중: 일반 캐시 히트 (지연 1ms).
     - 백그라운드 쿼리 진행 중 만료 시각이 경과한 경우:
       - Stale-While-Revalidate 패턴에 따라 현재 캐시를 계속 제공 (`status = "CACHE_HIT_STALE_REVALIDATING"`, 지연 1ms, `cache_hits += 1`).
     - 캐시 완전 만료 시(폴백): 캐시 미스 및 DB 쿼리 실행.

---

## 4. 입력 및 출력 형식

### 입력 형식 (Standard Input - JSON)
```json
{
  "strategy": "XFETCH",
  "initial_ttl_ms": 60000,
  "compute_cost_ms": 200,
  "beta": 1.0,
  "db_capacity": 5,
  "requests": [
    {"req_id": "PRE_1", "time_ms": 59850, "random_val": 0.03},
    {"req_id": "BURST_1", "time_ms": 60005, "random_val": 0.5}
  ]
}
```

### 출력 형식 (Standard Output - JSON)
```json
{
  "strategy": "XFETCH",
  "metrics": {
    "total_requests": 2,
    "cache_hits": 2,
    "cache_misses": 0,
    "early_recomputations": 1,
    "db_queries_total": 1,
    "max_concurrent_db_queries": 0,
    "db_overload_errors": 0,
    "avg_latency_ms": 1.0,
    "max_latency_ms": 1
  },
  "requests": [
    {
      "req_id": "PRE_1",
      "status": "XFETCH_EARLY_RECOMPUTE",
      "served_value": "VALUE_V1",
      "latency_ms": 1
    },
    {
      "req_id": "BURST_1",
      "status": "CACHE_HIT_STALE_REVALIDATING",
      "served_value": "VALUE_V1",
      "latency_ms": 1
    }
  ],
  "diagnosis": "OPTIMAL: XFetch probabilistic early expiration eliminated cache stampede! Cache hits 2/2, early recomputations 1, 0 DB overloads, avg latency 1.0ms."
}
```
