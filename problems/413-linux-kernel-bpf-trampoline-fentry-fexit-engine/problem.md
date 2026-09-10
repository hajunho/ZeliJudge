# 문제 413: Linux 커널 eBPF 트램펄린(fentry/fexit) 직접 호출 엔진 및 재귀 방어·에러 주입 상태 머신

## 문제 설명

리눅스 커널의 실시간 관측성(Observability), 보안 감사(Security Auditing), 그리고 성능 프로파일링(Profiling) 분야에서 eBPF(Extended Berkeley Packet Filter)는 현대 클라우드 인프라(Cilium, Falco, Tetragon 등)의 표준 기술로 자리 잡았습니다.

초기 eBPF는 임의의 커널 함수를 추적하기 위해 **kprobe (`BPF_PROG_TYPE_KPROBE`)** 서브시스템에 의존했습니다. 그러나 kprobe는 다음과 같은 치명적인 성능 한계를 가지고 있었습니다:
1. **소프트웨어 브레이크포인트 트랩(Trap) 오버헤드**: 대상 커널 함수의 첫 번째 바이트를 `int3`(0xCC) 중단점 명령어로 덮어씌워 강제 CPU 예외(Exception)를 유발합니다.
2. **비효율적인 레지스터 스태킹 및 컨텍스트 스위칭**: 인터럽트 프레임 저장, 인터럽트 비활성화, kprobe 핸들러 호출, 단일 명령어 스텝 실행(Single-Stepping), 그리고 `iret` 복귀까지 수백 개의 CPU 사이클이 소모됩니다.
3. **높은 호출 지연 시간**: kprobe 1회 호출당 약 **150ns~200ns**의 지연 시간이 발생하여, 초당 수백만 번 실행되는 고주파수 커널 함수(예: `vfs_read()`, `tcp_rcv_established()`)에 kprobe를 연결하면 시스템 전체 CPU 성능이 15%~30% 이상 급격히 저하됩니다.

이 문제를 완전히 종식시키기 위해 리눅스 커널 5.5에 Alexei Starovoitov에 의해 도입된 혁신적인 서브시스템이 바로 **eBPF 트램펄린 (eBPF Trampoline, `kernel/bpf/trampoline.c`, `arch/x86/net/bpf_jit_comp.c`, `CONFIG_BPF_TRAMPOLINE`)**입니다.

### eBPF 트램펄린 핵심 동작 메커니즘

1. **JIT 직접 호출 브릿지 (Zero-Overhead Direct Call)**:
   - 커널 함수의 진입점 5바이트 NOP(`__fentry__`)을 원자적 코드 패칭(`text_poke`)을 통해 동적으로 JIT 컴파일된 트램펄린 메모리 주소로 직접 `call <trampoline_addr>` 점프시킵니다.
   - CPU 트랩이나 예외 처리 없이 C 언어 함수 호출과 완전히 동일한 속도(단 **1ns~2ns**)로 eBPF 프로그램에 직접 진입합니다 (레거시 kprobe 대비 100배 가속!).

2. **3단계 BPF 실행 파이프라인**:
   - **`FENTRY` (`BPF_TRACE_FENTRY`)**: 함수 본체가 실행되기 직전에 호출되며, 함수의 입력 인자(Arguments)를 레지스터 수준에서 즉시 복사 없이 직접 관측합니다.
   - **`FMOD_RET` (`BPF_MODIFY_RETURN`)**: 보안 정책(BPF LSM)을 위한 계층입니다. BPF 프로그램이 0이 아닌 값(예: `-13` / `-EACCES`, `-1` / `-EPERM`)을 반환하면, **원래의 커널 함수 본체 실행을 완전히 바이패스(Bypass)**하고 해당 에러 코드를 최종 반환값으로 강제 확정합니다.
   - **`FEXIT` (`BPF_TRACE_FEXIT`)**: 원래 커널 함수(또는 fmod_ret에 의해 확정된 값)가 실행을 마친 직후 호출됩니다. 함수의 원본 입력 인자뿐만 아니라 **최종 반환값(Return Value)**까지 동시에 관측할 수 있습니다.

