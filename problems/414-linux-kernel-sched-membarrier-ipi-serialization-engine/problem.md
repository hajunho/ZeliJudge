# 문제 414: Linux 커널 동시성 및 스케줄링 membarrier(2) IPI 직렬화 엔진 및 JIT/URCU 무장벽 가속 상태 머신

## 문제 설명

현대 고성능 멀티스레드 런타임 시스템(V8 JavaScript 엔진, HotSpot Java 가상 머신, WebKit JavaScriptCore, 그리고 사용자 공간 RCU인 `liburcu`)에서 동시성 제어의 핵심 도전 과제는 **비대칭 동기화(Asymmetric Synchronization)**입니다.

자주 실행되는 읽기 작업(Read-side)은 초당 수억 번 수행되는 반면, 데이터 구조를 변경하거나 기계어 코드를 패칭하는 쓰기/수정 작업(Write-side)은 비교적 드물게 발생합니다.
전통적인 메모리 장벽(Memory Barrier, e.g., x86의 `mfence`, ARM64의 `dmb ish`)을 읽기 경로에 배치하면 파이프라인 정체(Stall) 및 스토어 버퍼 드레인 오버헤드로 인해 읽기 처리량이 20%~50% 이상 급격히 저하됩니다.

이 문제를 해결하기 위해 리눅스 커널 4.3에서 Mathieu Desnoyers에 의해 도입되고 커널 4.16~5.x에 걸쳐 완성된 시스템 호출이 바로 **`membarrier(2)` (`kernel/sched/membarrier.c`, `CONFIG_MEMBARRIER`)**입니다.

### membarrier(2) 핵심 철학: 제로 배리어(Zero-Barrier) 읽기
`membarrier(2)`의 핵심 설계 철학은 **"읽기 스레드에게 부과되던 하드웨어 메모리 장벽 비용을 전적으로 드물게 실행되는 쓰기 스레드로 전가(Offload)하는 것"**입니다.
- **읽기 스레드(Readers)**: 하드웨어 메모리 장벽 없이 단순한 일반 메모리 읽기 명령어(`mov`, `ldr`)만 수행합니다 (오버헤드 0ns!).
- **쓰기 스레드(Writers)**: 수정을 완료한 후 `sys_membarrier()` 시스템 호출을 호출합니다. 커널은 프로세서 간 인터럽트(**IPI, Inter-Processor Interrupt**)를 발송하여 해당 프로세스의 메모리를 공유하는 다른 코어들로 하여금 원격으로 메모리 장벽(`smp_mb()`)을 강제 실행하도록 지시합니다.

---

### 주요 커맨드 및 커널 동작 메커니즘

1. **`MEMBARRIER_CMD_QUERY` (기능 질의)**:
   - 커널이 지원하는 membarrier 커맨드 세트를 비트마스크 형태로 반환합니다.
   - 본 엔진에서는 표준 기능 플래그 조합인 `0x7F` (10진수 127)를 반환합니다.

2. **`MEMBARRIER_CMD_GLOBAL` (전역 브로드캐스트 IPI)**:
   - 호출 코어를 제외한 시스템 내의 **모든 활성(non-idle) 온라인 CPU**로 브로드캐스트 IPI를 전송합니다.
   - 전체 시스템의 다른 무관한 프로세스에도 인터럽트를 유발하므로 시스템 전체 레이턴시 스파이크가 발생할 수 있습니다.

3. **`MEMBARRIER_CMD_REGISTER_PRIVATE_EXPEDITED` (프라이빗 등록)**:
   - 현재 호출 스레드의 메모리 디스크립터(`mm_struct`) 상태에 `MEMBARRIER_STATE_PRIVATE_EXPEDITED (0x1)` 플래그를 등록합니다.
   - 향후 `MEMBARRIER_CMD_PRIVATE_EXPEDITED` 호출을 안전하게 허용하기 위한 사전 승인 등록 절차입니다.

4. **`MEMBARRIER_CMD_PRIVATE_EXPEDITED` (타깃 고속 IPI)**:
   - 호출 스레드의 주소 공간(`mm_id`)이 사전에 등록되지 않은 경우 즉시 허가 거부 에러(`-1` / `-EPERM`)를 반환합니다.
   - 등록된 경우, **동일한 주소 공간(`curr_mm == caller_mm`)을 현재 실행 중인 다른 활성 CPU들만을 선별**하여 타깃 IPI를 발송합니다.
   - 수신 코어는 하드웨어 메모리 장벽(`smp_mb()`)을 실행하여 관측 일관성을 확보합니다. 다른 프로세스를 실행 중인 코어나 유휴(Idle) 코어에는 인터럽트가 전송되지 않으므로 IPI 오버헤드가 극적으로 감소합니다.

5. **`MEMBARRIER_CMD_REGISTER_PRIVATE_EXPEDITED_SYNC_CORE` (JIT 코어 동기화 등록)**:
   - 현재 호출 스레드의 메모리 디스크립터(`mm_struct`)에 `MEMBARRIER_STATE_PRIVATE_EXPEDITED_SYNC_CORE (0x2)` 플래그를 등록합니다.

