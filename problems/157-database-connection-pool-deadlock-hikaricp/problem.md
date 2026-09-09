# #157 트래픽이 조금 늘었을 뿐인데 왜 DB 커넥션 풀이 30초간 굳어버려요?!: 중첩 트랜잭션 커넥션 풀 고갈 데드락(HikariCP Pool Starvation)과 수학적 최소 풀 사이징 공식 (Database Connection Pool Deadlock & HikariCP Sizing Formula)

## 1. 실무 장애 시나리오: "평소엔 멀쩡하던 결제 API가 트래픽 조금 늘었다고 30초간 굳더니 Connection Timeout으로 폭사해요?!"

글로벌 핀테크/결제 플랫폼 '젤리페이'의 백엔드 엔지니어 태호는 결제 승인 후 감사 로그(Audit Log)를 남기는 비즈니스 로직을 개발했습니다. 결제 트랜잭션이 실패하더라도 감사 로그는 반드시 독립적으로 DB에 커밋되어야 했기에, 스프링 트랜잭션 전파 속성으로 `@Transactional(propagation = Propagation.REQUIRES_NEW)`를 적용했습니다:

```java
@Service
public class PaymentService {
    @Autowired
    private AuditLogService auditLogService;

    // [부모 트랜잭션: DB 물리 커넥션 #1 획득 및 점유]
    @Transactional
    public void processPayment(PaymentRequest req) {
        deductBalance(req); // 잔액 차감 (커넥션 #1 사용)

        // [자식 트랜잭션: REQUIRES_NEW로 인해 DB 물리 커넥션 #2 추가 획득 시도!]
        auditLogService.recordAuditLog(req.getId(), "PAYMENT_SUCCESS");

        completeOrder(req); // 주문 완료 (커넥션 #1 사용)
    }
}
```

평상시 QA 환경이나 개발 환경에서는 아무런 문제가 없었습니다. Spring Boot의 기본 커넥션 풀 라이브러리인 **HikariCP**의 기본 설정(`maximum-pool-size = 10`)으로도 모든 기능이 원활하게 동작했습니다.

그러나 금요일 저녁 타임세일 이벤트가 시작되자마자 **치명적인 프로덕션 마비 사태**가 터졌습니다:
* 동시 결제 요청이 단 10건 들어오는 순간, **서버의 모든 스레드가 30초 동안 완전히 얼어붙었습니다(Thread Freeze)**.
* 30초 뒤, 톰캣의 모든 워커 스레드에서 다음과 같은 치명적인 에러가 쏟아졌습니다:
```
org.springframework.transaction.CannotCreateTransactionException: 
Could not open JPA EntityManager for transaction; nested exception is 
org.hibernate.exception.JDBCConnectionException: 
HikariPool-1 - Connection is not available, request timed out after 30000ms.
```
* CPU 점유율은 3%에 불과하고 DB에 아무런 Row Lock 경합도 없는데, **오직 DB 커넥션을 얻지 못해 수백 건의 결제 요청이 줄줄이 타임아웃 폭사**한 것입니다!

긴급 소집된 데이터베이스 인프라 수석 아키텍트 민우 님이 화이트보드에 스레드와 커넥션 풀 상태를 그리며 원인을 설명해주었습니다:

> "태호 님! 이것은 DB 쿼리 문제가 아니라, **'HikariCP 커넥션 풀 자체에서 발생한 상호 대기 데드락(Pool Starvation Deadlock)'**입니다!  
> 10개의 스레드가 동시에 `processPayment()`에 진입하여 풀에 있던 10개의 커넥션을 1개씩 낚아챘습니다.  
> 그리고 `recordAuditLog()`를 호출하는 순간, **부모 커넥션을 손에 쥔 채로 2번째 자식 커넥션을 요청**했습니다!  
> 하지만 풀에는 남은 커넥션이 0개입니다! 10개 스레드 모두 HikariCP 대기열에 들어가 서로가 커넥션을 반납하기만을 기다리며 영구 대기(Deadlock)에 빠진 것입니다!  
> HikariCP 창시자 Brett Wooldridge가 제시한 **수학적 최소 풀 크기 공식**을 적용해야 합니다:  
> $$\text{Pool Size} \ge T_n \times (C_m - 1) + 1$$  
> 스레드 10개가 커넥션을 2개씩 필요로 한다면, 최소 $10 \times (2 - 1) + 1 = \mathbf{11}$개의 커넥션이 있어야만 비둘기집 원리에 의해 최소 1개 스레드가 작업을 완주하고 커넥션을 반납하여 연쇄적으로 풀이 해소됩니다! 기본값 10개는 **단 1개가 부족하여 100% 데드락에 빠지는 마법의 숫자**였던 것이죠!"

태호는 민우 님의 조언에 따라 커넥션 풀 시뮬레이터를 개발하여, 동시 유입되는 작업 패턴과 풀 크기에 따른 데드락 발생 여부 및 안전 풀 크기를 정밀 계산하고 검증하기로 했습니다.

---

## 2. 핵심 이론: HikariCP 최소 풀 사이징 공식과 비둘기집 원리

