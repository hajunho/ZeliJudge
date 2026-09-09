# 101. 트랜잭션 분리(REQUIRES_NEW) 걸었을 뿐인데 왜 동시 요청 10개에 전사 DB가 뻗어요?!: HikariCP 커넥션 풀 고갈 데드락(Connection Pool Deadlock)과 자원 할당 공식

---

## 1. 비극의 시작 (Real-World Disaster)

스타트업 백엔드 개발자 준호는 결제 승인 비즈니스 로직을 개발하며 아주 똑똑한 생각을 했습니다:
> *"결제 트랜잭션이 실패하더라도, 사용자가 어떤 결제를 시도했는지는 감사 로그(Audit Log) 테이블에 반드시 남겨야 해! 부모 트랜잭션이 롤백되어도 로그는 독립적으로 커밋되도록 스프링의 `@Transactional(propagation = Propagation.REQUIRES_NEW)`를 쓰자!"*

```java
@Service
public class PaymentService {
    @Autowired private AuditLogService auditLogService;

    @Transactional // 부모 트랜잭션: DB 커넥션 1개 점유 (C1)
    public void processPayment(Order order) {
        orderRepository.save(order);

        // REQUIRES_NEW: 부모 커넥션을 쥔 채로 새 DB 커넥션 1개 추가 점유 (C2)!
        auditLogService.logPaymentAttempt(order.getId()); 

        paymentGateway.charge(order);
    }
}
```

사내 테스트 환경에서는 동시 요청이 1~2개뿐이라 모든 단위 테스트가 100% 성공했습니다.  
스프링 부트의 기본 HikariCP 커넥션 풀 크기는 **10개(`maximum-pool-size: 10`)**였습니다.

하지만 서비스 오픈 첫날, 동시 결제 요청이 딱 **10개** 들어오는 순간, 전사 서버가 돌처럼 굳어버렸습니다:
- CPU 사용률 0%, 메모리 사용률 10%, 네트워크 트래픽 0%.
- 하지만 모든 사용자의 결제창이 30초 동안 멈추더니 일제히 500 에러를 뿜었습니다!

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
   - 오른손으로 본 계약서(부모 트랜잭션)를 쓰고, **그 볼펜을 절대 놓지 않은 채로** 왼손으로 서약서(자식 트랜잭션)를 써야 합니다.
   - 서약서를 다 써서 왼손 볼펜을 반납해야 비로소 본 계약서 업무가 끝나 오른손 볼펜도 반납합니다.
2. **참사의 순간 (손님 10명 동시 입장)**:
   - 10명의 손님이 창구로 동시에 우르르 몰려왔습니다.
   - 10명이 각자 **오른손에 볼펜을 1자루씩 쥐었습니다.**
   - 이제 창구 책상 위에 남아있는 볼펜은 **0자루(풀 완전 고갈)**입니다!
   - 10명의 손님 모두 왼손을 내밀며 **"왼손에 쥘 볼펜 1자루 더 주세요!"**라고 외칩니다.
   - 하지만 10명 모두 **"오른손 볼펜은 본 계약서가 끝나기 전까지 절대 내려놓을 수 없다(점유 대기)!"**며 볼펜을 꽉 쥔 채 서로가 볼펜을 내려놓기만을 기다립니다.
3. **결과**:
   - 10명 모두 단 1글자도 더 쓰지 못하고 멍하니 서 있다가, 30초 뒤 은행 문을 닫으며(타임아웃 30,000ms) 전원 쫓겨났습니다!

---

## 3. 핵심 아키텍처 및 요구사항

당신은 HikariCP 커넥션 풀, 부모-자식 중첩 트랜잭션 모델(`REQUIRES_NEW`), 점유 대기 상태 추적, 교착상태 감지(`POOL_DEADLOCK_DETECTED`), 타임아웃 회수, 그리고 HikariCP 공식 회피 풀 크기 계산기를 시뮬레이션해야 합니다.

### 1) 풀 기본 설정 (`CONFIG_POOL`)
- `CONFIG_POOL <pool_size> <timeout_ms>`
  - 커넥션 풀 크기와 커넥션 대기 타임아웃(ms)을 설정합니다.
  - 출력: `CONFIG_POOL_OK pool_size=<size> timeout=<timeout_ms>ms`

