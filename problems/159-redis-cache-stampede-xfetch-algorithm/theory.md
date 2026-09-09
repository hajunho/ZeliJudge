# 캐시 스탬피드(Cache Stampede / Dogpile Effect)와 확률적 조기 재계산 XFetch 알고리즘

## 1. 개요 및 실무 장애 시나리오: "핫딜 캐시 만료 1초 만에 왜 DB CPU가 100% 찍고 서버가 뻗어요?!"

글로벌 이커머스/라이브커머스 플랫폼 '젤리마켓'의 백엔드 엔지니어 태호는 홈 화면 상단에 노출되는 '실시간 핫딜 특가 상품' 정보를 Redis에 캐싱하여 서비스하고 있었습니다.

이 데이터는 여러 테이블(상품, 쿠폰, 실시간 재고, 셀러 정보)을 JOIN하고 할인율을 계산해야 하므로 DB 쿼리 연산에 약 **200ms**의 무거운 연산 비용이 소요됩니다. 태호는 데이터 신선도를 위해 Redis TTL을 **60초(1분)**로 설정했습니다:

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

이것이 바로 고트래픽 대규모 시스템에서 가장 빈번하게 발생하는 대참사인 **'캐시 스탬피드(Cache Stampede)'**, 일명 **'도그파일 효과(Dogpile Effect)'**입니다!

---

## 2. 기존 해결책들의 한계

### (1) 분산 뮤텍스 락 (Mutex Lock / SETNX)
* 캐시 미스가 났을 때 Redis `SETNX`로 분산 락을 획득한 1개 스레드만 DB에 접근하고, 나머지는 락이 풀릴 때까지 대기(Wait)하게 하는 방식.
* **한계**: DB 과부하는 막을 수 있지만, 락을 얻지 못한 수천 명의 사용자가 200ms ~ 1,000ms 동안 블로킹 대기(Latency Spike)를 겪게 되며, 락 획득 타임아웃 시 서비스 장애가 전파됩니다.

### (2) 백그라운드 주기적 갱신 (Cron / Scheduler)
* 캐시를 만료시키지 않고 백그라운드 크론 작업이 주기적으로 DB를 읽어 캐시를 갱신하는 방식.
* **한계**: 핫딜 키가 수만 개, 수십만 개로 늘어나면 어떤 키가 인기 키인지 알 수 없고, 아무도 보지 않는 키까지 갱신하느라 DB 리소스가 낭비됩니다.

---

## 3. 궁극의 구원자: VLDB 최우수 논문의 XFetch 알고리즘

2015년 세계 최고 권위의 데이터베이스 학회 VLDB에서 발표된 논문 *"Optimal Probabilistic Cache Stampede Prevention"* (Vattani et al.)은 이 문제를 수학적으로 완전히 해결하는 **확률적 조기 재계산(Probabilistic Early Expiration) 알고리즘 'XFetch'**를 발표했습니다.

```
[XFetch 알고리즘의 동작 타임라인]

TTL 만료 시각: t = 60.000초
DB 연산 비용(delta): 200ms

t=0s                t=59.800s          t=60.000s
────────────────────────┬──────────────────┬──────────────> Time
     캐시 히트 (99%)    │ 확률적 조기 당첨!│ (물리적 만료 시점)
                        ▼                  │
                [XFetch 조건 충족!]        │
                - 현재 캐시 값 즉시 반환!  │
                  (사용자 지연 1ms)       │
                - 백그라운드에서 DB 쿼리  │
                  비동기 실행 시작!       │
                        │                  │
                        ▼ t=60.000s        ▼
                [새 캐시 갱신 완료!]       이미 캐시가 최신화되어
                                           캐시 미스 0건! 락 대기 0초!
```

### (1) XFetch의 확률적 조기 재계산 공식
클라이언트가 캐시를 읽을 때, 캐시가 아직 물리적으로 유효하더라도 다음 확률적 조건이 참(True)이면 **만료 전에 미리 비동기로 캐시를 재계산**합니다:

$$-eta 	imes \delta 	imes \ln(U) > (	ext{expiry} - 	ext{now})$$

