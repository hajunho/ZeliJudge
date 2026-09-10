# 문제 421: Linux 커널 기밀 컴퓨팅(Confidential Computing) AMD SEV-ES/SEV-SNP GHCB VMGEXIT 프로토콜 및 #VC 예외 에뮬레이션 엔진

## 문제 설명

현대 퍼블릭 클라우드(Azure Confidential VMs, AWS Nitro Enclaves, Google Cloud Confidential Space) 환경에서 가장 중요한 보안 패러다임은 **제로 트러스트(Zero-Trust) 기밀 컴퓨팅 (Confidential Computing)**입니다.
기존 가상화 모델에서는 하이퍼바이저(KVM/QEMU)와 호스트 OS가 가상 머신(게스트 OS)의 모든 물리 메모리와 CPU 레지스터를 직접 열람하고 수정할 수 있는 무소불위의 권한을 가졌습니다. 이로 인해 호스트 관리자 권한 탈취, 악성 하이퍼바이저 취약점, 또는 물리적 메모리 도청(Cold Boot Attack)이 발생하면 게스트의 기밀 데이터(암호화 키, 금융 데이터, AI 모델 가중치)가 완전히 노출되었습니다.

AMD는 이를 방지하기 위해 하드웨어 기반 메모리 암호화 기술인 **SEV (Secure Encrypted Virtualization)**를 발표했으나, 초기 SEV는 CPU 레지스터를 암호화하지 못해 VM-Exit 발생 시 레지스터 상태가 호스트로 유출되는 한계가 있었습니다.

이 문제를 종식시키기 위해 AMD EPYC 프로세서에 도입되고 리눅스 커널 5.10+ 및 5.15+에 탑재된 핵심 가상화 보안 서브시스템이 바로 **AMD SEV-ES (Encrypted State) 및 SEV-SNP (Secure Nested Paging)의 GHCB VMGEXIT 아키텍처 (`arch/x86/kernel/sev.c`, `arch/x86/kvm/svm/sev.c`, `arch/x86/include/asm/sev-common.h`, `CONFIG_AMD_MEM_ENCRYPT`)**입니다.

---

### GHCB 및 VMGEXIT 핵심 아키텍처 및 동작 메커니즘

SEV-ES/SNP 환경에서는 하이퍼바이저가 게스트의 레지스터 상태를 직접 읽을 수 없도록 하드웨어 암호화 VMSA(Virtual Machine Save Area)로 봉인합니다.
게스트가 하이퍼바이저의 에뮬레이션 지원이 필요한 특권 연산(CPUID 질의, MSR 읽기/쓰기, 포트 I/O, VirtIO DMA를 위한 메모리 공유 등)을 실행할 때, 하드웨어는 다음과 같은 프로토콜을 강제합니다:

1. **`#VC` 예외 (VMM Communication Exception, Vector 29)**:
   - 게스트 vCPU가 인터셉트 대상 명령어(`CPUID`, `RDMSR`, `WRMSR`, `IN`/`OUT`)를 실행하면, 하이퍼바이저로 즉시 탈출하는 대신 게스트 OS 내부에서 **`#VC` 예외**가 하드웨어적으로 발생합니다.
   - 이를 통해 게스트 OS가 하이퍼바이저에게 어떤 정보를 공개할지 스스로 통제(Sanitization)할 수 있는 주도권을 확보합니다.

2. **GHCB (Guest-Host Communication Block)**:
   - 게스트와 하이퍼바이저 간의 데이터 교환을 위해 사전에 합의된 4KB 크기의 공유 비암호화(Shared) 메모리 페이지입니다.
   - 게스트의 `#VC` 핸들러는 에뮬레이션에 필요한 최소한의 입력 파라미터만을 GHCB 필드에 기록하고, 해당 필드가 유효함을 나타내는 **`valid_bitmap`**을 비트 단위로 활성화합니다:
     - `SVM_VMGEXIT_CPUID (0x80000001)`: CPUID 기능 번호(RAX) 및 하위 기능(RCX) 전달.
     - `SVM_VMGEXIT_MSR (0x80000002)`: MSR 색인(RCX) 및 쓰기 데이터(RAX, RDX) 전달.
     - `SVM_VMGEXIT_IOIO (0x80000003)`: 포트 주소 및 입출력 바이트 전달.
     - `SVM_VMGEXIT_PSC (0x80000010)`: SEV-SNP 전용 Page State Change (Private $\leftrightarrow$ Shared 메모리 속성 변환).

3. **`VMGEXIT` 명령어 (Opcode: `0F 01 D7`)**:
   - GHCB 작성이 완료되면 게스트는 `VMGEXIT` 명령어를 명시적으로 실행하여 하이퍼바이저로 제어를 넘깁니다.
   - 하이퍼바이저는 GHCB의 `sw_exit_code`를 확인하여 요청된 연산을 안전하게 에뮬레이션하고, 결과값을 GHCB에 채운 후 `valid_bitmap`을 갱신하고 `VMRUN`을 실행합니다.

