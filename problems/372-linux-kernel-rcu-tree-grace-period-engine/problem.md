# Linux Kernel Tree RCU: 유예 기간(Grace Period) 상태 머신, 정지 상태(Quiescent State) 보고 및 RCU CPU 스톨 탐지 엔진

## 문제 설명

리눅스 커널의 **트리 RCU(Tree RCU / `kernel/rcu/tree.c`, `include/linux/rcupdate.h`)**는 폴 매케니(Paul E. McKenney) 박사가 개발한 커널 동기화의 핵심 서브시스템으로, 수천 개의 CPU 코어를 장착한 초대형 NUMA 서버에서도 읽기 연산자(`rcu_read_lock()` / `rcu_read_unlock()`)가 원자적 명령어(Atomic Instructions)나 버스 잠금(Bus Locking) 없이 $O(1)$의 비용으로 초고속 무잠금 읽기를 수행할 수 있도록 보장하는 메커니즘입니다.

RCU의 불변성(Invariant)은 다음과 같습니다:
> **"어떤 공유 메모리 객체를 변경하거나 삭제하려는 쓰기 작업자(Writer)는 원본 객체를 즉시 해제할 수 없으며, 시스템의 모든 CPU가 최소 한 번 이상의 정지 상태(Quiescent State, QS)를 통과하여 유예 기간(Grace Period, GP)이 완전히 만료될 때까지 메모리 반환(`kfree`)을 안전하게 유예해야 한다."**

```
                    [ RCU 유예 기간(Grace Period) 타임라인 ]
CPU 0: --[ rcu_read_lock ]---------------------[ rcu_read_unlock ]----(QS: 컨텍스트 스위치)---->
CPU 1: -------(call_rcu 객체 삭제 등록)-------------------------------(QS)-------------------->
CPU 2: ------------------------(QS)---------------------------------------------------------->
                                  ^                                     ^
                                  |                                     |
                          [ 유예 기간 시작 ]                    [ 유예 기간 만료! ]
                                                     (모든 CPU가 QS를 통과했으므로
                                                      콜백 함수 rcu_do_batch 실행)
```

### 핵심 아키텍처 및 상태 머신 메커니즘

1. **읽기 측 임계 구역 (`RCU_READ_LOCK` / `RCU_READ_UNLOCK`)**:
   - `read_depth` 카운터를 증가/감소시킵니다 (중첩 진입 지원).
   - `read_depth > 0`인 동안 CPU는 RCU 보호 객체를 참조 중일 수 있으므로 **절대로 정지 상태(Quiescent State)를 보고할 수 없습니다**.

2. **지연 메모리 해제 콜백 (`CALL_RCU`)**:
   - `call_rcu()`는 해제할 메모리와 콜백 ID를 등록합니다.
   - 현재 유예 기간(GP)이 이미 진행 중이라면, 새 콜백은 다음 유예 기간을 위해 `callbacks_next` 큐에 대기합니다.
   - 유예 기간이 진행 중이지 않다면 곧 시작될 유예 기간을 위해 `callbacks_wait` 큐에 배치됩니다.

3. **정지 상태 보고 (`REPORT_QS`)**:
   - 컨텍스트 스위치, 유저 모드 진입, 또는 유휴(Idle) 루프 진입 시 CPU는 RCU 엔진에 정지 상태를 보고합니다.
   - `read_depth > 0`인 상태에서 `REPORT_QS`가 호출되면 `REJECTED_BLOCKED_IN_RCU_READER`로 거절되며 `qs_reports_blocked_in_reader` 통계가 증가합니다.
   - 정상 보고 시 `qs_reported = True`가 되며, 시스템 내 **모든 CPU가 QS를 보고하면 현재 유예 기간이 즉시 만료(`gp_completed = True`)**됩니다:
     - `gp_seq`가 1 증가합니다.
     - `callbacks_wait` 큐에 머물던 콜백들이 안전하게 실행 가능한 `callbacks_done` 큐로 승격됩니다.

4. **RCU CPU 스톨 경고 탐지 (`TICK`)**:
   - 유예 기간이 시작된 후 `stall_timeout_ticks` 시간이 경과했음에도 불구하고, 여전히 QS를 보고하지 못한 CPU가 존재하면 커널 패닉을 방지하기 위한 경고(`rcu_stalls_detected`)가 발생합니다.

5. **콜백 배치 호출 (`INVOKE_CALLBACKS`)**:
   - 유예 기간이 완료된 `callbacks_done` 큐의 콜백들을 소프트웨어 인터럽트(`rcu_do_batch`) 컨텍스트에서 안전하게 실행하여 메모리를 최종 반환합니다.

본 문제에서는 이 리눅스 커널 Tree RCU의 유예 기간 생명주기, 계층적 QS 보고, 콜백 파이프라인 및 스톨 감지 엔진을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "num_cpus": 2,
  "cpus_per_node": 2,
  "stall_timeout_ticks": 3,
  "operations": [
    {"op": "RCU_READ_LOCK", "cpu": 0},
    {"op": "CALL_RCU", "callback_id": "free_node_1", "cpu": 1},
    {"op": "START_GRACE_PERIOD"},
    {"op": "REPORT_QS", "cpu": 1},
    {"op": "REPORT_QS", "cpu": 0},
    {"op": "TICK"},
    {"op": "TICK"},
    {"op": "TICK"},
    {"op": "RCU_READ_UNLOCK", "cpu": 0},
    {"op": "REPORT_QS", "cpu": 0},
    {"op": "INVOKE_CALLBACKS", "cpu": 1}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 객체를 공백 없이 출력합니다:

```json
{
  "num_cpus": 2,
  "cpus_per_node": 2,
  "final_gp_seq": 1,
  "gp_active": false,
  "per_cpu_summary": {
    "cpu_0": {
      "read_depth": 0,
      "qs_reported": false,
      "pending_wait_cb_count": 0,
      "pending_done_cb_count": 0
    },
    "cpu_1": {
      "read_depth": 0,
      "qs_reported": false,
      "pending_wait_cb_count": 0,
      "pending_done_cb_count": 0
    }
  },
  "stats": {
    "grace_periods_completed": 1,
    "callbacks_queued": 1,
    "callbacks_invoked": 1,
    "qs_reports_accepted": 2,
    "qs_reports_blocked_in_reader": 1,
    "rcu_stalls_detected": 1
  },
  "op_log": [
    {
      "op": "RCU_READ_LOCK",
      "cpu": 0,
      "read_depth": 1
    }
  ]
}
```
