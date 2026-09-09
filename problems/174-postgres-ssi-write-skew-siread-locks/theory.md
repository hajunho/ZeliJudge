# PostgreSQL SSI (Serializable Snapshot Isolation)과 SIREAD 락 & 쓰기 왜곡(Write Skew) 방어

## 1. 개요: REPEATABLE READ에서도 데이터가 깨진다고요?!

수많은 개발자와 DBA들이 데이터베이스 격리 수준(Isolation Level)을 배울 때 다음과 같은 표를 암기합니다:

| 격리 수준 | Dirty Read | Non-Repeatable Read | Phantom Read |
|:---:|:---:|:---:|:---:|
| Read Uncommitted | O | O | O |
| Read Committed | X | O | O |
| Repeatable Read | X | X | X (InnoDB/Postgres) |
| Serializable | X | X | X |

많은 이들이 `REPEATABLE READ`를 쓰면 트랜잭션 도중 스냅샷이 고정되므로 동시성 이상 현상이 거의 모두 해결된다고 믿습니다.
하지만 1995년, 컴퓨터 과학의 거장 짐 그레이(Jim Gray)와 연구진은 전설적인 논문 **"A Critique of ANSI SQL Isolation Levels"**를 통해 ANSI SQL-92 표준의 치명적 맹점을 폭로했습니다.

`REPEATABLE READ` (정확히는 현대 MVCC의 **스냅샷 격리, Snapshot Isolation**) 환경에서도 데이터의 비즈니스 무결성이 완전히 붕괴되는 치명적인 이상 현상이 존재합니다.
그것이 바로 **쓰기 왜곡(Write Skew)**입니다.

---

## 2. 참사의 발단: 병원 야간 당직 의사(Doctors on Call) 잔혹사

### 2.1 비즈니스 불변식(Invariant)
어느 대형 병원의 응급실 시스템에는 절대 깨져서는 안 되는 엄격한 제약조건이 있습니다:
$$\text{"병원에는 항상 최소 1명 이상의 의사가 당직(on\_call = true) 근무를 서야 한다."}$$

현재 당직 명단에는 **앨리스(Alice)**와 **밥(Bob)** 두 명의 의사가 등록되어 있습니다.

```
+---------------+---------+
| doctor_name   | on_call |
+---------------+---------+
| doctor_alice  | true    |
| doctor_bob    | true    |
+---------------+---------+
```

### 2.2 쓰기 왜곡(Write Skew)의 발생 과정

```
[트랜잭션 1: 앨리스의 퇴근 신청]                     [트랜잭션 2: 밥의 퇴근 신청]
               |                                                   |
1. BEGIN (REPEATABLE READ)                         1. BEGIN (REPEATABLE READ)
2. SELECT COUNT(*) FROM doctors                    2. SELECT COUNT(*) FROM doctors
   WHERE on_call = true;                              WHERE on_call = true;
   -> 2명 반환! ("밥이 남으니 퇴근해도 되겠군")            -> 2명 반환! ("앨리스가 남으니 퇴근해도 되겠군")
3. UPDATE doctors SET on_call = false              3. UPDATE doctors SET on_call = false
   WHERE name = 'doctor_alice';                       WHERE name = 'doctor_bob';
4. COMMIT; (성공!)                                  4. COMMIT; (성공!)
```

### 2.3 참혹한 결과: 당직 의사 0명!
1. 앨리스의 트랜잭션은 `doctor_alice` 행을 수정했습니다.
2. 밥의 트랜잭션은 `doctor_bob` 행을 수정했습니다.
3. **두 트랜잭션이 수정한 물리적 레코드가 서로 완전히 다릅니다(Disjoint)!**
4. 따라서 전통적인 MVCC의 Write-Write 충돌(동일 행에 대한 동시 수정)이 전혀 발생하지 않습니다.
5. 두 트랜잭션 모두 아무런 락 경합이나 에러 없이 기분 좋게 `COMMIT`에 성공합니다.
6. **결과: 응급실에 당직 의사가 0명이 되어, 밤새 후송된 응급 환자가 방치되는 끔찍한 의료 사고가 터집니다!**

이처럼 **두 트랜잭션이 겹치는 데이터를 읽고, 그 읽은 결과를 바탕으로 서로 다른 행을 수정하여 전체 데이터베이스의 불변식을 파괴하는 현상**을 **쓰기 왜곡(Write Skew)**이라고 부릅니다.
은행 계좌의 복합 잔액 한도($A + B \ge 0$), 회의실 중복 예약, 선착순 정원 초과 등 실무의 수많은 핵심 제약조건이 이 쓰기 왜곡으로 인해 소리 없이 무너집니다.

---

## 3. 전통적 해결책의 한계: 동시성의 파멸

