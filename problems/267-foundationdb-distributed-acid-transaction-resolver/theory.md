# [이론 및 배경] FoundationDB의 분리형(Decoupled) 분산 트랜잭션 아키텍처와 리졸버(Resolver)의 충돌 검증 알고리즘

## 1. 일체형(Monolithic) vs 분리형(Decoupled) 분산 트랜잭션

전통적인 NewSQL(Google Spanner, CockroachDB, TiDB)은 데이터 샤드(Shard/Tablet)마다 Raft/Paxos 합의 그룹을 구성하고, 2단계 잠금(2PL)과 2단계 커밋(2PC)을 통해 분산 트랜잭션을 조정합니다.
이 방식은 샤드가 많아질수록 2PC 코디네이터와 다중 샤드 간의 네트워크 왕복(Round-trip)이 기하급수적으로 증가하며, 핫스팟 키에 대한 잠금 경합(Lock Contention)으로 인해 분산 데드락(Distributed Deadlock)이 발생합니다.

반면 **FoundationDB**는 SIGMOD 2021 논문에서 입증된 바와 같이 **트랜잭션 처리 계층(Transaction System)과 데이터 보관 계층(Storage System)을 완벽히 분리**했습니다:
- **Stateless Transaction System**: 시퀀서(Sequencer), 트랜잭션 프록시(Proxies), 리졸버(Resolvers), 트랜잭션 로그(TLogs).
- **Stateful Storage System**: 비동기적으로 TLog를 당겨와 로컬 B-Tree(Redwood)에 반영하는 스토리지 서버들.

---

## 2. 시퀀서와 단조 증가 버전 할당

FoundationDB에는 물리적 잠금(Pessimistic Locking)이 전혀 존재하지 않습니다. 모든 동시성 제어는 **논리적 버전(Logical Version Number)**을 기반으로 하는 **낙관적 동시성 제어(OCC, Optimistic Concurrency Control)**입니다:
1. 클라이언트가 트랜잭션을 시작하면 프록시는 시퀀서에 질의하여 현재 커밋된 최신 버전 $R_v = \text{ReadVersion}$을 얻습니다.
2. 클라이언트는 $R_v$ 시점의 과거 일관된 스냅샷(Consistent Snapshot)을 스토리지 노드로부터 읽습니다.
3. 커밋 요청 시, 클라이언트는 자신이 읽은 키 목록($K_{read}$)과 쓰고자 하는 변경 사항($K_{write}$)을 프록시로 보냅니다.

---

## 3. 리졸버(Resolvers)의 인메모리 키 충돌 검증 알고리즘

리졸버는 디스크 I/O 없이 순수 램(RAM)에서만 동작하는 초고속 충돌 판정기입니다:
- 전체 키 공간을 $M$개의 리졸버가 해시 또는 레인지로 샤딩하여 분담합니다.
- 각 리졸버는 최근 $W$ 버전(기본 5초 분량) 동안 어떤 키가 몇 번 버전에 커밋되었는지를 기록하는 해시 테이블(`key -> list[commit_version]`)을 유지합니다.

### 직렬화 충돌 판정 규칙
트랜잭션 $T$의 읽기 버전이 $R_v$이고, 읽은 키 집합이 $K_{read}$일 때:
$$\exists k \in K_{read}, \; \exists C_v \in \text{History}(k) \quad \text{s.t.} \quad R_v < C_v \le \text{CurrentVersion}$$
위 조건을 만족하는 키 $k$가 단 하나라도 존재한다면:
- $T$가 $k$를 읽은 이후에 다른 트랜잭션이 $k$의 값을 변경하여 커밋에 성공했다는 뜻입니다.
- 즉, **더티 리드(Dirty Read / Write Conflict)**가 발생했으므로 리졸버는 즉시 트랜잭션을 중단(Abort, `not_committed`, 1020)시킵니다.

만약 $T$의 모든 읽기 키가 담당 리졸버들로부터 충돌 없음을 승인받으면:
- 시퀀서는 새로운 커밋 버전 $C_{new} = \text{CurrentVersion} + 1$을 발급합니다.
- 리졸버들은 $T$가 쓴 키들($K_{write}$)의 최신 커밋 버전을 $C_{new}$로 갱신합니다.
- 트랜잭션 변동분은 TLog의 Paxos 쿼럼에 기록된 후 클라이언트에게 커밋 완료(ACK)가 반환됩니다.

---

## 4. 5초 MVCC 제한과 `transaction_too_old` (1007)

리졸버가 무한정 과거의 커밋 이력을 유지할 수는 없습니다(RAM 고갈 방지).
따라서 FoundationDB는 리졸버의 이력 보관 창을 **5초(약 500만 버전)**로 엄격히 제한합니다:
- 트랜잭션의 실행 시간이 5초를 초과하여 $R_v < \text{CurrentVersion} - \text{MaxHistoryVersions}$가 되면, 리졸버는 과거에 충돌이 있었는지 여부를 확신할 수 없습니다.
- 이때 트랜잭션은 즉시 `transaction_too_old` (에러 코드 1007)로 중단되며, 클라이언트는 새로운 $R_v$를 받아 처음부터 재시도해야 합니다.
