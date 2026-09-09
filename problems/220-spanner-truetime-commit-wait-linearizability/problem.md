# 문제 220: 구글 스패너(Google Spanner) 분산 트랜잭션: TrueTime API 시계 불확실성(epsilon)과 커밋 대기(Commit Wait) vs 선형성(Linearizability) 보장

## 1. 개요 (Incident Scenario)

글로벌 금융 결제 및 크로스-리전(Cross-Region) 원장 시스템을 운영하는 글로벌 핀테크 인프라 팀은 차세대 분산 뉴SQL 데이터베이스(Google Spanner / CockroachDB / YugabyteDB 계열)를 도입하여 다중 대륙 데이터센터 간 데이터 정합성을 유지하고 있습니다.

스패너는 전 세계 데이터센터에 분산된 Paxos 복제 그룹과 2단계 커밋(2PC) 프로토콜, 그리고 원자 시계(Atomic Clock)와 GPS 수신기로 구축된 **TrueTime API**를 통해 분산 락(Read Lock) 없이도 전역 스냅샷 읽기(Lock-Free Consistent Snapshot Reads)와 **외부 일관성(External Consistency, 일명 선형성 / Strict Serializability)**을 보장하는 유일무이한 아키텍처를 자랑합니다.

그러나 최근 인프라 점검 및 네트워크 케이블 장애, 데이터센터 GPS 안테나 결함 이후 다음과 같은 두 가지 치명적인 분산 트랜잭션 장애가 보고되었습니다:

1. **커밋 대기(Commit Wait) 비활성화로 인한 인과성 역전 및 유령 읽기(Stale Snapshot Reads)**:
   트랜잭션 지연 시간을 극단적으로 줄이려는 의도로 특정 리전에서 커밋 대기 규칙(`commit_wait_enabled = false`)을 우회하자, 실시간(Real Absolute Time) 상으로 트랜잭션 $T_1$이 완료된 후 시작된 트랜잭션 $T_2$가 로컬 시계 지연으로 인해 $s_2 < s_1$인 타임스탬프를 할당받는 사태가 발생했습니다.
   그 결과 유럽 리전의 스냅샷 읽기 쿼리가 이미 커밋된 최신 송금 내역을 조회하지 못하고 과거의 잔액을 읽어 이중 출금(Double Spending) 및 선형성 위반(`STALE_SNAPSHOT_EXTERNAL_CONSISTENCY_VIOLATION`)이 일어났습니다.

2. **GPS 안테나 단선에 따른 시계 불확실성($\epsilon$) 폭증 및 락 대기 타임아웃 붕괴**:
   미국 동부 데이터센터의 루비듐 원자 시계 드리프트와 마스터 안테나 장애로 인해 TrueTime 오차 범위($\epsilon$)가 평상시 4ms 미만에서 최대 80ms~150ms까지 치솟았습니다.
   스패너의 선형성 보장 규칙에 따라 코디네이터는 최소 $2\epsilon$ (160ms~300ms) 동안 트랜잭션 락을 해제하지 못하고 대기(`Commit Wait`)해야 했습니다.
   핫스팟 행(Hot Key)을 갱신하려는 후속 쓰기 트랜잭션들의 대기 큐가 급증하여 락 획득 타임아웃(`lock_wait_timeout_ms = 300ms~500ms`)을 초과하고 줄줄이 롤백되는 연쇄 트랜잭션 마비(`CLOCK_UNCERTAINTY_COMMIT_WAIT_COLLAPSE`) 사태가 초래되었습니다.

당신은 분산 데이터베이스 및 고성능 인프라 엔지니어로서, TrueTime 시간 구간 모델($TT.now() = [t - \epsilon, t + \epsilon]$), 커밋 타임스탬프 $s$의 결정, 커밋 대기 대기 시간 계산, 2단계 잠금(2PL) 충돌 해소 및 선형성 위반 여부를 시뮬레이션하고 클러스터의 상태를 판정하는 진단 엔진을 구축해야 합니다.

---

## 2. 아키텍처 및 상태 모델

