# Problem 187: 분산 트랜잭션 동시성 제어: Wait-Die vs Wound-Wait 교착상태 회피(Deadlock Avoidance)와 Google Spanner 선점 아키텍처

## 문제 설명

수백 대의 노드와 전 세계 데이터센터에 샤딩된 대규모 분산 트랜잭션 데이터베이스(Google Spanner, CockroachDB, TiKV 등)를 운영하는 코어 엔지니어링 팀은 멀티 샤드 동시성 제어(Distributed Concurrency Control) 방식 설계 중 심각한 난관에 부딪혔습니다.

단일 인스턴스 RDBMS(MySQL, PostgreSQL)처럼 **대기 그래프(Wait-For Graph, WFG)**를 중앙에서 주기적으로 수집하여 사이클(DFS $O(V+E)$)을 감지하는 방식은 분산 환경에서 다음과 같은 치명적 문제를 유발했습니다:
1. **분산 WFG 수집의 네트워크 오버헤드와 탐지 지연**: 여러 샤드에 흩어진 락 대기 간선(Edge)을 중앙 코디네이터로 모으는 과정에서 네트워크 지연이 발생하여, 이미 데드락에 빠진 수천 개의 트랜잭션이 수 초 동안 자원을 잠근 채 시스템 전체를 마비시켰습니다.
2. **나이브 락 타임아웃(`NAIVE_LOCK_TIMEOUT`)의 참사**: 데드락 탐지기 대신 단순 타임아웃에 의존하자, 고경합 상황에서 정상적으로 대기 중이던 트랜잭션들까지 줄줄이 50ms 타임아웃 롤백을 맞아 TPS가 바닥을 쳤습니다.
3. **분산 데드락 방지(Deadlock Avoidance)의 필요성**: 데드락이 발생한 후 탐지하여 롤백하는 사후 수습(Detection) 대신, **트랜잭션 타임스탬프(Monotonic Timestamp) 우선순위**를 이용하여 **데드락 사이클 형성을 원천 차단(Avoidance)**하는 비차단(Non-blocking) 알고리즘이 필수적이었습니다.

엔지니어링 팀은 1978년 Rosenkrantz 등이 제안하고 **Google Spanner**가 채택한 2대 분산 교착 회피 기법인 **Wait-Die(비선점형)**와 **Wound-Wait(선점형)**를 시뮬레이션하고, 데드락 제로(Zero-Deadlock)와 커밋 성공률을 비교 평가하는 엔진을 구축하기로 결정했습니다.

---

## 핵심 동시성 제어 모드 (Concurrency Modes)

모든 트랜잭션은 고유한 단조 증가 타임스탬프($ts$)를 부여받습니다.
**타임스탬프가 작을수록 먼저 시작된 연장자(Older Transaction)이며, 우선순위가 높습니다.**

### 1. `NAIVE_LOCK_TIMEOUT` (순진한 타임아웃 대기)
- 자원이 이미 다른 트랜잭션에 의해 잠겨 있으면 무조건 대기 큐에 진입합니다.
- 상호 대기 사이클(Deadlock Cycle, 예: $T_1 \to T_2 \to T_1$)이 형성되어도 감지하지 못하며, 대기 시간이 `lock_wait_timeout_ms`를 초과할 때까지 락을 잡고 굳어버립니다 (`ABORT_TIMEOUT`).
- 평가 판정(Verdict): `DISTRIBUTED_DEADLOCK_TIMEOUT_COLLAPSE` (데드락 사이클 발생 시 `status: FAILED`)

### 2. `WAIT_DIE` (비선점형 - Older Waits, Younger Dies)
- 요청자($T_{req}$)가 점유자($T_{holder}$)의 자원을 요청할 때:
  - **$T_{req}.ts < T_{holder}.ts$ (요청자가 연장자인 경우)**:
    - **Older Waits**: 연장자는 대기 큐에 들어가 점유자가 끝날 때까지 기다립니다 (`waits_queued += 1`).
  - **$T_{req}.ts > T_{holder}.ts$ (요청자가 연하인 경우)**:
    - **Younger Dies**: 연하는 기다리지 못하고 **즉시 자결(Abort/Die)**합니다 (`aborts_die += 1`).
