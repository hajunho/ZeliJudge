# 문제 406: Linux 커널 x86 KPTI(Kernel Page Table Isolation) 이중 CR3 격리 및 PCID 기반 TLB 플러시 최적화 엔진

## 문제 설명

2018년 초, 컴퓨터 아키텍처 역사상 가장 파괴적인 하드웨어 보안 취약점 중 하나인 **Meltdown (CVE-2017-5754)**이 공개되었습니다.

현대 x86_64 고성능 CPU는 명령어 처리량을 극대화하기 위해 명령어를 순서대로 실행하지 않고 분기 예측(Branch Prediction)을 바탕으로 미리 계산하는 **비순차적 투기적 실행(Out-of-Order Speculative Execution)**을 수행합니다. 

전통적인 리눅스 커널은 가상 메모리 공간(48비트 표준 256TB) 중:
- 하위 128TB(`0x0000000000000000` ~ `0x00007fffffffffff`)를 유저 공간(User Space)으로,
- 상위 128TB(`0xffff800000000000` ~ `0xffffffffffffffff`)를 커널 공간(Kernel Space)으로 분할하여,
**단일 4단계 페이지 테이블(Single PGD, Single CR3)**에 유저와 커널 매핑을 동시에 공존시켰습니다. 유저 코드가 커널 영역에 접근하지 못하도록 페이지 테이블 엔트리의 `U/S (User/Supervisor)` 비트를 0으로 설정하여 하드웨어 보호를 수행했습니다.

그러나 Meltdown 취약점의 핵심은 **"권한 검사(Privilege Check)보다 캐시 적재(Cache Allocation)가 먼저 일어난다"**는 하드웨어 파이프라인의 레이스 컨디션에 있었습니다:
```c
// 비인가 유저 프로세스의 투기적 실행 공격 코드
char secret = *(char *)0xffff888000100000;   // 커널 비밀 메모리 역참조 (특권 위반)
int dummy = probe_array[secret * 4096];       // 비밀 값에 따른 캐시 라인 적재
```
비록 CPU가 뒤늦게 특권 위반을 감지하고 `#GP(General Protection Fault)` 또는 `#PF(Page Fault)` 예외를 발생시켜 파이프라인을 롤백(Rollback)하더라도, `secret` 값에 해당하는 `probe_array`의 특정 캐시 라인은 이미 CPU L1/L2 데이터 캐시에 적재된 상태로 남습니다. 공격자는 **Flush+Reload** 타이밍 분석을 통해 1바이트당 불과 수 마이크로초 만에 커널의 모든 물리 메모리(비밀번호, 암호화 키, 프로세스 크리덴셜)를 100% 탈취할 수 있었습니다.

리눅스 커널 커뮤니티는 하드웨어 결함을 소프트웨어로 원천 봉쇄하기 위해 **KPTI (Kernel Page Table Isolation, 구 KAISER, `arch/x86/mm/kpti.c`, `CONFIG_PAGE_TABLE_ISOLATION`)**를 전면 도입했습니다.

KPTI의 코어 아키텍처 원리는 다음과 같습니다:

1. **이중 CR3 (Dual-CR3 / Shadow PGD) 구조**:
   - 각 프로세스는 이제 1개가 아닌 **2개의 분리된 페이지 테이블**을 가집니다:
     1. **`kernel_pgd` (Kernel CR3)**:
        - 시스템 콜, 인터럽트 등 커널 모드에서만 사용됩니다.
        - 전체 커널 메모리(물리 직접 매핑, vmalloc, 커널 텍스트/데이터)와 유저 공간 매핑이 모두 온전히 존재합니다.
     2. **`user_pgd` (Shadow PGD / User CR3)**:
        - 유저 공간 코드가 실행되는 동안 CPU CR3에 로드됩니다.
        - 유저 가상 주소는 정상 매핑되지만, **커널 가상 주소 영역은 거의 100% 완전히 미매핑(Unmapped / P=0)** 상태로 비워둡니다.
        - 오직 시스템 콜 진입 및 인터럽트 처리에 필수적인 극소수의 **트램펄린(Trampoline) 영역(`.entry.text`, IDT, TSS, 트램펄린 스택)**만 읽기 전용으로 최소 매핑됩니다.
   - 결과적으로 유저 모드에서 투기적 실행으로 커널 비밀 주소를 읽으려 해도, MMU 변환 자체가 존재하지 않아 하드웨어 수준에서 버스 읽기 자체가 차단되므로 Meltdown이 완벽히 무력화됩니다!

