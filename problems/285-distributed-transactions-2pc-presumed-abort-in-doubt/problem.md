# 문제 285: 분산 트랜잭션 2단계 커밋(2PC) & Presumed Abort 최적화 및 의문 상태 협조적 종결 엔진 (Distributed 2-Phase Commit with Presumed Abort & In-Doubt Cooperative Termination Engine)

## 문제 설명

구글 스패너(Google Spanner), 칵로치DB(CockroachDB), TiDB와 같은 현대 분산 데이터베이스나 금융 코어 뱅킹 시스템에서는 여러 물리적 샤드(Shard)와 파티션에 걸쳐 데이터의 원자성(Atomicity)과 일관성(Consistency)을 보장하기 위해 **2단계 커밋(Two-Phase Commit, 2PC)** 프로토콜을 사용합니다.

그러나 고전적인 2PC는 코디네이터(Coordinator)의 단일 장애점(SPOF), 디스크 fsync로 인한 높은 지연 시간, 그리고 참여자 노드가 결정을 내리지 못하고 락을 영구히 쥐고 있는 **의문 상태(In-Doubt State / 블로킹 취약점)**라는 치명적인 문제를 안고 있습니다.

이를 해결하기 위해 IBM R* 분산 데이터베이스 연구팀(C. Mohan 등, 1986)은 **Presumed Abort (PA)** 최적화와 **협조적 종결 프로토콜(Cooperative Termination Protocol, CTP)**을 제안했습니다:

### 1. 기본 2PC 프로토콜 흐름
- **1단계 (Prepare Phase)**:
  - 코디네이터가 모든 참여자(Participant)에게 `PREPARE` 메시지를 전송합니다.
  - 각 참여자는 로컬 트랜잭션 검증 및 락을 획득하고, 성공 시 WAL에 `PREPARED` 레코드를 강제 기록(fsync)한 후 `VOTE_COMMIT`을 응답합니다. 실패 시 `ABORT` 레코드를 기록하고 `VOTE_ABORT`를 응답합니다.
  - `VOTE_COMMIT`을 보낸 참여자는 코디네이터의 최종 결정을 받기 전까지 스스로 커밋하거나 롤백할 수 없는 **의문 상태(In-Doubt State, `in_doubt=true`)**에 진입합니다.
- **2단계 (Commit/Abort Phase)**:
  - 모든 참여자가 `VOTE_COMMIT`을 보낸 경우: 코디네이터는 WAL에 `COMMIT` 레코드를 강제 기록(fsync)하고 `GLOBAL_COMMIT`을 브로드캐스트합니다. 모든 참여자가 커밋하고 ACK를 보내면 코디네이터는 `END` 레코드를 기록하고 트랜잭션을 메모리에서 소멸(Forget)시킵니다.
  - 한 참여자라도 `VOTE_ABORT`를 보낸 경우: 코디네이터는 `GLOBAL_ABORT`를 브로드캐스트합니다.

### 2. Presumed Abort (PA) 최적화
- 분산 시스템에서 트랜잭션 중단(Abort)은 직렬성 충돌, 제약조건 위반, 네트워크 타임아웃 등으로 빈번하게 발생합니다.
- 고전적 2PC는 중단 시에도 코디네이터가 `ABORT` 레코드를 디스크에 강제 기록하고 모든 참여자의 ACK를 수집해야 했습니다.
- **Presumed Abort 규칙**:
  - 코디네이터는 트랜잭션이 중단될 때 **디스크에 ABORT 레코드를 강제 기록하지 않으며, 메모리에서 즉시 트랜잭션을 소멸(Forget)**시킵니다.
  - 만약 네트워크 장애나 크래시 후 참여자가 해당 트랜잭션의 상태를 코디네이터에게 문의했을 때, 코디네이터의 WAL에 `COMMIT` 기록이 없다면 코디네이터는 **"해당 트랜잭션은 당연히 중단되었다(Presumed Abort)"**고 간주하고 즉시 `GLOBAL_ABORT`를 응답합니다.
  - 이로써 중단 트랜잭션의 디스크 I/O fsync 오버헤드와 메시지 왕복을 완전히 제거합니다.

### 3. 의문 상태(In-Doubt)와 협조적 종결 프로토콜 (CTP)
- 참여자가 `VOTE_COMMIT`을 보낸 후 네트워크 단절이나 코디네이터 크래시로 인해 최종 결정을 수신하지 못하면 행(Row) 락을 무한정 쥐고 시스템 전체가 정체됩니다.
- **협조적 종결 (Cooperative Termination)**:
  - 의문 상태의 참여자는 코디네이터의 복구를 무작정 기다리는 대신, **동료 참여자(Peer Participants)**들에게 상태를 질의합니다.
  - 동료 중 단 한 노드라도 `COMMITTED` 상태라면 코디네이터가 `GLOBAL_COMMIT`을 결정했음이 확실하므로 즉시 커밋합니다 (`COMMITTED_VIA_PEER`).
  - 동료 중 단 한 노드라도 `ABORTED` 상태라면(또는 `VOTE_ABORT`를 투표했다면) 즉시 중단합니다 (`ABORTED_VIA_PEER`).
  - 만약 연락 가능한 모든 동료가 여전히 `PREPARED` 상태라면, 참여자들끼리는 결정을 내릴 수 없으므로 코디네이터의 복구를 기다려야 합니다 (`BLOCKED_ALL_PEERS_IN_DOUBT`).

