# 물리 삭제의 위험과 소프트 딜리트 & CDC 툼스톤 (Hard Delete vs Soft Delete & CDC Tombstone)

> **"회원 탈퇴 버튼 한 번 눌렀을 뿐인데, 왜 지난 5년간의 100만 건 주문 결제 이력이 영구 삭제됐을까요?!"**  
> **"서류 파쇄기(Hard Delete)의 비극 vs 해지 도장 날인과 부고장 공문(Soft Delete & Tombstone)"**

---

## 1. 현실 세계 비유: 헬스장 계약서 파쇄 vs 해지 도장 날인

회원 철수가 헬스장에 찾아와 회원권 탈퇴를 신청했습니다.

```
[방식 1: 하드 딜리트 (Hard Delete / 물리 삭제)]
신입 직원이 철수의 서류를 집어 들더니, 사무실 문서 파쇄기에 넣고 갈아버렸습니다! (DELETE FROM users)

그런데 알고 보니, 그 서류철 뒤에는:
- "라커룸 1년 임대 계약서"
- "PT 50회 결제 영수증 (500만 원)"
- "국세청 제출용 세금계산서 증빙"
이 외래키로 클립에 묶여 있었습니다 (ON DELETE CASCADE).

파쇄기로 갈아버렸기 때문에:
1. 연말 세무조사가 나왔을 때, 헬스장은 500만 원 매출 증빙을 제출하지 못해 탈세 혐의로 과징금을 맞습니다.
2. 철수가 며칠 뒤 "남은 PT 10회 환불해 주세요"라고 왔을 때, 결제 이력이 0원이 되어 법적 분쟁이 터집니다.
3. 더 황당한 참사: 헬스장 주차장 차단기 컴퓨터는 철수가 탈퇴했다는 사실을 전혀 모릅니다!
   (서류가 흔적도 없이 사라져서 삭제 소식을 전달받지 못해, 철수 차량이 1년 내내 주차장에 무료 주차 중 - Ghost Cache!)
```

```
[방식 2: 소프트 딜리트 (Soft Delete) & CDC 툼스톤 (Tombstone)]
베테랑 점장은 서류를 절대 파쇄기에 넣지 않습니다.
대신 서류 상단에 빨간색 도장을 쾅 찍습니다:
[해지 완료: 2026-09-09, 사유: 고객 요청] (deleted_at = NOW())

그리고 서류철은 감사/회계용 영구 보관 캐비닛으로 옮깁니다.
동시에 주차장 관리실 컴퓨터에 "회원 101번 탈퇴함 (부고장 / 툼스톤 메시지)" 공문을 전송합니다:
{ key: 101, value: null } (Tombstone!)

결과:
1. 고객 센터는 탈퇴 회원을 일반 명단에서 즉시 제외합니다.
2. 회계팀은 철수의 과거 500만 원 결제 영수증을 100% 안전하게 열람합니다.
3. 철수가 "저 마음이 바뀌어서 다시 복구할래요" 하면 도장만 지우면 1초 만에 원복(Restore)됩니다!
4. 주차장 컴퓨터(Redis/Elasticsearch)는 부고장을 받아 철수 차량을 캐시에서 깨끗하게 제거합니다!
```

---

## 2. 물리 삭제(Hard Delete / `DELETE FROM`)의 3대 치명적 재앙

단순한 취업용 토이 프로젝트에서는 `DELETE FROM users WHERE id = 1`을 쉽게 날립니다.  
하지만 수백만 명이 이용하는 엔터프라이즈 실무에서 `DELETE` 쿼리는 원칙적으로 **금기(Anti-Pattern)**에 가깝습니다.

### 1) 외래키 CASCADE 연쇄 소각 (Cascade Destruction)
RDBMS의 외래키에 `ON DELETE CASCADE`가 걸려 있는 경우, 부모 레코드(User)를 삭제하는 순간 연관된 자식 테이블(Orders, Payments, Receipts, Deliveries) 수십만 건이 연쇄적으로 영구 삭제됩니다.  
이는 **전자상거래법상 5년간 의무 보존해야 하는 결제/주문 데이터가 영구 소각**되는 법적 재앙을 초래합니다.

### 2) 복구 불가능성 (Irreversibility)
물리 삭제된 데이터는 트랜잭션이 커밋되는 순간 디스크에서 지워지므로, DB 백업본(WAL/Binlog)을 복원하지 않는 한 원클릭 롤백이나 사용자 복구가 원천적으로 불가능합니다.