```
 [TrueTime API Time Window & Commit Wait Mechanics]

  Real Absolute Time (t) ────────────────────────────────────────────────────────►
  Coordinator Local Clock (t_local = t + offset,  -ε <= offset <= +ε)

                   [Prepare Phase: Coordinator picks s]
                   s = max(TT.now().latest, last_assigned_ts + 0.1)
                                      │
                                      ▼
             [Commit Wait Period: Must wait until TT.now().earliest > s]
             ◄───────────────── Minimum Wait: 2ε ────────────────►
             │                                                    │
     t_prepare (Lock Held)                                  t_release (Lock Released)
             │                                                    │
             ▼                                                    ▼
    ┌─────────────────┐                                  ┌─────────────────┐
    │  Transaction 1  │ ── Commit Wait (Hold 2PL Locks) ─►│ Locks Released! │
    └─────────────────┘                                  └─────────────────┘
                                                                  │
                                   Client ACK received            ▼
                               ───────────────────────────► ┌─────────────────┐
                                                            │  Transaction 2  │
                                                            │  Starts at t_2  │
                                                            └─────────────────┘
                                                            t_start(T2) > t_commit(T1)
                                                            ==> Guarantees s2 > s1!
```

### 시뮬레이션 동작 규격

1. **TrueTime API 시계 모델**:
   - 클러스터의 전역 시계 불확실성 상한을 `clock_uncertainty_epsilon_ms` ($\epsilon$)로 정의합니다.
   - 각 데이터센터(리전)는 실시간(Absolute Real Time, $t$) 대비 시계 오프셋 `datacenter_clock_offsets_ms`를 가집니다.
   - 오프셋은 물리적 드리프트 한계 내에 존재하므로 $[-\epsilon, +\epsilon]$ 범위로 클램핑됩니다.
   - 데이터센터의 로컬 시계는 $t_{\text{local}} = t_{\text{real}} + \text{offset}$ 입니다.
   - `TT.now()` 질의 시 반환되는 신뢰 구간은 $[t_{\text{local}} - \epsilon, t_{\text{local}} + \epsilon]$ 입니다:
     - $TT.now().\text{earliest} = t_{\text{local}} - \epsilon$
     - $TT.now().\text{latest} = t_{\text{local}} + \epsilon$

2. **트랜잭션 실행 및 2단계 락킹(2PL)**:
   - 각 트랜잭션은 `id`, `type` (`READ_WRITE` 또는 `SNAPSHOT_READ`), `datacenter`, `keys`, `arrival_time_ms`, `execution_duration_ms`를 갖습니다.
   - `READ_WRITE` 트랜잭션은 갱신할 키(`keys`)에 대해 배타적 잠금(Exclusive Lock)을 획득해야 합니다.
   - 이미 다른 트랜잭션이 해당 키의 락을 보유 중이고 해제 절대시간(`lock_release_real_time`)이 현재보다 뒤라면, 락이 해제될 때까지 대기합니다.
   - 대기 시간($\Delta t$)이 `lock_wait_timeout_ms`를 초과하면 트랜잭션은 즉시 중단(`aborted_lock_timeouts += 1`)되고 실행을 종료합니다.

3. **커밋 타임스탬프 $s$ 결정 및 커밋 대기(Commit Wait)**:
   - 트랜잭션 연산이 완료되는 시점($t_{\text{prepare}}$)에 코디네이터는 커밋 타임스탬프 $s$를 결정합니다:
     $$s = \max(TT.now().\text{latest},\; \text{last\_assigned\_ts} + 0.1)$$
   - **커밋 대기 규칙 (`commit_wait_enabled = true`)**:
     - 코디네이터는 로컬 시계의 $TT.now().\text{earliest} > s$가 될 때까지 절대 락을 해제하거나 클라이언트에 커밋 완료를 반환할 수 없습니다.
     - 로컬 시계 기준 대기 조건: $(t_{\text{real}} + \text{offset}) - \epsilon > s \implies t_{\text{real}} > s + \epsilon - \text{offset}$
     - 대기 시간 $\text{wait\_duration} = \max(0, (s + \epsilon - \text{offset}) - t_{\text{real}})$ 만큼 시스템 시간을 전진시키고 누적합니다.
     - 락 해제 절대시간은 대기가 완료된 시점입니다.
   - **커밋 대기 우회 (`commit_wait_enabled = false`)**:
     - 커밋 대기를 무시하고 $t_{\text{prepare}}$ 시점에 락을 즉시 해제하며, 타임스탬프는 로컬 준비 시각($t_{\text{prepare}} + \text{offset}$)으로 부여됩니다.

