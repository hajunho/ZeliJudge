# Linux Kernel KVM x86 중첩 가상화(Nested VMX) 및 VMCS Shadowing 에뮬레이션 엔진

## 문제 설명

현대 엔터프라이즈 클라우드 및 하이퍼스케일 가상화 환경에서 **중첩 가상화(Nested Virtualization)**는 클라우드 인스턴스(L1 게스트 하이퍼바이저) 내부에서 다시 경량 가상 머신이나 컨테이너 격리 샌드박스(L2 게스트)를 고성능으로 구동하기 위한 핵심 기반 기술입니다. 인텔 x86 아키텍처의 하드웨어 가상화 지원(Intel VT-x)에서 물리 CPU는 본질적으로 단일 레벨의 가상화 제어 구조체(VMCS: Virtual Machine Control Structure)만을 하드웨어 레벨에서 직접 인식하므로, 리눅스 KVM 커널(`arch/x86/kvm/vmx/nested.c`)은 **L0 (베어메탈 KVM 하이퍼바이저)**, **L1 (게스트 하이퍼바이저)**, **L2 (중첩 게스트 VM)** 간의 3계층 상태 전이와 하드웨어 트랩을 정밀하게 중재해야 합니다.

과거 소프트웨어 에뮬레이션 방식에서는 L1이 L2를 제어하기 위해 실행하는 모든 `VMREAD`, `VMWRITE`, `VMPTRLD` 명령이 물리 CPU에서 L0로의 고비용 하드웨어 VM-Exit(수천 CPU 사이클 소요)을 유발하여 치명적인 성능 병목을 초래했습니다. 이를 해결하기 위해 최신 CPU는 **VMCS Shadowing (`SECONDARY_EXEC_ENABLE_SHADOW_VMCS`)** 기능을 도입하였습니다. VMCS Shadowing 활성화 시 L0는 L1에 일반 VMCS 대신 **섀도 VMCS(Shadow VMCS)**를 제공하고, **VMREAD/VMWRITE 비트맵**을 통해 하이퍼바이저 개입이 불필요한 비트 필드는 하드웨어 레벨에서 0 VM-Exit(나노초 단위 메모리 액세스)으로 통과시키며, L0의 보안 및 격리 정책상 검증이 필수적인 제어 필드만을 선택적으로 L0로 트랩합니다.

본 과제에서는 리눅스 커널 KVM의 중첩 VMX 서브시스템(`nested.c`, `vmcs12.h`)의 동작 원리를 정밀하게 수학적/시스템적으로 모델링한 **Nested VMX & VMCS Shadowing 에뮬레이션 엔진**을 구축합니다.

---

## 시스템 아키텍처 및 계층 다이어그램

```
+-------------------------------------------------------------------------+
|                  L0 Bare-Metal Hypervisor (Linux KVM)                   |
|  - Physical CPU Hardware VT-x Control                                   |
|  - vmcs01: Hardware VMCS configured by L0 to run L1                     |
|  - vmcs02: Merged Hardware VMCS constructed by L0 to run L2 directly    |
+------------------------------------+------------------------------------+
                                     |
                       Hardware VMCS | VMCS Shadowing Bitmaps
                       (vmcs01/02)   | (VMREAD / VMWRITE Bitmaps)
                                     v
+-------------------------------------------------------------------------+
|                       L1 Guest Hypervisor (e.g. KVM)                    |
|  - vmcs12: Software VMCS page allocated in L1 GPA space                 |
|  - Executes VMPTRLD, VMREAD, VMWRITE, VMLAUNCH, VMRESUME                |
|  - Intercepts L2 Exits if reflected by L0                               |
+------------------------------------+------------------------------------+
                                     |
                          vmentry    | vmexit (Reflected or L0-handled)
                                     v
+-------------------------------------------------------------------------+
|                         L2 Nested Guest (VM/Workload)                   |
|  - Runs directly on CPU hardware under vmcs02 controls                  |
|  - Events: CPUID, I/O, Page Fault, CR3 Write, EPT Violation, Interrupts |
+-------------------------------------------------------------------------+
```

---

## 핵심 요구사항 및 동작 규칙

