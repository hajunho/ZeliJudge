# 리눅스 커널 KVM x86 중첩 가상화(Nested VMX) 및 VMCS Shadowing 이론적 심층 분석

## 1. 개요 및 하드웨어 배경 (Intel VT-x Architecture)

인텔 x86 아키텍처의 하드웨어 지원 가상화(VT-x)는 CPU 동작 모드를 **VMX Root Operation (하이퍼바이저 실행 모드)**과 **VMX Non-Root Operation (게스트 OS 실행 모드)**으로 분리합니다. 게스트 실행 중 특권 명령(Privileged Instruction), 페이지 폴트, 외부 하드웨어 인터럽트, EPT 위반 등이 발생하면 CPU는 하드웨어 수준에서 **VM-Exit**를 유발하여 VMX Root 모드의 호스트 하이퍼바이저로 제어권을 넘기며, 하이퍼바이저는 작업을 처리한 후 **VM-Entry (`VMLAUNCH`/`VMRESUME`)**를 통해 게스트로 복귀합니다.

이 과정에서 CPU의 실행 제어 및 게스트/호스트 레지스터 상태를 보관하는 핵심 하드웨어 구조체가 바로 **VMCS (Virtual Machine Control Structure)**입니다. VMCS는 크게 6가지 논리적 영역으로 구성됩니다:
1. **Guest-state area**: VM-Exit 시 하드웨어가 자동 저장하고 VM-Entry 시 복원하는 게스트 레지스터(RIP, RSP, CR0, CR3, CR4, RFLAGS 등).
2. **Host-state area**: VM-Exit 시 로드되는 하이퍼바이저 레지스터(CR0, CR3, CR4, RIP, RSP, 세그먼트 레지스터 등).
3. **VM-execution control fields**: VM-Exit를 유발할 조건을 결정하는 비트마스크 필드들 (`PIN_BASED_VM_EXEC_CONTROL`, `CPU_BASED_VM_EXEC_CONTROL`, `SECONDARY_VM_EXEC_CONTROL`, `EXCEPTION_BITMAP` 등).
4. **VM-exit control fields**: VM-Exit 시 동작 제어(MSR 저장/로드, 64비트 호스트 모드 진입 등).
5. **VM-entry control fields**: VM-Entry 시 동작 제어(이벤트 주입, 인터럽트 억제 등).
6. **VM-exit information fields**: VM-Exit 발생 원인(`VM_EXIT_REASON`), 부가 정보(`EXIT_QUALIFICATION`, 게스트 선형 주소 등).

---

## 2. 중첩 가상화(Nested Virtualization)의 3계층 모델과 VMCS 3총사

중첩 가상화는 다음과 같은 3계층으로 구성됩니다:
- **L0 (Level 0)**: 물리 하드웨어 위에서 구동되는 최상위 베어메탈 하이퍼바이저 (Bare-Metal KVM).
- **L1 (Level 1)**: L0 위에서 게스트로서 실행되면서 자신만의 가상 머신을 호스팅하는 게스트 하이퍼바이저 (Nested KVM).
- **L2 (Level 2)**: L1 위에서 구동되는 중첩 게스트 VM.

```
       +------------------------------------+
       |          L0 (Host KVM)             |  <-- Runs in VMX Root
       +-----------------+------------------+
                         |
           vmentry (01)  |  vmexit (01)
                         v
       +-----------------+------------------+
       |          L1 (Guest KVM)            |  <-- Runs in VMX Non-Root (emulates VMX Root)
       +-----------------+------------------+
                         |
           vmentry (02)  |  vmexit (02) [traps to L0 first!]
                         v
       +-----------------+------------------+
       |          L2 (Nested Guest)         |  <-- Runs in VMX Non-Root
       +------------------------------------+
```

