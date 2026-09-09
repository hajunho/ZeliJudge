# 분산 처리율 제한기(Rate Limiter)와 GCRA(Generic Cell Rate Algorithm) 가상 스케줄링

## 1. 개요: 대규모 분산 API 게이트웨이와 처리율 제한의 딜레마

현대 대규모 클라우드 서비스(Stripe, GitHub, Cloudflare, AWS API Gateway)에서 **처리율 제한(Rate Limiting)**은 특정 사용자나 악의적인 크롤러가 초당 수만 건의 요청을 퍼부어 시스템 전체를 마비시키는 것을 방지하는 핵심 보안 및 인프라 보호 장치입니다.

전통적인 처리율 제한 알고리즘들은 저마다 심각한 한계를 안고 있습니다:
1. **고정 윈도우 카운터 (Fixed Window Counter)**:
   - 윈도우 경계(예: 00:59:59와 01:00:01) 사이에 2배의 트래픽이 일순간에 쏟아지는 경계 급증(Boundary Burst) 취약점 발생.
2. **슬라이딩 윈도우 로그 (Sliding Window Log)**:
   - 모든 요청의 타임스탬프를 Redis Sorted Set 등에 저장하므로 요청 수에 비례하여 메모리가 $O(N)$으로 폭발.
3. **토큰 버킷 (Token Bucket / Leaky Bucket)**:
   - 직관적이지만, 분산 환경(Redis 등)에서 구현할 때 각 사용자 키마다 **`tokens`(잔여 토큰 수)**와 **`last_updated`(마지막 갱신 시각)**라는 2개 이상의 상태 변수를 저장해야 합니다.
   - 요청마다 토큰 리필량을 계산하고 잔여 토큰을 차감하는 복합 연산 때문에 **Redis 트랜잭션(`MULTI/EXEC`), 분산 락(Distributed Lock), 또는 복잡한 Lua 스크립트**가 강제되어 고빈도 트래픽에서 CPU 병목과 락 경합이 발생합니다.

---

## 2. 구원: GCRA (Generic Cell Rate Algorithm)의 혁신

**GCRA (Generic Cell Rate Algorithm)**는 원래 ATM(Asynchronous Transfer Mode, ITU-T I.371) 네트워크에서 셀 단위 트래픽 셰이핑을 위해 고안된 표준 알고리즘입니다.

현대 고성능 분산 시스템(Redis의 `redis-cell` 모듈의 `CL.THROTTLE`, Go 언어의 `uber-go/ratelimit`)은 이 알고리즘을 API Rate Limiting에 차용하여 분산 처리율 제한기의 패러다임을 바꿨습니다.

```
+-------------------------------------------------------------------------------+
|                       GCRA 가상 스케줄링 모델 (Virtual Scheduling)            |
+-------------------------------------------------------------------------------+
|   t (현재 시각)                                                               |
|   |                                                                           |
|   v                                                                           |
| =====+-------------------------+-----------------------------------> 시간(ms)  |
|      |                         |                                              |
|      |<--- tau (허용 버스트) --->|                                              |
|      +-------------------------+                                              |
|                                |                                              |
|                                v                                              |
|                               TAT (이론적 도착 시각, Theoretical Arrival Time)|
+-------------------------------------------------------------------------------+
```

### 2.1 단 하나의 정수(State)만 저장하는 마법
GCRA의 가장 위대한 장점은 **키당 오직 단 하나의 값: `TAT` (Theoretical Arrival Time, 이론적 도착 시각)**만 저장하면 된다는 점입니다!
- 잔여 토큰 수를 저장할 필요가 없습니다.
- 마지막 갱신 시각을 따로 저장할 필요가 없습니다.
- 미래에 요청이 도착해야 하는 이론적 시각(`TAT`) 하나만으로 현재 사용자가 얼마나 많은 버스트를 소진했는지, 다음 요청까지 몇 밀리초를 대기(`Retry-After`)해야 하는지 100% 수학적으로 완벽히 도출됩니다.

---

