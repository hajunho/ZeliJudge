# 토큰 버킷 매번 락 걸다 Redis가 뻗었다구요?!: 분산 처리율 제한기와 GCRA(가상 스케줄링) 알고리즘

## 1. 장애 현장: 타임세일 1초 전, Redis CPU 100% 폭사와 분산 락 지옥

글로벌 전자상거래 플랫폼의 오픈 API 게이트웨이에서 대규모 타임세일 이벤트 직전 전면 마비 장애가 발생했습니다.

초당 10만 건 이상의 API 요청이 쏟아지는 환경에서, 서비스는 사용자별 초당 호출 수 제한(Rate Limiting)을 위해 Redis 기반 **토큰 버킷(Token Bucket)** 알고리즘을 사용하고 있었습니다.
각 사용자 키마다 `tokens`와 `last_updated_at`을 저장하고, 매 요청마다 Redis Lua 스크립트로 락을 걸고 두 필드를 읽고 쓰는 작업을 반복했습니다:

```
[Client Request 100,000 req/s] -> [API Gateway 50 Pods]
      |
      | (각 파드마다 사용자 키에 대해 EVALSHA Lua Script 전송)
      v
[Redis Master]
  - CPU 100% 포화! 단일 스레드 이벤트 루프 지연 250ms 돌파!
  - Connection Pool Timeout 폭발!
  - 락 경합(Lock Contention)으로 인해 정상 사용자 요청까지 504 Gateway Timeout으로 전멸!
```

사후 분석 결과, 문제는 토큰 버킷의 "상태 2개 갱신" 구조였습니다. 10만 RPS 환경에서 두 개의 필드를 읽고 계산하고 쓰는 과정 자체가 Redis에 극심한 오버헤드를 유발했던 것입니다.

이에 인프라 아키텍트는 **Stripe과 Redis-Cell(`CL.THROTTLE`)이 사용하는 GCRA(Generic Cell Rate Algorithm)**를 도입하기로 결정했습니다.
키당 오직 **단 하나의 정수 타임스탬프(`TAT`)**만 저장하여 락 경합을 원천 제거하고, 마이크로초 단위의 정밀한 흐름 제어와 `Retry-After` 헤더를 산출하는 고성능 GCRA 가상 스케줄링 엔진을 구현하세요!

---

## 2. 요구 사항 및 알고리즘 명세

입력으로 주어지는 정격 비율(`rate`), 기간(`period_ms`), 허용 버스트 크기(`burst`), 그리고 시간 순서대로 유입되는 API 요청 목록(`requests`)을 GCRA 규칙에 따라 처리하여 전체 메트릭(`metrics`)과 개별 응답 로그(`response_log`)를 산출해야 합니다.

### 2.1 GCRA 파라미터 계산
- **방출 주기(Emission Interval) $T$**:
  $$T = \frac{\text{period\_ms}}{\text{rate}}$$
- **허용 버스트 허용 오차(Burst Tolerance) $\tau$**:
  $$\tau = \text{burst} \times T$$

### 2.2 요청 처리 규칙
각 요청은 `id`, 테넌트 식별자 `key`, 유입 시각 `timestamp_ms` ($t$), 소비 비용 `cost` ($C$, 기본값 1)를 가집니다:
1. 해당 `key`의 기존 $\text{TAT}$를 조회합니다 (최초 요청 시 $\text{TAT} = 0$).
2. 과거 유휴 시간 보정:
   $$\text{TAT}' = \max(t, \; \text{TAT})$$
3. 허용 조건 검사:
   $$\text{is\_allowed} = \left( \text{TAT}' + (C - 1) \times T - t \le \tau \right)$$
4. **승인(`is_allowed = True`) 시**:
   - $\text{new\_TAT} = \text{TAT}' + C \times T$로 `tat_map[key]`를 갱신합니다.
   - `allowed_requests += 1`, `total_cost_consumed += cost`.
   - `remaining = max(0, int((tau - (new_TAT - t - T)) // T))`
   - `reset_ms = max(0, int(new_TAT - t))`
   - `retry_after_ms = 0`
5. **거절(`is_allowed = False`) 시**:
   - **주의: `tat_map[key]`의 $\text{TAT}$는 절대로 갱신하지 않습니다!**
   - `rejected_requests += 1`.
   - `remaining = max(0, int((tau - (tat - t)) // T))` (단, $tat - t > tau$이면 0)
   - `reset_ms = max(0, int(tat - t))`
   - `retry_after_ms = max(0, int(tat_prime + (cost - 1) * T - t - tau))`

### 2.3 판정 기준 (`verdict`)
- 고유 `key`가 2개 이상인 경우 $\to$ `"MULTI_TENANT_ISOLATED_COMPLIANCE"`
- 가중 비용(`cost > 1`)으로 인해 거절된 요청이 존재하는 경우 $\to$ `"MULTI_COST_QUOTA_EXCEEDED"`
- 거절된 요청이 1건 이상 존재하는 경우 $\to$ `"BURST_TOLERANCE_EXHAUSTED"`
- 모든 요청이 100% 승인된 경우 $\to$ `"CONFORMANT_STEADY_STREAM"`

---

## 3. 입출력 포맷

### 입력 형식 (JSON on stdin)
```json
{
  "rate": 10,
  "period_ms": 1000,
  "burst": 5,
  "algorithm": "GCRA",
  "requests": [
    {"id": "req_1", "key": "user:100", "timestamp_ms": 0, "cost": 1},
    {"id": "req_2", "key": "user:100", "timestamp_ms": 0, "cost": 1},
    {"id": "req_3", "key": "user:100", "timestamp_ms": 0, "cost": 1}
  ]
}
```

### 출력 형식 (JSON on stdout)
```json
{
  "metrics": {
    "algorithm": "GCRA",
    "total_requests": 3,
    "allowed_requests": 3,
    "rejected_requests": 0,
    "total_cost_consumed": 3,
    "max_consecutive_burst": 3,
    "average_retry_after_ms": 0.0,
    "final_tats": {
      "user:100": 300
    },
    "verdict": "CONFORMANT_STEADY_STREAM"
  },
  "response_log": [...]
}
```