이 문제를 해결하기 위해 고전적인 데이터베이스는 두 가지 극단적인 방법을 썼습니다:

1. **명시적 비관적 락 (`SELECT ... FOR UPDATE`)**:
   - 의사 목록 전체에 배타 락(X-Lock)을 걸어버립니다.
   - 쿼리마다 개발자가 실수 없이 수동으로 락을 걸어야 하며, 데드락이 폭증하고 읽기 성능이 바닥으로 추락합니다.
2. **엄격한 2단계 락킹 (Strict 2PL, Traditional Serializable)**:
   - 읽기 작업에도 공유 락(S-Lock)을 걸어, 다른 트랜잭션의 쓰기를 전면 차단합니다.
   - 단 한 명이 보고서를 조회하는 동안 모든 주문과 결제가 올스톱되는 최악의 병목이 발생합니다.

---

## 4. 구원: PostgreSQL의 Serializable Snapshot Isolation (SSI)

2008년, 마이클 케이힐(Michael Cahill) 박사 연구팀은 혁신적인 논문 **"Serializable Isolation for Snapshot Databases"**를 발표했고, PostgreSQL 9.1은 세계 최초로 오픈소스 RDBMS에 **락-프리 직렬화 스냅샷 격리 (SSI)**를 구현했습니다.

SSI의 핵심 철학은 간단합니다:
> **"읽기 트랜잭션은 절대 쓰기 트랜잭션을 블로킹하지 않는다. 락도 걸지 않는다. 대신 직렬화 의존성 그래프(Dependency Graph)를 메모리에서 가볍게 관찰하다가, 진짜 사이클(Cycle)이 발생할 때만 딱 하나의 트랜잭션을 롤백시킨다!"**

### 4.1 SIREAD 락 (Predicate Lock)
- PostgreSQL에서 `SERIALIZABLE` 모드로 데이터를 읽을 때 걸리는 특수한 락입니다.
- **물리적으로 아무도 블로킹하지 않습니다.** (읽기와 쓰기가 서로 대기하지 않음)
- 단지 공유 메모리의 작은 테이블에 **"트랜잭션 $T$가 이 튜플(또는 페이지)을 읽었음"**이라는 흔적만 남겨둡니다.

### 4.2 rw 반의존성 (rw-antidependency / Conflict Edge)
만약 트랜잭션 $T_1$이 어떤 데이터를 읽고(SIREAD 락 등록), 동시 실행 중인 다른 트랜잭션 $T_2$가 그 데이터를 나중에 수정(`write`)한다면:
- 두 트랜잭션이 직렬화 가능하려면, $T_1$이 읽은 시점은 $T_2$가 쓰기 전이어야 하므로 직렬화 순서는 반드시 **$T_1 \to T_2$**여야만 합니다.
- 이를 **rw 반의존성 엣지 ($T_1 \xrightarrow{rw} T_2$)**라고 부릅니다.

### 4.3 위험 구조(Dangerous Structure) 감지와 원자적 롤백

```
[직렬화 이상 사이클 감지]

       (T1: 앨리스) ---------------- rw ----------------> (T2: 밥)
            ^                                                |
            |                                                |
            +---------------------- rw ----------------------+
```

- 앨리스($T_1$)는 밥의 행을 읽고, 밥($T_2$)은 앨리스의 행을 수정함 $\to T_1 \xrightarrow{rw} T_2$
- 밥($T_2$)은 앨리스의 행을 읽고, 앨리스($T_1$)는 밥의 행을 수정함 $\to T_2 \xrightarrow{rw} T_1$
- **수학적 정리 (Cahill's Theorem)**: 직렬화 이상(Write Skew)은 그래프에서 **$T_{\text{in}} \xrightarrow{rw} T_{\text{pivot}} \xrightarrow{rw} T_{\text{out}}$** 형태의 연속된 반의존성(또는 사이클)이 형성될 때만 발생합니다!
- 앨리스가 먼저 커밋에 성공하면, 밥이 `COMMIT`을 호출하는 순간 PostgreSQL 커널은 사이클을 감지하고 밥의 트랜잭션을 즉시 강제 롤백합니다:
  $$\mathbf{\text{ERROR: could not serialize access due to read/write dependencies among transactions}}$$
  $$\mathbf{\text{(SQLSTATE 40001)}}$$

### 4.4 결론: 무결성과 동시성의 완벽한 조화
- 락 대기 시간: **0ms** (전통 2PL 대비 처리량 수십 배 향상)
- 앨리스의 퇴근은 정상 처리되고, 밥의 퇴근은 40001 에러로 안전하게 롤백되어 **당직 의사는 항상 1명 이상 유지**됩니다.
- 애플리케이션은 40001 에러를 만나면 지수 백오프(Exponential Backoff)를 두고 트랜잭션을 재시도(Retry)하기만 하면 됩니다.
