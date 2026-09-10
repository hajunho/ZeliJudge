# 리눅스 커널 Tree RCU 유휴 상태(Quiescent State) 및 유예 기간(Grace Period) 상태 머신 엔진

## 1. 개요 및 배경

리눅스 커널의 **RCU(Read-Copy Update, `kernel/rcu/tree.c`)**는 읽기 작업이 쓰기 작업에 의해 블로킹되지 않도록 하여 다중 코어 시스템에서 최고의 읽기 확장성을 제공하는 핵심 동기화 메커니즘입니다.
독자(Reader)는 `rcu_read_lock()`과 `rcu_read_unlock()` 사이에서 원자적 명령어(Atomic Instruction)나 버스 락, 캐시라인 갱신 없이 공유 데이터 구조를 초고속으로 순회합니다.

그러나 갱신자(Updater)가 공유 객체를 리스트에서 제거(`list_del_rcu`)한 뒤 메모리를 안전하게 해제(`kfree`)하려면, 해당 제거 시점 이전에 진입했던 **모든 독자가 임계 구역(Critical Section)을 완전히 빠져나올 때까지 대기**해야 합니다. 이 대기 기간을 **유예 기간(Grace Period, GP)**이라 부릅니다.

대규모 멀티소켓 서버(수백~수천 CPU 코어)에서 모든 CPU가 전역 단일 카운터나 락을 갱신하면 심각한 캐시라인 바운싱이 발생합니다.
폴 매케니(Paul E. McKenney)가 고안한 **Tree RCU (`struct rcu_node`)**는 CPU들을 계층적 트리 구조로 조직화하여 락 경합을 O(1) 수준으로 분산시킵니다:
1. **리프 노드 (`leaf rcu_node`)**: 최대 `fanout`개의 CPU를 묶어 64비트 비트마스크(`qsmask`)로 관리합니다.
2. **유휴 상태(Quiescent State, QS)**: CPU가 컨텍스트 스위치(스케줄링), 사용자 공간 복귀, 또는 Idle 루프에 진입할 때 유휴 상태를 통과합니다. RCU 읽기 임계 구역(`rcu_read_lock`) 내부에 머무는 동안에는 절대 QS를 보고할 수 없습니다!
3. **계층적 전파(Hierarchical Propagation)**:
   - CPU가 QS를 보고하면 자신의 리프 노드 `qsmask`에서 해당 비트를 클리어합니다.
   - 리프 노드의 모든 CPU가 QS를 보고하여 `qsmask == 0`이 되면, 상위 부모 노드의 해당 비트를 클리어합니다.
   - 최상위 루트 노드의 `qsmask == 0`이 되는 순간 **유예 기간이 종료(Grace Period Completed)**되며, 해당 GP를 기다리던 모든 비동기 콜백(`call_rcu`)이 일괄 실행(`kfree`)됩니다.
4. **RCU 스톨 감지기(RCU CPU Stall Detector)**: 특정 CPU가 장시간 QS를 보고하지 못하면 스톨 경고를 발생시킵니다.

본 과제에서는 Tree RCU의 계층적 비트마스크 트리 초기화, 독자 중첩 레벨 추적, 유휴 상태 보고 및 트리 상향 전파, Grace Period 완결과 RCU 콜백 배치 실행, 그리고 RCU Stall 감지 파이프라인을 시뮬레이션하는 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------+
|                        Root RCU Node (struct rcu_node)                            |
|                        root_qsmask: [ Leaf 0 | Leaf 1 ]                           |
+-----------------------------------------------------------------------------------+
                               /                           \
                              /                             \
                             v                               v
+------------------------------------+       +------------------------------------+
|       Leaf Node 0 (rcu_node)       |       |       Leaf Node 1 (rcu_node)       |
|   qsmask: [ CPU0 | CPU1 | CPU2 | 3]|       |   qsmask: [ CPU4 | CPU5 | CPU6 | 7]|
+------------------------------------+       +------------------------------------+
       |       |       |       |                    |       |       |       |
       v       v       v       v                    v       v       v       v
    [CPU 0] [CPU 1] [CPU 2] [CPU 3]              [CPU 4] [CPU 5] [CPU 6] [CPU 7]
    (Idle)  (User)  (In RCU CS!)                 (Idle)  (Idle)  (Idle)  (Idle)
                      ^
                      |-- RCU Critical Section (nesting > 0)
                          BLOCKED from reporting Quiescent State!