4. **선형성(External Consistency / Linearizability) 검증**:
   - 시스템 내에서 완료된 모든 트랜잭션 쌍 $(T_1, T_2)$에 대해:
     - 실시간 상으로 $T_1$의 커밋 완료 절대 시각이 $T_2$의 시작(도착) 절대 시각보다 앞서고($t_{\text{commit}}(T_1) < t_{\text{commit}}(T_2)$), 두 트랜잭션이 겹치는 키를 다룬다면,
     - 반드시 커밋 타임스탬프는 $s_1 < s_2$를 만족해야 합니다. 만약 $s_1 \ge s_2$라면 인과성 역전 위반(`linearizability_violations += 1`)입니다.
   - `SNAPSHOT_READ` 트랜잭션:
     - 리더가 지정한 `read_timestamp_ms`로 조회할 때, 리드 도착 이전에 이미 실시간으로 커밋된 동일 키의 쓰기 트랜잭션 커밋 타임스탬프가 `read_timestamp_ms`보다 크다면 최신 데이터를 누락한 것이므로 선형성 위반으로 판정합니다.

5. **최종 상태 및 Verdict 판정 규칙**:
   - `linearizability_violations > 0`:
     - `status = "FAILED"`, `verdict = "STALE_SNAPSHOT_EXTERNAL_CONSISTENCY_VIOLATION"`
   - `aborted_lock_timeouts > 0` 또는 ($\epsilon \ge 50.0$ 이고 평균 커밋 대기 시간이 100.0ms 이상):
     - `status = "FAILED"`, `verdict = "CLOCK_UNCERTAINTY_COMMIT_WAIT_COLLAPSE"`
   - $\epsilon \le 7.0$ 이고 `commit_wait_enabled = true` 이며 위반 및 중단 건수가 0인 경우:
     - `status = "SUCCESS"`, `verdict = "OPTIMAL_TRUETIME_COMMIT_WAIT_LINEARIZABILITY"`
   - 그 외 정상 동작:
     - `status = "SUCCESS"`, `verdict = "NORMAL_SPANNER_TRANSACTION_FLOW"`

---

## 3. 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "clock_uncertainty_epsilon_ms": 4.0,
    "commit_wait_enabled": true,
    "lock_wait_timeout_ms": 500.0,
    "datacenter_clock_offsets_ms": {
      "us-east": 2.0,
      "europe-west": -2.0,
      "asia-east": 1.0
    }
  },
  "transactions": [
    {
      "id": "T1",
      "type": "READ_WRITE",
      "datacenter": "us-east",
      "keys": ["acc:101"],
      "arrival_time_ms": 0.0,
      "execution_duration_ms": 10.0
    },
    {
      "id": "T2",
      "type": "READ_WRITE",
      "datacenter": "europe-west",
      "keys": ["acc:101"],
      "arrival_time_ms": 25.0,
      "execution_duration_ms": 10.0
    }
  ]
}
```

---

## 4. 출력 형식

표준 출력(stdout)으로 JSON 객체를 출력합니다. 부동소수점 수치는 소수점 둘째 자리까지 반올림합니다.

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_TRUETIME_COMMIT_WAIT_LINEARIZABILITY",
  "metrics": {
    "clock_uncertainty_epsilon_ms": 4.0,
    "commit_wait_enabled": true,
    "total_transactions": 2,
    "committed_transactions": 2,
    "aborted_lock_timeouts": 0,
    "linearizability_violations": 0,
    "average_commit_wait_ms": 6.0,
    "average_transaction_latency_ms": 16.0
  }
}
```