### 1. VMCS Shadowing 메커니즘
- `shadow_vmcs_enabled`가 `true`인 경우:
  - `VMREAD` 대상 필드가 `vmread_bitmap`에 등록되어 있지 않으면 하드웨어 섀도 메모리 직접 접근으로 처리되어 VM-Exit가 발생하지 않습니다 (`shadow_bypassed_reads` 1 증가, 사이클 소모: `t_shadow_access`).
  - 등록되어 있다면 L0로 트랩되어 VM-Exit가 발생합니다 (`l0_vm_exits_total` 1 증가, `l0_vm_exits_shadow_trapped` 1 증가, 사이클 소모: `t_vmexit_l0`).
  - `VMWRITE` 대상 필드가 `vmwrite_bitmap`에 등록되어 있지 않으면 하드웨어 섀도 직접 기록으로 처리됩니다 (`shadow_bypassed_writes` 1 증가, 사이클 소모: `t_shadow_access`).
  - 등록되어 있다면 L0로 트랩되어 VM-Exit가 발생합니다 (`l0_vm_exits_total` 1 증가, `l0_vm_exits_shadow_trapped` 1 증가, 사이클 소모: `t_vmexit_l0`).
  - `VMPTRLD`는 `shadow_vmcs_enabled` 시 `t_shadow_access` 소모, 비활성화 시 `t_vmexit_l0` 소모 및 `l0_vm_exits_shadow_trapped` 1 증가.
- `shadow_vmcs_enabled`가 `false`인 경우:
  - 모든 `VMREAD`, `VMWRITE`, `VMPTRLD` 연산이 예외 없이 L0 VM-Exit를 유발합니다 (`t_vmexit_l0` 소모, `l0_vm_exits_total` 1 증가, `l0_vm_exits_shadow_trapped` 1 증가).

### 2. VMLAUNCH / VMRESUME 일관성 검증 (Consistency Checks)
L1이 L2 진입 명령(`VMLAUNCH` 또는 `VMRESUME`)을 내리면 무조건 물리 CPU에서 L0로 트랩됩니다 (`l0_vm_exits_total` 1 증가, 사이클 소모: `t_vmexit_l0`). L0는 `vmcs12`의 무결성을 검증합니다:
1. **활성 포인터 검증**: 현재 활성화된 `current_vmcs12_ptr`이 유효해야 합니다 (`None`이 아니어야 함).
2. **제어 레지스터 Fixed Bits 검증**:
   - $CR0_{\text{guest}}$는 $CR0_{\text{fixed0}}$ 비트가 모두 1이어야 하며($CR0 \& fixed0 == fixed0$), $CR0_{\text{fixed1}}$에서 0인 비트가 1이어서는 안 됩니다($CR0 \& (\sim fixed1 \& \text{0xFFFFFFFF}) == 0$).
   - $CR4_{\text{guest}}$ 역시 $CR4_{\text{fixed0}}$ 및 $CR4_{\text{fixed1}}$ 제약을 동일하게 만족해야 합니다.
3. **호스트 주소 64비트 정규(Canonical) 주소 검증**:
   - `HOST_RIP` 및 `HOST_RSP`는 64비트 정규 주소여야 합니다 (비트 47의 부호 비트가 비트 48~63으로 동일하게 확장되어야 함. 즉 비트 47이 1이면 상위 16비트가 `0xFFFF`, 0이면 `0x0000`).
- **검증 실패 시**:
  - `consistency_checks_failed` 1 증가, `vmcs12["VM_INSTRUCTION_ERROR"]`에 실패 사유 기록, 실행 계층은 L1에 유지됩니다.
- **검증 성공 시**:
  - `consistency_checks_passed` 1 증가, `vm_entries_to_l2` 1 증가, 사이클 소모: `t_vmentry`.
  - L0는 하드웨어 제어 구조체 `vmcs02`를 비트 단위 논리합(Bitwise OR)으로 병합 생성합니다:
    $$\text{PIN}_{02} = \text{PIN}_{01} \lor \text{PIN}_{12}$$
    $$\text{CPU}_{02} = \text{CPU}_{01} \lor \text{CPU}_{12}$$
    $$\text{SEC}_{02} = \text{SEC}_{01} \lor \text{SEC}_{12}$$
    $$\text{EXC}_{02} = \text{EXC}_{01} \lor \text{EXC}_{12}$$
  - CPU 상태가 L2로 전환됩니다 (`active_level = "L2"`). L2 레지스터(`rip`, `rsp`)는 `vmcs12`의 `GUEST_RIP`, `GUEST_RSP` 값으로 갱신됩니다.

