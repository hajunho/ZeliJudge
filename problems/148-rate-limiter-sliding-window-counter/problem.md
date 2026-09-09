# [API 요청이 1초에 1,000건 몰렸는데 왜 트래픽이 2배로 뚫려요?!: 분산 처리율 제한(Rate Limiting)과 고정 윈도우(Fixed Window) 경계 트랩 vs 슬라이딩 윈도우 카운터(Sliding Window Counter)]

## 1. 장애 시나리오: "초당 100건 제한을 걸어뒀는데 200건 폭탄을 맞고 DB가 폭사한 미스터리"

대규모 트래픽을 처리하는 공개 API 게이트웨이에서 서비스 보호 및 악성 스크래핑 차단을 위해 Redis 기반의 **처리율 제한 장치(Rate Limiter)**를 도입했습니다.
보안 정책은 **"분당 최대 100건 (100 requests per minute)"**이었습니다.

주니어 개발자는 가장 구현이 단순한 **고정 윈도우 카운터(Fixed Window Counter)** 방식을 선택했습니다:
```java
public boolean isAllowed(String userId) {
    long currentMinute = System.currentTimeMillis() / 60000;
    String key = "rate_limit:" + userId + ":" + currentMinute;
    
    Long count = redisTemplate.opsForValue().increment(key);
    if (count == 1) {
        redisTemplate.expire(key, Duration.ofMinutes(1));
    }
    return count <= 100;
}
```

개발자는 로컬에서 테스트하며 완벽하다고 확신했습니다.
하지만 인기 티켓팅 오픈 날, 백엔드 데이터베이스 서버가 **CPU 100% 포화 및 커넥션 풀 고갈로 뻗어버리는 대참사**가 터졌습니다:

로그를 역추적해 보니 기괴한 현상이 발견되었습니다:
- 유저 A는 `00:59`초에 정확히 100건의 요청을 쐈습니다 $	o$ 이전 윈도우(`00:00~00:59`) 한도 100건 이하이므로 **전원 허용(200 OK)!**
- 잠시 후 `01:01`초에 유저 A가 다시 100건의 요청을 쐈습니다 $	o$ 새로운 윈도우(`01:00~01:59`)이므로 카운터가 0으로 리셋되어 **다시 전원 허용(200 OK)!**

결과적으로 `00:59`초부터 `01:01`초까지 **단 2초 동안 200건(허용 한도의 정확히 2배!)의 폭발적인 트래픽이 무방비로 백엔드에 관통**되어 서버를 태워버린 것입니다! 이것이 바로 악명 높은 **고정 윈도우 경계선 스파이크(Fixed Window Boundary Trap)**입니다.

인프라 아키텍트의 해결책:
> "고정 윈도우는 경계선에서 2배 트래픽이 뚫리는 치명적 결함이 있습니다! Cloudflare와 Stripe가 사용하는 **슬라이딩 윈도우 카운터(Sliding Window Counter)**를 도입하여 $O(1)$의 초경량 메모리로 경계선 버스트를 완벽히 차단하십시오!"

---

## 2. 시뮬레이션 사양 및 규칙

본 문제에서는 **고정 윈도우(Fixed Window)** 방식과 **슬라이딩 윈도우 카운터(Sliding Window Counter)** 방식의 요청 허용/차단 판정 및 순간 최대 트래픽 집계를 시뮬레이션합니다.

### (1) 파라미터
- 알고리즘 모드: `mode` (`"FIXED_WINDOW"` 또는 `"SLIDING_WINDOW_COUNTER"`)
- 윈도우 크기: `window_size_sec` (초 단위 정수 $W$)
- 윈도우당 최대 허용 한도: `limit` (정수 $L$)
- 요청 타임스탬프 스트림: 초 단위 정수 $t_1, t_2, \dots, t_N$ (오름차순)

### (2) 알고리즘별 판정 메커니즘

