# 문제 416: Linux 커널 하드웨어 보안 및 x86 아키텍처 Intel CET 섀도우 스택(Shadow Stack) 엔진 및 ROP 공격 차단 상태 머신

## 문제 설명

소프트웨어 보안 역사에서 메모리 손상 취약점(C/C++의 버퍼 오버플로우, Use-After-Free)을 악용한 코드 실행 공격은 시스템의 가장 치명적인 위협이었습니다.
운영체제는 스택 메모리의 실행 권한을 제거하는 **NX/DEP (Data Execution Prevention)** 비트를 도입하여 쉘코드(Shellcode)의 직접 주입 및 실행을 차단했습니다.

그러나 공격자들은 이에 대응하여 메모리에 이미 적재되어 있는 정상적인 실행 가능 코드 조각들(Gadgets, e.g., `pop rdi; ret`, `mov [rax], rdx; ret`)을 이어 붙여 임의의 악성 행위를 수행하는 **ROP (Return-Oriented Programming, 반환 지향 프로그래밍)** 공격 기법을 창안했습니다.
- ROP 공격은 스택 버퍼 오버플로우를 통해 함수의 **복귀 주소(Return Address)**를 조작합니다.
- 함수가 실행을 마치고 `RET` 명령어를 실행할 때, 공격자가 조작한 가짜 복귀 주소로 점프하여 연속된 가젯 체인을 실행합니다.
- 스택 카나리(Stack Canary, `__stack_chk_fail`)는 메모리 정보 누출(Info Leak)이나 브루트포스에 의해 우회될 수 있는 소프트웨어적 방어에 불과했습니다.

이 오랜 공격 기법을 하드웨어 수준에서 완벽하게 종식시키기 위해 인텔 Tiger Lake / AMD Zen 3 이후 하드웨어에 탑재되고, 리눅스 커널 6.6에 공식 병합된 핵심 보안 서브시스템이 바로 **Intel CET 섀도우 스택 (Control-flow Enforcement Technology Shadow Stack, `arch/x86/kernel/shstk.c`, `CONFIG_X86_USER_SHADOW_STACK`)**입니다.

---

### Intel CET 섀도우 스택 핵심 동작 원리

1. **하드웨어 격리 섀도우 스택 (`SSP`, Shadow Stack Pointer)**:
   - CPU는 일반 데이터 스택(`RSP`)과 완전히 물리적으로 격리된 두 번째 스택인 **섀도우 스택 (`SSP`)**을 유지합니다.
   - 섀도우 스택은 오직 **함수의 복귀 주소(Return Address)**만을 저장하는 전용 보안 스택입니다.
   - 섀도우 스택 메모리 페이지는 특별한 페이지 테이블 속성(PTE의 Writeable=0, Dirty=1 등 특수 인코딩)으로 보호되어 있어, 사용자 공간의 일반적인 메모리 쓰기 명령어(`mov`, `memcpy` 등)로 쓰기를 시도하면 즉시 하드웨어 페이지 폴트(`#PF`, `SEGV_ACCERR`)가 발생합니다.

2. **`CALL` 명령어의 이중 푸시(Dual Push)**:
   - CPU가 `CALL` 명령어를 실행할 때:
     - 원래의 데이터 스택(`RSP`)에 복귀 주소를 푸시합니다.
     - 동시에 하드웨어적으로 섀도우 스택(`SSP`)에도 동일한 복귀 주소를 자동으로 푸시합니다.

3. **`RET` 명령어의 하드웨어 비교 검증 및 `#CP` 예외**:
   - 함수 종료 시 CPU가 `RET` 명령어를 실행할 때:
     - 데이터 스택(`RSP`)에서 복귀 주소를 팝(Pop)합니다.
     - 섀도우 스택(`SSP`)에서도 복귀 주소를 팝(Pop)합니다.
     - **두 복귀 주소를 하드웨어 비교기가 1사이클 내에 즉시 비교합니다**:
       - **일치(Match)**: 정상적인 실행 흐름이므로 지연 없이 다음 명령어로 복귀합니다.
       - **불일치(Mismatch)**: 데이터 스택의 복귀 주소가 버퍼 오버플로우로 변조되었음을 의미합니다!
         - 하드웨어는 즉시 **제어 보호 예외 (`#CP`, Control Protection Exception, Vector 21)**를 발생시킵니다.
         - 리눅스 커널은 해당 프로세스에 `SIGSEGV` 시그널을 전달하며, `si_code`를 **`SEGV_CPERR`**로 지정하고 공격을 시도한 스레드를 즉각 사살(Terminate)합니다.

4. **비로컬 점프(`longjmp` / C++ Exception)와 `INCSSP`**:
   - `setjmp`/`longjmp`나 C++ 예외 처리로 인해 스택 프레임을 여러 개 한 번에 되감아야(Unwind) 하는 경우:
     - 하드웨어 비특권 명령어인 **`INCSSP` (Increment Shadow Stack Pointer)**를 사용하여 섀도우 스택 포인터를 $N$개 프레임만큼 합법적으로 전진시켜 불일치 예외 없이 동기화를 유지합니다.

5. **`arch_prctl` 시스템 호출과 잠금(`ARCH_SHSTK_LOCK`)**:
   - `ARCH_SHSTK_ENABLE`: 프로세스/스레드의 섀도우 스택 기능을 활성화합니다.
   - `ARCH_SHSTK_DISABLE`: 섀도우 스택을 비활성화합니다.
   - `ARCH_SHSTK_LOCK`: 섀도우 스택 설정을 불변(Immutable) 상태로 동결합니다. 한 번 잠기면 이후 공격자가 인젝션된 코드를 통해 `ARCH_SHSTK_DISABLE`을 호출하더라도 커널이 `-EPERM` (`-1`)으로 차단합니다.

