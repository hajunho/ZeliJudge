# 데이터베이스 커넥션 풀 데드락(Connection Pool Deadlock)과 HikariCP 수학적 풀 사이징 공식

## 1. 개요 및 실무 장애 시나리오: "트래픽이 조금 늘었을 뿐인데 왜 DB 커넥션 풀이 30초간 굳어버려요?!"

글로벌 결제 플랫폼 '젤리페이'의 백엔드 엔지니어 태호는 결제 승인 후 감사 로그(Audit Log)를 남기는 비즈니스 로직을 작성했습니다. 결제 트랜잭션이 실패하더라도 감사 로그는 반드시 독립적으로 DB에 커밋되어야 했기에, 스프링 트랜잭션 전파 속성으로 `@Transactional(propagation = Propagation.REQUIRES_NEW)`를 적용했습니다:

```java
@Service
public class PaymentService {
    @Autowired
    private AuditLogService auditLogService;

    // [부모 트랜잭션: DB 커넥션 #1 획득 및 점유]
    @Transactional
    public void processPayment(PaymentRequest req) {
        deductBalance(req); // 계좌 잔액 차감 (커넥션 #1 사용)

        // [자식 트랜잭션: REQUIRES_NEW로 인해 DB 커넥션 #2 추가 획득 시도!]
        auditLogService.recordAuditLog(req.getId(), "PAYMENT_SUCCESS");

        completeOrder(req); // 주문 완료 처리 (커넥션 #1 사용)
    }
}

@Service
public class AuditLogService {
    // 부모 트랜잭션과 별개로 독립 커밋해야 하므로 새 물리 커넥션 필요!
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordAuditLog(Long orderId, String action) {
        auditLogRepository.save(new AuditLog(orderId, action));
    }
}
```

평상시 QA 환경이나 트래픽이 적을 때는 아무 문제 없이 동작했습니다.  
Spring Boot의 기본 커넥션 풀 라이브러리인 **HikariCP**의 기본 설정(`maximum-pool-size = 10`)으로도 초당 수십 건은 가뿐히 처리되었습니다.

그러나 금요일 저녁 타임세일 이벤트가 시작되자마자 **끔찍한 프로덕션 마비 사태**가 터졌습니다:
* 동시 결제 요청이 단 10건 들어오는 순간, **서버의 모든 스레드가 30초 동안 얼어붙었습니다(Thread Freeze)**.
* 30초 뒤, 톰캣의 모든 워커 스레드에서 다음과 같은 치명적인 에러가 폭풍처럼 쏟아졌습니다:
```
org.springframework.transaction.CannotCreateTransactionException: 
Could not open JPA EntityManager for transaction; nested exception is 
org.hibernate.exception.JDBCConnectionException: 
HikariPool-1 - Connection is not available, request timed out after 30000ms.
```
* CPU 점유율은 5%도 안 되고, 데이터베이스 쿼리도 아무 락(Row Lock)이 걸려있지 않은데, **오직 DB 커넥션 풀을 얻지 못해 100건이 넘는 결제 요청이 줄줄이 타임아웃 폭사**한 것입니다!

---

## 2. 참사의 근본 원인: 커넥션 풀 기아 데드락 (Connection Pool Starvation Deadlock)

태호는 코드를 뜯어보고 충격적인 사실을 발견했습니다.  
원인은 데이터베이스의 테이블 락이나 데드락이 아니라, **"HikariCP 커넥션 풀 자체에서 발생한 상호 대기 데드락(Pool Starvation Deadlock)"**이었습니다!

```
[커넥션 풀 크기 10, 동시 요청 10개 진입 시 데드락 발생 메커니즘]

1. 스레드 T1 ~ T10 (총 10개)이 동시에 processPayment() 진입:
   - 각 스레드가 부모 트랜잭션을 시작하며 HikariCP에서 커넥션을 1개씩 획득!
   - 획득된 커넥션: Conn 1, Conn 2, ..., Conn 10 (풀의 10개 모두 소진!)
   - 풀의 잔여 가용 커넥션: [ 0개 ]!

2. 스레드 T1 ~ T10이 각각 auditLogService.recordAuditLog() 호출:
   - REQUIRES_NEW 속성으로 인해, 부모 커넥션(Conn 1~10)을 손에 꼭 쥔 채
     새로운 물리 커넥션을 풀에 추가로 요청함!
   - 하지만 풀에는 남은 커넥션이 0개!
   - T1 ~ T10은 모두 HikariCP의 대기 큐(Waiters Queue)에 들어가 블로킹됨!

3. 상호 대기 데드락 완성:
   - T1이 커넥션을 얻으려면? 누군가 커넥션을 반납해야 함.
   - 다른 스레드(T2~T10)가 커넥션을 반납하려면? 자식 작업이 끝나야 부모가 끝남.
   - 하지만 T2~T10 역시 자식 커넥션을 얻지 못해 멈춰 있음!
   - 10개의 스레드가 서로가 커넥션을 뱉어내기만을 기다리며 영구 대기!

4. 30초 후:
   - HikariCP의 기본 connection-timeout(30,000ms)이 만료되며 10개 스레드 전원 폭사!
```