#### 1) `FIXED_WINDOW` (고정 윈도우)
- 요청 시간 $t$가 속한 고정 윈도우 시작 시점: $W_{curr} = \lfloor t / W floor 	imes W$
- 해당 윈도우의 현재 누적 카운트를 $c$라 할 때:
  - $c + 1 \le L$이면: 요청 승인 (`ALLOWED`), $c \leftarrow c + 1$
  - 초과 시: 요청 차단 (`REJECTED`)

#### 2) `SLIDING_WINDOW_COUNTER` (슬라이딩 윈도우 카운터)
- 현재 윈도우 시작 시점: $W_{curr} = \lfloor t / W floor 	imes W$
- 직전 윈도우 시작 시점: $W_{prev} = W_{curr} - W$
- 현재 윈도우에서 경과한 시간 비율: $weight = rac{t - W_{curr}}{W}$ ($0.0 \le weight < 1.0$)
- 슬라이딩 윈도우 내 가중 추정 요청 수 ($Estimated$):
  $$Estimated = Count(W_{prev}) 	imes (1 - weight) + Count(W_{curr})$$
- 판정 규칙:
  - $Estimated + 1 \le L$이면: 요청 승인 (`ALLOWED`), $Count(W_{curr}) \leftarrow Count(W_{curr}) + 1$
  - 초과 시: 요청 차단 (`REJECTED`)

### (3) 최종 집계 메트릭
- `TOTAL_REQUESTS`: 총 인입 요청 수
- `ALLOWED`: 승인된 요청 수
- `REJECTED`: 차단된 요청 수
- `MAX_WINDOW_BURST`: 실제로 승인되어 통과한 요청들 중, **임의의 길이 $W$ 구간 내에 집중된 최대 요청 건수** (슬라이딩 윈도우 기준 최대 관측치)

---

## 3. 입력 형식

- 첫째 줄에 알고리즘 모드 `mode`, 윈도우 크기 `window_size_sec`, 허용 한도 `limit`가 공백으로 구분되어 주어집니다.
- 둘째 줄에 요청 수 $N$ ($1 \le N \le 10,000$)이 주어집니다.
- 셋째 줄부터 공백 또는 줄바꿈으로 구분된 $N$개의 요청 타임스탬프(정수 초)가 주어집니다 ($0 \le t_i \le 10^9$, 오름차순).

## 4. 출력 형식

- 한 줄에 다음 통계를 공백으로 구분하여 출력합니다:
  - `TOTAL_REQUESTS: <n> ALLOWED: <n> REJECTED: <n> MAX_WINDOW_BURST: <n>`

---

## 5. 입출력 예제

### 예제 1 (`FIXED_WINDOW`: 경계선에서 200건 전원 통과 참사)
#### 입력
```text
FIXED_WINDOW 60 100
200
59 59 59 ... (59초에 100건) ... 61 61 61 ... (61초에 100건)
```
#### 출력
```text
TOTAL_REQUESTS: 200 ALLOWED: 200 REJECTED: 0 MAX_WINDOW_BURST: 200
```

### 예제 2 (`SLIDING_WINDOW_COUNTER`: 경계선 버스트 101건으로 철통 방어)
#### 입력
```text
SLIDING_WINDOW_COUNTER 60 100
200
59 59 59 ... (59초에 100건) ... 61 61 61 ... (61초에 100건)
```
#### 출력
```text
TOTAL_REQUESTS: 200 ALLOWED: 101 REJECTED: 99 MAX_WINDOW_BURST: 101
```
**설명**:
- 고정 윈도우는 59초와 61초가 서로 다른 윈도우(0~59, 60~119)에 속하므로 200건을 몽땅 통과시켰습니다.
- 슬라이딩 윈도우 카운터는 61초 시점에 이전 윈도우의 가중치 $59/60$를 합산 계산하여 직전의 100건 트래픽을 인지하고, 99건을 즉시 거부(`429 Too Many Requests`)하여 시스템을 보호했습니다.
