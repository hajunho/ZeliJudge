# 분산 추적(Distributed Tracing)과 샘플링 전략: Head-based vs Tail-based 심층 분석

## 1. 개요: 대규모 마이크로서비스 아키텍처(MSA)와 분산 추적의 딜레마

수백 개의 독립된 마이크로서비스로 구성된 클라우드 네이티브 환경에서, 단 하나의 사용자 요청은 인증, 장바구니, 결제, 재고, 배송, 알림 등 수십 개의 내부 RPC(gRPC, REST) 호출을 연쇄적으로 유발합니다.  
어느 한 서비스에서 지연(Latency)이 발생하거나 500 에러가 터졌을 때, 수백 대의 서버에 흩어진 로그(Log)만으로는 원인을 규명하기 불가능에 가깝습니다.

이 문제를 해결하기 위해 구글의 **Dapper(2010)** 논문을 필두로 **OpenTracing**, **OpenCensus**, 그리고 오늘날 사실상의 산업 표준인 **OpenTelemetry(OTel, CNCF)**가 등장했습니다:

```
[Client] ---> [API Gateway] ---> [Order Service] ---> [Payment Service] ---> [Bank API]
  Trace ID: 4bf92f3577b34da6a3ce929d0e0e4736
  ├── Span 1 (Gateway): 1200ms
  │   ├── Span 2 (Order): 1150ms
  │   │   ├── Span 3 (Payment): 1000ms (ERROR: 504 Timeout!)
  │   │   │   └── Span 4 (Bank API): 950ms (TIMEOUT)
```

- **Trace**: 하나의 사용자 요청이 시스템 전체를 통과하는 완전한 엔드-투-엔드 여정.
- **Span**: 단일 서비스 내에서 수행된 작업 단위(시작 시간, 종료 시간, 상태 코드, 속성/태그 포함).
- **Trace Context**: W3C 표준 헤더(`traceparent: 00-4bf92f35-00f067aa-01`)를 통해 HTTP/gRPC 헤더로 전달되는 문맥.

### 비용과 관측 가능성의 상충 관계 (Cost vs Observability)
초당 100만 건의 요청을 처리하는 엔터프라이즈 시스템에서 모든 스팬을 100% 수집한다면:
- 하루 수십 테라바이트~수 페타바이트의 트레이스 데이터가 생성됩니다.
- 네트워크 송신(Egress) 대역폭 비용과 스토리지(ClickHouse, Elasticsearch, Tempo) 인프라 유지비가 기하급수적으로 폭증합니다.
- 따라서 **"전체 트레이스 중 가치 있는 일부만을 선별하여 수집하는 샘플링(Sampling)"**이 필수적입니다.

---

## 2. 헤드 기반 샘플링 (Head-based Sampling)의 구조와 치명적 한계

헤드 기반 샘플링은 **요청이 시스템에 최초로 진입하는 시점(Root Span / Ingress Gateway)**에서 샘플링 여부를 즉시 결정하는 방식입니다.

```
+-------------------------------------------------------------------------+
|                        Head-based Sampling                              |
|                                                                         |
|  [Ingress Gateway]                                                      |
|  Request In ----> [Random Roll: 1%] ---> Sampled=True  ---> Trace Kept  |
|                                     ---> Sampled=False ---> Trace Lost! |
|                                                                         |
|  (문제: 요청 진입 시점에는 이 요청이 성공할지, 500 에러를 낼지 모름!) |
+-------------------------------------------------------------------------+
```

### 2.1 동작 메커니즘
- 인그레스 게이트웨이의 추적 SDK(Envoy, Nginx, Spring Cloud Gateway)가 확률적 비율(예: 1% 또는 5%)로 난수를 생성합니다.
- 샘플링하기로 결정되면 W3C 헤더의 Trace Flags 비트를 `01`(Sampled)로 설정하여 다운스트림으로 전파합니다.
- 하위 모든 마이크로서비스는 부모의 샘플링 플래그를 그대로 상속(ParentBased Sampler)받아 스팬을 기록하거나 건너뜁니다.

### 2.2 치명적 한계: 장애 트레이스 증발 참사
1. **사전 맹목성 (Blind at Ingress)**:
   - 요청이 인그레스에 들어오는 시점에는 이 요청이 10ms 만에 정상 완료될지, 3단계 깊은 결제 DB에서 데드락에 걸려 3500ms 후 504 타임아웃을 낼지 전혀 알 수 없습니다.
2. **희귀 장애의 99% 영구 유실**:
   - 1% 샘플링을 적용하면, 시스템에서 발생한 치명적인 HTTP 500 장애와 p99 극단 지연 스파이크 트레이스 또한 99%의 확률로 쓰레기통에 버려집니다.
   - SRE 엔지니어가 알람을 받고 Jaeger/Tempo 대시보드에서 에러 트레이스를 검색하면 아무것도 나타나지 않는 **관측성 블랙홀(Observability Blackhole)**이 발생합니다.

---

## 3. 테일 기반 샘플링 (Tail-based Sampling)의 구원 원리