2. **성능 재앙과 x86 PCID (Process-Context Identifiers) 최적화**:
   - 유저 공간과 커널 공간을 넘나들 때마다(시스템 콜 `SYSCALL` / `SYSRET`, 인터럽트) CPU CR3 레지스터를 교체해야 합니다(`SWITCH_TO_KERNEL_CR3`, `SWITCH_TO_USER_CR3`).
   - 전통적인 x86 아키텍처에서는 CR3를 다시 쓰는 즉시 CPU의 모든 비전역(Non-global) TLB 엔트리가 일괄 플러시(Flush)됩니다!
   - 매 시스템 콜마다 수백 개의 L1/L2 TLB 캐시가 모조리 증발하여, 후속 메모리 접근 시 4단계 페이지 워크(Page Table Walk) 페널티가 누적되어 데이터베이스, 웹 서버 등에서 5%~30%에 달하는 극심한 성능 저하가 발생했습니다.
   - 리눅스는 이를 해결하기 위해 **x86 하드웨어 PCID (CR4.PCIDE bit, 12-bit Context ID) 및 `NOFLUSH_BIT` (CR3 bit 63)**를 결합했습니다:
     - `kernel_pgd`와 `user_pgd`에 서로 다른 PCID 태그를 부여합니다.
     - CR3 스위칭 시 최상위 비트(`NOFLUSH_BIT = 1 << 63`)를 세팅하여 **TLB 플러시를 방지**합니다!
     - 메모리 해제(`munmap`, `mprotect`) 시에만 특정 PCID에 대해 선택적 무효화 명령어인 `INVPCID`를 발행하여 성능과 보안을 동시에 달성합니다.

여러분의 임무는 리눅스 커널의 x86 KPTI 이중 CR3 페이지 테이블 격리, 트램펄린 진입, PCID 기반 TLB 플러시 최적화, 그리고 Meltdown 부채널 방어 감사 엔진을 정밀 시뮬레이션하는 시스템을 구축하는 것입니다.

---

## 시스템 아키텍처 다이어그램

```
+========================================================================================+
|                       x86_64 KPTI Dual-CR3 Page Table Architecture                     |
+========================================================================================+

               [ Traditional Single-CR3 (Vulnerable to Meltdown) ]
    +--------------------------------------------------------------------------------+
    | Virtual Address Space: [ User Space (0..128TB) ] | [ Kernel Space (128..256TB)]|
    | Page Table (CR3):      Full User Mapping         | Full Kernel (U/S=0) [LEAK!] |
    +--------------------------------------------------------------------------------+
                                       |
                                       v
               [ KPTI Dual-CR3 Architecture (Meltdown Mitigated) ]
    
    1. User Page Table (User CR3 = user_pgd | user_pcid | NOFLUSH):
    +--------------------------------------------------+-----------------------------+
    | User Memory Mappings (Text, Heap, Stack, Libs)   | Trampoline ONLY (.entry.text|
    | [ Fully Accessible in User Mode ]                | IDT, TSS, Entry Stack)      |
    |                                                  | [ REST OF KERNEL: UNMAPPED!]|
    +--------------------------------------------------+-----------------------------+
            | (Speculative Read to 0xffff8880... -> UNMAPPED! -> BLOCKED!)
            |
            | Syscall / Interrupt Trapped to Trampoline
            v
    [ Trampoline Code: SWITCH_TO_KERNEL_CR3 ]
            |
            v
    2. Kernel Page Table (Kernel CR3 = kernel_pgd | kernel_pcid | NOFLUSH):
    +--------------------------------------------------+-----------------------------+
    | User Memory Mappings (For copy_from/to_user)     | COMPLETE KERNEL SPACE       |
    | [ Accessible in Kernel Mode ]                    | (Direct Physical Map, Heap, |
    |                                                  |  Page Cache, Secrets, etc.) |
    +--------------------------------------------------+-----------------------------+
            |
            | Kernel Syscall Service Routine Executes
            |
            v
    [ Trampoline Code: SWITCH_TO_USER_CR3 ]
            |
            v Return to User Mode (sysretq / iretq)
```

---

## 입출력 형식 및 명세

### 입력 JSON 구조

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 전달됩니다:

```json
{
  "config": {
    "enable_kpti": true,
    "enable_pcid": true,
    "tlb_capacity": 64,
    "cr3_switch_cost_cycles": 50,
    "tlb_miss_penalty_cycles": 100,
    "invpcid_cost_cycles": 80,
    "trampoline_overhead_cycles": 30,
    "base_mem_cycle": 4
  },
  "mappings": [
    {"vaddr": 4194304, "pfn": 256, "is_kernel": false},
    {"vaddr": 18446744071562067968, "pfn": 512, "is_kernel": true, "is_trampoline": true},
    {"vaddr": 18446603336221196288, "pfn": 768, "is_kernel": true, "is_trampoline": false}
  ],
  "instructions": [
    {"op": "USER_ACCESS", "vaddr": 4194304},
    {"op": "USER_ACCESS", "vaddr": 18446603336221196288, "is_speculative": true},
    {"op": "SYSCALL_ENTRY"},
    {"op": "KERNEL_ACCESS", "vaddr": 18446603336221196288},
    {"op": "SYSCALL_EXIT"},
    {"op": "USER_ACCESS", "vaddr": 4194304}
  ]
}
```

#### 파라미터 필드 명세:
- `enable_kpti` (bool): KPTI 이중 CR3 격리 활성화 여부.
- `enable_pcid` (bool): x86 PCID 태깅 및 NOFLUSH 비트 활성화 여부.
- `tlb_capacity` (int): 하드웨어 TLB 최대 엔트리 용량 (LRU 교체).
- `cr3_switch_cost_cycles` (int): `mov %rax, %cr3` 명령어 실행 비용 사이클.
- `tlb_miss_penalty_cycles` (int): TLB 미스 시 4단계 페이지 테이블 워크 페널티 사이클.
- `invpcid_cost_cycles` (int): 선택적 `INVPCID` 명령어 실행 비용 사이클.
- `trampoline_overhead_cycles` (int): 트램펄린 레지스터 백업/복원 오버헤드 사이클.
- `base_mem_cycle` (int): 정상 메모리 접근 기본 실행 사이클.

#### 명령어(`instructions`) 연산 코드 명세:
- `USER_ACCESS`: 유저 모드에서 가상 주소 읽기/쓰기 (선택 필드: `is_speculative: true/false`).
- `KERNEL_ACCESS`: 커널 모드에서 가상 주소 접근.
- `SYSCALL_ENTRY`: 유저 모드에서 커널 모드로 진입 (`SWITCH_TO_KERNEL_CR3`).
- `SYSCALL_EXIT`: 커널 모드에서 유저 모드로 복귀 (`SWITCH_TO_USER_CR3`).
- `UNMAP`: 가상 주소 매핑 해제 (`munmap`), 페이지 테이블 갱신 및 TLB 무효화 유발.

---

### 출력 JSON 구조

표준 출력(`sys.stdout`)으로 공백 없이 압축된 단일 JSON 문자열을 출력합니다:

```json
{
  "summary": {
    "total_cycles": 480,
    "execution_cycles": 20,
    "cr3_switch_cycles": 100,
    "tlb_miss_cycles": 300,
    "trampoline_cycles": 60,
    "invpcid_cycles": 0
  },
  "tlb_metrics": {
    "total_lookups": 5,
    "hits": 2,
    "misses": 3,
    "hit_ratio": 0.4,
    "flush_count": 0
  },
  "security_audit": {
    "enable_kpti": true,
    "enable_pcid": true,
    "meltdown_attempts": 1,
    "meltdown_blocked": 1,
    "meltdown_leaks": 0,
    "is_vulnerable": false
  }
}
```

---

## 핵심 하드웨어 및 보안 시뮬레이션 규칙

1. **TLB 히트 및 미스 판정**:
   - `PCID` 활성화 시: TLB 엔트리는 `(vpn, pcid, is_global)`로 관리됩니다.
     - 조회 시 `entry.is_global == True`이거나 `entry.pcid == current_pcid`일 때만 HIT.
   - `PCID` 비활성화 시:
     - CR3 전환 시마다 모든 비전역 TLB 엔트리가 즉시 플러시(`flush_non_global`)됩니다.
2. **KPTI 하에서의 투기적 접근 판정**:
   - `enable_kpti == True`일 때:
     - `user_pgd`에는 트램펄린이 아닌 일반 커널 페이지의 변환 엔트리가 전혀 없습니다.
     - 투기적 읽기(`is_speculative == True`) 시도 시 페이지 테이블 워크에서 `Unmapped`가 발생하여 공격이 완전히 차단(`meltdown_blocked += 1`)됩니다.
   - `enable_kpti == False`일 때:
     - 단일 PGD 내에 커널 페이지가 존재하므로, 비록 `U/S = 0`이라도 투기적 실행 파이프라인에서 데이터가 로드되어 캐시 부채널로 유출(`meltdown_leaks += 1, is_vulnerable = True`)됩니다.