3. **Per-CPU 재귀 방어 (`bpf_prog_active`)**:
   - 만약 `fentry` 프로그램 내부에서 호출한 헬퍼 함수가 또다시 동일한 트램펄린을 트리거하는 경우, 커널 스택 오버플로우로 인한 커널 패닉(Panic)이 발생할 수 있습니다.
   - 트램펄린은 CPU별 재귀 카운터(`bpf_prog_active[cpu]`)를 두어, 중첩된 재귀 호출을 즉시 감지하고 BPF 프로그램 실행을 안전하게 건너뛰는 **재귀 억제(`RECURSION_SUPPRESSED`)**를 수행합니다.

4. **동적 라이프사이클 및 오버헤드 회계**:
   - BPF 프로그램이 연결(`attach`)되거나 해제(`detach`)되면 트램펄린 이미지가 동적으로 재구성됩니다.
   - 등록된 프로그램이 0개가 되면 네이티브 실행 경로로 원복되어 오버헤드가 완전히 0ns로 환원됩니다.

여러분은 리눅스 커널 eBPF 트램펄린의 JIT 직접 호출 디스패처, FENTRY/FMOD_RET/FEXIT 3단계 파이프라인, 에러 주입 기반 함수 바이패스, Per-CPU 재귀 방어 및 레거시 kprobe 대비 오버헤드 측정 엔진을 충실히 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                       Linux Kernel eBPF Trampoline Architecture                                  |
+==================================================================================================+

   [ Kernel Caller (e.g. syscall entry) ]
                     |
                     | Direct Call (__fentry__ text_poke patched!)
                     v
