# 이론 문서 415: Linux 커널 가상 메모리와 Intel MPK/PKRU 아키텍처 및 하드웨어 권한 격리 내부 원리

## 1. 개요 및 설계 철학 (Historical Context & Motivation)

현대 운영체제 가상 메모리 보호의 근간은 페이지 테이블의 권한 플래그(`Read`, `Write`, `Execute`, `User/Supervisor`)에 기반합니다.
그러나 프로세스 주소 공간 내에서 특정 모듈, 서드파티 라이브러리, JIT 기계어 버퍼, 암호화 개인 키 등을 격리하고자 할 때 기존 `mprotect(2)` 시스템 호출은 현대 고성능 시스템에 치명적인 오버헤드를 발생시킵니다.

### 1.1 `mprotect(2)`의 3대 구조적 한계

1. **`mmap_lock` 쓰기 락 경합 (Global Lock Contention)**:
   - `mprotect(2)`는 프로세스의 `mm_struct` 내 VMA 리스트를 수정하므로 `down_write(&mm->mmap_lock)`을 획득해야 합니다.
   - 이는 수십 개의 워커 스레드가 동시에 페이지 폴트를 처리하거나 메모리를 할당하는 작업을 즉시 동결(Block)시킵니다.

2. **페이지 테이블 엔트리(PTE) 재작성 (PTE Traversal)**:
   - 1GB 크기의 영역에 권한을 변경할 경우 262,144개의 4KB PTE를 커널이 일일이 순회하며 수정해야 하므로 메모리 대역폭을 낭비합니다.

3. **멀티코어 TLB 슛다운 IPI 폭풍 (Cross-Core TLB Shootdown Stalls)**:
   - CPU는 주소 변환 및 권한 정보를 TLB(Translation Lookaside Buffer)에 캐싱합니다.
   - PTE의 권한이 축소(e.g., 쓰기 권한 제거)되면, 커널은 동일한 `mm`을 실행 중인 모든 CPU 코어에 IPI(Inter-Processor Interrupt)를 전송하여 원격 코어들의 TLB를 무효화해야 합니다.
   - 수십 코어 서버에서 TLB 슛다운 IPI 1회당 2~10µs가 소모되며, 시스템 전반의 레이턴시 스파이크를 유발합니다.

인텔 MPK(Memory Protection Keys)는 이러한 한계를 극복하기 위해 **"주소 변환(Translation)과 권한 검증(Protection)을 하드웨어 수준에서 분리"**하는 혁신적인 접근법을 제시합니다.

---

## 2. 하드웨어 아키텍처: PTE 비트 62:59와 `PKRU` 레지스터

### 2.1 페이지 테이블 엔트리(PTE) 구조와 4비트 키
인텔 Skylake-SP 이후 x86-64 아키텍처는 64비트 PTE의 사용되지 않던 상위 비트 62:59(4비트)를 **Protection Key (`pkey`)** 필드로 전용(Repurpose)했습니다:

$$\text{PTE}[62:59] \in \{0, 1, 2, \dots, 15\}$$

- 운영체제는 초기 메모리 매핑 시 `pkey_mprotect()`를 통해 각 가상 메모리 페이지에 0부터 15 사이의 키 번호를 부여합니다.
- 이 바인딩은 드물게 발생하므로 초기 1회만 PTE를 수정하고 TLB를 플러시하면 됩니다.

### 2.2 32비트 `PKRU` (Protection Key Rights Userspace) 레지스터
각 CPU 하드웨어 코어 내부에는 32비트 크기의 전용 레지스터 `PKRU`가 존재합니다:

$$\text{PKRU} = \sum_{k=0}^{15} \left( \text{AD}_k \cdot 2^{2k} + \text{WD}_k \cdot 2^{2k+1} \right)$$

- **$\text{AD}_k$ (Access Disable for Key $k$, 비트 $2k$)**:
  - $\text{AD}_k = 1$이면 해당 키가 할당된 메모리에 대한 **모든 읽기(Read) 및 쓰기(Write)가 하드웨어적으로 즉각 차단**됩니다.
- **$\text{WD}_k$ (Write Disable for Key $k$, 비트 $2k+1$)**:
  - $\text{WD}_k = 1$이면 해당 키가 할당된 메모리에 대한 **쓰기(Write)가 차단**되며, 읽기(Read)는 정상 허용됩니다.

### 2.3 비특권 명령어 `WRPKRU`
`PKRU` 레지스터는 커널 모드로 진입할 필요 없이 사용자 공간에서 직접 실행 가능한 **`WRPKRU` (Opcode: `0F 01 EF`)** 명령어에 의해 갱신됩니다:
- 레지스터 변경 소요 시간: 단 **1~2 CPU 사이클 (약 0.5ns)**.
- `mprotect(2)` 시스템 호출 대비 약 **$2,000\times \sim 10,000\times$ 속도 향상**.
- 페이지 테이블을 변경하지 않으므로 **TLB 무효화(Shootdown)가 전혀 불필요**합니다.

---

## 3. 리눅스 커널 내부 구현 (`arch/x86/mm/pkeys.c`)