6. **`MEMBARRIER_CMD_PRIVATE_EXPEDITED_SYNC_CORE` (명령어 파이프라인 직렬화)**:
   - JIT 컴파일러(V8, JVM 등)가 동적으로 생성된 기계어 코드를 수정하거나 최적화/역최적화(Deoptimization)할 때 사용됩니다.
   - 사전 등록이 되어 있지 않은 경우 `-1` (`-EPERM`)을 반환합니다.
   - 등록된 경우, 동일한 `mm_id`를 실행 중인 대상 CPU들에 타깃 IPI를 발송하여 메모리 장벽(`smp_mb()`)뿐만 아니라 **`sync_core()` (x86의 `cpuid`/`iret`, ARM의 `isb`)**를 강제 실행합니다.
   - 이를 통해 원격 코어의 하드웨어 명령어 프리페치 버퍼(Prefetch Buffer) 및 디코딩된 명령어 파이프라인을 즉시 플러시(Flush)하여 새로 수정된 기계어 명령어가 원자적으로 실행되도록 직렬화합니다.

7. **스케줄러 문맥 교환 연계 (`finish_task_switch()`)**:
   - 만약 대상 스레드가 IPI 전송 시점에 CPU에서 실행 중이지 않고 런큐에서 대기 중이거나 문맥 교환이 발생한다면 어떻게 될까요?
   - 커널 스케줄러(`kernel/sched/core.c`)는 스케줄링 시점에 대상 태스크의 `mm->membarrier_state`에 프라이빗 비트가 설정되어 있으면, 문맥 교환 완료 루틴(`finish_task_switch`)에서 자동으로 완전 메모리 장벽(`smp_mb()`)을 실행합니다 (`context_switch_barriers` 증가).
   - 이를 통해 IPI를 놓친 태스크가 다시 CPU에 적재될 때 이전의 모든 쓰기 작업이 완벽하게 가시화(Visibility)되도록 보장합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                       Linux Kernel membarrier(2) Architecture                                    |
+==================================================================================================+

   [ Writer Thread (JIT/URCU) ]                     [ Reader Thread (Fast Path) ]
              |                                                   |
              | sys_membarrier()                                  | Executes memory loads
              v                                                   | with ZERO BARRIER (0ns!)
 +----------------------------------------+                       v
 | kernel/sched/membarrier.c              |                  [ Load Data ]
 |                                        |
 | 1. Check mm->membarrier_state          |
 |    - If not registered: return -EPERM  |
 |                                        |
 | 2. Identify Target CPUs:               |
 |    For each online CPU c:              |
 |      if c != caller_cpu and            |
 |         cpu_rq[c]->curr_mm == mm_id:   |
 |           Add c to target_cpumask      |
 +----------------------------------------+
              |
              | smp_call_function_many(target_cpumask, ipi_handler)
              v
   +-----------------------+               +-----------------------+
   | CPU 1 (Target Core)   |               | CPU 2 (Unrelated MM)  |
   | Running Reader Thread |               | Running Other Process |
   +-----------------------+               +-----------------------+
   | [ Hardware IPI Trap ] |               |                       |
   | 1. smp_mb()           |               |   NO INTERRUPT SENT!  |
   | 2. sync_core() (opt)  |               |   Zero Noise/Latency  |
   |    - Pipeline Flush   |               +-----------------------+
   +-----------------------+
              |
              | IPI ACK / Return to User
              v
   [ Writer Thread Resumes ]

 +-------------------------------------------------------------------------------------------------+
 | Scheduler Integration (kernel/sched/core.c : finish_task_switch)                               |
 |   - When context switching to/from thread with (mm->membarrier_state & 1):                      |
 |     Automatically issue local smp_mb() (Context Switch Memory Barrier Guaranteed)               |
 +-------------------------------------------------------------------------------------------------+
```

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "num_cpus": 8
  },
  "trace": [
    {"time": 0, "type": "CREATE_PROCESS", "pid": 100, "mm_id": 1},
    {"time": 1, "type": "CONTEXT_SWITCH", "cpu_id": 0, "pid": 100},
    {"time": 2, "type": "SYS_MEMBARRIER", "cpu_id": 0, "pid": 100, "cmd": "MEMBARRIER_CMD_PRIVATE_EXPEDITED"}
  ]
}
```

- `config.num_cpus`: 시뮬레이션할 시스템의 논리 CPU 코어 수 (기본값 8).
- `trace`: 시간 순서대로 실행되는 이벤트 리스트:
  - `CREATE_PROCESS`: `{"time": t, "type": "CREATE_PROCESS", "pid": p, "mm_id": m}`
  - `CONTEXT_SWITCH`: `{"time": t, "type": "CONTEXT_SWITCH", "cpu_id": c, "pid": p}`
  - `SET_CPU_IDLE`: `{"time": t, "type": "SET_CPU_IDLE", "cpu_id": c, "is_idle": true/false}`
  - `SYS_MEMBARRIER`: `{"time": t, "type": "SYS_MEMBARRIER", "cpu_id": c, "pid": p, "cmd": "..."}`

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다 (compact JSON, `ensure_ascii=False`):

```json
{
  "summary": {
    "total_membarrier_calls": 3,
    "successful_calls": 2,
    "failed_calls": 1,
    "total_ipis_sent": 2,
    "targeted_ipis_sent": 2,
    "global_ipis_sent": 0,
    "sync_core_flushes": 0,
    "context_switch_barriers": 1
  },
  "mms": {
    "1": {
      "state": 1,
      "pids": [100, 101]
    }
  },
  "call_logs": [
    {
      "time": 2,
      "caller_cpu": 0,
      "caller_pid": 100,
      "caller_mm": 1,
      "cmd": "MEMBARRIER_CMD_PRIVATE_EXPEDITED",
      "return_code": -1,
      "ipi_targets": [],
      "ipis_sent_count": 0,
      "sync_core": false
    }
  ],
  "event_logs": [ ... ]
}
```