물리 CPU는 언제나 단 하나의 하드웨어 VMCS 포인터만을 가질 수 있습니다. 따라서 리눅스 커널 KVM(`arch/x86/kvm/vmx/nested.c`)은 세 종류의 VMCS를 정밀하게 관리합니다:
1. **`vmcs01`**: L0가 L1을 물리 CPU 위에서 직접 실행하기 위해 할당하고 유지하는 하드웨어 VMCS.
2. **`vmcs12`**: L1이 L2를 제어하기 위해 자신의 게스트 물리 메모리(GPA)에 소프트웨어적으로 할당한 구조체. L1은 자신이 물리 하이퍼바이저라고 생각하므로 `VMPTRLD`, `VMREAD`, `VMWRITE`를 사용하여 `vmcs12`를 다룹니다.
3. **`vmcs02`**: L0가 L2를 물리 CPU 위에서 직접 하드웨어 가속으로 구동하기 위해 `vmcs01`의 요구조건과 `vmcs12`의 요구조건을 병합(Merge)하여 물리 CPU에 로드하는 실제 하드웨어 VMCS.

---

## 3. 성능의 구원투수: VMCS Shadowing (`SECONDARY_EXEC_ENABLE_SHADOW_VMCS`)

### 3.1 VMCS Shadowing 이전의 치명적 오버헤드
L1이 L2를 실행하기 전 VMCS를 설정할 때, 수십~수백 개의 필드에 대해 `VMWRITE`를 수행합니다. VMCS Shadowing이 없던 1세대 가상화 하드웨어에서는 L1의 모든 `VMREAD`/`VMWRITE` 명령이 Non-Root 모드에서 무조건 하드웨어 VM-Exit를 유발하여 L0로 트랩되었습니다.
- 단 1회의 VM-Exit 비용: CPU 파이프라인 플러시, 레지스터 저장/복원 등 최소 1,000 ~ 1,500 CPU 사이클.
- L2 부팅 또는 콘텍스트 스위칭 1회당 수백 번의 `VMWRITE` $\to$ 수십만 사이클 낭비 발생!

### 3.2 VMCS Shadowing의 동작 원리
인텔은 Haswell 프로세서부터 `SECONDARY_EXEC_ENABLE_SHADOW_VMCS` 기능을 하드웨어에 내장하였습니다.
1. L0는 `vmcs01`의 `SECONDARY_VM_EXEC_CONTROL`에 비트 14(`ENABLE_SHADOW_VMCS`)를 활성화합니다.
2. L0는 `VMCS_LINK_POINTER` 필드에 L1의 `vmcs12`를 가리키는 섀도 VMCS 물리 주소를 지정합니다.
3. L0는 물리 메모리에 각각 4KB 크기(4096 비트)의 **VMREAD 비트맵**과 **VMWRITE 비트맵**을 생성합니다.
   - 특정 VMCS 필드 인코딩에 대응하는 비트가 **0**인 경우:
     물리 CPU 하드웨어는 VM-Exit를 발생시키지 않고, 섀도 VMCS 메모리 페이지에 직접 읽기/쓰기를 즉각 수행합니다 (수 나노초, 일반 캐시 메모리 액세스 속도).
   - 특정 필드 인코딩에 대응하는 비트가 **1**인 경우:
     물리 CPU는 L0로 VM-Exit를 발생시켜, L0 하이퍼바이저가 해당 필드의 유효성을 검증하거나 특수 정책을 적용할 수 있도록 허용합니다.

이를 통해 읽기/쓰기 빈도가 높은 게스트 상태 필드는 0 VM-Exit로 처리되고, 보안상 위험한 제어 필드만 선별적으로 L0가 트랩하여 중첩 가상화 성능을 비약적으로 향상시킵니다.

---

## 4. VM-Entry 일관성 검증 (Consistency Checks) 수리 모델

L1이 `VMLAUNCH` 또는 `VMRESUME`를 호출하면 물리 CPU는 무조건 L0로 VM-Exit를 발생시킵니다. L0의 `nested_vmx_run()` 함수는 물리 하드웨어의 결함을 방지하기 위해 엄격한 사전 검증을 수행합니다:

1. **Active VMCS 검증**:
   $$current\_vmcs12\_ptr \neq \text{NULL}$$
