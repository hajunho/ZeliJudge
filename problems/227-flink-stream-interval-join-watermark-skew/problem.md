# 문제 227: 분산 스트림 처리: 인터벌 조인(Interval Join) vs 윈도우 조인(Windowed Join)과 워터마크 스큐(Watermark Skew) RocksDB 상태 만료 시뮬레이터

## 1. 개요 및 배경 (Incident Scenario)

대규모 글로벌 이커머스 및 핀테크 결제 플랫폼의 실시간 이상 금융 거래 탐지(Fraud Detection) 및 주문-결제 정산 파이프라인(Apache Flink 클러스터)에서 심각한 데이터 누락과 태스크 매니저(TaskManager) OOM(Out of Memory) 크래시 장애가 발생했습니다.

주문 이벤트 스트림(`Orders`)과 결제 승인 이벤트 스트림(`Payments`)은 별도의 Kafka 토픽에서 비동기적으로 발행되며, 네트워크 지연 및 PG사 인증 지연으로 인해 결제 이벤트는 주문 이벤트 발생 시점 기준 $[-5\text{분}, +30\text{분}]$ 사이의 가변적인 시간차를 두고 유입됩니다.

초기 파이프라인을 구축한 엔지니어링 팀은 두 가지 치명적인 아키텍처 결함에 직면했습니다:

1. **윈도우 조인(Windowed Join)의 경계선 분할(Boundary Splitting) 데이터 유실**:
   - 10분 단위 텀블링 윈도우(Tumbling Window Join)를 적용했을 때, 윈도우 경계(예: 09:59분 주문, 10:02분 결제)에 걸쳐 발생한 주문과 결제는 서로 다른 윈도우로 분리되어 영원히 매칭되지 못하고 유실(`WINDOW_BOUNDARY_MISSED_JOIN_DATA_LOSS`)되었습니다. 실무 결제 매칭율이 50% 수준으로 급락했습니다.
2. **워터마크 스큐(Watermark Skew)와 RocksDB 상태 팽창 및 OOM**:
   - 경계선 문제를 해결하기 위해 주문 시점 기준 상대적 시간차를 허용하는 **인터벌 조인(Interval Join)**을 도입했습니다. 그러나 특정 Kafka 파티션(예: 특정 국가나 가맹점의 유휴 파티션)에 트래픽이 일시적으로 끊기자, Flink의 연산자 복합 워터마크($W = \min(W_1, W_2, \dots, W_p)$)가 멈춰버렸습니다(Watermark Stalled).
   - Flink 인터벌 조인의 RocksDB 상태(State) 정리는 **워터마크가 $t + \text{upper\_bound}$를 초과할 때 트리거**되는데, 워터마크가 전진하지 않자 처리 완료된 수백만 건의 주문/결제 상태가 RocksDB에 영구 누적(`WATERMARK_SKEW_STATE_TTL_STARVATION_OOM`)되어 수 기가바이트의 디스크와 메모리를 잠식하며 클러스터가 연쇄 폭사했습니다.
3. **섣부른 State TTL 설정으로 인한 조기 퇴출(Premature Eviction)**:
   - 상태 메모리를 줄이겠다고 `state_ttl_ms`를 결제 유입 지연시간(예: 30분)보다 짧은 1분으로 강제 설정하자, 결제 이벤트가 합법적인 인터벌 이내에 도착했음에도 주문 상태가 이미 삭제되어 조인에 실패하는 참사(`PREMATURE_STATE_EVICTION_DATA_LOSS`)가 발생했습니다.

본 문제에서는 스트림 조인 전략(윈도우 조인 vs 인터벌 조인), 워터마크 아이들니스(`withIdleness`), 상태 TTL 및 파티션 활동성 조건에 따른 조인 성공률과 RocksDB 상태 메모리 점유율을 시뮬레이션하고 최적 파이프라인을 진단하는 프로그램을 구현합니다.

---

## 2. 아키텍처 및 스트림 조인 비교

