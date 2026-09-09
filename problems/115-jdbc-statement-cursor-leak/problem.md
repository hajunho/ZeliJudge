# 커넥션을 닫았는데 왜 커서가 터져요?!: JDBC Statement 누수와 ORA-01000 (JDBC Statement Leak & Cursor Exhaustion)

## 문제 설명

자바(Java) 백엔드 애플리케이션에서 데이터베이스를 연동할 때 수많은 주니어 개발자가 겪는 대표적인 실무 장애 중 하나는 **"분명히 `conn.close()`를 꼬박꼬박 호출했는데, 서비스 오픈 며칠 만에 `ORA-01000: maximum open cursors exceeded` 에러가 터지며 모든 쿼리가 셧다운되는 현상"**입니다.

이 참사의 원인은 **커넥션 풀(Connection Pool)의 동작 방식**과 **DB 서버 측 커서(Cursor) 라이프사이클**에 대한 오해에서 비롯됩니다:

```java
// ❌ 실무 최악의 안티패턴: conn만 닫으면 다 닫히는 줄 알았다!
Connection conn = dataSource.getConnection();
PreparedStatement stmt = conn.prepareStatement("SELECT * FROM users WHERE id = ?");
ResultSet rs = stmt.executeQuery();
// 데이터 처리...
conn.close(); // "커넥션을 닫았으니 stmt랑 rs도 알아서 닫히겠지?" -> 절대 아님!
```

### 💥 커넥션 풀의 진실
1. **`conn.close()`의 실체**:
   - 히카리CP(HikariCP)나 DBCP 환경에서 `conn.close()`는 실제 DB와의 물리적 TCP 소켓을 끊는 것이 아닙니다.
   - 단지 **물리 커넥션을 재사용하기 위해 풀(Pool)에 반환(Return)하는 프록시 메서드**일 뿐입니다.
2. **열린 채 버려진 커서(Orphan Cursors)**:
   - 물리 커넥션이 종료되지 않고 살아있기 때문에, 그 커넥션 안에서 생성된 `PreparedStatement`와 DB 서버 측 **커서(Cursor)**는 해제되지 않고 영구히 열려 있습니다.
3. **치명적 장애 (`ORA-01000`)**:
   - 오라클/MySQL 등 모든 관계형 데이터베이스는 세션별/인스턴스별로 동시 열람 가능한 최대 커서 수(`max_open_cursors`, 예: 50~300)를 제한합니다.
   - 쿼리가 수십~수백 번 실행되는 동안 누수된 커서가 누적되어 한계에 도달하면, 다음 쿼리는 즉시 **`ORA-01000: maximum open cursors exceeded`** 에러를 뿜으며 전사 서비스가 마비됩니다.

이를 방지하기 위해 현대 자바에서는 `AutoCloseable` 인터페이스를 구현한 **`try-with-resources` 문법(RAII 패턴)**을 사용하여 생성 역순(`rs` $\to$ `stmt` $\to$ `conn`)으로 안전하게 자원을 해제해야 합니다.

당신은 커넥션 풀과 데이터베이스 서버의 커서 누수/회수 메커니즘을 시뮬레이션하는 엔진을 구현해야 합니다.

---

## 시뮬레이션 규칙

### 1. 커넥션 풀과 DB 커서 동작
- 데이터베이스 서버는 전체 세션에서 열 수 있는 최대 커서 상한(`max_cursors`, 기본값: 50)을 가집니다.
- 커넥션 풀은 `pool_size`(기본값: 5)개의 물리 커넥션을 관리합니다.
- 쿼리가 실행될 때:
  - 풀에서 커넥션을 라운드로빈 방식으로 대여합니다: `conn_idx = (query_index) % pool_size`.
  - 쿼리는 실행을 위해 1개의 DB 커서를 생성합니다.
  - 만약 현재 DB에 열려있는 총 커서 수(`active_cursors`)가 `max_cursors` 이상이라면:
    - 쿼리는 실패하며 즉시 에러(`ORA-01000_MAX_CURSORS_EXCEEDED`)가 발생하고 쿼리 배치가 중단됩니다.
  - 커서 용량이 남아있다면 `active_cursors += 1`이 되고 쿼리가 정상 실행됩니다.

### 2. 자원 반납 모드 (`mode`)
- **`AUTO_CLOSE` (기본값 / try-with-resources)**:
  - 쿼리가 끝나면 `ResultSet`과 `PreparedStatement`를 즉시 닫아 DB 커서를 반환합니다: `active_cursors -= 1`.
  - 커넥션은 깨끗한 상태로 풀에 반납됩니다.
