# 심층 이론: Linux 커널 x86 KPTI(Kernel Page Table Isolation) 아키텍처와 마이크로아키텍처 보안

---

## 1. Meltdown (CVE-2017-5754) 취약점의 마이크로아키텍처적 기원

현대 고성능 마이크로프로세서는 IPC(Instructions Per Cycle)를 극대화하기 위해 다단계 명령어 파이프라인, 분기 예측기(Branch Target Buffer / Direction Predictor), 비순차 실행 엔진(Reservation Station, Reorder Buffer - ROB)을 탑재하고 있습니다.

### 1.1 투기적 실행(Speculative Execution)과 메모리 접근
조건 분기문이나 트랩 명령어 뒤에 위치한 코드는 이전 명령어의 완료 여부를 기다리지 않고 예측 경로를 따라 "투기적으로" 실행됩니다.

문제는 **CPU의 MMU 권한 검사(Privilege Checking)와 실행 유닛(Execution Unit)의 캐시 적재가 비동기적으로(Asynchronously) 수행**된다는 점입니다:
1. `mov (%kernel_secret_vaddr), %al` 명령어가 디스패치됩니다.
2. 실행 유닛은 L1 Data 캐시에서 해당 가상 주소에 매핑된 데이터를 즉시 레지스터로 가져옵니다.
3. 동시에 다음 종속 명령어인 `mov (%probe_array, %rax, 4096), %rbx`가 투기적으로 실행되어, 비밀 데이터 값에 대응하는 `probe_array[secret]` 캐시 라인을 L1D/L2 캐시로 풀링(Pulling)합니다.
4. 뒤늦게 Reorder Buffer(ROB)에서 권한 검사가 커밋(Commit) 단계에 도달하여 특권 위반을 감지하고 아키텍처 상태(레지스터)를 원복한 뒤 `#GP` 예외를 발생시킵니다.
5. 그러나 **마이크로아키텍처 상태인 CPU 캐시 태그는 롤백되지 않습니다!** 공격자는 이후 `probe_array`의 256개 페이지에 접근하는 시간(Access Latency)을 `RDTSC`로 측정하여, 가장 빠르게 접근되는 인덱스를 확인함으로써 커널 비밀 데이터를 그대로 복원할 수 있었습니다.

---

## 2. KPTI (Kernel Page Table Isolation)의 설계 원리

그라츠 공과대학교(TU Graz)의 연구진이 제안한 **KAISER** 기법을 바탕으로 리눅스 커널 4.15에 긴급 백포트된 **KPTI**의 핵심 철학은 매우 단순하지만 강력합니다:

> **"유저 모드가 실행되는 동안에는 커널 메모리 자체를 페이지 테이블에서 물리적으로 지워버려라(Unmap)."**

```
                     [ x86_64 4-Level Page Table Layout under KPTI ]

                 Kernel PGD (CR3)                         User PGD (CR3)
            +------------------------+               +------------------------+
   PGD 0    | User Space (0..128TB)  |----Shared---->| User Space (0..128TB)  |
     ...    | (Text, Data, Heap,     |               | (Fully accessible)     |
   PGD 255  |  Stack, Libraries)     |               |                        |
            +------------------------+               +------------------------+
   PGD 256  | Kernel Direct Mapping  |               |                        |
     ...    | Kernel Heap, Modules,  |               |     ALL UNMAPPED       |
   PGD 510  | vmalloc, Page Cache    |               |      (P-bit = 0)       |
            +------------------------+               |                        |
   PGD 511  | Trampoline & Stubs     |----Shared---->| Trampoline & Stubs     |
            | (.entry.text, IDT, TSS)|               | (entry_SYSCALL_64 ONLY)|
            +------------------------+               +------------------------+
```

### 2.1 섀도우 PGD(Shadow PGD)와 메모리 분할
리눅스는 프로세스 생성(`mm_init`) 시 4KB짜리 PGD 페이지를 연속으로 2개(총 8KB) 할당합니다:
- `kernel_pgd`: 오프셋 0x0000.
- `user_pgd`: 오프셋 0x1000 (`kernel_pgd + PAGE_SIZE`).

유저 모드에서 실행 중일 때 CR3는 `user_pgd`를 가리킵니다. 유저 공간 코드가 악의적으로 임의의 커널 주소(`0xffff8880...`)를 읽으려 투기적 실행을 시도하더라도, PGD 256~510의 엔트리가 전부 0(Not Present)이므로 MMU는 물리 주소 변환을 시작조차 하지 못하고 즉시 중단됩니다. 따라서 캐시로 데이터가 적재되는 일 자체가 물리적으로 불가능합니다.

