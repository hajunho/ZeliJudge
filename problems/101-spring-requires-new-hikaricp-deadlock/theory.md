# 101. 트랜잭션 분리(REQUIRES_NEW) 걸었을 뿐인데 왜 동시 요청 10개에 전사 DB가 뻗어요?!: HikariCP 커넥션 풀 고갈 데드락(Connection Pool Deadlock)과 자원 할당 공식

---

## 1. 비극의 시작: 로그 하나 남기려다 터진 전사 장애

스타트업 백엔드 개발자 준호는 결제 승인 비즈니스 로직을 개발하며 아주 똑똑한 생각을 했습니다:
> *"결제 트랜잭션이 어떤 이유로 실패(Rollback)하더라도, 사용자가 어떤 시도를 했는지는 감사 로그(Audit Log) 테이블에 반드시 남겨야 해! 부모 트랜잭션이 롤백되어도 로그는 독립적으로 커밋되도록 스프링의 `@Transactional(propagation = Propagation.REQUIRES_NEW)`를 쓰자!"*

```java
@Service
public class PaymentService {
    @Autowired private AuditLogService auditLogService;

    @Transactional // 부모 트랜잭션: DB 커넥션 1개 점유 (C1)
    public void processPayment(Order order) {
        // 1. 주문 검증 및 처리
        orderRepository.save(order);

        // 2. 실패해도 무조건 남아야 하는 감사 로그 (새 트랜잭션!)
        // REQUIRES_NEW: 부모 커넥션을 쥐고 있는 상태에서 새 DB 커넥션 1개 추가 점유 (C2)!
        auditLogService.logPaymentAttempt(order.getId()); 

        // 3. 결제 완료
        paymentGateway.charge(order);
    }
}
```

로컬 환경이나 사내 테스트 서버에서는 테스트 케이스 100개가 모두 100% 초록불(PASS)을 뿜었습니다.  
스프링 부트의 기본 HikariCP 커넥션 풀 크기는 **10개(`maximum-pool-size: 10`)**였습니다.

하지만 서비스 오픈 첫날, 동시 결제 요청이 딱 **10개** 들어오는 순간, 전사 서버가 돌처럼 굳어버렸습니다:
- CPU 사용률 0%, 메모리 사용률 10%, 네트워크 트래픽 0%.
- 하지만 모든 사용자의 결제창이 30초 동안 뱅글뱅글 돌더니 일제히 500 에러를 뿜었습니다!

```text
java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms.
    at com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:217)
    at org.springframework.jdbc.datasource.DataSourceUtils.getConnection(DataSourceUtils.java:82)
```

**"동시 요청이 고작 10명 들어왔는데 왜 10개짜리 커넥션 풀이 30초 동안 타임아웃나서 전사 서비스가 마비된 거지?!"**

---

## 2. 현실 비유: 볼펜 10자루와 양손 쓰기 규칙

은행 창구에 고객을 위한 **볼펜 10자루(커넥션 풀 10개)**가 비치되어 있습니다:
1. **업무 규칙 (REQUIRES_NEW)**:
   - 한 손님(스레드)이 업무를 보려면 **동시에 2자루의 볼펜**이 필요합니다.
   - 오른손으로 본 계약서(부모 트랜잭션)를 쓰고, **그 볼펜을 절대 놓지 않은 채로** 왼손으로 서약서(REQUIRES_NEW 자식 트랜잭션)를 써야 합니다.
   - 서약서를 다 써서 왼손 볼펜을 반납해야 비로소 본 계약서 업무가 끝나 오른손 볼펜도 반납합니다.
2. **평화로운 상황 (손님 1~2명)**:
   - 손님 A가 들어와 오른손에 볼펜 1자루(C1), 왼손에 볼펜 1자루(C2)를 쥐고 서약서 쓰고 본 계약서 쓰고 볼펜 2자루를 모두 반납합니다.