### 2) 트랜잭션 요청 시작 (`START_REQUEST`)
- `START_REQUEST <thread_id> <requires_nested_new:TRUE|FALSE>`
  - 1단계: 부모 트랜잭션을 위한 1번째 커넥션을 요청합니다.
  - 풀에 여유 커넥션이 있다면:
    - 커넥션 1개 할당 (`has_parent_conn = True`).
    - 만약 `requires_nested_new == FALSE`:
      - 자식 커넥션이 필요 없으므로 즉시 실행 가능.
      - 출력: `REQUEST_STARTED thread=<thread_id> parent_conn=ACQUIRED nested=NONE status=RUNNING available_pool=<avail>`
    - 만약 `requires_nested_new == TRUE`:
      - 부모 커넥션을 쥔 상태에서 즉시 2번째 커넥션을 추가 요청합니다!
      - 추가 여유가 있다면 2번째 커넥션도 할당되어 실행:
        `REQUEST_STARTED thread=<thread_id> parent_conn=ACQUIRED nested_conn=ACQUIRED status=RUNNING available_pool=<avail>`
      - 추가 여유가 없다면 부모를 쥔 채 자식을 기다리는 상태로 대기 큐 진입:
        `REQUEST_WAITING thread=<thread_id> parent_conn=ACQUIRED waiting=NESTED_CONN available_pool=0`
  - 1단계 부모 커넥션조차 여유가 없다면:
    - 부모 커넥션을 기다리는 상태로 대기 큐 진입:
      `REQUEST_WAITING thread=<thread_id> waiting=PARENT_CONN available_pool=0`

### 3) 가상 시간 경과 및 데드락 감지 (`TICK`)
- `TICK <ms>`
  - 대기 큐의 스레드들의 경과 시간을 증가시킵니다.
  - 대기 시간이 `timeout_ms` 이상이 되면 **커넥션 타임아웃 예외** 발생:
    - 점유 중이던 부모 커넥션이 있다면 강제 롤백 후 풀에 반납합니다.
    - 출력: `TIMEOUT_FAILED thread=<thread_id> elapsed=<dur>ms released_conns=<count>`
  - 커넥션이 반납되어 여유가 생기면 대기 중인 스레드에게 우선순위에 따라 배정합니다:
    - **우선순위 1 (`WAITING_CHILD`)**: 이미 부모를 쥐고 있어 1개만 더 주면 즉시 작업을 끝낼 수 있는 스레드.
    - **우선순위 2 (`WAITING_PARENT`)**: 부모부터 기다리는 스레드.
  - **풀 교착상태 감지**:
    - 가용 커넥션이 0이고, 실행 중인 스레드는 0명인데, 모든 활성 스레드가 `WAITING_CHILD` 상태(점유 대기)라면:  
      `STATUS:POOL_DEADLOCK_DETECTED threads_stalled=<count> available_pool=0`
  - 출력: `TICK_OK elapsed=<ms>ms` 및 수반되는 언블록/타임아웃/데드락 로그

### 4) 작업 정상 완료 (`FINISH_REQUEST`)
- `FINISH_REQUEST <thread_id>`
  - 실행 중(`RUNNING`)인 스레드가 작업을 완료하고 점유 중이던 모든 커넥션을 풀에 반납합니다.
  - 출력: `REQUEST_FINISHED thread=<thread_id> released_conns=<count> available_pool=<avail>`
  - 반납된 커넥션에 의해 대기 스레드가 깨어나면 언블록 로그 순차 출력.

### 5) 데드락 회피 권장 풀 크기 계산 (`CALCULATE_SAFE_POOL`)
- `CALCULATE_SAFE_POOL <max_threads> <max_conns_per_thread>`
  - HikariCP 공식 위키의 교착상태 회피 공식 적용:  
    $$	ext{Safe Pool Size} = T_n 	imes (C_m - 1) + 1$$
  - 출력: `SAFE_POOL_SIZE threads=<T> conns_per_thread=<C> recommended_pool_size=<P>`

### 6) 상태 요약 (`STATS`)
- `STATS`
  - 출력: `STATS pool_total=<total> pool_available=<avail> running_threads=<r> waiting_child=<wc> waiting_parent=<wp> timeouts=<t>`

---

## 4. 실무 권장 아키텍처 및 교훈

1. **HikariCP 데드락 공식 준수**:
   - $T_n 	imes (C_m - 1) + 1$ 공식을 통해, 톰캣 스레드가 10개이고 단일 스레드가 중첩 트랜잭션으로 최대 2개 커넥션을 요구한다면 풀 크기는 최소 **11개**여야 데드락을 원천 방어할 수 있습니다.
2. **`REQUIRES_NEW` 대신 비동기 분리**:
   - 부모 트랜잭션 커넥션을 붙잡고 있는 시간을 줄이기 위해, 감사 로깅이나 외부 호출은 스프링 `@Async`나 이벤트 리스너(`@TransactionalEventListener(phase = AFTER_COMPLETION)`)를 통해 독립 워커로 분리해야 합니다.
3. **은행원 알고리즘(Banker's Algorithm)의 자원 배분 원칙**:
   - 자원이 부족할 때는 이미 자원을 일부 획득하여 조금만 더 주면 완료할 수 있는 프로세스에게 우선 배정해야 시스템 전체의 순환 정체를 해소할 수 있습니다.