```

---

## 3. 핵심 규칙 및 상태 전이 모델

### 3.1 Grace Period 시작 (`START_GRACE_PERIOD`)
- 이미 GP가 진행 중(`gp_active == True`)이면 `EBUSY_GP_IN_PROGRESS` 에러.
- `gp_number += 1`, `gp_active = True`.
- 각 리프 노드 $L$의 `leaf_qsmask[L]`에 소속된 CPU들의 비트를 `1`로 세팅.
- 복수 리프 노드가 존재할 경우 `root_qsmask`에 각 리프 노드에 대응하는 비트를 `1`로 세팅.

### 3.2 독자 임계 구역 (`RCU_READ_LOCK`, `RCU_READ_UNLOCK`)
- `RCU_READ_LOCK`: 지정된 CPU의 `nesting += 1`.
- `RCU_READ_UNLOCK`: 지정된 CPU의 `nesting -= 1`. (`nesting < 0` 방지).

### 3.3 유휴 상태 보고 (`CPU_QUIESCENT_STATE`)
1. **임계 구역 블로킹 검사**:
   `cpu_nesting[c] > 0`인 경우: RCU 독자 임계 구역 내부이므로 `BLOCKED_IN_CRITICAL_SECTION` 반환.
2. **리프 마스크 클리어**:
   해당 CPU의 리프 노드 $L = c // \text{fanout}$, 비트 위치 $b = c \% \text{fanout}$.
   `leaf_qsmask[L] &= ~(1 << b)`.
3. **상위 트리 전파**:
   - `leaf_qsmask[L] == 0`이 되면, 해당 리프 노드의 모든 CPU가 QS를 보고한 것임.
   - `root_qsmask &= ~(1 << L)`.
   - `root_qsmask == 0`이 되면 **유예 기간 완결(`gp_completed = True`)**!
4. **콜백 실행**:
   - `target_gp <= gp_number`인 대기 중인 모든 RCU 콜백을 즉시 실행 상태로 전환.
   - `gp_active = False`.

### 3.4 RCU 콜백 등록 (`CALL_RCU`)
- 현재 GP가 활성 상태이면 `target_gp = gp_number` (현재 GP 완결 시 실행).
- 현재 GP가 유휴 상태이면 `target_gp = gp_number + 1` (다음 번 GP 완결 시 실행).

### 3.5 RCU Stall 검사 (`RCU_STALL_CHECK`)
- 활성 GP에서 아직 `qsmask`에 남아있는 CPU 목록과, 해당 CPU가 RCU 임계 구역에 갇혀있는지(`nesting > 0`) 여부를 탐지.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {
    "nr_cpus": 4,
    "fanout": 4
  },
  "operations": [
    {"type": "CALL_RCU", "cb_id": "cb1", "payload": "free_dentry"},
    {"type": "START_GRACE_PERIOD"},
    {"type": "CPU_QUIESCENT_STATE", "cpu": 0},
    {"type": "CPU_QUIESCENT_STATE", "cpu": 1},
    {"type": "CPU_QUIESCENT_STATE", "cpu": 2},
    {"type": "CPU_QUIESCENT_STATE", "cpu": 3},
    {"type": "QUERY_RCU_STATE"}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "CALL_RCU",
      "status": "SUCCESS",
      "cb_id": "cb1",
      "target_gp": 1
    },
    {
      "op_index": 1,
      "type": "START_GRACE_PERIOD",
      "status": "SUCCESS",
      "gp_number": 1,
      "leaf_masks": {"0": 15},
      "root_mask": 15
    },
    {
      "op_index": 5,
      "type": "CPU_QUIESCENT_STATE",
      "status": "QS_RECORDED",
      "cpu": 3,
      "leaf_index": 0,
      "leaf_cleared": true,
      "gp_completed": true,
      "invoked_callbacks_count": 1
    }
  ],
  "summary": {
    "total_operations": 7,
    "total_gp_started": 1,
    "total_gp_completed": 1,
    "total_callbacks_registered": 1,
    "total_callbacks_invoked": 1,
    "final_gp_number": 1,
    "final_gp_active": false,
    "active_readers_count": 0
  }
}
```