```
[1. Windowed Join (Tumbling Window 10m)]
Window 1 [09:50 ~ 10:00)              Window 2 [10:00 ~ 10:10)
+-------------------------------+     +-------------------------------+
| Order A (09:58)               |     | Payment A (10:02)             |
| => Cannot match across window |     | => Orphaned payment!          |
+-------------------------------+     +-------------------------------+
=> MISSED JOIN! (Boundary Splitting Disaster)

[2. Interval Join (t_order - 5m <= t_payment <= t_order + 30m)]
Order A (09:58) -----------------------------------------------------> [State Buffer in RocksDB]
                      Payment A (10:02) arrives (+4m difference) ----> MATCH SUCCESS!
                                                                     |
Event Time Watermark advances past (09:58 + 30m = 10:28) -----------> [Evict Order A from RocksDB!]
                                                                      (Zero Memory Leak)

[3. The Watermark Skew Trap (Idle Partition)]
Partition 0 (Active): Event Ts = 10:30, Watermark = 10:30
Partition 1 (Idle)  : Event Ts = 09:50, Watermark = 09:50 (STALLED!)
Operator Watermark = min(10:30, 09:50) = 09:50!
=> Watermark NEVER advances! Order A remains in RocksDB FOREVER -> OOM Crash!
=> Solution: WatermarkStrategy.withIdleness(Duration.ofMinutes(1))
```

---