- 대기 간선은 오직 "연장자 $\to$ 연하" 방향으로만 생기므로 사이클이 절대 형성되지 않습니다.
- 단점: 연하 트랜잭션이 연장자의 긴 작업을 만나면 재시도할 때마다 반복해서 자결하는 기아 현상(Abort Churn)이 발생합니다.
- 평가 판정(Verdict): `WAIT_DIE_STARVATION_CHURN`

### 3. `WOUND_WAIT` (선점형 - Google Spanner 채택 기법: Younger Waits, Older Wounds)
- 요청자($T_{req}$)가 점유자($T_{holder}$)의 자원을 요청할 때:
  - **$T_{req}.ts < T_{holder}.ts$ (요청자가 연장자인 경우)**:
    - **Older Wounds Younger**: 연장자는 연하 점유자를 **즉시 상처 입히고 선점 강제 종료(Preempt/Wound)**시킵니다 (`aborts_wound += 1`).
    - 연하가 점유하던 자원을 즉시 회수하여 연장자가 지체 없이 락을 획득합니다!
  - **$T_{req}.ts > T_{holder}.ts$ (요청자가 연하인 경우)**:
    - **Younger Waits**: 연하는 대기 큐에 들어가 연장자가 끝날 때까지 평화롭게 기다립니다 (`waits_queued += 1`).
- 대기 간선은 오직 "연하 $\to$ 연장자" 방향으로만 생기므로 사이클이 절대 형성되지 않습니다.
- **장점 (Google Spanner 채택 이유)**:
  - 연장자 트랜잭션은 어떤 연하에게도 방해받지 않고 초고속 완주할 수 있습니다.
  - 연하는 연장자가 자원을 실제로 요구할 때만 선점되므로, 불필요한 연쇄 취소가 최소화됩니다.
- 평가 판정(Verdict): `OPTIMAL_WOUND_WAIT_SPANNER`

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "concurrency_mode": "WOUND_WAIT",
    "lock_wait_timeout_ms": 50.0
  },
  "workload": [
    {"op": "REQUEST_LOCK", "wallclock_ms": 10.0, "tx_id": "T1", "ts": 10.0, "res_id": "R1"},
    {"op": "REQUEST_LOCK", "wallclock_ms": 20.0, "tx_id": "T2", "ts": 20.0, "res_id": "R2"},
    {"op": "REQUEST_LOCK", "wallclock_ms": 30.0, "tx_id": "T1", "ts": 10.0, "res_id": "R2"},
    {"op": "COMMIT", "wallclock_ms": 50.0, "tx_id": "T1"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "concurrency_mode": "WOUND_WAIT",
    "total_lock_requests": 3,
    "successful_commits": 1,
    "total_aborts": 1,
    "commit_rate": 0.5,
    "deadlock_cycles": 0
  },
  "metrics": {
    "total_lock_requests": 3,
    "locks_granted_immediately": 2,
    "waits_queued": 0,
    "aborts_die": 0,
    "aborts_wound": 1,
    "aborts_timeout": 0,
    "successful_commits": 1,
    "commit_rate": 0.5,
    "deadlock_cycles_detected": 0,
    "verdict": "OPTIMAL_WOUND_WAIT_SPANNER"
  },
  "sample_events": [
    {
      "wallclock_ms": 10.0,
      "action": "LOCK_GRANTED",
      "tx_id": "T1",
      "res_id": "R1"
    }
  ]
}
```

> **성공 기준**: `deadlock_cycles_detected == 0`일 때 `status: "SUCCESS"`, 데드락이 1회라도 감지되면 `status: "FAILED"`.
