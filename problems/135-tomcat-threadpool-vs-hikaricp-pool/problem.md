# 135. DB 커넥션을 100개나 줬는데 왜 스레드 2,000개가 줄서다 톰캣이 뻗어요?!: 스레드 풀(Thread Pool) vs 커넥션 풀(Connection Pool)의 불균형과 리틀의 법칙(Little's Law) & 톰캣 큐 포화 참사

## 문제 설명

이커머스 결제/주문 시스템의 백엔드 엔지니어 젤리(Zeli)는 대규모 프로모션 트래픽을 감당하기 위해 스프링 부트(Spring Boot) 애플리케이션의 톰캣(Tomcat) 스레드 풀을 대폭 늘렸습니다:

```yaml
# application.yml
server:
  tomcat:
    threads:
      max: 1000        # 동시성을 높이겠다고 스레드를 1,000개로 뻥튀기!
    accept-count: 500  # 톰캣 대기 큐도 500개로 넉넉하게 설정!

spring:
  datasource:
    hikari:
      maximum-pool-size: 10  # DB 과부하를 막기 위해 커넥션은 10개로 작게 유지!
      connection-timeout: 100 # 100ms 동안 커넥션 못 얻으면 타임아웃
```

*"스레드를 1,000개나 줬으니 동시 요청이 1,000개가 몰려와도 끄떡없겠지?!"* 😎

하지만 할인 행사 오픈 10초 만에 특정 상품 재고를 확인하는 복잡한 SQL 쿼리가 슬로우 쿼리(200ms 지연)로 돌변하면서 전사 서비스 모니터링에 충격적인 경보가 울렸습니다! 🚨

```
[ALERT] Active Tomcat Threads: 600 / 1000 (스레드 600개 폭증!)
[ALERT] JVM Memory Spike: Thread Stack Memory Consumption > 500MB!
[ALERT] CPU Usage: 100% (OS Context Switching 폭풍!)
[ERROR] org.springframework.dao.CannotAcquireLockException: ConnectionTimeout
[ERROR] 504 Gateway Timeout (대다수 결제 트랜잭션 마비!)
```

서버 CPU는 스레드 수백 개 간의 컨텍스트 스위칭(Context Switching)으로 100% 포화되었고, 수백 개의 톰캣 스레드가 DB 커넥션을 얻지 못해 줄줄이 타임아웃으로 나가떨어졌습니다! 😱

---

### 원인: 리틀의 법칙(Little's Law)과 병목 자원(DB 커넥션)의 불균형

대기행렬 이론(Queueing Theory)의 핵심인 **리틀의 법칙(Little's Law)**:

$$L = \lambda 	imes W$$

- $L$: 시스템 내부 동시 체류 요청 수 (활성 스레드 수)
- $\lambda$: 초당 유입 요청 수 (TPS)
- $W$: 1건당 평균 소요 시간 (Latency)

### 시스템의 실제 처리량은 가장 느린 병목 자원에 의해 결정된다!
톰캣 스레드가 1,000개든 10,000개든, DB 커넥션 풀이 10개이고 쿼리가 200ms(0.2초) 걸린다면 DB가 초당 처리할 수 있는 최대 처리량은 다음과 같습니다:

$$	ext{Max Throughput} = rac{10	ext{ connections}}{0.2	ext{ s}} = 50	ext{ TPS}$$

- DB는 초당 50건밖에 처리할 수 없는데 초당 수백 건의 요청이 쏟아지면, 톰캣 스레드가 600개까지 생성되어도 **590개의 스레드는 DB 커넥션 대기열에 멍하니 갇혀 있게 됩니다.**
- **스택 메모리 낭비**: 스레드당 1MB 스택 메모리가 할당되어 메모리가 낭비됩니다.
- **컨텍스트 스위칭 지옥**: 수백 개의 스레드가 CPU를 서로 차지하려다 스위칭 오버헤드로 CPU가 100% 마비됩니다.
- **연쇄적 다운(Cascading Failure)**: 커넥션을 제때 얻지 못한 스레드들이 504 타임아웃을 뿜어내며 시스템 전체가 붕괴합니다!

---

### 해결책: 올바른 스레드 풀 및 큐 사이징 (Fast-Fail 보호)

HikariCP 창시자의 황금 공식:

$$	ext{Connections} = (	ext{CPU Cores} 	imes 2) + 	ext{Effective Spindles}$$

- 스레드 풀을 무작정 늘리는 대신, **DB 커넥션 수용 한도에 맞추어 스레드 풀을 적절히 제한**해야 합니다.
- 톰캣 대기 큐(`accept-count`)를 적절히 설정하여, 시스템이 감당할 수 없는 초과 요청은 **즉시 503 Service Unavailable로 빠른 실패(Fast-Fail)** 처리함으로써 기존 실행 중인 트랜잭션들을 안전하게 보호해야 합니다!

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "tomcat_max_threads": 1000,          // 톰캣 최대 워커 스레드 수
  "tomcat_queue_capacity": 500,        // 톰캣 대기 큐 크기
  "hikaricp_pool_size": 10,            // HikariCP 최대 DB 커넥션 수
  "hikaricp_connection_timeout_ms": 100, // DB 커넥션 획득 대기 타임아웃 (ms)
  "requests": [
    {
      "request_id": "req_001",
      "timestamp_ms": 0,
      "query_duration_ms": 200         // DB 쿼리 실행 소요 시간 (ms)
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다:

```json
{
  "summary": {
    "tomcat_max_threads": 1000,
    "tomcat_queue_capacity": 500,
    "hikaricp_pool_size": 10,
    "total_requests": 600,
    "completed_requests": 30,
    "rejected_queue_full": 0,
    "rejected_db_timeout": 570,
    "peak_active_threads": 600,
    "peak_tomcat_queue": 0,
    "peak_hikari_active": 10,
    "thread_stack_memory_mb": 600,
    "overall_verdict": "THREAD_POOL_SATURATION_CASCADE_FAILURE"
  },
  "sample_results": [
    {
      "request_id": "req_001",
      "status": "SUCCESS",
      "finish_time_ms": 200
    }
  ]
}
```

---

## 제약 사항 및 상태 판정 기준

- 스레드 스택 메모리: 활성 스레드 1개당 1MB 계산 (`thread_stack_memory_mb = peak_active_threads * 1`).
- `overall_verdict` 판정 기준:
  - `rejected_db_timeout > 0`:
    - `peak_active_threads >= 500`이면 `"THREAD_POOL_SATURATION_CASCADE_FAILURE"`
    - `peak_active_threads < 500`이면 `"DB_BOTTLENECK_QUEUE_EXHAUSTION"`
  - `rejected_db_timeout == 0`이고 `rejected_queue_full > 0`:
    - `"TOMCAT_QUEUE_OVERFLOW_FAST_FAIL"`
  - 모든 요청이 성공적으로 처리된 경우:
    - `"BALANCED_OPTIMAL_THROUGHPUT"`
