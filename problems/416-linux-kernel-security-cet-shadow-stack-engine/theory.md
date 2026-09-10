# 이론 문서 416: Linux 커널 하드웨어 보안과 Intel CET 섀도우 스택 및 제어 흐름 무결성(CFI) 내부 원리

## 1. 개요 및 배경 (Historical Threat Model & Motivation)

컴퓨터 시스템 보안에서 제어 흐름 하이재킹(Control-flow Hijacking)은 원격 코드 실행(RCE) 공격의 핵심 통로였습니다.
운영체제와 컴파일러가 도입한 방어 기법들은 끊임없는 공격 기법의 발전과 맞물려 발전해 왔습니다:

1. **W^X / DEP / NX 비트 (Data Execution Prevention)**:
   - 스택과 힙 메모리에 실행 권한(`PROT_EXEC`)을 제거했습니다.
   - 공격자의 대응: 기존 바이너리 및 공유 라이브러리(`libc`)에 존재하는 실행 가능 코드 조각(Gadget)의 끝에 위치한 `ret` 명령어를 이용하는 **ROP (Return-Oriented Programming)**를 고안했습니다.

2. **ASLR (Address Space Layout Randomization)**:
   - 라이브러리와 스택의 베이스 주소를 무작위화했습니다.
   - 공격자의 대응: 메모리 정보 유출(Information Leak) 취약점을 결합하여 라이브러리 오프셋을 역계산하고 ROP 가젯 체인을 동적으로 구성했습니다.

3. **스택 카나리 (Stack Canary / ProPolice)**:
   - 로컬 변수와 복귀 주소 사이에 난수(Canary)를 삽입하고 함수 종료 시 검증했습니다.
   - 공격자의 대응: 카나리 값을 읽어내는 누출 공격, 또는 스택 카나리를 거치지 않는 스택 피보팅(Stack Pivoting) 기법을 사용했습니다.

이러한 소프트웨어적 확률 기반 방어의 한계를 극복하고, **"복귀 주소의 변조를 수학적·물리적으로 불가능하게 만드는 하드웨어 결정론적 보안"**을 실현하기 위해 도입된 것이 바로 **Intel CET (Control-flow Enforcement Technology)**입니다.

---

## 2. Intel CET 하드웨어 아키텍처

Intel CET는 제어 흐름 무결성(CFI, Control-Flow Integrity)을 보장하기 위해 두 가지 독립적인 하드웨어 메커니즘을 제공합니다:
1. **IBT (Indirect Branch Tracking)**: 간접 점프(`jmp rax`, `call rbx`)의 대상이 유효한 엔드포인트(`ENDBR64` 명령어)인지 검증하여 JOP/COP 공격을 차단합니다.
2. **Shadow Stack (섀도우 스택)**: 모든 함수 복귀(`ret`) 시 복귀 주소의 무결성을 검증하여 ROP 공격을 100% 차단합니다.