### 3) CDC와 분산 캐시의 유령 데이터 잔류 (Ghost Data in Cache)
Debezium 같은 CDC(Change Data Capture) 파이프라인이나 분산 이벤트 환경에서, row가 물리 삭제되면 이벤트 페이로드에 이전 데이터가 남지 않아 다운스트림의 Redis 캐시나 Elasticsearch 검색엔진에 무효화 이벤트가 누락될 위험이 높습니다. 그 결과 검색창에 "이미 탈퇴한 회원", "삭제된 품절 상품"이 영구 노출되는 버그가 발생합니다.

---

## 3. 엔터프라이즈의 표준: 소프트 딜리트 (Soft Delete)

소프트 딜리트는 물리적인 레코드를 지우지 않고, **삭제 플래그 또는 타임스탬프**를 마킹하는 논리적 삭제 패턴입니다.

### 1) 데이터 모델링 표준: `deleted_at TIMESTAMP NULL`
```sql
CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP NULL DEFAULT NULL  -- NULL이면 활성, 값이 있으면 삭제된 유저
);
```

### 2) 쿼리 레이어 분리
- **일반 비즈니스 쿼리**:
  ```sql
  SELECT * FROM users WHERE deleted_at IS NULL;
  ```
- **회계/법적 감사 쿼리**:
  ```sql
  -- 탈퇴 회원이라도 과거 주문 내역은 100% 정상 조회 보장!
  SELECT u.id, u.name, o.order_id, o.amount 
  FROM orders o 
  JOIN users u ON o.user_id = u.id 
  WHERE u.id = 101;
  ```
- **원클릭 복구 (Restore)**:
  ```sql
  UPDATE users SET deleted_at = NULL WHERE id = 101;
  ```

---

## 4. 분산 시스템의 삭제 부고장: CDC 툼스톤 (Tombstone)

마이크로서비스(MSA) 환경에서는 RDBMS의 변경 사항이 Kafka를 거쳐 Redis 캐시, Elasticsearch 검색엔진, 데이터 레이크로 실시간 복제(CDC)됩니다.

```
[소프트 딜리트 발생]
RDBMS (users) 
  --> [UPDATE users SET deleted_at = NOW() WHERE id = 101]
  --> Debezium (CDC)
  --> Kafka Topic (users-compacted)
      메시지 발행: { Key: "101", Value: null }  <-- 🪦 툼스톤(Tombstone)!
  --> Downstream Consumers:
      - Redis: DEL user:101 (캐시에서 즉시 제거!)
      - Elasticsearch: DELETE /users/_doc/101 (검색 인덱스에서 즉시 제거!)
      - Kafka Broker: Log Compaction 시 해당 키의 과거 로그를 영구 압축 정리!
```

- **툼스톤(Tombstone)**이란 키-값 메시지 시스템에서 **값이 `null`인 특수 삭제 마커**를 의미합니다.
- 툼스톤을 통해 다운스트림 캐시와 검색엔진은 "이 키가 완전히 삭제/비활성화되었음"을 명확히 인지하고 자신의 로컬 저장소에서 유령 데이터를 안전하게 제거할 수 있습니다.

---

## 5. 실무 비교 요약

| 점검 항목 | Hard Delete (물리 삭제) | Soft Delete & CDC Tombstone |
| :--- | :--- | :--- |
| **명령어** | `DELETE FROM table WHERE ...` | `UPDATE table SET deleted_at = NOW() ...` |
| **데이터 보존** | **영구 소각 (복구 불가)** | **100% 보존 (법적 감사, 회계 정산 완벽 대응)** |
| **연관 외래키** | `ON DELETE CASCADE` 연쇄 소각 위험 | **과거 주문/결제 이력 온전히 보존** |
| **사용자 복구** | 불가능 (DB 백업 복원 필요) | **`deleted_at = NULL` 1초 원클릭 복구** |
| **다운스트림 캐시** | 삭제 이벤트 누락으로 유령 데이터 잔류 위험 | **CDC 툼스톤 전파로 캐시/ES 즉시 자동 무효화** |
| **검색 최적화** | 별도 인덱스 불필요 | `WHERE deleted_at IS NULL` 부분 인덱스(Partial Index) 활용 |