### 3. L2 실행 및 탈출 라우팅 (Exit Reflection vs L0 Handling)
`L2_EXECUTE` 명령은 L2 게스트를 지정된 `cycles`만큼 실행합니다 (`total_cycles += cycles`). 실행 중 `event`가 발생할 경우 하드웨어 VM-Exit가 발생하여 탈출 라우팅 정책이 평가됩니다:
1. **CPUID (`CPUID`)**:
   - 무조건 L1으로 리플렉션(Reflected Exit)됩니다 (Exit Reason = 10).
2. **I/O 포트 명령 (`IO_INSTRUCTION`)**:
   - $CPU_{12}$ 비트 24(`CPU_BASED_UNCOND_IO_EXITING`, `0x01000000`)가 1이면 $\to$ L1 리플렉션 (Exit Reason = 30, Qualification = `port`).
   - 그렇지 않고 $CPU_{01}$ 비트 24가 1이면 $\to$ L0 내부 처리 (Exit Reason = 30).
3. **CR3 레지스터 변경 (`CR3_WRITE`)**:
   - $CPU_{12}$ 비트 15(`CPU_BASED_CR3_STORE_EXITING`, `0x00008000`)가 1이면 $\to$ L1 리플렉션 (Exit Reason = 28, Qualification = `0x3`).
   - 그렇지 않고 $CPU_{01}$ 비트 15가 1이면 $\to$ L0 내부 처리.
   - `vmcs12["GUEST_CR3"]`는 신규 CR3 값으로 갱신됩니다.
4. **페이지 폴트 (`PAGE_FAULT`)**:
   - $EXC_{12}$ 비트 14(`1 << 14`, `0x00004000`)가 1이고, `(error_code & PAGE_FAULT_ERROR_CODE_MASK) == PAGE_FAULT_ERROR_CODE_MATCH` 조건을 만족하면 $\to$ L1 리플렉션 (Exit Reason = 0, Qualification = `cr2`).
   - 불일치 시 $\to$ L0 내부 처리 (섀도 페이징/호스트 요구 페이징).
5. **외부 인터럽트 (`EXTERNAL_INTERRUPT`)**:
   - $PIN_{01}$ 비트 0(`PIN_BASED_EXT_INTR_MASK`, `0x00000001`)이 1이면 $\to$ 물리 CPU 하드웨어 인터럽트로 간주하여 **L0가 가로채어 내부 처리**합니다.
   - $PIN_{01}$이 0이고 $PIN_{12}$ 비트 0이 1이면 $\to$ L1 리플렉션 (Exit Reason = 1, Qualification = `irq`).
6. **중첩 EPT 위반 (`EPT_VIOLATION`)**:
   - $SEC_{12}$ 비트 1(`SECONDARY_EXEC_ENABLE_EPT`, `0x00000002`)이 1이고, `is_l1_violation`이 `true`이면 $\to$ L1 리플렉션 (Exit Reason = 48, Qualification = `gpa`).
   - 불일치 시 $\to$ L0 내부 처리 (L0 호스트 EPT 프레임 매핑).

- **L1으로 리플렉션(Reflected Exit)되는 경우**:
  - `l0_vm_exits_total` 1 증가, `l1_reflected_vm_exits` 1 증가.
  - 소모 사이클: `t_vmexit_l0 + t_reflect_overhead`.
  - `vmcs12` 상태 갱신: `GUEST_RIP = l2.rip`, `GUEST_RSP = l2.rsp`, `VM_EXIT_REASON = exit_reason`, `EXIT_QUALIFICATION = exit_qual`.
  - L1 호스트 문맥 복원: `l1.rip = vmcs12["HOST_RIP"]`, `l1.rsp = vmcs12["HOST_RSP"]`.
  - 활성 계층 전환: `active_level = "L1"`.