### 2.1 섀도우 스택 포인터 (`SSP`)와 메모리 보호
- CPU는 일반 데이터 스택 포인터 `RSP` 외에 전용 내부 레지스터 **`SSP` (Shadow Stack Pointer)**를 유지합니다.
- 섀도우 스택 페이지는 MMU 수준에서 다음과 같은 특수 페이지 속성을 가집니다:
  - 사용자 공간 일반 읽기: 허용 (`PROT_READ`).
  - 사용자 공간 일반 쓰기(`mov`, `push` 등): **절대 불허 (하드웨어 #PF 예외 발생)**.
  - 오직 CPU 내부 마이크로코드에 의한 `CALL`, `RET`, `RSTORSSP`, `WRSS` 명령어만이 섀도우 스택 메모리에 쓰기를 수행할 수 있습니다.

### 2.2 `CALL`과 `RET`의 마이크로코드 동작
```
[ CALL Target ]
  1. RSP -= 8; *RSP = ReturnAddress;
  2. SSP -= 8; *SSP = ReturnAddress;   <--- Hardware Dual Push!

[ RET ]
  1. ReturnAddress_RSP = *RSP; RSP += 8;
  2. ReturnAddress_SSP = *SSP; SSP += 8;
  3. if (ReturnAddress_RSP != ReturnAddress_SSP) {
         RAISE_EXCEPTION(#CP, CP_RET);  <--- Hardware Mismatch Trap!
     }
  4. RIP = ReturnAddress_RSP;
```

---

## 3. 리눅스 커널 6.6+ 구현 (`arch/x86/kernel/shstk.c`)

리눅스 커널은 사용자 공간 프로세스가 CET 섀도우 스택을 안전하게 활용할 수 있도록 정교한 라이프사이클 관리 인터페이스를 제공합니다.

### 3.1 `arch_prctl` 인터페이스
- **`ARCH_SHSTK_ENABLE`**:
  - 현재 태스크의 섀도우 스택을 활성화합니다.
  - 커널은 `mmap` 서브시스템을 통해 섀도우 스택 전용 VMA(`VM_SHADOW_STACK`)를 할당하고 하드웨어 `MSR_IA32_U_CET` 레지스터의 `SH_STK_EN` 비트를 활성화합니다.
- **`ARCH_SHSTK_DISABLE`**:
  - 섀도우 스택을 비활성화합니다.
- **`ARCH_SHSTK_LOCK`**:
  - `shstk_locked` 플래그를 세팅합니다.
  - 잠금 상태에서는 `ARCH_SHSTK_DISABLE` 호출이 커널에서 `-EPERM`으로 거부되므로, 공격자가 프로세스 권한을 획득하더라도 섀도우 스택을 임의로 끌 수 없습니다.

### 3.2 제어 보호 예외 (`#CP`) 디스패치
- x86 하드웨어는 복귀 주소 불일치를 감지하면 벡터 21 예외인 `#CP`를 발생시킵니다.
- 커널의 `do_control_protection_exception()` 핸들러는:
  1. 에러 코드가 `CP_RET` (Return Address Mismatch)인지 확인합니다.
  2. 태스크의 비정상 제어 흐름을 감사 로그(`dmesg`)에 기록합니다.
  3. 프로세스에 `SIGSEGV` 시그널을 전달하며, `siginfo_t`에 `si_code = SEGV_CPERR`을 채워 프로세스를 안전하게 종료시킵니다.

---

## 4. 스택 언와인딩과 비로컬 점프 (`setjmp`/`longjmp`)

프로그래밍 언어(C, C++)는 예외 처리나 `longjmp()`를 통해 호출 스택을 여러 단계 한꺼번에 되감아야 하는 경우가 있습니다.
일반 스택 `RSP`만 이동시키고 `RET`을 실행하면 섀도우 스택 `SSP`와의 불일치로 `#CP` 예외가 발생합니다.

이를 위해 x86 하드웨어는 **`INCSSP`** 명령어를 제공합니다:
$$\text{SSP} \leftarrow \text{SSP} + (8 \times \text{count})$$
- C 라이브러리(`glibc`)의 `longjmp()` 구현은 목적지 jmp_buf에 도달할 때까지 건너뛸 프레임 수를 계산한 후 `INCSSP`를 실행하여 섀도우 스택을 정상 프레임 위치로 동기화합니다.

---

## 5. 보안 및 성능 평가

### 5.1 ROP 공격 방어 결정론 (Determinism)
- **전통적 방어(Canary, ASLR)**: 확률적(Probabilistic) 방어 모델 ($P_{\text{bypass}} > 0$).
- **Intel CET 섀도우 스택**: 물리적 분리 및 하드웨어 비교 검증 ($P_{\text{bypass}} = 0$). 모든 복귀 주소 조작 시도가 100% 하드웨어 차단됩니다.

### 5.2 런타임 성능 오버헤드
- 섀도우 스택의 푸시 및 팝은 L1 D-Cache 내부에서 0~1 사이클 내에 병렬로 처리됩니다.
- 실제 SPEC CPU 및 웹 서버 벤치마크에서 CET 섀도우 스택의 성능 저하는 **1%~2% 미만**으로 측정되어, 프로덕션 환경에 상시 활성화하기에 최적화된 하드웨어 보안 솔루션입니다.
