# [컴퓨터 과학 이론 백서] 캐시 관통(Cache Penetration)과 블룸 필터(Bloom Filter)의 수학적 원리

## 1. 캐시 관통(Cache Penetration)의 메커니즘과 파괴성

### 1.1 Cache-Aside 패턴의 취약점
현대 분산 시스템의 95% 이상은 **Cache-Aside(또는 Look-Aside)** 캐싱 패턴을 사용합니다:
```python
def get_user(user_id):
    # 1. Redis 캐시 확인
    cached = redis.get(f"user:{user_id}")
    if cached is not None:
        return cached
        
    # 2. 캐시 미스 시 DB 쿼리
    user = db.query("SELECT * FROM users WHERE id = %s", user_id)
    
    # 3. DB에 있으면 캐시에 저장
    if user is not None:
        redis.set(f"user:{user_id}", user, ttl=3600)
        
    return user
```
이 코드는 평상시에는 훌륭하게 작동하지만, **"DB에도 없는 무효한 키"**가 들어오는 순간 치명적인 설계 결함이 드러납니다:
1. `user_id = -1` 요청이 들어옴.
2. Redis에 없음 (`None`).
3. DB 조회 $\to$ 결과 없음 (`None`).
4. `user is None`이므로 **Redis에 아무것도 저장하지 않음!**
5. 다음번에 또 `user_id = -1`이 들어오면? **또다시 1~4번을 반복하며 DB를 타격!**

악의적인 공격자나 잘못 짜인 웹 크롤러가 초당 10,000건의 무작위 ID를 요청하면, **Redis 캐시의 적중률(Hit Ratio)은 0%로 추락하고 모든 트래픽이 고스란히 RDBMS의 인덱스 탐색으로 직격**합니다. 그 결과 DB Connection Pool 고갈, CPU 100%, 전체 서비스의 504 Gateway Timeout 참사로 이어집니다.

---

## 2. 블룸 필터 (Bloom Filter)의 수학적 원리와 위양성 제어

1970년 버튼 하워드 블룸(Burton Howard Bloom)이 제안한 **블룸 필터**는 어떤 원소가 집합에 속해 있는지 여부를 검사하는 공간 효율적인 **확률적 자료구조(Probabilistic Data Structure)**입니다.

### 2.1 핵심 수학적 특성
- **False Negative = 0 (100% 보장)**:
  - "집합에 원소가 존재하지 않는다(Negative)"고 판정한 경우, 그 원소는 **절대로 100% 집합에 존재하지 않습니다**.
  - 따라서 블룸 필터가 거부한 요청은 DB나 캐시를 조회할 필요가 전혀 없습니다!
- **False Positive > 0 (위양성 가능성 존재)**:
  - "집합에 원소가 존재한다(Positive)"고 판정한 경우, 우연히 다른 원소들의 해시 비트들이 겹쳐서 `1`로 채워진 것일 수 있으므로 **"실제로는 없을 수도 있습니다"**.

### 2.2 위양성 확률 (False Positive Probability, $p$)
$M$비트 크기의 비트 배열에 $N$개의 원소를 $K$개의 독립적인 균등 해시 함수로 삽입했을 때, 특정 비트가 0으로 남아있을 확률은:
$$P(\text{bit} = 0) = \left( 1 - \frac{1}{M} \right)^{KN} \approx e^{-\frac{KN}{M}}$$
따라서 어떤 원소가 집합에 없는데도 모든 $K$개 비트가 1로 채워져 있을 위양성 확률 $p$는 다음과 같습니다:
$$p \approx \left( 1 - e^{-\frac{KN}{M}} \right)^K$$

### 2.3 최적의 해시 함수 개수 ($K$)와 비트 크기 ($M$)
주어진 원소 수 $N$과 목표 위양성 확률 $p$ (예: $1\% = 0.01$)에 대해, 필요한 최적 비트 수 $M$과 해시 함수 개수 $K$는 미분을 통해 유도됩니다:
$$M = -\frac{N \ln p}{(\ln 2)^2} \approx -1.44 \cdot N \log_2 p$$
$$K = \frac{M}{N} \ln 2 \approx 0.693 \cdot \frac{M}{N}$$

> **실무 기준 수치**:
> $1\%$ ($p=0.01$)의 위양성 확률을 얻으려면 **원소 1개당 단 9.6비트($\approx 1.2\text{ Byte}$)**와 **$K=7$개의 해시 함수**만 있으면 충분합니다!
> 1,000만 개의 회원 ID를 필터링하는 데 단 **12MB**의 메모리만으로 99%의 악의적인 캐시 관통 공격을 DB 앞단에서 완벽하게 차단할 수 있습니다.

---

## 3. 프로덕션 아키텍처 구현 전략

실무 대규모 분산 아키텍처에서는 다음과 같은 2계층 방어벽을 구축합니다:

```
[클라이언트 요청]
       │
       ▼
┌───────────────────────────────┐
│  API Gateway / 로컬 메모리    │
│  Guava / RedisBloom 필터      │  ──(Negative: 100% 없음)──> [ 즉시 404 반환 ] (DB/캐시 접근 0%)
└───────────────────────────────┘
       │ (Positive: 있을 수도 있음)
       ▼
┌───────────────────────────────┐
│  Redis Distributed Cache      │  ──(Cache Hit)────────────> [ 캐시 데이터 응답 ]
└───────────────────────────────┘
       │ (Cache Miss)
       ▼
┌───────────────────────────────┐
│  RDBMS Master / Replica       │  ──(DB Hit)───────────────> [ 캐시 적재 후 200 응답 ]
└───────────────────────────────┘
       │ (False Positive로 인한 DB Miss)
       ▼
   [ Null 값 단기 TTL(30s) 캐싱 후 404 응답 ]
```

1. **블룸 필터가 1차 방어**: 무효한 ID의 99% 이상을 API 서버 인메모리 또는 RedisBloom 모듈에서 0.001ms 만에 즉시 404로 차단.
2. **Null 캐싱이 2차 보완**: 1% 미만의 위양성으로 인해 DB를 조회하여 빈 결과가 나온 경우, `NULL` 객체를 30초의 짧은 TTL로 캐싱하여 동일 키의 반복 공격 방어.