## 3. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "join_strategy": "INTERVAL_JOIN",
    "interval_lower_ms": -300000,
    "interval_upper_ms": 1800000,
    "window_size_ms": 600000,
    "watermark_idleness_enabled": true,
    "state_ttl_ms": null,
    "max_state_memory_mb": 512.0
  },
  "workload": {
    "orders": [
      {"id": "ord-1", "ts": 1000, "partition": 0},
      {"id": "ord-2", "ts": 2000, "partition": 0}
    ],
    "payments": [
      {"order_id": "ord-1", "ts": 5000, "partition": 1},
      {"order_id": "ord-2", "ts": 6000, "partition": 1}
    ],
    "partitions_activity": {
      "0": "ACTIVE",
      "1": "IDLE"
    }
  }
}
```

- `config`:
  - `join_strategy`: `"WINDOWED_JOIN"` 또는 `"INTERVAL_JOIN"`
  - `interval_lower_ms`: 주문 시점 기준 하한 오프셋 (ms, 예: `-300000` = -5분)
  - `interval_upper_ms`: 주문 시점 기준 상한 오프셋 (ms, 예: `1800000` = +30분)
  - `window_size_ms`: 윈도우 조인 시 텀블링 윈도우 크기 (ms, 기본 600000 = 10분)
  - `watermark_idleness_enabled`: 유휴 파티션을 워터마크 계산에서 일시 제외하는 Flink 아이들니스 활성화 여부 (boolean)
  - `state_ttl_ms`: 명시적 상태 TTL (ms, 미설정 시 `null`)
  - `max_state_memory_mb`: RocksDB 허용 최대 상태 메모리/디스크 크기 (MB)
- `workload`:
  - `orders`: 주문 이벤트 목록 (`id`, `ts`, `partition`)
  - `payments`: 결제 이벤트 목록 (`order_id`, `ts`, `partition`)
  - `partitions_activity`: 각 파티션의 활동 상태 (`"ACTIVE"`, `"IDLE"` 등)

---

## 4. 연산 및 시뮬레이션 규칙

1. **비즈니스 참 매칭(True Matchable Pairs)**:
   - 주문 $O$와 결제 $P$에 대해 $O.\text{id} == P.\text{order\_id}$ 이고,
     $$\text{interval\_lower\_ms} \le (P.\text{ts} - O.\text{ts}) \le \text{interval\_upper\_ms}$$
     를 만족하는 순수 논리적 매칭 대상 건수를 $\text{true\_matchable\_count}$로 정의합니다.
2. **윈도우 조인 (WINDOWED_JOIN)**:
   - 주문의 윈도우 인덱스: $w_o = \lfloor O.\text{ts} / \text{window\_size\_ms} \rfloor$
   - 결제의 윈도우 인덱스: $w_p = \lfloor P.\text{ts} / \text{window\_size\_ms} \rfloor$
   - $w_o == w_p$ 인 경우에만 매칭 성공(`joined_count += 1`), 다르면 유실(`missed_joins += 1`).
   - 피크 상태 메모리: $\text{peak\_state\_mb} = (\lfloor |\text{orders}| / 2 \rfloor \times 0.5) / 1024.0$
3. **인터벌 조인 (INTERVAL_JOIN)**:
   - `partitions_activity`에 `"IDLE"` 파티션이 존재하고 `watermark_idleness_enabled == False`인 경우:
     - 워터마크가 멈춤 (`watermark_stalled = True`).
     - 상태 퇴출(Eviction)이 완전히 중단되어 모든 주문과 결제가 RocksDB에 무한 누적:
       $$\text{peak\_state\_entries} = |\text{orders}| + |\text{payments}|$$
       $$\text{peak\_state\_mb} = (\text{peak\_state\_entries} \times 2.5) / 1024.0$$
     - $\text{peak\_state\_mb} > \text{max\_state\_memory\_mb}$ 이면 $\text{oom\_occurred} = \text{True}$.
   - 정상 워터마크 전진 시:
     - `state_ttl_ms`가 설정되어 있고 $\text{state\_ttl\_ms} < \text{interval\_upper\_ms}$인 경우:
       - 차이 $(P.\text{ts} - O.\text{ts}) > \text{state\_ttl\_ms}$ 인 이벤트는 조기 삭제되어 유실 (`premature_evictions += 1`, `missed_joins += 1`).
     - 그렇지 않은 경우 100% 매칭 성공.
     - 활성 동시 인터벌 윈도우 비율에 비례하여 바운디드(Bounded) 상태 유지:
       $$\text{ratio} = \min(1.0, \frac{\text{interval\_upper\_ms} - \text{interval\_lower\_ms}}{3600000})$$
       $$\text{peak\_state\_entries} = \max(10, \lfloor (|\text{orders}| + |\text{payments}|) \times \text{ratio} \times 0.25 \rfloor)$$
       $$\text{peak\_state\_mb} = (\text{peak\_state\_entries} \times 1.5) / 1024.0$$

---

## 5. 진단 판정 (Verdict Rules)

1. `oom_occurred == True`:
   - `status`: `"FAILED"`
   - `verdict`: `"WATERMARK_SKEW_STATE_TTL_STARVATION_OOM"`
2. `premature_evictions > 0` 이고 유실 비율 $\ge 10\%$:
   - `status`: `"FAILED"`
   - `verdict`: `"PREMATURE_STATE_EVICTION_DATA_LOSS"`
3. `join_strategy == "WINDOWED_JOIN"`:
   - `missed_joins > 0` 이고 유실 비율 $\ge 15\%$:
     - `status`: `"FAILED"`
     - `verdict`: `"WINDOW_BOUNDARY_MISSED_JOIN_DATA_LOSS"`
   - 유실이 없는 경우:
     - `status`: `"SUCCESS"`
     - `verdict`: `"WINDOWED_JOIN_PERFECT_ALIGNMENT"`
4. `watermark_stalled == True` (메모리 초과 전):
   - `status`: `"WARNING"`
   - `verdict`: `"WATERMARK_STALLED_IDLE_PARTITION_LEAK"`
5. 그 외 정상 인터벌 조인:
   - `status`: `"SUCCESS"`
   - `verdict`: `"OPTIMAL_INTERVAL_JOIN_WATERMARK_EVACUATION"`

---

## 6. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_INTERVAL_JOIN_WATERMARK_EVACUATION",
  "metrics": {
    "join_strategy": "INTERVAL_JOIN",
    "true_matchable_count": 10000,
    "joined_count": 10000,
    "missed_joins": 0,
    "join_success_rate": 1.0,
    "peak_state_entries": 1458,
    "peak_state_mb": 2.14,
    "watermark_stalled": false,
    "oom_occurred": false
  }
}
```
