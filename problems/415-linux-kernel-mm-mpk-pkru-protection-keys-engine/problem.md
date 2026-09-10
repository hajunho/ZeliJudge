# 문제 415: Linux 커널 가상 메모리 및 하드웨어 아키텍처 Intel MPK/PKRU 메모리 보호 키 엔진 및 제로-TLB 권한 격리 시뮬레이터

## 문제 설명

현대 엔터프라이즈 소프트웨어(웹 브라우저 샌드박스, OpenSSL 암호화 키 볼트, SQLite 인메모리 엔진, WebAssembly 런타임)에서 프로세스 내부의 특정 메모리 영역을 악성 코드나 취약점(e.g., Buffer Overflow, Use-After-Free)으로부터 보호하는 것은 가장 중요한 보안 과제입니다.

전통적인 리눅스 환경에서 메모리 접근 권한을 동적으로 제어하기 위해 **`mprotect(2)`** 시스템 호출을 사용해 왔습니다. 그러나 `mprotect(2)`는 다음과 같은 심각한 성능 병목을 안고 있습니다:
1. **커널 모드 전환 및 락 경합**: 시스템 호출 트랩(`syscall`) 발생 및 프로세스의 가상 메모리 락인 `mmap_lock` (또는 Per-VMA 락)을 쓰기 모드로 획득해야 합니다.
2. **페이지 테이블 트리(PTE) 순회 및 분할**: 대상 가상 메모리 주소 범위 전체의 페이지 테이블 엔트리(PTE)를 일일이 순회하며 읽기/쓰기 비트(`_PAGE_RW`)를 수정해야 합니다.
3. **멀티코어 TLB 슛다운(TLB Shootdown) IPI 폭풍**: 수정된 PTE 권한을 다른 CPU 코어에 반영하기 위해 프로세서 간 인터럽트(IPI)를 발송하여 모든 코어의 하드웨어 TLB를 강제로 플러시(`flush_tlb_mm_range()`)해야 합니다.
4. **극심한 지연 시간**: 단 한 번의 `mprotect(2)` 호출에 **수 마이크로초(1~5µs, 수천 CPU 사이클)**가 소모되어, 고빈도로 메모리 영역을 잠그고 해제하는 실시간 샌드박싱에 적용할 수 없습니다.

이 문제를 근본적으로 해결하기 위해 인텔 Skylake 서버 CPU부터 하드웨어적으로 도입되고, 리눅스 커널 4.9+에 채택된 혁신적인 가상 메모리 서브시스템이 바로 **인텔 MPK (Memory Protection Keys for Userspace, PKU / PKRU, `arch/x86/mm/pkeys.c`, `CONFIG_X86_INTEL_MEMORY_PROTECTION_KEYS`)**입니다.

---

### Intel MPK / PKRU 핵심 아키텍처 및 동작 메커니즘

1. **PTE 상위 4비트와 보호 키 (Protection Key 0~15)**:
   - x86-64 4단계/5단계 페이징 구조에서 각 4KB 페이지 테이블 엔트리(PTE)의 비트 **62:59**에 4비트 크기의 보호 키(Protection Key, `pkey`: 0 ~ 15)를 태깅합니다.
   - 키 0은 기본 사용자 공간 메모리에 예약되어 있으며, 사용자 프로세스는 키 1부터 15까지 최대 15개의 독립된 보호 키를 동적으로 할당받을 수 있습니다.

2. **코어별 32비트 `PKRU` 레지스터**:
   - 각 CPU 논리 코어는 32비트 크기의 `PKRU` (Protection Key Rights Userspace) 레지스터를 가집니다.
   - 16개의 각 키 $k \in [0, 15]$에 대해 2비트씩 할당되어 접근 권한을 독립적으로 제어합니다:
     - **비트 $2k$ (`AD`, Access Disable)**: 1로 설정 시 해당 키가 태그된 모든 페이지에 대해 **읽기와 쓰기를 모두 차단**합니다.
     - **비트 $2k+1$ (`WD`, Write Disable)**: 1로 설정 시 해당 키가 태그된 페이지에 대해 **쓰기만 차단하고 읽기는 허용**합니다.

