# 대규모 데이터베이스 무중단 마이그레이션 및 정합성 보장 심층 기술 백서

## 1. 개요: 무중단 라이브 마이그레이션의 본질적 난제

글로벌 금융 플랫폼, 전자상거래 서비스, SaaS 인프라에서 데이터베이스를 교체하거나 샤딩(Sharding) 구조로 전환할 때, 서비스를 일시 중단하는 '점검 시간(Maintenance Window)'을 갖는 것은 막대한 비즈니스 손실과 사용자 이탈을 초래합니다.

하지만 데이터베이스가 서비스 중인 상태에서 라이브로 데이터를 복제하고 전환하는 **무중단 마이그레이션(Zero-Downtime Live Migration)**은 분산 시스템에서 가장 악명 높은 난제들을 동반합니다:
- **동시성 경합 (Concurrency Race Conditions)**: 스냅샷을 뜨고 있는 와중에도 초당 수천 건의 쓰기가 지속적으로 유입됨.
- **비순차 도착 (Out-of-Order Execution)**: 네트워크 지연의 불확실성으로 인해 과거 버전의 데이터가 최신 버전 이후에 도착.
- **부분 실패 (Partial Failure)**: 두 개 이상의 이기종 데이터베이스에 동시에 쓰기를 시도할 때 한쪽만 성공하고 다른 쪽이 실패하여 데이터가 영구 분기(Drift).

---

## 2. 나이브 듀얼 라이팅(Naive Dual-Writing)의 치명적 안티패턴

많은 개발팀이 무중단 마이그레이션을 처음 시도할 때 애플리케이션 코드에 단순 듀얼 라이팅을 구현합니다:

```python
# 나이브 듀얼 라이팅 안티패턴 코드
def update_user_balance(user_id, delta):
    db_old.update(user_id, delta)  # 1차 쓰기
    db_new.update(user_id, delta)  # 2차 쓰기 (위험!)
```

### 왜 나이브 듀얼 라이팅은 반드시 실패하는가?

#### (1) 분산 트랜잭션의 부재와 부분 실패 (Partial Failure)
`db_old`에는 쓰기가 커밋되었으나 네트워크 타임아웃, 커넥션 풀 고갈, 프로세스 재시작 등으로 인해 `db_new` 쓰기가 누락되면, 양쪽 데이터베이스 간에 조용한 정합성 괴리(Silent Drift)가 누적됩니다. 그렇다고 이기종 DB 간에 2단계 커밋(2PC, XA)을 도입하면 쓰기 지연시간(Latency)이 10배 이상 폭증하고 시스템 전체 가용성이 파괴됩니다.

#### (2) 백필 덮어쓰기 참사 (The Backfill Overwrite Race)
수천만 건의 기존 데이터를 신규 DB로 옮기려면 대용량 백필 배치(Backfill Worker)를 돌려야 합니다.
1. $t=1$: 백필 워커가 사용자 A의 잔액 100달러(v1) 스냅샷을 읽음.
2. $t=2$: 사용자가 50달러를 입금하여 실시간 트랜잭션이 `db_old`와 `db_new`에 반영됨 (잔액 150달러, v2).
3. $t=3$: 백필 워커가 $t=1$ 시점에 읽어둔 스냅샷(100달러, v1)을 `db_new`에 INSERT/UPDATE함.
4. **결과**: 신규 DB의 잔액이 150달러에서 100달러로 되돌아감! 사용자 계좌에서 50달러가 영구 증발!

#### (3) 분산 파드 간 도착 역전 (Out-of-Order Execution)
MSA 환경에서는 수십 대의 애플리케이션 파드가 독립적으로 실행됩니다.
- Pod A가 User 1의 잔액을 100 $	o$ 150으로 수정 (v2).
- Pod B가 User 1의 잔액을 150 $	o$ 200으로 수정 (v3).
- 네트워크 라우팅 차이로 인해 `db_new`에 Pod B의 v3 쓰기가 먼저 도착하고, 뒤이어 Pod A의 v2 쓰기가 도착함.
- 신규 DB에 v2가 최종 기록되면서 **최신 업데이트(v3)가 영구 소실되는 갱신 손실(Lost Update)** 발생.

---

## 3. 단조 버전 펜싱 (Monotonic Version Fencing)

위와 같은 동시성 역전과 백필 덮어쓰기를 수학적으로 완벽히 차단하는 기법이 **단조 버전 펜싱(Monotonic Version Fencing)**입니다.

### 동작 원리
모든 레코드에 단조 증가하는 시퀀스 번호(`version`) 또는 램포트 타임스탬프(Lamport Logical Timestamp)를 부여합니다. 그리고 신규 데이터베이스에 데이터를 쓸 때는 백필, 실시간 듀얼 라이팅, CDC를 막론하고 **예외 없이 조건부 업서트(Conditional Upsert)**를 강제합니다:

```sql
-- PostgreSQL / CockroachDB / TiDB 표준 버전 펜싱 쿼리
INSERT INTO db_new (id, balance, version, updated_at)
VALUES (:id, :balance, :version, :updated_at)
ON CONFLICT (id) DO UPDATE
SET balance = EXCLUDED.balance,
    version = EXCLUDED.version,
    updated_at = EXCLUDED.updated_at
WHERE EXCLUDED.version > db_new.version; -- 핵심 가드 조건!
```