---

## 3. 트램펄린(Trampoline)과 엔트리 스텁

유저 모드에서 커널 모드로 진입하는 순간(`syscall` 명령어 또는 타이머 인터럽트 발생 시) CPU는 여전히 `user_pgd` 상태입니다. 커널 코드가 실행되려면 최소한 진입 코드와 페이지 테이블을 교체할 어셈블리 루틴이 매핑되어 있어야 합니다.

이 최소한의 징검다리를 **트램펄린(Trampoline Code, `arch/x86/entry/entry_64.S`)**이라 부릅니다:
1. **`.entry.text` 섹션**: `entry_SYSCALL_64` 진입점 어셈블리 코드.
2. **인터럽트 서술자 테이블 (IDT)**: 하드웨어 인터럽트 및 예외 벡터.
3. **태스크 상태 세그먼트 (TSS)**: 특권 레벨 전환 시 사용할 커널 스택 포인터.
4. **트램펄린 스택 (Per-CPU Trampoline Stack)**: 레지스터를 임시로 백업할 1페이지 스택.

### 3.2 CR3 스위칭 어셈블리 시퀀스
```assembly
/* arch/x86/entry/calling.h */
.macro SWITCH_TO_KERNEL_CR3 scratch_reg:req
    movq    %cr3, \scratch_reg
    ADJUST_KERNEL_CR3 \scratch_reg
    movq    \scratch_reg, %cr3
.endm
```
진입 시 트램펄린 스택에 `%rax`를 보존한 뒤 CR3의 비트를 조작하여 `kernel_pgd`로 전환하고, 복귀 시 반대로 `user_pgd`로 전환합니다.

---

## 4. 성능 재앙의 주범: TLB 플러시와 PCID 최적화

x86 프로세서의 `mov %cr3, %reg` 명령어는 본래 **"현재 프로세서의 모든 비전역 TLB를 완전히 비운다"**는 하드웨어 시맨틱을 갖고 있습니다.

시스템 콜 한 번(`getpid`, `read`)에 CR3가 2회(진입 시 1회, 복귀 시 1회) 변경됩니다.
- Nginx 웹서버나 Redis, PostgreSQL과 같이 초당 수십만 번의 시스템 콜과 컨텍스트 스위칭을 수행하는 서버에서는 매 시스템 콜마다 TLB 캐시가 모조리 파괴되었습니다.
- KPTI 도입 초기, Linux 커뮤니티는 **15%~40%에 달하는 엄청난 I/O 성능 폭락**을 겪었습니다.

### 4.1 PCID (Process-Context Identifiers)의 구원
인텔 웨스트미어(Westmere) 아키텍처부터 도입된 **PCID**는 하드웨어 TLB 태그에 12비트 식별자를 붙여 프로세스 컨텍스트를 분리하는 기술입니다:

$$\text{CR3 Register Format (x86\_64 PCID Enabled):}$$
$$\text{Bit 63: } \mathbf{NOFLUSH} \text{ (1이면 CR3 로드 시 해당 PCID의 TLB를 보존)}$$
$$\text{Bits 12..62: PGD Physical Base Address}$$
$$\text{Bits 0..11: PCID (0 ~ 4095)}$$

리눅스는 KPTI와 PCID를 결합하여 다음과 같이 동작시킵니다:
- 각 프로세스의 유저 공간에는 `PCID = k`, 커널 공간에는 `PCID = k | 0x800` (11번 비트 세팅)을 할당합니다.
- 시스템 콜 진입/복귀 시 CR3를 변경할 때 **Bit 63 (NOFLUSH)을 항상 1로 설정**하여 로드합니다!
- 이로써 CPU는 CR3가 바뀌어도 유저 TLB와 커널 TLB를 플러시하지 않고 그대로 보존합니다.
- 실제 메모리가 해제되거나 권한이 변경될 때만 **`INVPCID` (Invalidate Process-Context Identifier)** 명령어를 호출하여 특정 PCID의 특정 가상 주소만 정밀 타격하여 무효화합니다.

이 혁신적인 최적화 덕분에 KPTI의 실무 성능 오버헤드는 초기 30%에서 **1%~3% 미만**으로 기적적으로 감소할 수 있었습니다.