```
[커넥션 풀 10개, 스레드 10개 동시 REQUIRES_NEW 진입 시 데드락]
스레드:   T1   T2   T3   T4   T5   T6   T7   T8   T9   T10
부모 점유: C1   C2   C3   C4   C5   C6   C7   C8   C9   C10  (풀 10개 전원 소진!)
자식 요청: [대기][대기][대기][대기][대기][대기][대기][대기][대기][대기] (잔여 0개 -> 영구 데드락!)

[커넥션 풀 11개 (공식 적용: 10 * 1 + 1 = 11) 적용 시]
부모 점유: C1   C2   C3   C4   C5   C6   C7   C8   C9   C10
잔여 풀:   [ C11 ]  ==> T1에게 C11 할당!
T1 완주:  T1이 C11, C1 반납! ==> 풀에 2개 반납 ==> T2, T3 완주... 전원 성공!
```

* **공식**: $\text{Safe Minimum Pool Size} = T_n \times (C_m - 1) + 1$
  - $T_n$: 동시 실행 스레드 수 (동시 작업 수)
  - $C_m$: 스레드 1개가 동시에 필요로 하는 최대 커넥션 수 (`nested_depth`)
* 풀 크기가 이 공식보다 작고 모든 스레드가 동시에 자식 커넥션을 요청하면, 모든 가용 커넥션이 부모에게 물려 100% 데드락(`CONNECTION_POOL_DEADLOCK_COLLAPSE`)에 빠집니다.
* 풀 크기가 공식 이상이면, 최소 1개 스레드가 필요한 모든 커넥션을 얻어 작업을 마치고 반납하므로 전원 정상 완료(`OPTIMAL_POOL_EXECUTION`)됩니다.

---

## 3. 문제 요구사항

입력으로 주어지는 커넥션 풀 크기(`pool_size`), 커넥션 대기 타임아웃(`connection_timeout_ms`), 그리고 작업 목록(`tasks`)을 바탕으로 이벤트 기반 시뮬레이션을 수행하고, 데드락 발생 여부와 태스크별 실행 경과, 안전 풀 크기를 계산하여 JSON 형식으로 출력하는 프로그램을 작성하세요.

### 상세 규칙
1. **작업 라이프사이클**:
   * `nested_depth == 1` (단일 트랜잭션):
     - `parent` 커넥션 요청 $\to$ 획득 후 `parent_duration_ms` 동안 작업 $\to$ 반납 후 `COMPLETED`.
   * `nested_depth == 2` (`REQUIRES_NEW` 중첩 트랜잭션):
     - `parent` 커넥션 요청 $\to$ 획득 후 `parent_duration_ms // 2` 동안 작업.
     - **부모 커넥션을 유지한 채** `child` 커넥션 추가 요청.
     - `child` 커넥션 획득 후 `child_duration_ms` 동안 작업 $\to$ 자식 커넥션 반납.
     - 잔여 부모 작업(`parent_duration_ms - parent_duration_ms // 2`) 수행 $\to$ 부모 커넥션 반납 후 `COMPLETED`.
2. **커넥션 획득 및 대기**:
   * 가용 커넥션이 있으면 즉시 획득, 없으면 FIFO 대기열에 진입.
   * 대기 시간이 `connection_timeout_ms`를 초과하면 즉시 `TIMED_OUT` 처리되며, 점유 중이던 부모 커넥션이 즉시 풀에 롤백/반납됨.
3. **데드락 판정**:
   * 타임아웃 발생 태스크가 존재하고, 풀 크기가 공식($T_n \times (C_m - 1) + 1$) 미만이며 $C_m > 1$인 경우:
     `deadlock_detected = true`, `overall_verdict = "CONNECTION_POOL_DEADLOCK_COLLAPSE"`.
   * 모든 태스크가 성공적으로 완료되면:
     `deadlock_detected = false`, `overall_verdict = "OPTIMAL_POOL_EXECUTION"`.

---

## 4. 입력 및 출력 형식

### 입력 형식 (Standard Input - JSON)
```json
{
  "pool_size": 10,
  "connection_timeout_ms": 1000,
  "tasks": [
    {"task_id": "T1", "arrival_time_ms": 0, "nested_depth": 2, "parent_duration_ms": 50, "child_duration_ms": 50},
    {"task_id": "T2", "arrival_time_ms": 0, "nested_depth": 2, "parent_duration_ms": 50, "child_duration_ms": 50}
  ]
}
```

### 출력 형식 (Standard Output - JSON)
```json
{
  "summary": {
    "total_tasks": 10,
    "completed_tasks": 5,
    "failed_tasks": 5,
    "deadlock_detected": true,
    "timed_out_tasks": ["T1", "T2", "T3", "T4", "T5"],
    "max_pool_utilization": 10,
    "safe_pool_size_calculated": 11,
    "overall_verdict": "CONNECTION_POOL_DEADLOCK_COLLAPSE"
  },
  "tasks": [
    {
      "task_id": "T1",
      "status": "TIMED_OUT",
      "parent_acquired_at": 0,
      "child_requested_at": 25,
      "child_acquired_at": null,
      "finished_at": 1025,
      "error": "ConnectionTimeoutException: Connection not available within 1000ms"
    }
  ],
  "diagnosis": "CRITICAL: HikariCP connection pool starvation deadlock detected! 5 threads timed out waiting for child connections. Formula Pool Size >= T * (C - 1) + 1 requires at least 11 connections, but pool size is only 10."
}
```
