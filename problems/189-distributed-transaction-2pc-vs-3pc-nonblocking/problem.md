# 문제 189: 분산 트랜잭션: 2PC vs 3PC 코디네이터 크래시 블로킹 병목과 Pre-Commit 비차단 복구

## 문제 배경
현대 대규모 분산 데이터베이스 및 금융 결제 시스템에서는 여러 독립된 데이터베이스 노드나 마이크로서비스에 걸쳐 원자적 트랜잭션을 보장하기 위해 원자적 커밋 프로토콜(Atomic Commit Protocol)을 사용합니다.

가장 널리 알려진 고전 프로토콜은 **2단계 커밋(2PC, Two-Phase Commit - Jim Gray 1978)**입니다:
1. **준비 단계 (Prepare Phase)**:
   - 코디네이터(Coordinator)가 모든 참여자(Participant)에게 `PREPARE` 메시지를 보냅니다.
   - 각 참여자는 로컬 트랜잭션 락을 획득하고 WAL 로그를 기록한 후 `YES` 또는 `NO`로 투표합니다.
2. **커밋 단계 (Commit Phase)**:
   - 모든 참여자가 `YES`로 투표하면 코디네이터는 `COMMIT`을 지시하고, 한 곳이라도 `NO`이거나 응답이 없으면 `ABORT`를 지시합니다.

### 2PC의 치명적 설계 결함: 코디네이터 크래시 블로킹 재앙 (Skeen's Theorem)
2PC는 단순하지만 **코디네이터 장애 시 시스템이 영구 정지하는 블로킹(Blocking) 프로토콜**입니다:
- 만약 모든 참여자가 `YES`로 투표하고 `PREPARED` 상태에 진입한 직후, 코디네이터가 `COMMIT`이나 `ABORT` 결정을 내리기 전에 갑작스러운 정전이나 서버 크래시로 사망했다고 가정해 봅시다.
- 참여자 노드들의 관점에서는:
  - 독자적으로 `COMMIT`할 수 없습니다 (코디네이터가 다른 노드의 투표 실패로 `ABORT`를 결정했을 가능성 존재).
  - 독자적으로 `ABORT`할 수도 없습니다 (코디네이터가 이미 다른 일부 노드에게 `COMMIT`을 보내고 죽었을 가능성 존재).
- 결국 참여자 노드들은 **영구 블로킹(`BLOCKED`) 상태에 빠져 모든 행 락(Row Lock)을 쥔 채 얼어붙고(`COORDINATOR_CRASH_2PC_BLOCKING_DISASTER`)**, 연관된 모든 비즈니스 트랜잭션이 줄줄이 마비됩니다!

---

## 3단계 커밋(3PC, Three-Phase Commit - Dale Skeen 1981)의 구원
Dale Skeen 박사는 페일-스톱(Fail-Stop) 환경에서 코디네이터 크래시가 발생하더라도 참여자들이 독자적으로 안전하게 트랜잭션을 종결지을 수 있는 **비차단 3단계 커밋(Non-blocking 3PC)**을 창안했습니다:

1. **Phase 1: Prepare (투표 단계)**
   - 코디네이터가 `PREPARE` 전송 -> 참여자가 `YES` 투표 후 `PREPARED` 진입.
2. **Phase 2: Pre-Commit (준비 커밋 단계 - 핵심 버퍼 단계!)**
   - 코디네이터가 전원 `YES` 확인 시 곧바로 커밋하지 않고 **`PRE_COMMIT` 메시지를 먼저 전파**합니다.
   - 참여자들은 `PRE_COMMIT` 상태로 전이합니다.
3. **Phase 3: Do-Commit (실제 커밋 단계)**
   - 코디네이터가 `COMMIT` 명령을 전송하여 트랜잭션을 최종 완료합니다.

### 3PC의 비차단 타임아웃 종결 프로토콜 (Termination Protocol)
코디네이터가 크래시되어 타임아웃(`PARTICIPANT_TIMEOUT`)이 발생했을 때:
- **상황 A: 참여자 중 누군가가 이미 `PRE_COMMIT` 상태에 도달한 경우**:
  - 참여자들은 **"모든 노드가 예외 없이 `YES`로 투표했음"을 수학적으로 100% 확신**할 수 있습니다 (누군가 `NO`였다면 코디네이터가 결코 `PRE_COMMIT`을 보냈을 리 없기 때문).
  - 따라서 참여자들은 코디네이터 없이도 **안전하게 `COMMITTED`로 승격**하고 락을 해제합니다!