### 4. 코디네이터 크래시 복구 (WAL Crash Recovery)
- 코디네이터가 재부팅되면 로컬 WAL 로그를 스캔합니다.
- `COMMIT` 레코드는 존재하지만 `END` 레코드가 없는 트랜잭션은 커밋 결정 후 모든 ACK를 수집하기 전에 크래시가 발생한 것이므로, 참여자들에게 `GLOBAL_COMMIT`을 재전송하고 `END`를 기록합니다.
- `COMMIT` 레코드가 없는 트랜잭션은 Presumed Abort 원칙에 따라 무시(중단 처리)됩니다.

당신은 Presumed Abort와 협조적 종결 프로토콜을 지원하는 분산 2PC 트랜잭션 코디네이션 엔진을 구현해야 합니다.

---

## 입력 형식 (JSON)

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "participants": ["Node-A", "Node-B", "Node-C"],
  "operations": [
    {
      "step": 1,
      "op": "START_TX",
      "tx_id": "TX-101"
    },
    {
      "step": 2,
      "op": "PREPARE",
      "tx_id": "TX-101",
      "votes": {
        "Node-A": "VOTE_COMMIT",
        "Node-B": "VOTE_COMMIT",
        "Node-C": "VOTE_COMMIT"
      }
    },
    {
      "step": 3,
      "op": "COMMIT_PHASE",
      "tx_id": "TX-101",
      "decision": "GLOBAL_COMMIT",
      "failed_participants": ["Node-C"]
    },
    {
      "step": 4,
      "op": "COOPERATIVE_TERMINATION",
      "participant": "Node-C",
      "tx_id": "TX-101"
    },
    {
      "step": 5,
      "op": "GET_SNAPSHOT"
    }
  ]
}
```

### 연산 종류
1. `START_TX`: 새로운 분산 트랜잭션(`tx_id`)을 시작합니다.
2. `PREPARE`: 1단계를 실행하여 각 참여자의 투표를 수집합니다. 모두 `VOTE_COMMIT`이면 코디네이터 WAL에 `COMMIT`을 강제 기록하고 `GLOBAL_COMMIT`을 결정합니다. 하나라도 `VOTE_ABORT`이면 코디네이터 WAL 기록 없이 `GLOBAL_ABORT`를 결정합니다 (Presumed Abort).
3. `COMMIT_PHASE`: 결정된 명령(`GLOBAL_COMMIT` 또는 `GLOBAL_ABORT`)을 브로드캐스트합니다. `failed_participants`에 지정된 노드는 메시지를 수신하지 못하고 이전 상태(의문 상태)에 머뭅니다. 모든 참여자가 정상 수신하면 코디네이터는 `END`를 기록합니다.
4. `COOPERATIVE_TERMINATION`: 의문 상태의 특정 참여자가 동료 노드들에게 상태를 질의하여 자체적으로 트랜잭션을 종결합니다.
5. `COORDINATOR_QUERY`: 의문 상태의 참여자가 코디네이터에게 상태를 직접 질의합니다. 코디네이터 WAL에 `COMMIT`이 없으면 `GLOBAL_ABORT`로 응답합니다.
6. `CRASH_AND_RECOVER_COORDINATOR`: 코디네이터 재부팅 및 WAL 복구를 수행하여 `COMMIT`은 있으나 `END`가 없는 트랜잭션을 찾아 재전송하고 복구합니다.
7. `GET_SNAPSHOT`: 코디네이터 WAL, 상태, 참여자별 상태 및 메트릭 스냅샷을 반환합니다.

---

## 출력 형식 (JSON)

표준 출력(stdout)으로 다음 스키마를 만족하는 단일 줄 JSON 객체를 출력합니다.

```json
{
  "operations_log": [
    {
      "step": 1,
      "op": "START_TX",
      "tx_id": "TX-101",
      "status": "INITIATED"
    },
    {
      "step": 2,
      "op": "PREPARE",
      "tx_id": "TX-101",
      "votes": {
        "Node-A": "VOTE_COMMIT",
        "Node-B": "VOTE_COMMIT",
        "Node-C": "VOTE_COMMIT"
      },
      "decision": "GLOBAL_COMMIT"
    }
  ],
  "final_state": {
    "coordinator_state": {
      "TX-101": "COMMITTED"
    },
    "coordinator_wal": [
      {"tx_id": "TX-101", "record": "COMMIT"}
    ],
    "participant_states": {
      "Node-A": {"TX-101": "COMMITTED"},
      "Node-B": {"TX-101": "COMMITTED"},
      "Node-C": {"TX-101": "COMMITTED"}
    },
    "metrics": {
      "transactions_started": 1,
      "transactions_committed": 1,
      "transactions_aborted": 0,
      "coord_forced_wal_writes": 1,
      "in_doubt_resolutions": 1
    }
  }
}
```

---

## 제약 조건

- 참여자 노드 수: $2 \le N \le 8$
- 연산 수: $1 \le M \le 30$
- 각 트랜잭션 ID는 고유한 문자열
