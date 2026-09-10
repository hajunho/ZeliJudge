# 이론: Linux Kernel Kprobes 동적 브레이크포인트 패칭 및 SSOL (Single-Step Out-of-Line) 아키텍처

## 1. 커널 동적 인스트루멘테이션과 Kprobes의 필요성

전통적으로 운영체제 커널의 동작을 관찰하거나 성능 병목을 진단하기 위해서는 소스 코드에 `printk()`를 삽입하고 커널 전체를 재컴파일하여 재부팅해야 했습니다. 이는 프로덕션 서버 환경에서 서비스 다운타임을 유발하며, 타이밍에 민감한 레이스 컨디션 버그를 은폐(Heisenbug)시키는 심각한 결함이 있었습니다.

리눅스 커널 2.6에 도입된 **Kprobes**(Kernel Probes)는 실행 중인 라이브 커널의 메모리 텍스트 세그먼트를 런타임에 직접 수정하여, 거의 오버헤드 없이 임의의 명령어 위치에 관측 후크(Observation Hook)를 설치할 수 있도록 설계된 커널 서브시스템입니다 (`kernel/kprobes.c`, `arch/x86/kernel/kprobes/core.c`).

---

## 2. x86 아키텍처의 `INT3` (0xCC) 브레이크포인트와 원자적 패칭

x86-64 명령어 셋에서 소프트웨어 브레이크포인트 명령어는 `INT3` (1바이트 크기, opcode `0xCC`)입니다. 일반적인 2바이트 소프트웨어 인터럽트 `INT n` (`0xCD n`)과 달리 1바이트로 설계된 이유는 다중 바이트 명령어를 대체할 때 다른 CPU 코어가 명령어의 중간 바이트를 인출(Instruction Fetch)하여 미정의 명령어 예외(Undefined Opcode)를 일으키는 레이스 컨디션을 방지하기 위함입니다.

```
 [Original Instruction: 5 Bytes]
 +------+------+------+------+------+
 | 0xE8 | 0x12 | 0x34 | 0x56 | 0x78 |  CALL relative
 +------+------+------+------+------+
 
 [Patched with INT3: 1 Byte atomic patch]
 +------+------+------+------+------+
 | 0xCC | 0x12 | 0x34 | 0x56 | 0x78 |  INT3 (Breakpoint)
 +------+------+------+------+------+
```

커널은 `text_poke()` 함수를 통해 대상 명령어의 첫 바이트를 원자적으로 `0xCC`로 덮어씁니다. CPU 코어가 이 주소를 실행하는 순간 즉시 하드웨어 예외인 `#BP` (Breakpoint Exception, Vector 3)가 발생하여 제어권이 커널의 `do_int3()` 핸들러로 넘어갑니다.

---

## 3. 인-플레이스 단일 단계 실행 vs SSOL (Single-Step Out-of-Line)

`INT3` 적중 후 원래의 명령어를 실행하는 방법에는 두 가지가 있습니다:

### 방식 A: 인-플레이스 단일 단계 실행 (In-Place Single-Stepping)
1. 대상 주소의 `0xCC`를 원래 바이트로 복원.
2. CPU의 EFLAGS 레지스터에 Trap Flag(`TF`) 설정.
3. 인터럽트 복귀(`IRET`)하여 원래 명령어를 제자리에서 실행.
4. 실행 완료 직후 하드웨어 싱글스텝 트랩(`#DB`, Vector 1) 발생.
5. `#DB` 핸들러에서 다시 대상 주소에 `0xCC`를 주입.
- **치명적 결함**: 멀티코어 환경에서 1번과 5번 사이에 다른 CPU 코어가 해당 주소를 통과하면 프로브가 누락(Miss)되는 심각한 SMP 동시성 문제가 발생합니다.

### 방식 B: SSOL (Single-Step Out-of-Line, Kprobes 표준 방식)
1. 원래 명령어를 사전에 할당된 전용 버퍼(`kprobe_insn_page`)의 빈 슬롯으로 복사해 둡니다.
2. 프로브 적중 시 대상 주소의 `0xCC`를 건드리지 않고, 예외 복귀 주소(`pt_regs->ip`)를 **SSOL 슬롯의 복사된 명령어 주소**로 리다이렉트합니다.
3. 복사된 명령어가 SSOL 슬롯에서 안전하게 단일 단계 실행됩니다.
4. 실행 후 복귀는 슬롯 끝의 점프문 또는 `#DB` 트랩에서 원래 코드의 다음 주소(`resume_addr`)로 직접 점프합니다.
- **장점**: 원본 코드 세그먼트의 `0xCC`를 복원할 필요가 전혀 없으므로, 다른 CPU 코어가 동시에 진입하더라도 락 경합이나 프로브 누락 없이 100% 안전하게 동시 실행됩니다.

---

## 4. RIP 상대 주소 보정 (RIP-Relative Displacement Fixup)

x86-64 아키텍처에서는 메모리 피연산자 및 점프/호출 명령어 대부분이 명령어 포인터 상대 주소(RIP-Relative Addressing)를 사용합니다.

예를 들어, `0x401005`에 위치한 5바이트 상대 점프 `JMP_REL32`가 `0x401014`로 점프한다면:
$$	ext{Target} = 	ext{RIP}_{	ext{next}} + 	ext{disp} = (0x401005 + 5) + 10 = 0x401014$$

이 명령어가 SSOL 슬롯 `0x7fff0000`으로 복사되었을 때 기존 변위 `disp = 10`을 그대로 실행하면:
$$	ext{New Target} = (0x7fff0000 + 5) + 10 = 0x7fff000f 
eq 0x401014$$

엉뚱한 메모리를 점프하여 즉각 커널 패닉이 발생합니다. 따라서 Kprobes 서브시스템은 명령어를 SSOL 슬롯에 복사할 때 디스어셈블러(`arch_copy_kprobe`)를 거쳐 RIP 상대 주소의 변위를 다음과 같이 재계산합니다:
$$	ext{new\_disp} = 	ext{target\_addr} - (	ext{slot\_addr} + 	ext{insn\_len})$$

이러한 정밀한 보정을 통해 코드가 슬롯에서 실행되더라도 원래 의도했던 대상 주소로 정확하게 분기할 수 있습니다.

---

## 5. Kprobes 안전성 제약: 명령어 경계 및 블랙리스트

1. **명령어 경계 검증 (Instruction Boundary)**:
   - x86은 가변 길이 명령어(1~15바이트) 아키텍처입니다. 명령어가 5바이트인 경우, 2번째나 3번째 바이트에 `INT3`을 박으면 CPU가 앞부분을 유효하지 않은 프리픽스나 opcode로 잘못 해석하여 `#UD`(Invalid Opcode) 예외를 일으킵니다. 따라서 Kprobes는 사전에 커널 심볼 디코더나 eBPF verifier를 통해 등록 주소가 올바른 명령어 시작 지점인지 검증합니다.
2. **재귀 트랩 방지 블랙리스트 (NOKPROBE_SYMBOL)**:
   - `do_int3()`, `do_debug()`, `nmi_handle()` 등 예외 핸들러 내부에 kprobe를 설치하면, 예외 처리 중 다시 `#BP`가 발생하여 커널 콜 스택이 고갈되고 CPU가 트리플 폴트(Triple Fault)로 즉사합니다. 커널은 이 함수들을 `__kprobes` 또는 `NOKPROBE_SYMBOL()` 매크로로 표시하여 프로브 등록을 원천 차단합니다.