### 수학적 불변성 (Invariance Guarantee)
신규 데이터베이스에 저장된 레코드의 버전 $V_{\text{stored}}$에 대해:
$$V_{\text{stored}}(t) = \max_{k \le t} (V_k)$$
즉, 어떤 순서로 쓰기 요청이 네트워크를 타고 도착하든, 신규 DB에는 **과거에 발생한 모든 쓰기 중 가장 높은 버전의 데이터만이 남게 되며, 과거 버전으로의 역행(Regression)은 수학적으로 불가능**합니다.

---

## 4. 트랜잭셔널 아웃박스(Transactional Outbox)와 CDC 스트리밍

단조 버전 펜싱으로 덮어쓰기를 막더라도, 듀얼 라이팅 코드 레벨의 네트워크 부분 실패는 여전히 데이터를 누락시킬 수 있습니다. 이를 원천 박멸하는 최고 수준의 엔지니어링 패턴이 바로 **트랜잭셔널 아웃박스(Transactional Outbox) + CDC(Change Data Capture)**입니다.

```
[ Application Server ]
          |
          | 1. Single Local ACID Transaction!
          v
+-----------------------------+
|          DB_Old             |
|  +-----------------------+  |
|  | account_balances      |  |
|  +-----------------------+  |
|  | outbox_events         |  |
|  +-----------------------+  |
+-----------------------------+
          |
          | 2. DB Transaction Log (Binlog / WAL)
          v
[ Debezium / Kafka CDC Connector ]
          |
          | 3. At-Least-Once Ordered Streaming
          v
[ DB_New (Version-Fenced Sink) ]
```

1. **단일 로컬 트랜잭션 보장**:
   애플리케이션은 원장 테이블과 아웃박스 이벤트 테이블을 `DB_Old`의 **단일 로컬 ACID 트랜잭션**으로 함께 커밋합니다. 네트워크 분할이 일어나도 원장과 이벤트의 원자성은 100% 보장됩니다.
2. **비동기 무손실 전송 (Lossless Pipeline)**:
   Debezium 같은 CDC 엔진이 `DB_Old`의 트랜잭션 로그(MySQL Binlog, Postgres WAL)를 테일링(Tailing)하여 Kafka로 전송하고, 컨슈머가 이를 `DB_New`로 단조 버전 펜싱과 함께 적재합니다.
3. **멱등성(Idempotency) 달성**:
   Kafka가 네트워크 재시도로 인해 동일한 CDC 이벤트를 여러 번 전달하더라도(At-Least-Once), `DB_New`의 버전 펜싱 조건문(`WHERE EXCLUDED.version > db_new.version`)에 의해 중복 이벤트는 안전하게 기각되므로 자연스럽게 완전한 멱등성이 성립합니다.

---

## 5. 다크 리드(Dark Read) 및 정합성 대사(Reconciliation Validator)

신규 DB로 실제 트래픽을 넘기기 전, 양쪽 DB의 모든 데이터가 1비트의 오차도 없이 일치하는지 비동기로 검증하는 단계입니다.

### 대사 메커니즘
1. **해시 청크 스캔 (Hash-Chunk Scanning)**:
   전체 테이블을 기본키(PK) 범위 단위(예: 1,000개씩)로 쪼개어 `DB_Old`와 `DB_New`에서 동시에 읽은 뒤, 레코드들의 해시값(Checksum)을 비교합니다.
2. **동적 드리프트 감지 (Drift Detection)**:
   - 레코드가 신규 DB에 누락된 경우
   - 잔액(Balance)이 일치하지 않는 경우
   - 버전(Version)이 일치하지 않는 경우
3. **자동 자가 치유 (Auto-Healing)**:
   발견된 불일치 키에 대해 권위 있는 원본(`DB_Old`)의 최신 상태를 읽어와 `DB_New`에 버전 펜싱 업서트를 수행함으로써 정합성을 능동적으로 회복합니다.

---

## 6. 무중단 마이그레이션 4대 라이프사이클 체크리스트

| 단계 | 주요 작업 | 검증 게이트 (Gate) | 롤백 전략 |
| :--- | :--- | :--- | :--- |
| **1단계: 인프라 프로비저닝 & CDC 기동** | 신규 DB 스키마 생성 및 Debezium CDC 파이프라인 연결 | CDC 커넥터 상태 정상, 지연시간 모니터링 구축 | CDC 태스크 중단 |
| **2단계: 과거 데이터 스냅샷 백필** | 백필 워커가 과거 데이터를 청크 단위로 신규 DB에 버전 펜싱 적재 | 백필 진행률 100% 도달, 덮어쓰기 손실 0건 | 신규 DB 테이블 TRUNCATE 후 재시작 |
| **3단계: 다크 리드 및 실시간 대사** | 백그라운드 대사기를 통한 100% 레코드 해시 대조 및 자가 치유 | **불일치율 0.00%**, CDC 지연 0건 | 불일치 원인 분석 및 재대사 |
| **4단계: 무중단 트래픽 컷오버** | 읽기 트래픽 전환 $\to$ 쓰기 트래픽 전환 $\to$ 구 DB 읽기 전용화 | 에러율 0%, P99 지연시간 정상 확인 | 즉시 구 DB로 라우팅 롤백 |