3. **참사의 순간 (손님 10명 동시 입장)**:
   - 10명의 손님(스레드 10개)이 창구로 동시에 우르르 몰려왔습니다.
   - 10명이 각자 **오른손에 볼펜을 1자루씩 쥐었습니다.**
   - 이제 창구 책상 위에 남아있는 볼펜은 **0자루(풀 완전 고갈)**입니다!
   - 10명의 손님 모두 왼손을 내밀며 **"왼손에 쥘 볼펜 1자루 더 주세요!"**라고 외칩니다.
   - 하지만 10명 모두 **"오른손 볼펜은 본 계약서가 끝나기 전까지 절대 내려놓을 수 없다(점유 대기)!"**며 볼펜을 꽉 쥔 채 서로가 볼펜을 내려놓기만을 기다립니다.
4. **결과**:
   - 10명 모두 단 1글자도 더 쓰지 못하고 멍하니 서 있다가, 30분 뒤 은행 문을 닫으며(타임아웃 30,000ms) 전원 쫓겨났습니다!

---

## 3. 컴퓨터 과학 / 자원 할당 이론

### 1) 코프만(Coffman) 교착상태 4대 조건
이 참사는 컴퓨터 과학 교과서에 나오는 전형적인 **자원 할당 그래프(Resource Allocation Graph)의 순환 교착상태(Deadlock)**입니다:
1. **상호 배제 (Mutual Exclusion)**: DB 커넥션은 한 번에 한 스레드만 사용할 수 있다.
2. **점유 대기 (Hold and Wait)**: 부모 트랜잭션 커넥션을 쥔 채로 자식 트랜잭션 커넥션을 추가로 요구한다.
3. **비선점 (No Preemption)**: 다른 스레드가 쥐고 있는 커넥션을 강제로 뺏어올 수 없다.
4. **순환 대기 (Circular Wait)**: 10개 스레드 모두가 상대방의 커넥션 반납을 기다리는 대기 루프가 형성된다.

### 2) HikariCP 공식 커넥션 풀 데드락 회피 공식
HikariCP 창시자(Brett Wooldridge)는 단일 스레드가 복수의 커넥션을 요구하는 시스템에서 교착상태를 수학적으로 방지하는 공식을 명시했습니다:

$$	ext{Pool Size} = T_n 	imes (C_m - 1) + 1$$

- $T_n$: 시스템의 최대 동시 스레드 수 (예: 톰캣 워커 스레드 10개)
- $C_m$: 단일 스레드가 동시에 점유하는 최대 커넥션 수 (부모 1개 + REQUIRES_NEW 1개 = 2개)

스레드가 10개라면, 데드락을 방지하기 위한 최소 커넥션 풀 크기는:
$$	ext{Pool Size} = 10 	imes (2 - 1) + 1 = 11	ext{개}$$

- 풀이 **10개**일 때는 10개 스레드가 각각 1개씩 쥐면 잔여가 0개가 되어 100% 데드락이 터집니다.
- 풀이 **11개**라면, 10개 스레드가 1개씩 쥐어도 **적어도 1자루의 여분 볼펜이 남아있으므로**, 어떤 한 스레드가 그 볼펜을 쥐고 자식 작업을 끝내 2자루를 모두 반납할 수 있습니다! 연쇄적으로 모든 스레드가 작업을 완수합니다!

---

## 4. 실무 아키텍처 및 튜닝 모범 사례

1. **`REQUIRES_NEW`의 남용 금지**:
   - 감사 로그나 알림 발송은 동일 트랜잭션 또는 동일 요청 스레드에서 처리하지 말고, 스프링 이벤트(`@TransactionalEventListener(phase = AFTER_COMPLETION)`)나 비동기 큐(Kafka, SQS)로 분리하여 메인 커넥션을 즉시 반납하게 만들어야 합니다.
2. **커넥션 풀 크기 재산정**:
   - 부득이하게 단일 스레드 내에서 중첩 트랜잭션을 사용해야 한다면, $T_n 	imes (C_m - 1) + 1$ 공식을 철저히 적용하여 풀 크기를 설계해야 합니다.
3. **`connection-timeout` 모니터링**:
   - HikariCP의 `connectionTimeout` 기본값은 30초입니다. 데드락 발생 시 30초 동안 스레드가 잠겨 톰캣 스레드 풀까지 연쇄 고갈되므로, 비정상 대기를 빠르게 감지하고 실패하도록 타임아웃을 합리적으로(예: 3초~5초) 조율해야 합니다.