### 3.1 시스템 호출 동작 원리

1. **`sys_pkey_alloc(unsigned long flags, unsigned long init_val)`**:
   - `mm->context.pkey_allocation_map` 비트마스크를 확인하여 미사용 중인 키(1~15)를 탐색합니다.
   - 키 0은 시스템 기본 키로 항상 예약되어 있습니다.
   - 가용 키가 없으면 `-ENOSPC` (`-28`)를 반환합니다.
   - 호출 스레드의 `PKRU` 레지스터에 `init_val`을 반영합니다.

2. **`sys_pkey_free(int pkey)`**:
   - 지정된 키의 할당 비트를 초기화하여 풀로 환원합니다.
   - 키 0이거나 유효하지 않은 키는 `-EINVAL` (`-22`)을 반환합니다.

3. **`sys_pkey_mprotect(unsigned long start, size_t len, unsigned long prot, int pkey)`**:
   - 해당 `pkey`가 현재 `mm`에 적법하게 할당되었는지 검증합니다.
   - 대상 가상 메모리 영역의 VMA 플래그(`vm_flags`)에 키를 설정하고, 하위 PTE 워크를 통해 각 엔트리의 비트 62:59를 `pkey`로 갱신합니다.

### 3.2 하드웨어 페이지 폴트 `#PF` 및 시그널 전달 메커니즘
CPU가 메모리에 접근할 때 MMU는 다음 순서로 권한을 평가합니다:
1. 대상 가상 주소의 PTE에서 `pkey`를 추출합니다.
2. 현재 실행 중인 코어의 `PKRU` 레지스터에서 비트 $2 \cdot \text{pkey}$ 및 $2 \cdot \text{pkey} + 1$을 읽습니다.
3. 위반이 감지되면 하드웨어는 페이지 폴트 예외(`#PF`)를 발생시키며, 폴트 에러 코드의 **비트 5 (`PF_PK`)**를 1로 세팅합니다.
4. 리눅스 커널의 페이지 폴트 핸들러(`do_user_addr_fault()`)는 `PF_PK` 비트를 확인하여 이 오류가 단순 접근 권한 위반이 아닌 **보호 키 위반**임을 인식합니다.
5. 커널은 프로세스에 `SIGSEGV` 시그널을 전송하며, `siginfo_t` 구조체의 `si_code`를 **`SEGV_PKUERR`**로 지정하고 `si_pkey` 필드에 위반된 보호 키 번호를 채워 넣습니다.

---

## 4. 스레드 로컬 권한 분리와 컨텍스트 스위칭

`PKRU` 레지스터는 각 하드웨어 코어의 독립된 레지스터이므로, **동일한 주소 공간(`mm_struct`)을 공유하는 멀티스레드 프로세스라 할지라도 스레드마다 서로 다른 `PKRU` 값을 가질 수 있습니다**:

```
[ Thread 1 (Crypto Worker) ]          [ Thread 2 (Web Server Worker) ]
  Shared Address Space (mm)             Shared Address Space (mm)
  PKRU = 0x00000000                     PKRU = 0x00000004 (Key 1 AD=1)
  - Key 1 (Vault): Full RW Allowed       - Key 1 (Vault): Access DENIED (#PF!)
```

### 4.1 XSAVE와 문맥 교환 (`arch/x86/kernel/fpu/xstate.c`)
- 리눅스 스케줄러가 스레드 A에서 스레드 B로 문맥을 교환할 때, `PKRU` 레지스터는 확장 프로세서 상태(Extended State, XSAVE)의 일부로 저장(`XSAVE` / `XSAVEOPT`)되고 복원(`XRSTOR`)됩니다.
- 따라서 커널은 별도의 오버헤드 없이 각 스레드의 독립된 권한 도메인을 완벽하게 보존합니다.

---

## 5. 성능 및 비용 수학적 모델

보호 도메인 전환 횟수를 $N_C$, 도메인 보호 메모리 접근 횟수를 $N_A$라고 할 때:

### 5.1 전통적 `mprotect(2)` 총 비용
$$\text{Cost}_{\text{mprotect}} = N_C \cdot \left( T_{\text{syscall}} + T_{\text{lock}} + T_{\text{PTE\_walk}} + T_{\text{TLB\_shootdown}} \cdot N_{\text{cores}} \right) + N_A \cdot T_{\text{access}}$$
- 여기서 $T_{\text{mprotect}} \approx 2,000 \sim 5,000\text{ns}$ 이며, 코어 수 $N_{\text{cores}}$가 증가할수록 선형으로 증가합니다.

### 5.2 Intel MPK / PKRU 무장벽 총 비용
$$\text{Cost}_{\text{MPK}} = N_C \cdot T_{\text{WRPKRU}} + N_A \cdot T_{\text{access}}$$
- 여기서 $T_{\text{WRPKRU}} \approx 0.5 \sim 1\text{ns}$ (단 1~2 사이클)이며, 코어 수와 완전히 무관합니다 ($O(1)$).
- 따라서 도메인 전환이 빈번한 엔터프라이즈 워크로드에서 성능 저하를 사실상 0으로 수렴시킵니다.