- **`LEAK_ALL` (구시대 안티패턴 / 자원 누수)**:
  - `conn.close()`만 호출되고 `Statement`와 `ResultSet`이 닫히지 않습니다.
  - 해당 물리 커넥션에 할당된 DB 커서는 **닫히지 않고 그대로 누수(`active_cursors` 유지)**됩니다.
- **`LEAK_RESULTSET` (클라이언트 버퍼 누수)**:
  - Statement는 닫혀서 DB 커서는 정상 회수(`active_cursors -= 1`)되지만, 클라이언트 ResultSet 버퍼가 누수됩니다.

### 3. 응급 커넥션 풀 축출 (`EVICT_IDLE_CONNECTIONS`)
- 커서가 꽉 차서 장애가 발생했을 때의 응급 조치입니다.
- 커넥션 풀의 기존 물리 커넥션들을 강제 파기하고 새 물리 커넥션들로 교체합니다.
- 물리 커넥션 세션이 종료되면 DB 서버는 해당 커넥션에 묶여 있던 **모든 고아 커서(Orphan Cursors)를 0으로 강제 일괄 회수**합니다.

---

## 명령어 명세

모든 명령어는 표준 입력(stdin)으로 한 줄씩 주어지며, 인자는 `key=value` 형태 또는 공백 구분 위치 인자를 지원합니다.

1. **`CONFIG max_cursors=<int> pool_size=<int> mode=<str>`**
   - 시스템 설정을 변경합니다. (기본값: `max_cursors=50, pool_size=5, mode=AUTO_CLOSE`)
   - 모드: `AUTO_CLOSE`, `LEAK_ALL`, `LEAK_RESULTSET`
   - 출력: `CONFIG_OK max_cursors=<M> pool_size=<P> mode=<MODE>`

2. **`EXECUTE_QUERY count=<int>`**
   - 풀을 통해 `count`개의 쿼리를 순차 실행합니다.
   - 출력:
     - 모든 쿼리 성공: `EXECUTE_OK executed=<count> active_cursors=<active>`
     - 커서 한도 초과로 중단: `EXECUTE_FAIL executed=<E> failed=<F> reason=ORA-01000_MAX_CURSORS_EXCEEDED active_cursors=<active>`

3. **`EVICT_IDLE_CONNECTIONS`**
   - 커넥션 풀의 물리 연결을 강제 파기 및 재생성하여 누수된 커서를 회수합니다.
   - 출력: `EVICT_OK freed_cursors=<freed> remaining_cursors=0`

4. **`STATUS`**
   - 풀 및 DB 커서 상태를 덤프합니다.
   - 출력 형식:
     ```
     --- JDBC_POOL_STATUS ---
     MODE: <MODE>
     POOL_SIZE: <int>
     MAX_CURSORS: <int>
     ACTIVE_CURSORS: <int>
     TOTAL_QUERIES: <int>
     CURSOR_ERRORS: <int>
     STATUS: <HEALTHY|LEAKING|EXHAUSTED>
     --- END_STATUS ---
     ```
     - 상태 판정: `cursor_errors > 0`이면 `EXHAUSTED`, 아니면 `active_cursors > 0`이면 `LEAKING`, 그 외는 `HEALTHY`

5. **`RESET`**
   - 모든 설정을 초기화하고 풀을 리셋합니다.
   - 출력: `RESET_OK`

---

## 입출력 예시

### 예시 입력
```
CONFIG max_cursors=30 pool_size=3 mode=LEAK_ALL
EXECUTE_QUERY count=35
STATUS
EVICT_IDLE_CONNECTIONS
STATUS
```

### 예시 출력
```
CONFIG_OK max_cursors=30 pool_size=3 mode=LEAK_ALL
EXECUTE_FAIL executed=30 failed=5 reason=ORA-01000_MAX_CURSORS_EXCEEDED active_cursors=30
--- JDBC_POOL_STATUS ---
MODE: LEAK_ALL
POOL_SIZE: 3
MAX_CURSORS: 30
ACTIVE_CURSORS: 30
TOTAL_QUERIES: 30
CURSOR_ERRORS: 1
STATUS: EXHAUSTED
--- END_STATUS ---
EVICT_OK freed_cursors=30 remaining_cursors=0
--- JDBC_POOL_STATUS ---
MODE: LEAK_ALL
POOL_SIZE: 3
MAX_CURSORS: 30
ACTIVE_CURSORS: 0
TOTAL_QUERIES: 30
CURSOR_ERRORS: 1
STATUS: EXHAUSTED
--- END_STATUS ---
```