- **L0 내부에서 처리(Unreflected / L0 Handled)되는 경우**:
  - `l0_vm_exits_total` 1 증가, `l0_vm_exits_unreflected_l0` 1 증가.
  - 소모 사이클: `t_vmexit_l0 + t_l0_handle`.
  - L1은 탈출 사실을 전혀 인지하지 못하며, L0 처리 완료 후 L2가 즉각 무중단 재개됩니다 (`active_level = "L2"` 유지).

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "t_vmexit_l0": 1000,
    "t_vmentry": 600,
    "t_shadow_access": 10,
    "t_reflect_overhead": 300,
    "t_l0_handle": 500,
    "shadow_vmcs_enabled": true,
    "vmread_bitmap": ["GUEST_RIP", "VM_EXIT_REASON"],
    "vmwrite_bitmap": ["CPU_BASED_VM_EXEC_CONTROL"],
    "cr0_fixed0": 2147483649,
    "cr0_fixed1": 4294967295,
    "cr4_fixed0": 8192,
    "cr4_fixed1": 4294967295,
    "vmcs01_pin": 1,
    "vmcs01_cpu": 0,
    "vmcs01_sec": 2,
    "vmcs01_exc": 0,
    "l1_initial_regs": {"rip": 4194304, "rsp": 2147483632, "rax": 0},
    "l2_initial_regs": {"rip": 8388608, "rsp": 1073741808, "rax": 0}
  },
  "commands": [
    {"op": "VMPTRLD", "gpa": 65536},
    {"op": "VMWRITE", "field": "GUEST_RIP", "value": 8388608},
    {"op": "VMWRITE", "field": "GUEST_RSP", "value": 1073741808},
    {"op": "VMWRITE", "field": "HOST_RIP", "value": 4200000},
    {"op": "VMWRITE", "field": "HOST_RSP", "value": 2147483632},
    {"op": "VMWRITE", "field": "GUEST_CR0", "value": 2147483649},
    {"op": "VMWRITE", "field": "GUEST_CR4", "value": 8192},
    {"op": "VMWRITE", "field": "CPU_BASED_VM_EXEC_CONTROL", "value": 16777216},
    {"op": "VMLAUNCH"},
    {"op": "L2_EXECUTE", "cycles": 5000, "event": {"type": "CPUID", "rip_advance": 2}}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없는 압축 JSON(`separators=(',', ':')`, `ensure_ascii=False`)을 출력합니다:
```json
{
  "final_level": "L1",
  "l1_state": {"rip": 4200000, "rsp": 2147483632, "rax": 0},
  "l2_state": {"rip": 8388610, "rsp": 1073741808, "rax": 0},
  "vmcs12_state": {
    "GUEST_RIP": 8388610,
    "GUEST_RSP": 1073741808,
    "VM_EXIT_REASON": 10,
    "EXIT_QUALIFICATION": 0,
    "VM_INSTRUCTION_ERROR": null
  },
  "vmcs02_merged_controls": {
    "PIN_BASED_VM_EXEC_CONTROL": 1,
    "CPU_BASED_VM_EXEC_CONTROL": 16777216,
    "SECONDARY_VM_EXEC_CONTROL": 2,
    "EXCEPTION_BITMAP": 0
  },
  "metrics": {
    "total_cycles": 11360,
    "l0_vm_exits_total": 3,
    "l0_vm_exits_shadow_trapped": 1,
    "l0_vm_exits_unreflected_l0": 0,
    "l1_reflected_vm_exits": 1,
    "shadow_bypassed_reads": 0,
    "shadow_bypassed_writes": 6,
    "vm_entries_to_l2": 1,
    "consistency_checks_passed": 1,
    "consistency_checks_failed": 0
  },
  "event_log_count": 10
}
```

---

## 제약 사항

- $1 \le \text{len}(commands) \le 100$
- 사이클 및 시간 파라미터는 $1 \le t \le 100,000$ 범위의 정수
- 메모리 주소 및 레지스터 값은 64비트 양의 정수 ($0 \le x < 2^{64}$)
- 부동소수점 오차가 없도록 모든 계산은 64비트 정수 연산으로 수행합니다.
