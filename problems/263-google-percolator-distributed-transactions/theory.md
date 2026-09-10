# [이론 및 배경] Google Percolator와 NewSQL 분산 트랜잭션의 수학적 기초

## 1. 전통적인 2단계 커밋(2PC)의 딜레마와 Percolator의 탄생

전통적인 분산 트랜잭션은 중앙 집중식 트랜잭션 관리자(Transaction Manager / Coordinator)가 참여 노드들에게 `Prepare`를 묻고 모든 노드가 응답하면 `Commit`을 지시하는 **2PC(Two-Phase Commit)** 프로토콜을 사용합니다.
그러나 2PC에는 치명적인 두 가지 아킬레스건이 존재합니다:
1. **코디네이터 단일 장애점(SPOF)과 블로킹(Blocking)**:
   - 코디네이터가 `Commit` 결정을 내린 직후 네트워크에서 고립되거나 사망하면, 모든 참여 노드는 트랜잭션 락을 쥔 채 무한정 대기(Block)해야 합니다.
2. **확장성(Scalability) 병목**:
   - 구글 검색 인덱스(Caffeine)처럼 수십억 개의 웹 문서 링크를 지속적으로 갱신하는 초대형 분산 환경에서 모든 트랜잭션의 상태를 중앙 코디네이터가 관리하는 것은 물리적으로 불가능합니다.

2010년 마이크 버로우스(Mike Burrows)와 다니엘 펭(Daniel Peng)이 발표한 **Google Percolator**는 전용 분산 합의 관리자 없이, **Bigtable과 같은 단순한 분산 KV 저장소의 단일 행 원자성(Row-level Atomicity)만으로 글로벌 분산 ACID 트랜잭션을 구현**하는 혁신을 이뤄냈습니다.

---

## 2. 컬럼 패밀리(Column Family) 3중 분리 아키텍처

Percolator의 핵심은 하나의 논리적 레코드를 세 개의 독립된 물리적 컬럼 패밀리로 분리하여 관리하는 것입니다:

```
[Logical Key: "user:101"]
├── data: (user:101, start_ts: 100) -> {"name": "Alice", "balance": 500}
├── lock: (user:101)                -> {primary: "user:101", start_ts: 100, ttl: 3000ms}
└── write:(user:101, commit_ts: 150) -> {start_ts: 100, op: PUT}
```

- **`data`**: 트랜잭션이 시작된 타임스탬프 $T_{\text{start}}$를 키의 버전으로 삼아 실제 페이로드를 기록합니다.
- **`lock`**: 트랜잭션이 진행 중일 때만 임시로 존재하는 락입니다. 커밋되거나 롤백되면 즉시 삭제됩니다.
- **`write`**: 트랜잭션이 성공적으로 완결된 커밋 타임스탬프 $T_{\text{commit}}$을 키로 가지며, 실제 데이터가 어느 $T_{\text{start}}$에 저장되어 있는지 가리키는 포인터 역할을 합니다.

이러한 분리를 통해 Percolator는 쓰기 작업이 진행 중이더라도 과거의 $T_{\text{read}}$ 시점을 읽는 리더(Reader)에게 **락 프리(Lock-Free) 스냅샷 읽기**를 보장합니다.

---

## 3. Primary Lock 불변식(Invariant)과 불가역적 커밋

Percolator의 가장 우아한 수학적 통찰은 **트랜잭션의 상태(State)를 Primary Key의 락 존재 여부 하나에 온전히 매핑**했다는 점입니다.

- N개의 키를 수정하는 트랜잭션에서 임의로 1개의 키를 Primary로 지정하고, 나머지 N-1개는 Secondary로 지정합니다.
- 모든 Secondary Key의 락 정보는 `primary_key`의 주소를 참조합니다.
- **커밋의 원자적 순간**:
  1. Primary Key의 락을 제거하고 `write` 컬럼 패밀리에 커밋 마커를 쓰는 순간:
     $$\text{Status}(T) = \text{COMMITTED}$$
  2. 그 이후 Secondary Key를 커밋하는 작업은 지연되거나 실패하더라도 트랜잭션의 결과에 영향을 주지 못합니다.

---

## 4. 자가 치유 크래시 복구: 롤포워드(Roll-Forward)와 롤백(Roll-Back)

분산 시스템에서 클라이언트(코디네이터)는 언제든 크래시될 수 있습니다. Percolator는 장애 발생 시 복구를 위해 별도의 백그라운드 크래시 데몬을 필요로 하지 않습니다:

### 시나리오 A: Primary 커밋 후 클라이언트 사망 (Roll-Forward)
1. 클라이언트가 Primary Key 커밋 완료 후, Secondary Key를 커밋하기 전에 죽었습니다.
2. 시간이 흐른 뒤 다른 트랜잭션이 해당 Secondary Key에 접근하다가 만료된 락을 발견합니다.
3. 락에 적힌 Primary Key를 조회합니다.
4. Primary Key에 이미 커밋 레코드가 존재함을 확인합니다!
5. **결론**: 트랜잭션은 이미 성공했음. 후속 프로세스가 대신 Secondary Key의 락을 지우고 `write` 레코드를 써주는 **롤포워드(Roll-Forward)**를 수행합니다.

### 시나리오 B: Primary 커밋 전 클라이언트 사망 (Roll-Back)
1. 클라이언트가 Prewrite만 마치고 Primary Key를 커밋하기 전에 죽었습니다.
2. 다른 트랜잭션이 만료된 락을 발견하고 Primary Key를 조회합니다.
3. Primary Key에 커밋 레코드가 존재하지 않습니다.
4. **결론**: 트랜잭션은 미완료 상태로 실패했음.
5. Secondary 락을 지우고, 향후 사망했던 클라이언트가 뒤늦게 살아나 Primary를 커밋하지 못하도록 `write:Primary`에 **롤백 마커(`ROLLBACK`)**를 영구 기록합니다.

이 자가 치유 프로토콜 덕분에 TiDB(TiKV)와 CockroachDB는 노드 장애 및 파티션 상황에서도 데이터의 원자성과 일관성(Strict Serializability / Snapshot Isolation)을 100% 사수할 수 있습니다.