* $U$: $0$과 $1$ 사이의 균등 난수 ($U \sim 	ext{Uniform}(0, 1)$).
* $\delta$ (**delta**): 이전 갱신 시 DB 쿼리 및 연산에 걸렸던 시간(ms).
* $eta$ (**beta**): 공격성 계수 ($eta > 0$, 기본값 $1.0$). $eta$가 클수록 만료 시점보다 더 일찍 재계산을 시도함.
* $	ext{expiry} - 	ext{now}$: 물리적 만료까지 남은 잔여 시간(ms).

### (2) 수학적 원리: 왜 완벽하게 1개 요청만 당첨되는가?
* $\ln(U)$는 $U \in (0, 1)$에서 항상 음수이므로, $-eta 	imes \delta 	imes \ln(U)$는 항상 양수입니다.
* 만료까지 시간이 많이 남았을 때($	ext{expiry} - 	ext{now} \gg 0$):
  - 우변이 매우 크므로, $U$가 극단적으로 0에 가깝지 않은 이상 부등식은 거의 항상 `False`입니다.
* **만료가 임박할수록($	ext{expiry} - 	ext{now} 	o 0$)**:
  - 우변이 0에 수렴하므로, 부등식이 `True`가 될 확률이 지수함수적으로 급증합니다!
* 결과적으로 **만료 직전(예: 만료 100~200ms 전)에 캐시를 조회한 수천 개의 요청 중 딱 1개(또는 극소수)가 통계적으로 당첨**되어 백그라운드 갱신을 시작합니다!
* 당첨된 요청조차도 사용자에게는 **현재 캐시 값을 즉시 반환(지연 1ms)**하므로 사용자는 단 1밀리초도 기다리지 않습니다(Stale-While-Revalidate).
* 물리적 만료 시점($t = 60.000$초)이 되었을 때는 이미 백그라운드 갱신이 완료되어 새 캐시가 세팅되어 있으므로, **캐시 미스는 영구히 0건**이 됩니다!

---

## 4. 캐시 전략 3종 비교 매트릭스

| 비교 항목 | Naive (일반 만료) | Mutex Lock (SETNX 분산 락) | XFetch (확률적 조기 재계산) |
|:---|:---:|:---:|:---:|
| **캐시 미스 시 DB 부하** | 수천 건 동시 폭격 (100% 다운) | **1건 (DB 보호)** | **1건 (DB 보호)** |
| **사용자 체감 지연시간** | 수초 대기 / 503 타임아웃 | **수백 ms 대기 (락 병목)** | **항상 1ms (Zero Latency!)** |
| **락 경합 / 데드락 위험** | 없음 (대신 DB 폭사) | 높음 (락 획득 타임아웃) | **완전 0 (락 자체가 불필요)** |
| **구현 복잡도** | 매우 낮음 | 중간 (Redis 분산 락) | **낮음 (단순 확률 수식 1줄)** |
| **실무 권장도** | 절대 금지 (대규모 환경) | 트래픽 낮은 배치성 키 | **고트래픽 핫키 1순위 표준** |

---

## 5. 실무 구현 가이드 (Redis + Java/Python)

Redis에는 값(value)과 함께 **계산 소요 시간($\delta$)** 및 **논리적 만료 시각($	ext{expiry}$)**을 JSON으로 함께 저장합니다:

```json
{
  "value": { "productId": 101, "name": "에어팟 프로 핫딜", "price": 199000 },
  "delta_ms": 185,
  "expiry_ms": 1725894100000
}
```

```java
public String getWithXFetch(String key, double beta) {
    CacheEntry entry = redis.get(key);
    long now = System.currentTimeMillis();

    // XFetch 확률 부등식 검사
    double u = ThreadLocalRandom.current().nextDouble();
    if (-beta * entry.getDeltaMs() * Math.log(u) > (entry.getExpiryMs() - now)) {
        // 조기 갱신 당첨! 백그라운드 비동기 갱신 트리거
        asyncExecutor.submit(() -> recomputeAndSave(key));
    }

    // 사용자는 대기 0초! 현재 캐시 즉시 반환
    return entry.getValue();
}
```