- **상황 B: 모든 참여자가 아직 `PREPARED` 상태에 머물러 있는 경우**:
  - 아직 아무도 `PRE_COMMIT`에 도달하지 못했으므로, **"그 어떤 노드도 `COMMITTED` 상태에 도달하지 않았음"이 완벽하게 보장**됩니다.
  - 따라서 참여자들은 코디네이터 없이도 **안전하게 `ABORTED`로 전이**하고 락을 해제합니다!
- 결과: **어떤 시점에 코디네이터가 사망하더라도 영구 블로킹 0건, 100% 비차단 자가 치유(`NON_BLOCKING_3PC_SAFE_TERMINATION`) 달성!**

당신은 분산 트랜잭션 코디네이터 엔진을 구축하여, 2PC와 3PC 하에서 코디네이터 장애 시 발생하는 블로킹과 비차단 복구 메커니즘을 시뮬레이션해야 합니다.

---

## 입력 형식
입력은 표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다.

```json
{
  "system": {
    "protocol": "3PC",
    "participants": ["P1", "P2", "P3"],
    "participant_timeout_ms": 200.0
  },
  "workload": [
    {
      "op": "START_TX",
      "tx_id": "TX1",
      "votes": {"P1": "YES", "P2": "YES", "P3": "YES"},
      "resource_locks": {"P1": ["R1"], "P2": ["R2"], "P3": ["R3"]},
      "crash_before_commit": true,
      "wallclock_ms": 10.0
    },
    {
      "op": "COORDINATOR_CRASH",
      "tx_id": "TX1",
      "at_phase": "POST_PRE_COMMIT",
      "wallclock_ms": 25.0
    },
    {
      "op": "PARTICIPANT_TIMEOUT",
      "tx_id": "TX1",
      "wallclock_ms": 220.0
    }
  ]
}
```

### 필드 설명
- `system`:
  - `protocol` (string): `"2PC"` 또는 `"3PC"`.
  - `participants` (list of strings): 트랜잭션에 참여하는 노드 ID 목록.
  - `participant_timeout_ms` (float): 참여자가 코디네이터 응답을 기다리는 타임아웃 한계 시간.
- `workload`: 시간 순서대로 발생하는 이벤트 목록.
  - `START_TX`: 분산 트랜잭션 시작 (`tx_id`, `votes`, `resource_locks`, `crash_before_commit`, `crash_before_pre_commit`).
  - `COORDINATOR_CRASH`: 코디네이터 사망 (`at_phase`: `"POST_PREPARE"`, `"POST_PRE_COMMIT"`).
  - `PARTICIPANT_TIMEOUT`: 참여자들의 타임아웃 만료 및 종결 프로토콜 트리거.

---

## 출력 형식
표준 출력(stdout)으로 JSON 형태로 들여쓰기 2칸으로 출력합니다.

```json
{
  "status": "SUCCESS",
  "protocol": "3PC",
  "metrics": {
    "protocol": "3PC",
    "total_transactions": 1,
    "committed_transactions": 1,
    "aborted_transactions": 0,
    "blocked_participants_count": 0,
    "nonblocking_recoveries": 1,
    "coordinator_crashes": 1,
    "verdict": "NON_BLOCKING_3PC_SAFE_TERMINATION"
  },
  "participant_states": {
    "P1": "COMMITTED",
    "P2": "COMMITTED",
    "P3": "COMMITTED"
  },
  "events_log": [
    {
      "wallclock_ms": 10.0,
      "action": "PARTICIPANT_VOTED_YES",
      "participant": "P1",
      "state": "PREPARED",
      "locks": ["R1"]
    }
  ]
}
```

### 판정(Verdict) 규칙
1. `blocked_participants_count > 0`인 경우:
   - `status = "FAILED"`, `verdict = "COORDINATOR_CRASH_2PC_BLOCKING_DISASTER"`
2. 코디네이터 크래시 후 참여자들이 비차단 타임아웃으로 자가 종결한 경우:
   - `status = "SUCCESS"`, `verdict = "NON_BLOCKING_3PC_SAFE_TERMINATION"`
3. 참여자가 `NO`로 투표하여 정상 중단된 경우:
   - `status = "SUCCESS"`, `verdict = "TRANSACTION_VOTE_NO_ABORT"`
4. 2PC 프로토콜로 정상 커밋 완료된 경우:
   - `status = "SUCCESS"`, `verdict = "TWO_PHASE_COMMIT_SUCCESS"`
5. 3PC 프로토콜로 정상 커밋 완료된 경우:
   - `status = "SUCCESS"`, `verdict = "THREE_PHASE_COMMIT_SUCCESS"`
