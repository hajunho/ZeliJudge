# 문제 455: Linux Kernel Kprobes 브레이크포인트 주입 및 SSOL (Single-Step Out-of-Line) 트램펄린 엔진

## 문제 설명

리눅스 커널의 **Kprobes**(Kernel Dynamic Probes, `kernel/kprobes.c`, `arch/x86/kernel/kprobes/core.c`)는 실행 중인 커널 코드를 재컴파일하거나 재부팅하지 않고도, 임의의 커널 인스트럭션 주소에 동적으로 중단점(Probe)을 설치하여 실행 컨텍스트(레지스터, 메모리, 콜스택)를 추적할 수 있게 해주는 핵심 저수준 트레이싱 메커니즘입니다.

Kprobes의 동작 원리는 고도로 정교한 CPU 아키텍처 및 기계어 명령어 패칭 기법에 기반합니다:

```
+-----------------------------------------------------------------------------------------+
|                  Linux Kernel Kprobes SSOL Execution Flow                               |
+-----------------------------------------------------------------------------------------+

 [Original Code Segment]                      [SSOL Area: kprobe_insn_page]
      |                                              |
 0x401000: MOV rax, 10                               |
      |                                              |
 0x401005: [0xCC: INT3]  <--- Probe Hit!             |
      |                                              |
      +--- [CPU Exception #BP (Vector 3)]            |
      |    1. kprobe_pre_handler() invoked           |
      |    2. Setup Single-Step Out-of-Line (SSOL)   |
      |    3. Redirect RIP to SSOL slot ------------>+ 0x7fff0000: ADD rax, 50 (copied insn)
      |                                              |              (with RIP fixup if rel)
      |                                              |
      |                                              +--- [CPU Trap #DB (Vector 1)]
      |                                                   1. kprobe_post_handler() invoked
      |                                                   2. Restore execution flow
      |<--------------------------------------------------3. Set RIP to resume_addr (0x40100a)
      |
 0x40100a: SUB rax, 20
      |
      v
```

### 1. Kprobe 등록 시점 (`register_kprobe`)
1. **명령어 경계 검증 (`EINVAL_NOT_INSN_BOUNDARY`)**: 대상 주소(`addr`)는 반드시 명령어의 시작 바이트에 위치해야 합니다. 다중 바이트 명령어의 중간 바이트에 브레이크포인트를 주입하면 잘못된 opcode 디코딩으로 커널 크래시(Kernel Panic)가 발생합니다.
2. **블랙리스트 검증 (`EINVAL_BLACKLISTED`)**: Kprobe 인터럽트 핸들러 자체(`do_int3`, `kprobe_fault_handler`, NMI 루틴 등)에 프로브를 설치하면 무한 재귀 트랩에 빠지므로, `NOKPROBE_SYMBOL`로 지정된 블랙리스트 주소 범위의 프로브 등록은 엄격히 차단됩니다.
3. **SSOL (Single-Step Out-of-Line) 슬롯 할당**:
   - 실행 가능한 전용 페이지(`kprobe_insn_page`)의 슬롯 풀(`max_slots`)에서 빈 슬롯을 할당받습니다. 슬롯이 없으면 `ENOSPC_SSOL_FULL`을 반환합니다.
   - 대상 위치의 원래 명령어(`orig_insn`)를 SSOL 슬롯에 복사합니다.
4. **RIP 상대 주소 보정 (RIP-Relative Displacement Fixup)**:
   - x86-64 아키텍처의 상대 점프(`JMP_REL32`, `JE_REL32`) 등은 현재 명령어의 끝 주소(`RIP`)를 기준으로 상대 변위(`disp`)를 가집니다.
   - 명령어가 원래 코드 영역(`addr`)에서 SSOL 슬롯(`slot_addr`)으로 복사되면 기준 주소가 변경되므로, 타깃 주소(`target_addr`)에 정상 도달하도록 새로운 변위 `new_disp = target_addr - (slot_addr + len)`로 보정(`ssol_fixups += 1`)해야 합니다.
5. **텍스트 패칭 (`text_poke`)**: 대상 주소의 첫 바이트를 x86 브레이크포인트 명령어인 `INT3` (0xCC, 길이 1)로 치환합니다.

### 2. 프로브 적중 및 실행 시점 (`step` / `run_until_ret`)
1. `rip`가 가리키는 명령어가 `INT3`인 경우:
   - `probe_hits` 카운터를 증가시킵니다.
   - `pre_handler`가 존재하면 실행합니다 (선택적 레지스터 조작 `set_reg` 지원).
   - `rip`를 해당 프로브의 SSOL 슬롯 주소로 이동시켜 복사된 원래 명령어를 실행합니다.
   - 명령어 실행 후 `post_handler`가 존재하면 실행합니다.
   - 다음 `rip` 복원:
     - 복사된 명령어가 분기문(`JMP_REL32`, `JE_REL32`)이고 분기가 성립(taken)된 경우 분기 대상 주소(`target_addr`)로 이동합니다.
     - 분기가 미성립되었거나 일반 순차 명령어인 경우 원래 코드의 다음 주소인 `resume_addr` (`addr + orig_len`)로 복귀합니다.
     - `RET`인 경우 정상 종료(`next_rip = None`)합니다.
2. 일반 명령어인 경우 정상 실행 후 `rip`를 다음 명령어로 전진시킵니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `ssol_config`: SSOL 메모리 풀 설정 (기본값: `base = 0x7fff0000`, `slot_size = 64`, `max_slots = 16`).
- `operations`: 일련의 연산 배열.

지원되는 연산:
1. `{"op": "LOAD_CODE", "instructions": [...], "start_rip": int|null, "init_regs": dict|null}`
   - 코드 메모리에 명령어 목록을 적재하고 레지스터/RIP를 초기화합니다.
2. `{"op": "SET_BLACKLIST", "ranges": [{"start": int, "end": int}, ...]}`
   - 프로브 설치가 금지된 블랙리스트 주소 구간(`[start, end)`)을 등록합니다.
3. `{"op": "REGISTER_KPROBE", "probe_id": str, "addr": int, "pre_handler": dict|null, "post_handler": dict|null}`
   - `addr`에 kprobe를 등록합니다.
   - 에러 반환: `EEXIST_PROBE_ID`, `EBUSY_ALREADY_PROBED`, `EINVAL_BLACKLISTED`, `EINVAL_NOT_INSN_BOUNDARY`, `ENOSPC_SSOL_FULL`.
   - 성공 시: `{"status": "KPROBE_REGISTERED", "probe_id": str, "addr": int, "slot_addr": int, "fixup_applied": bool}`.
4. `{"op": "UNREGISTER_KPROBE", "probe_id": str}`
   - kprobe를 제거하고 원래 명령어를 복원하며 SSOL 슬롯을 반납합니다.
   - 에러: `{"status": "ENOENT_PROBE_NOT_FOUND", "probe_id": str}`.
   - 성공 시: `{"status": "KPROBE_UNREGISTERED", "probe_id": str, "addr": int, "freed_slot": int}`.
5. `{"op": "STEP"}`
   - 현재 `rip`의 명령어를 단일 단계 실행합니다.
6. `{"op": "RUN_UNTIL_RET", "max_steps": int}`
   - `RET` 명령어를 만나거나 최대 단계 수에 도달할 때까지 연속 실행합니다.
7. `{"op": "QUERY_STATE"}`
   - 활성 프로브, 남은 슬롯 수, 레지스터 상태, 통계(`stats`)를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