여러분은 리눅스 커널 Intel CET 섀도우 스택의 하드웨어 Call/Ret 듀얼 스택 동작, ROP 버퍼 오버플로우 감지 시 `#CP` (`SEGV_CPERR`) 예외 유발, 섀도우 스택 직접 쓰기 방어(`#PF`), `INCSSP` 언와인딩 및 `ARCH_SHSTK_LOCK` 불변성 제어 엔진을 충실히 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                       Intel CET Shadow Stack Architecture & Kernel Flow                          |
+==================================================================================================+

   [ Normal User Code ]                             [ Attacker / Exploit ]
           |                                                  |
           | 1. CALL func()                                   | Buffer Overflow Attack!
           v                                                  v
 +-----------------------------------+              +-----------------------------------+
 | Data Stack (RSP)                  |              | Corrupts Return Address on RSP!   |
 |  [ ... Local Variables ... ]      |              | [ Return Addr: 0xDEADBEEF (ROP) ] |
 |  [ Return Addr: 0x401000   ] <----+              +-----------------------------------+
 +-----------------------------------+                                |
           |                                                          |
           | Hardware simultaneously pushes to SSP                    |
           v                                                          |
 +-----------------------------------+                                |
 | Shadow Stack (SSP) (Protected)    |                                |
 |  (Write-Protected Page Table)     |                                |
 |  [ Return Addr: 0x401000   ]      |                                |
 +-----------------------------------+                                |
           |                                                          |
           | 2. RET func()                                            |
           v                                                          |
 +--------------------------------------------------------------------+----------------------------+
 | Hardware Comparator (CPU Execution Unit)                                                        |
 |                                                                                                 |
 |  Pops RSP: actual_ret  = 0xDEADBEEF (Corrupted by ROP!)                                         |
 |  Pops SSP: expected_ret = 0x401000  (Pure hardware truth!)                                       |
 |                                                                                                 |
 |  Compare actual_ret == expected_ret ?                                                           |
 |    - MISMATCH DETECTED!                                                                         |
 |    ===> Trigger Control Protection Exception (#CP, Vector 21)                                   |
 +-------------------------------------------------------------------------------------------------+
           |
           v
 +-------------------------------------------------------------------------------------------------+
 | Linux Kernel Interrupt Handler (arch/x86/kernel/shstk.c : do_control_protection_exception)      |
 |   - Identify error code: CP_RET                                                                 |
 |   - Deliver SIGSEGV to process with si_code = SEGV_CPERR                                        |
 |   - Terminate offending thread, write audit security alert to dmesg                             |
 +-------------------------------------------------------------------------------------------------+
```

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "max_threads": 4,
    "default_shstk_size": 1024
  },
  "trace": [
    {"time": 0, "type": "CREATE_THREAD", "thread_id": 1},
    {"time": 1, "type": "ARCH_PRCTL", "thread_id": 1, "cmd": "ARCH_SHSTK_ENABLE"},
    {"time": 2, "type": "CALL_FUNC", "thread_id": 1, "func": "main", "ret_addr": 4198400},
    {"time": 3, "type": "ATTACK_ROP_CORRUPT_STACK", "thread_id": 1, "offset": 0, "fake_ret_addr": 3735928559},
    {"time": 4, "type": "RET_FUNC", "thread_id": 1}
  ]
}
```

- `config.max_threads`: 시스템 최대 스레드 수.
- `config.default_shstk_size`: 기본 섀도우 스택 프레임 용량.
- `trace`: 시간 순서대로 실행되는 이벤트 리스트:
  - `CREATE_THREAD`: `{"time": t, "type": "CREATE_THREAD", "thread_id": tid}`
  - `ARCH_PRCTL`: `{"time": t, "type": "ARCH_PRCTL", "thread_id": tid, "cmd": "..."}`
  - `CALL_FUNC`: `{"time": t, "type": "CALL_FUNC", "thread_id": tid, "func": "foo", "ret_addr": addr}`
  - `RET_FUNC`: `{"time": t, "type": "RET_FUNC", "thread_id": tid}`
  - `ATTACK_ROP_CORRUPT_STACK`: `{"time": t, "type": "ATTACK_ROP_CORRUPT_STACK", "thread_id": tid, "offset": 0, "fake_ret_addr": addr}`
  - `DIRECT_MEM_WRITE`: `{"time": t, "type": "DIRECT_MEM_WRITE", "thread_id": tid, "target": "DATA_STACK" | "SHADOW_STACK", "addr": a, "value": v}`
  - `INCSSP`: `{"time": t, "type": "INCSSP", "thread_id": tid, "count": n}`

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다 (compact JSON, `ensure_ascii=False`):

```json
{
  "summary": {
    "total_calls": 1,
    "total_rets": 1,
    "successful_rets": 0,
    "cp_exceptions": 1,
    "rop_attacks_blocked": 1,
    "shadow_stack_write_violations": 0,
    "active_threads": 0
  },
  "thread_states": {
    "1": {
      "thread_id": 1,
      "shstk_enabled": true,
      "shstk_locked": false,
      "data_stack_depth": 0,
      "shadow_stack_depth": 0,
      "is_alive": false
    }
  },
  "security_alerts": [
    {
      "time": 4,
      "thread_id": 1,
      "type": "CONTROL_PROTECTION_EXCEPTION",
      "reason": "SHADOW_STACK_MISMATCH",
      "si_code": "SEGV_CPERR",
      "expected_ret": "0x00401000",
      "corrupted_ret": "0xdeadbeef"
    }
  ],
  "event_logs": [ ... ]
}
```