## 3. GCRA 가상 스케줄링(Virtual Scheduling) 알고리즘 수학적 명세

### 3.1 파라미터 정의
- **방출 주기 $T$ (Emission Interval)**:
  규정된 기간(`period_ms`) 동안 허용되는 정격 비율(`rate`)에 따라 단 1개의 요청이 처리되는 표준 시간 간격:
  $$T = \frac{\text{period\_ms}}{\text{rate}}$$
  *(예: 1초당 10개 허용 $\to T = 1000 / 10 = 100\text{ms}$)*
- **버스트 허용 한도 $\tau$ (Delay Variation Tolerance / Burst Offset)**:
  버킷이 일순간에 수용할 수 있는 최대 허용 버스트 지연 한도:
  $$\tau = \text{burst} \times T$$
  *(예: burst = 5, $T = 100\text{ms} \to \tau = 500\text{ms}$)*

### 3.2 요청 판정 및 상태 전이 규칙
현재 시각 $t$에 비용(Cost) $C$를 소모하는 요청이 도착했을 때:
1. **과거 유휴 시간 리셋**:
   만약 현재 시각 $t$가 기존 $\text{TAT}$보다 미래라면(장기 미사용 상태), $\text{TAT}$를 현재 시각으로 당겨옵니다:
   $$\text{TAT}' = \max(t, \; \text{TAT})$$
2. **허용 여부 판정 (Tolerance Check)**:
   이번 요청을 수용했을 때의 가상 스케줄이 허용 한도 $\tau$ 이내인지 검사합니다:
   $$\text{is\_allowed} = \left( \text{TAT}' + (C - 1) \times T - t \le \tau \right)$$
3. **승인(`ALLOWED`) 시 상태 갱신**:
   - 새로운 이론적 도착 시각을 갱신합니다:
     $$\text{new\_TAT} = \text{TAT}' + C \times T$$
   - 클라이언트에게 전달할 표준 HTTP 헤더 계산:
     - `X-RateLimit-Remaining`: $\max\left(0, \; \left\lfloor \frac{\tau - (\text{new\_TAT} - t - T)}{T} \right\rfloor\right)$
     - `X-RateLimit-Reset`: $\max(0, \; \text{new\_TAT} - t)$
4. **거절(`REJECTED`, HTTP 429) 시 상태 보존**:
   - **중요: $\text{TAT}$는 절대로 갱신되지 않고 기존 값을 그대로 유지합니다!**
   - 클라이언트가 다시 시도할 수 있는 최소 대기 시간 계산:
     $$\text{Retry-After (ms)} = \max(0, \; \text{TAT}' + (C - 1) \times T - t - \tau)$$

---

## 4. 전통적 토큰 버킷 vs GCRA 알고리즘 비교

| 비교 항목 | 고전적 토큰 버킷 (Token Bucket) | GCRA 가상 스케줄링 (Virtual Scheduling) |
| :--- | :--- | :--- |
| **저장 상태 (State)** | 2개 이상 (`tokens`, `last_updated`) | **단 1개 (`TAT` 밀리초 타임스탬프)** |
| **동시성 제어 (Concurrency)** | 락(Lock) 또는 복잡한 Multi-Field Lua Script 필요 | 단일 값 원자적 CAS(`COMPARE-AND-SWAP`) 또는 단일 키 연산 |
| **시간 흐름 누적** | 매 요청마다 경과 시간 $\times$ 리필율 부동소수점 곱셈 | 정수 덧셈 및 $\max(t, \text{TAT})$ 비교 |
| **버스트 제어** | 버킷 깊이(Capacity)로 직접 제한 | 허용 지연 오차 $\tau = \text{burst} \times T$로 수학적 동일 제어 |
| **재시도 시간 계산** | 토큰 1개 리필까지의 시간 역산 필요 | $\text{TAT} - t - \tau$로 즉시 도출 |
| **다중 가중치 비용(Cost)** | 잔여 토큰 $\ge$ Cost 비교 | $\text{TAT}' + C \times T$로 자연스러운 스케줄 밀림 |
