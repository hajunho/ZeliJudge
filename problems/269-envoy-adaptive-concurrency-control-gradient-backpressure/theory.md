# [Pro #269 깊이 읽기] 엔보이 프록시 적응형 동시성 제어(ACC)와 베이거스 그래디언트(Vegas Gradient): 리틀의 법칙과 L7 배압의 수학

## 1. 정적 레이트 리미팅의 맹점과 리틀의 법칙(Little's Law)

기존 분산 시스템에서 서버 과부하를 막기 위해 널리 사용되던 정적 처리율 제한(Static Rate Limiting, 예: 토큰 버킷 500 req/sec)은 **모든 요청의 처리 비용과 다운스트림 상태가 항상 동일하다는 비현실적인 가정**에 기반합니다.

1961년 존 리틀(John Little) 교수가 증명한 **리틀의 법칙(Little's Law)**은 대기 행렬 이론(Queuing Theory)의 가장 근본적인 법칙입니다:

$$L = \lambda \cdot W$$

여기서:
- $L$: 시스템 내부에서 동시에 처리 중이거나 대기 중인 평균 요청 수 (In-flight concurrency)
- $\lambda$: 단위 시간당 시스템으로 유입되어 처리되는 평균 요청 수 (Throughput, req/sec)
- $W$: 각 요청이 시스템에 체류하는 평균 시간 (Latency, sec)

```
 [정상 상태 (Healthy)]
  Throughput λ = 500 rps, Latency W = 0.02s (20ms)
  ==> In-flight Concurrency L = 500 * 0.02 = 10 requests

 [다운스트림 장애 발생 (DB Lock / GC Pause)]
  Latency W 급증: 0.02s -> 0.20s (200ms, 10배 폭증)
  동일한 유입량 유지 시 (λ = 500 rps):
  ==> In-flight Concurrency L = 500 * 0.20 = 100 requests!
```

지연 시간이 10배 증가하면, 고정된 처리율(500 rps) 하에서도 시스템 내부의 동시 병목 요청 수는 10개에서 100개로 폭증합니다. 스레드 풀은 수 초 만에 고갈되고, 메모리 버퍼 큐는 팽창하며, 클라이언트 타임아웃이 발생하여 재시도 폭풍(Retry Storm)이 뒤따르는 악순환에 빠집니다.

따라서 최신 클라우드 인프라에서는 처리량($\lambda$)을 통제하는 대신, **시스템이 감당할 수 있는 동시 처리 한계($L$)를 직접 제어**해야 합니다.

---

## 2. TCP 베이거스(TCP Vegas)와 L7 적응형 동시성 제어

1994년 로렌스 브라크모(Lawrence Brakmo)와 래리 피터슨(Larry Peterson)이 고안한 **TCP 베이거스(TCP Vegas)**는 패킷 손실(Packet Loss)이 발생할 때까지 무작정 윈도우를 키우는 TCP 리노(Reno)와 달리, **RTT 지연의 미세한 변화를 감지하여 큐잉이 시작되는 무손실 무지연 변곡점(Knee Point)**에서 전송 속도를 선제적으로 조절하는 혁신적인 딜레이 기반(Delay-based) 혼잡 제어였습니다.

넷플릭스(Netflix)와 리프트(Lyft, Envoy Proxy 개발사)는 이 베이거스 알고리즘을 HTTP/gRPC 프록시 계층으로 승화시켰습니다:
- 네트워크 패킷의 혼잡 윈도우(CWND) 대신 **프록시 인플라이트 동시성 한계($L$)**를 제어합니다.
- 패킷 RTT 대신 **다운스트림 백엔드 RPC 응답 지연 시간**을 측정합니다.

```
 Throughput
    ▲               /│  (이상적인 최대 처리량 도달)
    │              / │
    │             /  │  <--- [ 변곡점 (Knee Point) ]
    │            /   │       - 처리량 최대, 큐잉 지연 0
    │           /    │       - RTT_sample ≈ RTT_min
    │          /     │       - Gradient ≈ 1.0
    │         /      │───────────────────────── (용량 포화 상태)
    │        /       :
    │       /        : 큐잉 지연 폭증 (Queue Building)
    │      /         : RTT_sample >> RTT_min
    │     /          : Gradient < 1.0 (배압 발동!)
    └────┴───────────┴─────────────────────────────► In-flight Concurrency (L)
```

---

## 3. 그래디언트(Gradient) 수학 모델과 배압 메커니즘

### 3.1 기준 최소 지연($RTT_{\min}$)과 샘플 지연($RTT_{\text{sample}}$)
- $RTT_{\min}$: 시스템 큐가 텅 비어 있을 때 오직 하드웨어 처리 능력에 의해서만 결정되는 고유 기저 지연입니다.
- $RTT_{\text{sample}}$: 최근 완료된 $K$개 요청의 평균 RTT입니다.

$$\text{gradient} = \frac{RTT_{\min}}{RTT_{\text{sample}}}$$

1. **$\text{gradient} \approx 1.0$ (정상/유휴)**:
   대기 큐가 없음을 의미합니다. 여유분 $\beta$(`headroom`)를 더해 한계를 점진적으로 확장(Additive Increase)하여 시스템의 잠재 용량을 탐색합니다:
   $$L_{\text{next}} = L \times 1.0 + \beta$$
2. **$\text{gradient} < 1.0$ (혼잡/지연 발생)**:
   백엔드 큐에 요청이 밀려들기 시작했음을 의미합니다. $L$에 1 미만의 그래디언트가 곱해지면서 승수 감소(Multiplicative Decrease)가 일어나 동시성 한계가 즉각 축소됩니다:
   $$L_{\text{next}} = L \times \text{gradient} + \beta$$
3. **그래디언트 클램핑(Gradient Clamping)**:
   단 한 번의 일시적 지연 이상치(Outlier)로 인해 한계가 0으로 급락하거나 비정상적으로 치솟는 것을 막기 위해 상하한을 둡니다:
   $$\text{gradient} \in [\text{min\_gradient}, \text{max\_gradient}] \quad (\text{예: } [0.5, 1.5])$$

### 3.2 롤링 Min RTT 윈도우와 기준선 시프트(Baseline Shift)
실제 환경에서는 영구적인 인프라 변경(예: 보안 암호화 계층 추가, 다른 리전으로의 DB 이전, VM 인스턴스 타입 다운그레이드)으로 인해 백엔드의 정상 기저 지연 자체가 10ms에서 30ms로 영구적으로 이동할 수 있습니다.
만약 $RTT_{\min}$을 초기의 10ms로 고정해 둔다면 그래디언트는 영원히 $10/30 = 0.33$에 머물러 동시성 한계가 영구적으로 바닥에 묶이게 됩니다.
따라서 **롤링 윈도우($W_{\min}$)**를 유지하여, 오래된 초저지연 표본이 윈도우 밖으로 밀려나면 새로운 영구 지연(30ms)이 자연스럽게 새로운 $RTT_{\min}$으로 승격되도록 설계합니다.

---

## 4. 부하 완화(Load Shedding)와 SRE 복원력

동시성 한계가 $L$로 축소되었을 때, 현재 인플라이트 요청 수 $I \ge \lfloor L \rfloor$인 상태에서 도착하는 초과 요청은 **지체 없이 즉시 거절(Shed)**됩니다.

이것이 시스템 전체의 생존을 결정짓는 이유:
1. **좋은 거절(Fast Failure)**: 큐에서 수 초간 썩다가 결국 타임아웃되는 것보다, 0.1ms 만에 HTTP 429/503을 반환받은 클라이언트는 재시도 백오프를 취하거나 다른 정상 복제본(Replica)으로 빠르게 페일오버할 수 있습니다.
2. **서비스 용량 보존**: 이미 처리 중인 요청들은 큐잉 간섭 없이 원래의 고속 속도로 완료될 수 있으므로, 시스템의 유효 처리량(Goodput)이 최대치로 유지됩니다.