+--------------------------------------------------------------------------------------------------+
| JIT-Compiled Trampoline Bridge (arch/x86/net/bpf_jit_comp.c)                                     |
|                                                                                                  |
|  [ Step 1: Push Args to Stack Frame (RDI, RSI, RDX, RCX, R8, R9) ]                               |
|                                                                                                  |
|  [ Step 2: Phase 1 - FENTRY Programs ]                                                           |
|    - Check bpf_prog_active[cpu] > 0 ?                                                            |
|        * YES: ===> RECURSION_SUPPRESSED (Skip to prevent kernel stack panic!)                    |
|        * NO : ===> Increment bpf_prog_active, Execute fentry progs, Decrement                    |
|                                                                                                  |
|  [ Step 3: Phase 2 - FMOD_RET Programs (Security LSM / Error Injection) ]                       |
|    - Execute fmod_ret progs:                                                                     |
|        * If ret != 0:                                                                            |
|            - Override effective_ret_val = override_code (e.g. -EACCES)                           |
|            - BYPASS Original Kernel Function Execution!                                          |
|        * If ret == 0:                                                                            |
|            - Call Original Kernel Function (e.g. vfs_read), set effective_ret_val = orig_ret    |
|                                                                                                  |
|  [ Step 4: Phase 3 - FEXIT Programs ]                                                            |
|    - Execute fexit progs passing BOTH (Original Args, effective_ret_val)                         |
|    - Recursion guard protected via bpf_prog_active[cpu]                                          |
|                                                                                                  |
|  [ Step 5: Restore Return Register (RAX) & ret to Caller ]                                       |
|    - Trampoline Overhead: ~2ns + N * 3ns  (vs Legacy Kprobe: 150ns ~ 200ns!)                     |
+==================================================================================================+
```

---

## 상세 요구사항 및 동작 규칙

### 1. 시스템 설정 파라미터 (`config`)
- `num_cpus`: 시스템의 CPU 코어 수 (기본값: `4`)
- `kprobe_cost_ns`: 레거시 kprobe 1회 호출 시의 기준 지연 시간 (기본값: `150` ns)
- `trampoline_base_ns`: 트램펄린 기본 점프/복귀 하드웨어 오버헤드 (기본값: `2` ns)
- `bpf_prog_cost_ns`: 부착된 BPF 프로그램 1개당 평균 실행 오버헤드 (기본값: `3` ns)
- `funcs`: 관측 대상 커널 함수 딕셔너리 (`func_id` -> `name`, `orig_ret`, `latency_ns`)

### 2. 이벤트 트레이스 연산 (`trace`)

1. **`ATTACH_PROG`**:
   - `time`, `func_id`, `prog_id`, `prog_type` (`"FENTRY"`, `"FMOD_RET"`, `"FEXIT"`), `override_ret_val` (선택적), `causes_recursion_func` (선택적).
   - 대상 함수의 트램펄린 등록 체인에 프로그램을 추가합니다.

2. **`DETACH_PROG`**:
   - `time`, `func_id`, `prog_id`.
   - 트램펄린 등록 체인에서 해당 프로그램을 제거합니다.

3. **`INVOKE_FUNC`**:
   - `time`, `func_id`, `cpu_id`, `args` (배열).
   - 대상 함수를 호출하여 트램펄린 파이프라인을 구동합니다:
     - **트램펄린 유무 검사**: 부착된 프로그램이 전혀 없다면 네이티브 직통 실행 (`trampoline_overhead_ns = 0`, `ret_val = orig_ret`).
     - **트램펄린 장착 시**:
       - 오버헤드 산출: `trampoline_overhead = trampoline_base_ns + (total_progs * bpf_prog_cost_ns)`.
       - 레거시 kprobe 환산 비용: `kprobe_equiv = total_progs * kprobe_cost_ns`.
       - **1단계 (FENTRY)**: 부착된 fentry 프로그램들을 순차 실행. 실행 전 `bpf_prog_active[cpu_id] > 0`이면 `RECURSION_SUPPRESSED` 처리.
       - **2단계 (FMOD_RET)**: fmod_ret 프로그램들을 실행. 0이 아닌 `override_ret_val`이 반환되면 즉시 `orig_func_executed = False`로 설정하고 원래 함수 실행을 생략(Bypass), `ret_val = override_ret_val`로 확정. 0이면 원래 함수 실행 후 `ret_val = orig_ret`.
       - **3단계 (FEXIT)**: fexit 프로그램들을 순차 실행하며 최종 반환값(`ret_val`)을 함께 관측.
       - 호출 로그 및 통계 카운터를 갱신합니다.

---

## 입출력 형식 (JSON)

### 입력 형식 (Standard Input)

```json
{
  "config": {
    "num_cpus": 4,
    "kprobe_cost_ns": 150,
    "trampoline_base_ns": 2,
    "bpf_prog_cost_ns": 3,
    "funcs": {
      "vfs_read": {"name": "vfs_read", "orig_ret": 4096, "latency_ns": 50},
      "do_unlinkat": {"name": "do_unlinkat", "orig_ret": 0, "latency_ns": 70}
    }
  },
  "trace": [
    {
      "time": 0,
      "type": "ATTACH_PROG",
      "func_id": "vfs_read",
      "prog_id": "fentry_audit",
      "prog_type": "FENTRY"
    },
    {
      "time": 1,
      "type": "ATTACH_PROG",
      "func_id": "vfs_read",
      "prog_id": "fexit_stats",
      "prog_type": "FEXIT"
    },
    {
      "time": 2,
      "type": "INVOKE_FUNC",
      "func_id": "vfs_read",
      "cpu_id": 0,
      "args": [3, "0x7fff000", 4096]
    }
  ]
}
```

### 출력 형식 (Standard Output)

공백 없이 압축된 단일 라인 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 출력해야 합니다:

```json
{
  "summary": {
    "total_invocations": 1,
    "fentry_invocations": 1,
    "fexit_invocations": 1,
    "fmod_ret_overrides": 0,
    "bypassed_orig_funcs": 0,
    "recursion_suppressed_count": 0,
    "total_trampoline_overhead_ns": 8,
    "legacy_kprobe_equivalent_overhead_ns": 300,
    "saved_overhead_ns": 292
  },
  "trampolines": {
    "vfs_read": {
      "fentry": [{"prog_id": "fentry_audit", "type": "FENTRY", "override_ret_val": null, "causes_recursion_func": null}],
      "fmod_ret": [],
      "fexit": [{"prog_id": "fexit_stats", "type": "FEXIT", "override_ret_val": null, "causes_recursion_func": null}]
    },
    "do_unlinkat": {"fentry": [], "fmod_ret": [], "fexit": []}
  },
  "invocation_logs": [
    {
      "time": 2,
      "func_id": "vfs_read",
      "cpu_id": 0,
      "args": [3, "0x7fff000", 4096],
      "orig_func_executed": true,
      "ret_val": 4096,
      "trampoline_overhead_ns": 8,
      "executed_fentry": [{"prog_id": "fentry_audit", "status": "EXECUTED"}],
      "executed_fexit": [{"prog_id": "fexit_stats", "status": "EXECUTED", "observed_ret": 4096}],
      "fmod_ret_applied": null
    }
  ],
  "event_logs": [ ... ]
}
```
