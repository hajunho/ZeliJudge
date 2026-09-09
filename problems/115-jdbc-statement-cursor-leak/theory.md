# [배경 이론] 커넥션을 닫았는데 왜 커서가 터져요?!: JDBC Statement 누수와 ORA-01000 (JDBC Statement Leak & Cursor Exhaustion)

## 1. 현실 비유: 도서관 열람실 자리 반납과 책상 위 책 더미

도서관(데이터베이스 서버)에서 공부하는 상황을 비유해 보겠습니다.

- **열람실 좌석(Connection)**: 한 번에 최대 5명(Connection Pool Size = 5)까지만 좌석을 빌릴 수 있습니다.
- **도서관 전체 열람 가능 책 수(Database Open Cursors)**: 도서관 규정상 전체 열람실에 한 번에 꺼내둘 수 있는 책의 총합은 최대 50권(Max Cursors = 50)입니다.

어떤 학생이 좌석을 빌린 뒤 책장에서 책 10권(`PreparedStatement` & `ResultSet`)을 꺼내서 공부했습니다.  
공부를 마친 학생은 **책을 제자리에 꽂아두지 않고 책상 위에 그대로 둔 채(Statement/ResultSet 미반납)**, 도서관 출입증(Connection)만 반납 관리함에 쏙 넣고 나갔습니다(`conn.close()`).

### 💥 커넥션 풀(HikariCP)의 치명적 오해
초보 개발자는 생각합니다:  
*"어? 나 분명 `conn.close()` 불렀는데? 커넥션을 닫았으니 그 안에서 만든 Statement랑 ResultSet도 다 같이 닫힌 거 아니야?"*

**완벽한 착각입니다!**
- 커넥션 풀(HikariCP, DBCP 등) 환경에서 `conn.close()`는 실제 DB와의 TCP 소켓을 끊는 것이 아니라, **물리 커넥션을 재사용하기 위해 풀(Pool)에 반환(Return)하는 프록시 메서드**일 뿐입니다.
- 물리 커넥션이 끊어지지 않고 살아있기 때문에, 학생이 책상 위에 그대로 팽개치고 간 책 10권(DB 서버 측 열린 커서, Open Cursor)은 **DB 서버 메모리에 고스란히 남아 있습니다**!
- 다음 학생 5명이 들어와서 똑같이 책을 10권씩 꺼내놓고 나가면:
  - 꺼내진 책은 순식간에 50권에 도달합니다 (`active_cursors = 50`).
  - 다음 학생이 책 1권을 더 꺼내려는 순간, 도서관 관리자(DB 커널)가 버럭 소리를 지릅니다:  
    **`ORA-01000: maximum open cursors exceeded` (최대 열린 커서 수 초과!)**
  - 도서관 전체가 셧다운되고, 어떤 학생도 책을 빌릴 수 없게 됩니다.

---

## 2. RDBMS 커서(Cursor)와 JDBC 자원 라이프사이클

데이터베이스에서 SQL 쿼리가 실행될 때 자원이 할당되는 계층 구조는 다음과 같습니다:

```
[물리 커넥션 (Physical Connection)]
  │  (HikariCP가 영구히 유지함)
  ├── [PreparedStatement #1] ──► DB 서버 메모리에 1개의 커서(Cursor) 할당
  │      └── [ResultSet #1]  ──► 쿼리 결과 행 데이터를 담는 버퍼
  ├── [PreparedStatement #2] ──► 또 다른 커서 할당 (미반납 시 누수!)
  └── [PreparedStatement #3] ──► 또 다른 커서 할당 (미반납 시 누수!)
```

### 왜 Statement와 ResultSet을 개별적으로 닫아야 할까요?
1. **DB 서버 측 커서 메모리 고갈**:
   - 오라클(Oracle), MySQL, PostgreSQL 등 모든 관계형 데이터베이스는 실행 중인 쿼리의 파싱 트리, 실행 계획, 현재 행 포인터를 위해 세션별 **커서(Cursor)**를 유지합니다.
   - `stmt.close()`를 호출하지 않으면 DB 서버는 클라이언트가 나중에 다음 행을 읽을지도 모른다고 판단하여 커서를 영구히 해제하지 않습니다.
2. **JVM 클라이언트 측 힙 메모리 누수**:
   - `ResultSet`에는 수천~수만 건의 행 데이터 버퍼가 담겨 있습니다.
   - `rs.close()`를 누락하면 가비지 컬렉터(GC)가 객체를 즉시 회수하지 못해 OutOfMemoryError(OOM)로 이어질 수 있습니다.

---

## 3. 해결책: Java 7 AutoCloseable과 try-with-resources (RAII 패턴)

과거 Java 6 이전에는 `finally` 블록에서 3개의 자원을 역순으로 `null` 체크하며 일일이 `close()`해야 했기 때문에 코드가 지저분하고 버그가 잦았습니다:

```java
// ❌ 구시대 안티패턴: close 누락 위험 극심
Connection conn = null;
PreparedStatement stmt = null;
ResultSet rs = null;
try {
    conn = dataSource.getConnection();
    stmt = conn.prepareStatement("SELECT ...");
    rs = stmt.executeQuery();
    // ...
} finally {
    if (rs != null) try { rs.close(); } catch (Exception e) {}
    if (stmt != null) try { stmt.close(); } catch (Exception e) {}
    if (conn != null) try { conn.close(); } catch (Exception e) {}
}
```

### 현대적 표준: `try-with-resources` (Java 7+)
`AutoCloseable` 인터페이스를 구현한 자원은 `try(...)` 괄호 안에 선언하기만 하면, 정상 종료든 예외 발생이든 관계없이 **생성 역순(`rs` $\to$ `stmt` $\to$ `conn`)으로 완벽하게 자동 `close()`**됩니다:

```java
// ✅ 현대적 표준: RAII 패턴 기반 완벽한 자원 반환
try (Connection conn = dataSource.getConnection();
     PreparedStatement stmt = conn.prepareStatement("SELECT ...");
     ResultSet rs = stmt.executeQuery()) {
    while (rs.next()) {
        // 결과 처리
    }
} // 블록을 벗어나는 즉시 rs, stmt, conn이 역순으로 100% 안전하게 닫힘!
```

---

## 4. 커넥션 풀 강제 축출 (Emergency Pool Eviction)

만약 이미 레거시 코드의 버그로 인해 DB 커서가 꽉 차서 `ORA-01000`이 터졌다면 어떻게 응급 복구해야 할까요?

- 커넥션 풀에 쌓여 있는 물리 연결을 강제로 파기(Evict)하고 재생성(`EVICT_IDLE_CONNECTIONS`)합니다.
- 물리 TCP 세션이 종료되면 DB 서버는 해당 세션에 묶여 있던 모든 고아 커서(Orphan Cursors)를 강제로 일괄 회수합니다.