테일 기반 샘플링은 모든 마이크로서비스가 생성한 스팬을 중간 계층인 **OpenTelemetry Collector**로 일단 전송한 뒤, **전체 트레이스가 완료된 후 그 결과(에러 유무, 총 소요 시간 등)를 종합 평가하여 선별 수집**하는 아키텍처입니다.

```
+-------------------------------------------------------------------------+
|                    Tail-based Sampling (OTel Collector)                 |
|                                                                         |
|  [All Services] ---> Emits 100% Spans ---> [OpenTelemetry Collector]   |
|                                                       |                 |
|                     +---------------------------------+                 |
|                     | Trace In-Memory Buffer (Ring)   |                 |
|                     | [decision_wait: 3000ms]         |                 |
|                     +---------------------------------+                 |
|                                       |                                 |
|               [Composite Sampling Policy Evaluation]                    |
|               ├── 1. Error Policy: status == ERROR?  --> 100% KEEP!     |
|               ├── 2. Latency Policy: duration > 1s?  --> 100% KEEP!     |
|               └── 3. Normal Policy: 200 OK & Fast    --> 1% Sample      |
+-------------------------------------------------------------------------+
```

### 3.1 3대 핵심 평가 정책
1. **에러 정책 (`status_code` / `http_status`)**:
   - 트레이스 내 어느 자식 스팬이라도 `status_code == "ERROR"`이거나 `http.status_code >= 500`인 경우 100% 보존합니다.
   - 최하위 데이터베이스나 외부 PG사에서만 발생한 에러라도 완벽하게 추적됩니다.
2. **지연시간 정책 (`numeric_attribute` / `latency`)**:
   - 루트 스팬부터 리프 스팬까지의 총 지속 시간(`max(end_time) - min(start_time)`)이 임계치(예: 1000ms)를 초과하는 모든 트레이스를 100% 보존하여 슬로우 쿼리 및 병목을 포착합니다.
3. **정상 트레이스 선별 정책 (`probabilistic`)**:
   - 에러도 없고 지연도 없는 평범한 요청은 1% 미만의 극소수만 수집하여 스토리지 비용을 90% 이상 절감합니다.

---

## 4. 대규모 분산 환경에서의 핵심 과제와 해결책

테일 기반 샘플링은 인메모리 버퍼링을 동반하므로, 고성능 분산 인프라에서 두 가지 핵심 기술적 난제를 해결해야 합니다:

### 4.1 Trace ID 기반 로드 밸런싱 (Load-balancing Exporter)
- OpenTelemetry Collector가 여러 대(클러스터)로 스케일아웃되어 있을 때, 동일한 Trace ID에 속한 스팬들이 서로 다른 수집기로 분산되면 전체 트레이스를 완성할 수 없습니다.
- 프론트엔드 라우터나 **Load-balancing Exporter**가 Trace ID를 일관된 해싱(Consistent Hashing)하여, 동일 트레이스의 모든 스팬이 항상 동일한 Collector 노드로 전송되도록 보장합니다.

### 4.2 메모리 리미터와 조기 축출 (Memory Limiter & Flow Control)
- 블랙 프라이데이 등 대규모 트래픽 버스트 시 인메모리 버퍼에 수백만 개의 트레이스가 쌓이면 Collector가 OOM(Out of Memory)으로 연쇄 크래시할 위험이 있습니다.
- **메모리 리미터 프로세서(`memory_limiter`)**:
  - 메모리 사용량이 임계치(예: 80%)에 도달하면, OOM으로 뻗는 대신 `decision_wait`가 덜 끝난 오래된 정상 트레이스를 조기 평가(Early Evaluation)하여 버퍼에서 안전하게 방출합니다.
  - 이를 통해 메모리 안정성을 유지하면서도 에러 트레이스의 유실을 0건으로 통제합니다.

---

## 5. Head-based vs Tail-based 종합 비교

| 비교 항목 | Head-based Sampling | Tail-based Sampling |
|---|---|---|
| **결정 시점** | 요청 시작 시 (Ingress Gateway) | **트레이스 완료 후 (OTel Collector)** |
| **에러 트레이스 포착** | 확률적 유실 (95%~99% 유실) | **100% 전수 포착 보장** |
| **지연 스파이크 포착** | 사전 감지 불가 (유실) | **지연시간 임계치 기준 100% 포착** |
| **스토리지 비용 절감** | 단순 비율로 절감 | **노이즈는 버리고 핵심 트레이스만 압축 저장** |
| **인프라 복잡도** | 매우 단순 (SDK 설정만으로 가능) | OTel Collector 클러스터 및 버퍼 관리 필요 |
| **메모리 오버헤드** | 애플리케이션/게이트웨이 0에 수렴 | 수집기 인메모리 버퍼 및 메모리 리미터 필요 |
| **적합한 환경** | 소규모 모놀리스, 단순 트래픽 | **대규모 분산 MSA, 핀테크/이커머스 미션 크리티컬 인프라** |
