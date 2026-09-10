# [Pro #269] 엔보이 프록시(Envoy Proxy) 적응형 동시성 제어(Adaptive Concurrency Control) & 베이거스 그래디언트(Vegas Gradient) 배압 엔진

## 문제 설명

마이크로서비스 아키텍처(MSA) 및 클라우드 네이티브 서비스 메시(Envoy Proxy, Istio, Linkerd) 환경에서 백엔드 시스템을 보호하기 위해 초당 요청 수(RPS) 기반의 **정적 처리율 제한(Static Rate Limiting)**이나 고정 크기의 워커 스레드 풀(Thread Pool)을 사용하는 것은 심각한 운영상의 한계를 초래합니다:
1. **다운스트림 지연 시간 변동 취약성**: 백엔드 데이터베이스의 락 경합, 네트워크 혼잡, 또는 JVM 가비지 컬렉션(STW GC)으로 인해 평균 응답 시간이 10ms에서 200ms로 급증하면, 동일한 500 RPS 트래픽 하에서도 동시 처리 대기 요청 수(In-flight Requests)가 20배 폭증합니다. 이로 인해 인바운드 큐가 가득 차고 타임아웃이 연쇄적으로 발생하며 시스템 전체가 붕괴(Cascading Failure)하는 재앙이 일어납니다.
2. **리틀의 법칙(Little's Law)**: 큐잉 이론의 기초인 리틀의 법칙에 따르면, 시스템 내 평균 동시 처리 요청 수 $L$은 평균 유입 처리량 $\lambda$와 평균 체류 시간(응답 지연) $W$의 곱으로 결정됩니다:
   $$L = \lambda \cdot W$$
   진정한 시스템의 수용 용량은 "초당 요청 수"가 아니라 "시스템 내부 큐잉 지연 없이 안전하게 병렬 처리 가능한 **최대 동시 인플라이트 요청 수(Concurrency Limit, $L$)**"입니다.

이 문제를 해결하기 위해 넷플릭스(Netflix `concurrency-limits`)와 엔보이 프록시(Envoy Proxy `adaptive_concurrency` 필터)는 TCP 베이거스(TCP Vegas) 혼잡 제어 알고리즘의 원리를 L7 RPC 프록시 계층에 도입한 **적응형 동시성 제어(Adaptive Concurrency Control, ACC)**를 개발했습니다:
- **기준 지연($RTT_{\min}$) 추적**: 큐가 비어 있을 때의 순수 기저 처리 지연(Uncontended Processing Latency)을 롤링 윈도우 방식으로 지속 추적합니다.
- **그래디언트(Gradient) 기반 배압**: 최근 완료된 요청들의 평균 응답 지연($RTT_{\text{sample}}$)을 측정하여 $\text{gradient} = \frac{RTT_{\min}}{RTT_{\text{sample}}}$를 계산합니다.
  - 지연 시간이 기저치에 가까우면 $\text{gradient} \approx 1.0$이며, 가산 증가(Additive Increase, $+ \text{headroom}$)를 통해 동시성 한계를 완만히 넓혀 처리량을 극대화합니다.
  - 지연 시간이 급증하면 $\text{gradient} < 1.0$으로 떨어지며, 승수 감소(Multiplicative Decrease)를 통해 동시성 한계를 즉각 축소하여 대기 큐를 비웁니다.
- **인플라이트 차단 및 부하 완화(Load Shedding)**: 현재 동시 처리 중인 요청 수($I$)가 허용 한계($\lfloor L \rfloor$)에 도달하면 신규 요청을 즉시 거절(`CONCURRENCY_LIMIT_EXCEEDED` / HTTP 429 또는 503)하여 백엔드의 과부하 붕괴를 원천 차단합니다.

당신은 글로벌 클라우드 서비스 메시 및 사이드카 프록시 인프라 코어 팀의 시니어 플랫폼 엔지니어로서, Envoy Proxy의 적응형 동시성 제어 필터 명세를 따르는 **이산 사건 기반 적응형 동시성 제어 및 그래디언트 배압 시뮬레이터 엔진**을 구현해야 합니다.

---

## 시스템 사양 및 세부 동작 규칙

### 1. 설정 매개변수 (`config`)
- `initial_concurrency_limit` (실수, 기본값 10.0): 시뮬레이션 시작($t=0$) 시의 초기 동시성 한계 $L_0$.
- `min_concurrency_limit` (실수, 기본값 2.0): 동시성 한계의 하한선 (최악의 지연 시간 급증 시에도 이 값 이하로 축소되지 않음).
- `max_concurrency_limit` (실수, 기본값 100.0): 동시성 한계의 상한선.
- `headroom` (실수, 기본값 1.0): 지연 시간이 안정적일 때 동시성을 탐색적으로 확장하기 위한 가산 증가 여유분 $\beta$.
- `sample_window_size` (정수, 기본값 5): 동시성 한계를 재계산하기 위해 수집해야 하는 완료 요청의 수 $K$.
- `min_gradient` (실수, 기본값 0.5): 지연 시간 폭증 시 1회 갱신에서 허용되는 그래디언트의 최소 클램핑 하한.
- `max_gradient` (실수, 기본값 1.5): 지연 시간 개선 시 허용되는 그래디언트의 최대 클램핑 상한.
- `initial_min_rtt` (실수, ms, 기본값 20.0): 시스템 초기 기준 최소 RTT.
- `min_rtt_window_size` (정수, 기본값 3): 롤링 $RTT_{\min}$ 윈도우에 유지할 최근 샘플 RTT의 개수.

### 2. 이산 사건(Discrete Event) 처리 순서
시간축 상에서 요청의 도착(Arrival)과 완료(Completion) 사건이 발생합니다.
동일한 타임스탬프 $t$에 여러 사건이 동시에 발생하는 경우:
1. **완료 사건(Completion Event)을 먼저 모두 처리**합니다.
   - 인플라이트 요청 수($I$)를 1 감소시킵니다.
   - 완료된 요청의 실제 지연 시간($RTT = \text{processing\_time}$)을 현재 샘플 윈도우에 추가합니다.
   - 현재 샘플 윈도우에 수집된 표본 수가 `sample_window_size`에 도달하면, **즉시 동시성 한계 갱신(Limit Update)을 실행**합니다.
2. **그 후 도착 사건(Arrival Event)을 처리**합니다.
   - 입력 데이터의 `requests` 배열에 나타난 순서대로 처리합니다.
   - 현재 허용 가능한 최대 인플라이트 수는 $\lfloor L \rfloor$ (현재 $L$의 내림 정수값)입니다.
   - $I < \lfloor L \rfloor$인 경우:
     - 요청을 **승인(`ADMITTED`)**합니다.
     - $I \leftarrow I + 1$로 증가시킵니다.
     - 완료 예정 시간은 $\text{finish\_time} = \text{arrival\_time} + \text{processing\_time}$이며 완료 사건을 스케줄링합니다.
   - $I \ge \lfloor L \rfloor$인 경우:
     - 요청을 **거절(`REJECTED`, 부하 완화)**합니다.
     - 거절 사유는 `"CONCURRENCY_LIMIT_EXCEEDED"`로 기록하며 인플라이트 카운트는 변하지 않습니다.

### 3. 동시성 한계 및 롤링 Min RTT 갱신 공식
`sample_window_size`개의 요청이 완료될 때마다 다음 순서로 갱신됩니다:
1. 표본 평균 지연 시간 계산:
   $$RTT_{\text{sample}} = \frac{1}{K} \sum_{i=1}^K RTT_i$$
2. 롤링 Min RTT 갱신:
   - $RTT_{\text{sample}}$을 최근 샘플 RTT 이력 목록에 추가합니다.
   - 이력의 길이가 `min_rtt_window_size`를 초과하면 가장 오래된 항목을 제거합니다.
   - 현재 기준 최소 RTT는 이력 목록의 최솟값으로 결정됩니다:
     $$RTT_{\min} = \min(\text{sample\_rtt\_history})$$
3. 그래디언트(Gradient) 계산 및 클램핑:
   $$\text{raw\_gradient} = \frac{RTT_{\min}}{RTT_{\text{sample}}}$$
   $$\text{gradient} = \max(\text{min\_gradient}, \min(\text{max\_gradient}, \text{raw\_gradient}))$$
4. 차기 동시성 한계 산출:
   $$L_{\text{next}} = L_{\text{current}} \times \text{gradient} + \text{headroom}$$
   $$L_{\text{new}} = \max(\text{min\_concurrency\_limit}, \min(\text{max\_concurrency\_limit}, L_{\text{next}}))$$
   $$L \leftarrow \text{round}(L_{\text{new}}, 2)$$
5. 갱신 이력 기록 및 샘플 윈도우 버퍼 초기화.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "initial_concurrency_limit": 5.0,
    "min_concurrency_limit": 2.0,
    "max_concurrency_limit": 20.0,
    "headroom": 1.0,
    "sample_window_size": 4,
    "min_gradient": 0.5,
    "max_gradient": 1.5,
    "initial_min_rtt": 20.0,
    "min_rtt_window_size": 3
  },
  "requests": [
    {"id": "r1", "arrival_time": 0, "processing_time": 20},
    {"id": "r2", "arrival_time": 5, "processing_time": 20},
    {"id": "r3", "arrival_time": 10, "processing_time": 20},
    {"id": "r4", "arrival_time": 15, "processing_time": 20},
    {"id": "burst_1", "arrival_time": 20, "processing_time": 50}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 단일 JSON 객체를 공백 없이(또는 표준 JSON 포맷) 한 줄로 출력합니다:
```json
{
  "summary": {
    "total_requests": 5,
    "admitted_requests": 5,
    "rejected_requests": 0,
    "rejection_rate": 0.0,
    "final_concurrency_limit": 6.0,
    "final_min_rtt": 20.0,
    "total_limit_updates": 1
  },
  "limit_updates": [
    {
      "timestamp": 35,
      "sample_rtt": 20.0,
      "min_rtt": 20.0,
      "gradient": 1.0,
      "old_limit": 5.0,
      "new_limit": 6.0
    }
  ],
  "processed_requests": [
    {
      "id": "r1",
      "status": "ADMITTED",
      "arrival_time": 0,
      "finish_time": 20,
      "rtt": 20,
      "limit_at_arrival": 5.0,
      "in_flight_after_admission": 1
    }
  ]
}
```