3. **유저스페이스 `WRPKRU` 명령어 (Zero-Syscall, Zero-TLB, 1-Cycle)**:
   - 권한을 변경할 때 커널을 호출하거나 PTE를 수정할 필요가 전혀 없습니다!
   - 사용자 공간에서 비특권 명령어인 **`WRPKRU` (Write PKRU)**를 직접 실행하여 단 **1~2 CPU 사이클** 만에 레지스터 값을 즉시 교체합니다.
   - 페이지 테이블을 건드리지 않으므로 **TLB 슛다운 IPI가 완전히 0회**이며, 멀티코어 간섭 없이 **스레드 로컬(Thread-Local)**하게 독립적인 권한 도메인을 운영할 수 있습니다.

4. **2단계 권한 검증 및 하드웨어 페이지 폴트 (`SEGV_PKUERR`)**:
   - CPU가 가상 주소에 접근할 때 하드웨어 MMU는 2단계를 평가합니다:
     1. **VMA 계층 권한 (`prot`)**: 대상 VMA가 쓰기를 허용하지 않는 읽기 전용(`prot="r"`)인 경우, PKRU 권한과 무관하게 VMA 레벨 오류(`SEGV_ACCERR`)가 발생합니다.
     2. **하드웨어 PKRU 레지스터**: VMA의 `pkey`에 대해 현재 스레드의 `PKRU`에서 `AD` 비트가 1이거나, 쓰기 요청 시 `WD` 비트가 1이면 즉시 하드웨어 페이지 폴트(`#PF`, Error Code Bit 5 `PF_PK` 세트)를 발생시키고 커널은 프로세스에 `SIGSEGV` (`si_code = SEGV_PKUERR`, `si_pkey = pkey`)를 전달합니다.

5. **시스템 호출 인터페이스**:
   - `pkey_alloc(flags, init_val)`: 사용 가능한 키(1~15)를 할당하고 호출 스레드의 PKRU 초기 비트를 설정합니다. 가용 키 고갈 시 `-ENOSPC` (`-28`)를 반환합니다.
   - `pkey_free(pkey)`: 할당된 키를 해제하고 재사용 가능하도록 환원합니다. 잘못된 키는 `-EINVAL` (`-22`)을 반환합니다.
   - `pkey_mprotect(addr, size, prot, pkey)`: 지정된 메모리 주소 범위의 VMA 및 PTE에 해당 `pkey`를 결합(Binding)합니다.

여러분은 인텔 MPK / PKRU의 16개 보호 키 관리, 유저스페이스 `WRPKRU` 1사이클 도메인 전환, TLB 슛다운 회피 회계, 2단계 VMA/PKRU 하드웨어 권한 판정 및 `SEGV_PKUERR` 시그널 디스패치 엔진을 완벽하게 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                  Intel MPK / PKRU Hardware & Linux Kernel Architecture                           |
+==================================================================================================+

 [ Page Table Entry (PTE) ]
  63 62       59 58                                                       2 1 0
 +--+-----------+--------------------------------------------------------+-+-+-+
 |NX| pkey (4b) | Physical Page Base Address (PFN)                       |U|W|P|
 +--+-----------+--------------------------------------------------------+-+-+-+
          |
          | Extracts pkey (0 ~ 15)
          v
 +-------------------------------------------------------------------------------------------------+
 | CPU Hardware MMU (Per-Thread PKRU Register Evaluation)                                          |
 |                                                                                                 |
 | PKRU Register (32-bit):                                                                         |
 |  Key 15  ...  Key 2       Key 1       Key 0 (Default)                                           |
 | +-------+   +-------+   +-------+   +-------+                                                   |
 | |WD |AD |...|WD |AD |...|WD |AD |...|WD |AD |                                                   |
 | +-------+   +-------+   +-------+   +-------+                                                   |
 |                                                                                                 |
 | 1. Check AD (Bit 2*pkey):                                                                       |
 |    - If AD == 1 ===> TRAP #PF (Bit 5 PF_PK set!) -> SIGSEGV (SEGV_PKUERR, si_pkey)              |
 |                                                                                                 |
 | 2. Check WD (Bit 2*pkey + 1) on WRITE access:                                                   |
 |    - If WD == 1 ===> TRAP #PF (Bit 5 PF_PK set!) -> SIGSEGV (SEGV_PKUERR, si_pkey)              |
 |                                                                                                 |
 | 3. Otherwise: PASS (Access Granted in 0ns!)                                                     |
 +-------------------------------------------------------------------------------------------------+
          ^
          | WRPKRU (Non-privileged, 1-2 CPU cycles, ZERO syscall, ZERO TLB shootdown!)
 +-------------------------------------------------------------------------------------------------+
 | User-Space Security Application (OpenSSL Vault / Chrome V8 Sandbox)                             |
 |                                                                                                 |
 |  [ Step 1: pkey_alloc() -> allocate pkey 1 ]                                                    |
 |  [ Step 2: pkey_mprotect(vault_addr, size, PROT_READ|PROT_WRITE, pkey=1) ]                      |
 |  [ Step 3: WRPKRU(disable_access for pkey 1) -> Vault locked! ]                                 |
 |  [ Step 4: Normal worker execution (attempts to tamper vault => intercepted!) ]                 |
 |  [ Step 5: Critical crypto section: WRPKRU(unlock) -> Decrypt -> WRPKRU(relock) ]               |
 +-------------------------------------------------------------------------------------------------+
