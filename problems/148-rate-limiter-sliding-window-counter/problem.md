# #148 1분에 60번만 허용했는데 왜 2초 만에 120번이 뚫려요?!: 처리율 제한(Rate Limiting)의 고정 윈도우(Fixed Window) 경계선 버스트 참사와 슬라이딩 윈도우 카운터(Sliding Window Counter)

## 1. 실무 장애 시나리오: "분당 60개 제한인데 GPU 서버가 120개 폭격을 맞고 뻗었어요?!"

생성형 AI(LLM) 기반 코드 리뷰 서비스를 운영하는 '젤리AI'의 백엔드 엔지니어 준호는 비정상적인 크롤러와 무제한 API 호출을 차단하기 위해 **처리율 제한 장치(Rate Limiter)**를 구축했습니다.

비즈니스 요구사항:
> *"모든 무료 사용자는 분당 최대 60회(60 requests / minute)까지만 API를 호출할 수 있다."*

준호는 Redis를 활용해 가장 구현이 쉽고 직관적인 **고정 윈도우 카운터(Fixed Window Counter)**로 미들웨어를 작성했습니다:
```python
current_minute = int(time.time() / 60)
key = f"rate_limit:{user_id}:{current_minute}"
count = redis.incr(key)
if count == 1:
    redis.expire(key, 60)

if count <= 60:
    return 200_OK
else:
    return 429_TOO_MANY_REQUESTS
```

그런데 배포 다음 날, 특정 유저가 매크로를 돌리자마자 **비싼 GPU 인스턴스 3대가 일제히 CPU 100%를 찍고 CUDA Out-Of-Memory로 폭사**하는 참사가 발생했습니다!

서버 접근 로그를 뜯어본 준호는 경악을 금치 못했습니다:
```
[12:00:59.000 ~ 12:00:59.600] -> 60개 요청 100% 허용 (200 OK)
[12:01:00.500 ~ 12:01:01.100] -> 60개 요청 100% 허용 (200 OK)
-----------------------------------------------------------------
총 2초 동안 120개의 고비용 추론 요청이 통과되어 GPU 서버를 직격함!
```

"분당 60개 제한인데 어떻게 2초 만에 120개가 통과된 거지?!"

긴급 투입된 시니어 시스템 아키텍트 민우 님이 화이트보드에 그림을 그리며 설명했습니다:

> "준호 님, 고정 윈도우 방식은 12:00~12:59 윈도우와 13:00~13:59 윈도우가 완전히 독립된 버킷입니다!  
> 공격자가 **12:00:59초에 60개를 쏘고, 1초 뒤 시계가 13:00:00으로 넘어가 카운터가 리셋되자마자 다시 60개를 쏜 겁니다.**  
> 두 윈도우 각각은 60개 이하이므로 둘 다 통과시켰지만, **12:00:59부터 13:01:00까지의 임의의 60초 연속 구간(Rolling Window)을 보면 허용 한도의 정확히 2배인 120개가 쏟아진 겁니다!**"

준호가 물었습니다:
"그럼 요청마다 타임스탬프를 Redis Sorted Set(ZSET)에 다 기록하는 슬라이딩 윈도우 로그(Sliding Window Log)를 써야 하나요?"

> "절대 안 됩니다! 로그 방식은 요청 1건마다 타임스탬프를 메모리에 유지하므로, 활성 유저 100만 명 환경에서 초당 수만 건 공격이 들어오면 Redis 메모리가 수십 GB로 폭증해 OOM으로 레디스 서버 전체가 사망합니다!  
> Cloudflare와 AWS WAF에서도 사용하는 **슬라이딩 윈도우 카운터(Sliding Window Counter)** 알고리즘을 써야 합니다!  
> 직전 윈도우 카운터와 현재 윈도우 카운터 단 2개($O(1)$ 메모리)만 유지하면서, 현재 윈도우가 진행된 시간 비율(가중치)을 곱해 $O(1)$ 사칙연산만으로 경계선 버스트를 완벽히 억제할 수 있습니다!"

슬라이딩 윈도우 카운터를 적용하자, 12:01:00 직후에 쏟아진 공격 요청들은 직전 59초의 트래픽 가중치 때문에 단 1~2개만 아슬아슬하게 통과되고 나머지 58개는 즉시 HTTP 429로 철통 차단되었습니다.

---

## 2. 핵심 이론: 고정 윈도우 버스트와 슬라이딩 윈도우 카운터

### (1) 고정 윈도우(Fixed Window)의 경계선 버스트(Boundary Burst)
* 시간 축을 $WindowSize$ 단위의 고정된 격자로 분할합니다.
* 윈도우 경계선 직전($t_{win} - \epsilon$)과 직후($t_{win} + \epsilon$)에 트래픽이 집중되면, 연속된 $WindowSize$ 시간 동안 **최대 $2 	imes Limit$에 달하는 2배 버스트 트래픽**이 서버로 유입됩니다.