4. **게스트 측 검증 및 보안 종료 (`SECURITY_TERMINATION`)**:
   - 게스트 OS는 `VMGEXIT`에서 복귀한 직후, 하이퍼바이저가 작성한 GHCB 응답을 맹목적으로 신뢰하지 않습니다!
   - 하이퍼바이저가 요청하지 않은 임의의 레지스터를 변조하려 하거나 허용되지 않은 비트맵(`valid_bitmap` 무결성 위반)을 반환한 경우, 게스트는 즉시 **보안 종료 (`SECURITY_TERMINATION`)**를 선언하고 vCPU 실행을 중단하여 호스트의 악의적 코드 인젝션 공격을 원천 차단합니다.

여러분은 리눅스 커널 SEV-ES/SNP의 `#VC` 예외 발생, GHCB 포맷팅 및 `valid_bitmap` 제어, `VMGEXIT` 디스패치, CPUID/MSR/IOIO/PSC 에뮬레이션, 그리고 하이퍼바이저 위변조 탐지 보안 종료 엔진을 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                    AMD SEV-ES / SEV-SNP GHCB VMGEXIT Architecture                                |
+==================================================================================================+

   [ Confidential Guest VM (Encrypted VMSA) ]                [ Untrusted Host Hypervisor (KVM) ]
             |                                                               |
             | 1. Guest executes intercepted op (e.g. CPUID)                 |
             v                                                               |
    [ Hardware Traps #VC (Vector 29) ]                                       |
             |                                                               |
             | 2. Guest #VC Handler (arch/x86/kernel/sev.c)                  |
             |    - Copies ONLY required inputs into GHCB                    |
             |    - Sets valid_bitmap (e.g. RAX, RCX)                        |
             |    - Sets sw_exit_code = SVM_VMGEXIT_CPUID                    |
             v                                                               |
   +----------------------------------------------------+                    |
   | Shared GHCB Page (Guest-Host Communication Block)  |                    |
   |   valid_bitmap : [RAX|RCX]                         |                    |
   |   sw_exit_code : 0x80000001 (CPUID)                |                    |
   |   rax: 0x0, rcx: 0x0                               |                    |
   +----------------------------------------------------+                    |
             |                                                               |
             | 3. Guest executes VMGEXIT (0F 01 D7)                          |
             +-------------------------------------------------------------->| 4. KVM VM-Exit Handler
                                                                             |    - Reads GHCB
                                                                             |    - Emulates CPUID
                                                                             |    - Writes vendor "AuthenticAMD"
                                                                             |    - Sets valid_bitmap
                                                                             v
             |<--------------------------------------------------------------+ 5. KVM executes VMRUN
             |
             | 6. Guest Sanitizes Response:
             |    - Check valid_bitmap for corruption / injection?
             |        * CORRUPTED: ===> SECURITY_TERMINATION (Halt vCPU!)
             |        * OK       : ===> Copy results to Private Regs, Resume
             v
   [ Guest Continues Execution in Zero-Trust Isolation ]
```

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.

```json
{
  "config": {
    "guest_vcpus": 2,
    "snp_active": true
  },
  "trace": [
    {"time": 0, "type": "CREATE_VCPU", "vcpu_id": 0},
    {"time": 1, "type": "GUEST_EXEC_OP", "vcpu_id": 0, "op": "CPUID", "args": {"function": 0, "subfunction": 0}}
  ]
}
```

- `config.guest_vcpus`: 가상 머신 vCPU 수.
- `config.snp_active`: SEV-SNP 무결성 활성화 여부.
- `trace`: 시간 순서대로 실행되는 이벤트 리스트:
  - `CREATE_VCPU`: `{"time": t, "type": "CREATE_VCPU", "vcpu_id": vid}`
  - `GUEST_EXEC_OP`: `{"time": t, "type": "GUEST_EXEC_OP", "vcpu_id": vid, "op": "CPUID" | "MSR_READ" | "MSR_WRITE" | "IOIO_IN" | "IOIO_OUT" | "PAGE_STATE_CHANGE", "args": {...}}`

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다 (compact JSON, `ensure_ascii=False`):

```json
{
  "summary": {
    "total_vc_exceptions": 1,
    "total_vmgexits": 1,
    "successful_emulations": 1,
    "page_state_changes": 0,
    "security_terminations": 0,
    "emulations_by_type": {
      "CPUID": 1,
      "MSR": 0,
      "IOIO": 0,
      "PSC": 0
    }
  },
  "page_states": {},
  "vcpus": {
    "0": {
      "vcpu_id": 0,
      "state": "RUNNING",
      "regs": {
        "rax": 1,
        "rbx": 1752462657,
        "rcx": 1145913699,
        "rdx": 1769238117
      }
    }
  },
  "vmgexit_logs": [
    {
      "time": 1,
      "vcpu_id": 0,
      "op": "CPUID",
      "exit_code": "0x80000001",
      "status": "SUCCESS",
      "regs": { ... }
    }
  ],
  "event_logs": [ ... ]
}
```
