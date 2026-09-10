# Problem #392: Linux Kernel x86 Split Lock Detection & Bus Lock Mitigation Engine (`arch/x86/kernel/cpu/intel.c`, `CONFIG_SPLIT_LOCK_DETECT`)

## 문제 설명

현대 x86_64 멀티코어 프로세서에서 원자적 명령어(`LOCK CMPXCHG`, `LOCK ADD` 등)는 통상 **캐시 락킹(Cache Locking)** 메커니즘을 통해 단일 코어의 L1/L2 캐시라인 내부에서 MESI 캐시 일관성 프로토콜을 사용해 수 사이클 내에 원자성을 보장합니다.

그러나 원자적 피연산자가 64바이트 캐시라인 경계(Cache Line Boundary)에 걸쳐 위치하는 비정렬(Unaligned) 상태일 때, 이를 **스플릿 락 (Split Lock)**이라고 부릅니다.
두 개의 캐시라인에 걸친 데이터는 캐시 일관성만으로 원자성을 유지할 수 없으므로, CPU 하드웨어는 프로세서 버스 전체를 잠그는 전역 **버스 락(Bus Lock)** 신호를 발생시킵니다. 버스 락이 활성화되면 소켓 내의 모든 다른 CPU 코어와 메모리 컨트롤러가 1,000 사이클 이상 일제히 동결(Bus Stall)됩니다.

악의적이거나 버그가 있는 사용자 프로그램(또는 가상 머신 게스트)이 루프를 돌며 스플릿 락을 유발하면 전체 클라우드 물리 노드의 처리량이 90% 이상 폭락하는 DoS 공격이 가능해집니다.

리눅스 커널은 이를 차단하기 위해 **MSR 기반 스플릿 락 탐지 및 버스 락 속도 제한(Split Lock Detection & Bus Lock Mitigation, `arch/x86/kernel/cpu/intel.c`)** 서브시스템을 도입했습니다:

```
+----------------------------------------------------------------------------------------------------+
|                               Split Lock Detection & Bus Lock Mitigation                           |
+----------------------------------------------------------------------------------------------------+
| [ Instruction Execution: core_id, addr, size, is_locked ]                                          |
|   | 1. Boundary Check: c1 = addr // 64, c2 = (addr + size - 1) // 64                               |
|   |    If (c1 != c2) and is_locked:                                                                |
|   |        -> SPLIT LOCK CONDITION TRIGGERED!                                                      |
+---+------------------------------------------------------------------------------------------------+
| [ Kernel Policy Enforcement: split_lock_detect / bus_lock_ratelimit ]                              |
|   | Policy "OFF":                                                                                  |
|   |   -> Hardware asserts Bus Lock, stalls all other (num_cores - 1) cores by 1000 cycles!         |
|   | Policy "WARN":                                                                                 |
|   |   -> Traps #AC (Alignment Check), logs warning on first offense per task, allows bus lock.     |
|   | Policy "FATAL":                                                                                |
|   |   -> Traps #AC, sends SIGBUS to offending task immediately! Kills task, ZERO bus stall!       |
|   | Policy "RATELIMIT":                                                                            |
|   |   -> Allows up to bus_lock_ratelimit bus locks per 1000ms window.                               |
|   |   -> Exceeded requests penalized with throttle_delay_ms sleep, saving bus stall cycles!        |
+----------------------------------------------------------------------------------------------------+
```

### 정책별 세부 규칙

1. **OFF**: 하드웨어 버스 락 허용. 시스템 전체 버스 스톨 사이클 발생:
   $$\text{stall\_cycles} = 1000 \times (\text{num\_cores} - 1)$$
2. **WARN**: 태스크별 최초 1회 `#AC_SPLIT_LOCK_WARN` 경고 기록 후 버스 락 허용.
3. **FATAL**: 하드웨어 `#AC` 트랩 후 `SIGBUS` 시그널 전달, 태스크 즉각 종료 (`SIGBUS_TERMINATED`). 후속 명령어는 `FAIL_TASK_DEAD`로 거절되며 버스 스톨을 원천 차단 (`stall_cycles_saved`).
4. **RATELIMIT**: 1000ms 윈도우 내 상한선(`bus_lock_ratelimit`) 이하일 경우 허용(`BUS_LOCK_ALLOWED_WITHIN_LIMIT`). 상한선 초과 시 페널티 지연(`BUS_LOCK_THROTTLED`, `throttle_delay_ms`) 주입 및 버스 스톨 차단.

당신은 리눅스 커널의 x86 캐시라인 경계 스플릿 락 탐지 및 버스 락 완화 상태 머신을 시뮬레이션하는 프로그램을 작성해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "split_lock_policy": "RATELIMIT",
    "bus_lock_ratelimit": 2,
    "throttle_delay_ms": 20,
    "num_cores": 4
  },
  "commands": [
    { "op": "EXECUTE_INSN", "core_id": 0, "task_id": "t1", "addr": 62, "size": 4, "is_locked": true, "timestamp_ms": 10 }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "policy": "RATELIMIT",
  "total_insns": 1,
  "split_locks_detected": 1,
  "bus_locks_asserted": 1,
  "tasks_killed": 0,
  "throttles_injected": 0,
  "bus_stall_cycles": 3000,
  "bus_stall_saved": 0,
  "events": [ ... ]
}
```