---

## 3. 수학적 증명: HikariCP 최소 풀 사이징 공식 (The Sizing Formula)

HikariCP 창시자 Brett Wooldridge는 중첩 트랜잭션 환경에서 커넥션 풀 데드락을 원천 방지하기 위한 **수학적 최소 풀 크기 공식(비둘기집 원리)**을 제시했습니다:

$$	ext{Pool Size} \ge T_n 	imes (C_m - 1) + 1$$

* $T_n$ (**Thread Count**): 애플리케이션에서 동시에 실행될 수 있는 최대 스레드 수 (예: 동시 요청 수 또는 톰캣 스레드 풀 크기).
* $C_m$ (**Connections per Thread**): 단일 스레드가 동시에 점유할 수 있는 최대 커넥션 수.
  - 일반적인 단일 트랜잭션: $C_m = 1$
  - `REQUIRES_NEW` 또는 비동기 블로킹 중첩: $C_m = 2$
  - 3중 중첩 트랜잭션: $C_m = 3$

### 비둘기집 원리(Pigeonhole Principle)에 의한 증명
최악의 시나리오를 가정해 봅시다:
1. 모든 스레드($T_n$개)가 자식 커넥션을 요청하기 직전까지 도달하여, 각각 $C_m - 1$개의 커넥션을 이미 점유하고 있습니다.
2. 이때 모든 스레드가 소모한 총 커넥션 수는 $T_n 	imes (C_m - 1)$개입니다.
3. 만약 풀 크기가 정확히 $T_n 	imes (C_m - 1)$개라면? **남은 커넥션이 0개이므로 100% 데드락에 빠집니다!**
4. 하지만 여기에 **단 1개(+1)의 커넥션이 더 존재한다면?**
   - 어떤 1개의 스레드는 반드시 마지막 $C_m$번째 커넥션을 획득할 수 있습니다!
   - 그 스레드는 작업을 완료하고 자신이 쥐고 있던 $C_m$개의 커넥션을 모두 풀에 반납합니다!
   - 반납된 커넥션을 다른 스레드가 이어받아 연쇄적으로 모든 스레드가 데드락 없이 완료됩니다!

> **실무 예시**:  
> 동시 요청 스레드가 10개이고 `REQUIRES_NEW`($C_m = 2$)를 쓴다면:  
> 최소 안전 풀 크기 = $10 	imes (2 - 1) + 1 = \mathbf{11}$개!  
> 기본값 10개를 쓰면 **단 1개 부족하여 100% 데드락으로 폭사**하지만, 11개로 설정하면 단 한 건의 타임아웃 없이 완벽하게 통과합니다!

---

## 4. 프로덕션 아키텍처 개선 가이드

### (1) 근본적 해결: 트랜잭션 물리적 분리 (안티패턴 제거)
커넥션 풀을 무작정 늘리는 것은 DB 서버 메모리와 프로세스 컨텍스트 스위칭 비용을 가중시킵니다. 가장 우아한 실무 해결책은 **부모 트랜잭션이 커넥션을 쥔 채로 자식 커넥션을 기다리지 않게 만드는 것**입니다:

* **Spring Event / `@TransactionalEventListener` 활용**:
  ```java
  // 결제 완료 후 트랜잭션 커밋이 완료된(AFTER_COMMIT) 시점에 감사 로그 비동기 기록!
  @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
  @Async
  public void handleAuditLogEvent(PaymentCompletedEvent event) {
      auditLogService.recordAuditLog(event.getId()); // 부모 커넥션 이미 반납됨!
  }
  ```
* **Kafka / MQ 비동기 이벤트 발행**: 감사 로그나 알림 발송은 인메모리 트랜잭션에서 분리하여 메시지 큐로 위임.

### (2) HikariCP 프로덕션 필수 설정
```properties
# 1. 수학적 공식에 맞춘 풀 크기 설정
spring.datasource.hikari.maximum-pool-size=20

# 2. 장애 전파 방지를 위해 커넥션 타임아웃을 3초로 축소 (기본 30초는 너무 김!)
spring.datasource.hikari.connection-timeout=3000

# 3. 커넥션 누수 조기 탐지 (2초 이상 커넥션을 물고 있으면 경고 로그 스택트레이스 출력)
spring.datasource.hikari.leak-detection-threshold=2000
```