### (2) 슬라이딩 윈도우 로그(Sliding Window Log)의 한계
* 개별 요청 타임스탬프를 큐나 Sorted Set에 모두 보관하여 정확한 슬라이딩 윈도우를 계산합니다.
* 정확도는 100%이지만, $O(N)$ 메모리가 소모되어 대규모 분산 트래픽에서 Redis 메모리 고갈을 유발합니다.

### (3) 슬라이딩 윈도우 카운터(Sliding Window Counter / Cloudflare 알고리즘)
단 2개의 정수 카운터(`Count_prev`, `Count_curr`)만 보관하면서 $O(1)$ 시간에 직전 윈도우 트래픽을 가중 투영합니다:

1. 현재 윈도우 시작 시점으로부터 경과한 시간 비율($Progress$):
   $$Offset = CurrentTime - (CurrentWindowIndex 	imes WindowSize)$$
   $$Weight_{prev} = 1.0 - rac{Offset}{WindowSize}$$
2. 슬라이딩 윈도우 내 예상 요청 수 추정:
   $$EstimatedRequests = Count_{prev} 	imes Weight_{prev} + Count_{curr}$$
3. $EstimatedRequests < Limit$ 이면 요청을 승인하고 $Count_{curr} \leftarrow Count_{curr} + 1$, 초과 시 즉시 차단(HTTP 429).
4. $O(1)$ 시간 및 $O(1)$ 공간 복잡도로 99.9% 이상의 높은 정확도와 무버스트 처리를 보장합니다.

---

## 3. 입출력 규격 및 요구사항

처리율 제한 설정(`window_size_seconds`, `limit`, `algorithm`)과 일련의 요청 타임스탬프 스트림이 주어졌을 때, 각 요청의 승인/차단 여부를 판정하고 임의의 롤링 윈도우 내 최대 동시 처리량 및 버스트 발생 여부를 분석하는 엔진을 구현하세요.

### 입력 형식 (JSON)
```json
{
  "rate_limit_config": {
    "window_size_seconds": 60,
    "limit": 60,
    "algorithm": "FIXED_WINDOW"
  },
  "requests": [
    {"req_id": "R1_0", "timestamp_seconds": 59.0},
    {"req_id": "R1_1", "timestamp_seconds": 59.01},
    {"req_id": "R2_0", "timestamp_seconds": 60.5}
  ]
}
```

* `rate_limit_config`:
  * `window_size_seconds`: 윈도우 크기 (초 단위, 실수/정수)
  * `limit`: 윈도우당 최대 허용 요청 수 (정수)
  * `algorithm`: `"FIXED_WINDOW"` 또는 `"SLIDING_WINDOW_COUNTER"`
* `requests`: 요청 목록 (`req_id`, `timestamp_seconds`)

### 출력 형식 (JSON)
```json
{
  "summary": {
    "algorithm": "FIXED_WINDOW",
    "window_size_seconds": 60.0,
    "limit": 60,
    "total_requests": 120,
    "allowed_requests": 120,
    "blocked_requests": 0,
    "max_requests_in_any_rolling_window": 120,
    "burst_detected": true,
    "burst_ratio": 2.0,
    "overall_verdict": "FIXED_WINDOW_BOUNDARY_BURST_DISASTER"
  },
  "results": [
    {
      "req_id": "R1_0",
      "timestamp_seconds": 59.0,
      "allowed": true,
      "estimated_load": 1.0,
      "reason": "WITHIN_FIXED_WINDOW_LIMIT"
    }
  ]
}
```

### 판정 규칙 (`overall_verdict`)
* `algorithm == "FIXED_WINDOW"` 이고 `burst_detected == true`:
  * `"FIXED_WINDOW_BOUNDARY_BURST_DISASTER"`
* `algorithm == "SLIDING_WINDOW_COUNTER"` 이고 `burst_ratio <= 1.05`:
  * `"SLIDING_WINDOW_COUNTER_OPTIMAL"`
* `!burst_detected`:
  * `"BALANCED_EXECUTION"`
* 그 외:
  * `"BURST_LIMIT_EXCEEDED"`

---

## 4. 입출력 예시

### 예시 1: 고정 윈도우 2배 경계선 버스트 참사

#### 입력
```json
{
  "rate_limit_config": {
    "window_size_seconds": 60,
    "limit": 60,
    "algorithm": "FIXED_WINDOW"
  },
  "requests": [
    {"req_id": "R1_0", "timestamp_seconds": 59.0},
    {"req_id": "R2_0", "timestamp_seconds": 60.5}
  ]
}
```

### 예시 2: 슬라이딩 윈도우 카운터의 완벽한 버스트 억제

#### 입력
```json
{
  "rate_limit_config": {
    "window_size_seconds": 60,
    "limit": 60,
    "algorithm": "SLIDING_WINDOW_COUNTER"
  },
  "requests": [
    {"req_id": "R1_0", "timestamp_seconds": 59.0},
    {"req_id": "R2_0", "timestamp_seconds": 60.5}
  ]
}
```