2. **CR0 / CR4 고정 비트(Fixed Bits) 검증**:
   인텔 CPU는 VMX 동작을 위해 제어 레지스터의 특정 비트가 반드시 1이거나 0이어야 함을 MSR(`IA32_VMX_CR0_FIXED0/1`, `IA32_VMX_CR4_FIXED0/1`)을 통해 강제합니다.
   $$CR0_{\text{guest}} \land CR0_{\text{fixed0}} = CR0_{\text{fixed0}}$$
   $$CR0_{\text{guest}} \land (\neg CR0_{\text{fixed1}}) = 0$$
   $$CR4_{\text{guest}} \land CR4_{\text{fixed0}} = CR4_{\text{fixed0}}$$
   $$CR4_{\text{guest}} \land (\neg CR4_{\text{fixed1}}) = 0$$
3. **호스트 주소 64비트 정규형(Canonical Form) 검증**:
   x86-64 아키텍처에서 가상 주소는 48비트(또는 57비트)를 사용하며, 최상위 비트(비트 47)는 비트 48부터 63까지 부호 확장(Sign Extension)되어야 합니다.
   $$\text{is\_canonical}(A) = \begin{cases} \text{True} & \text{if } ((A \gg 47) \& 1 = 1) \land ((A \gg 48) = \text{0xFFFF}) \\ \text{True} & \text{if } ((A \gg 47) \& 1 = 0) \land ((A \gg 48) = \text{0x0000}) \\ \text{False} & \text{otherwise} \end{cases}$$

검증을 통과하면 L0는 `vmcs02`의 제어 비트마스크를 논리합(OR) 합성합니다:
$$Control_{02} = Control_{01} \lor Control_{12}$$

---

## 5. VM-Exit 리플렉션(Exit Reflection) 라우팅 알고리즘

L2가 물리 CPU에서 실행되다가 하드웨어 트랩이 발생하면, CPU는 무조건 VMX Root의 **L0**로 먼저 탈출합니다. L0의 `nested_vmx_exit_reflected()` 함수는 이 탈출을 L1으로 넘겨주어야 할지(Reflected Exit), 아니면 L0가 조용히 처리하고 L2를 재개해야 할지(Unreflected Exit)를 판정합니다:

$$\text{Destination} = \begin{cases}
\text{Reflect to L1} & \text{if } \text{CPUID} \\
\text{Reflect to L1} & \text{if } \text{IO} \land (CPU_{12}[24] = 1) \\
\text{Reflect to L1} & \text{if } \text{CR3 Write} \land (CPU_{12}[15] = 1) \\
\text{Reflect to L1} & \text{if } \text{\#PF} \land (EXC_{12}[14] = 1) \land ((err \& mask) = match) \\
\text{Reflect to L1} & \text{if } \text{ExtIntr} \land (PIN_{01}[0] = 0) \land (PIN_{12}[0] = 1) \\
\text{Reflect to L1} & \text{if } \text{EPT Violation} \land (SEC_{12}[1] = 1) \land \text{is\_l1\_violation} \\
\text{Handle by L0} & \text{otherwise}
\end{cases}$$

- **L1 리플렉션 처리**:
  1. L0는 `vmcs12`의 `GUEST_RIP`, `GUEST_RSP`, `VM_EXIT_REASON`, `EXIT_QUALIFICATION`을 L2의 탈출 시점 값으로 채웁니다.
  2. L0는 vCPU 레지스터를 L1의 호스트 상태(`vmcs12.HOST_RIP`, `vmcs12.HOST_RSP`)로 설정합니다.
  3. 물리 CPU는 L1 게스트 하이퍼바이저의 VM-Exit 핸들러로 복귀합니다.
- **L0 내부 처리**:
  L0가 호스트 타이머 인터럽트나 호스트 EPT 매핑을 수행한 뒤, L1에 아무런 통보 없이 L2를 즉시 재실행합니다. L1 입장에서는 시간이 약간 흘렀을 뿐 L2가 끊김 없이 연속 실행된 것으로 관측됩니다.

---

## 6. 결론 및 실무적 의의

중첩 가상화와 VMCS Shadowing의 조합은 클라우드 네이티브 환경(AWS Nitro, GCP Compute Engine Nested Virtualization, Azure Nested VMs)에서 Kubernetes 가상 클러스터, Kata Containers, 안드로이드 에뮬레이터 등을 베어메탈에 필적하는 고속으로 운영할 수 있게 하는 리눅스 커널 하이퍼바이저 공학의 정수입니다.