```

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "num_cpus": 4,
    "page_size": 4096,
    "default_init_pkru": 0
  },
  "trace": [
    {"time": 0, "type": "CREATE_THREAD", "thread_id": 1, "cpu_id": 0},
    {"time": 1, "type": "MMAP", "start": 268435456, "size": 8192, "prot": "rw", "pkey": 0},
    {"time": 2, "type": "PKEY_ALLOC", "thread_id": 1, "flags": 0, "init_val": 0},
    {"time": 3, "type": "PKEY_MPROTECT", "thread_id": 1, "addr": 268435456, "size": 8192, "prot": "rw", "pkey": 1},
    {"time": 4, "type": "SET_RIGHTS", "thread_id": 1, "pkey": 1, "disable_access": false, "disable_write": true},
    {"time": 5, "type": "MEM_ACCESS", "thread_id": 1, "addr": 268435456, "access_type": "WRITE"}
  ]
}
```

- `config.num_cpus`: 시뮬레이션할 시스템 논리 코어 수.
- `config.page_size`: 기본 페이지 크기 (기본값 4096).
- `config.default_init_pkru`: 스레드 생성 시 기본 PKRU 레지스터 값 (기본값 0).
- `trace`: 시간 순서대로 실행되는 이벤트 리스트:
  - `CREATE_THREAD`: `{"time": t, "type": "CREATE_THREAD", "thread_id": tid, "cpu_id": c, "initial_pkru": ...}`
  - `MMAP`: `{"time": t, "type": "MMAP", "start": addr, "size": s, "prot": "rw", "pkey": 0}`
  - `PKEY_ALLOC`: `{"time": t, "type": "PKEY_ALLOC", "thread_id": tid, "flags": 0, "init_val": 0}`
  - `PKEY_FREE`: `{"time": t, "type": "PKEY_FREE", "thread_id": tid, "pkey": k}`
  - `PKEY_MPROTECT`: `{"time": t, "type": "PKEY_MPROTECT", "thread_id": tid, "addr": a, "size": s, "prot": "rw", "pkey": k}`
  - `WRPKRU`: `{"time": t, "type": "WRPKRU", "thread_id": tid, "new_pkru": val}`
  - `SET_RIGHTS`: `{"time": t, "type": "SET_RIGHTS", "thread_id": tid, "pkey": k, "disable_access": bool, "disable_write": bool}`
  - `MEM_ACCESS`: `{"time": t, "type": "MEM_ACCESS", "thread_id": tid, "addr": a, "access_type": "READ" | "WRITE"}`

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다 (compact JSON, `ensure_ascii=False`):

```json
{
  "summary": {
    "total_accesses": 1,
    "successful_accesses": 0,
    "pkru_violations": 1,
    "vma_permission_faults": 0,
    "wrpkru_count": 1,
    "tlb_shootdowns_avoided": 1,
    "pkeys_allocated_count": 1
  },
  "allocated_pkeys": [0, 1],
  "thread_states": {
    "1": {
      "thread_id": 1,
      "cpu_id": 0,
      "pkru": "0x00000008"
    }
  },
  "access_logs": [
    {
      "time": 5,
      "thread_id": 1,
      "addr": 268435456,
      "access_type": "WRITE",
      "status": "SEGV_PKUERR",
      "fault_reason": "PKRU_WRITE_DISABLE",
      "pkey": 1,
      "si_code": "SEGV_PKUERR",
      "si_pkey": 1
    }
  ],
  "event_logs": [ ... ]
}
```
