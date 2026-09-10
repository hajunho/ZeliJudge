# Linux 커널 가상화 및 하드웨어 보안: 컨피덴셜 컴퓨팅 AMD SEV-SNP & Intel TDX 원격 증명 및 RMP 엔진

## 문제 설명

클라우드 컴퓨팅 환경(AWS Nitro Enclaves, Google Cloud Confidential VMs, Azure Confidential Computing)에서 엔터프라이즈 기업들은 가장 민감한 자산인 고객 개인정보, 금융 거래 원장, 독점 AI 모델 가중치를 퍼블릭 클라우드 인프라에 배포합니다.

그러나 전통적인 가상화 모델에서는 **하이퍼바이저(KVM / QEMU) 및 호스트 OS 관리자(root)**가 게스트 가상머신의 모든 물리 메모리와 CPU 레지스터를 언제든지 들여다보거나 조작할 수 있는 전지전능한 권한을 가집니다. 심지어 데이터센터 직원이 물리 서버에 접근하여 DRAM 버스 스누핑(Bus Snooping)이나 콜드 부트 공격(Cold Boot Attack)을 감행할 경우 평문 데이터가 고스란히 탈취됩니다.

이 근본적인 신뢰 모델을 뒤집기 위해 등장한 **컨피덴셜 컴퓨팅(Confidential Computing)**의 정점인 **AMD SEV-SNP (Secure Encrypted Virtualization - Secure Nested Paging)** 및 **Intel TDX (Trust Domain Extensions)**(`arch/x86/kvm/svm/sev.c`, `arch/x86/virt/svm/sev.c`)는 호스트 하이퍼바이저조차 신뢰할 수 없는 적으로 간주(Zero-Trust Hypervisor)하고, 하드웨어 프로세서(CPU) 보안 서브시스템이 직접 가상머신의 메모리와 실행 상태를 암호화하여 보호합니다:

```
+-----------------------------------------------------------------------------------------+
|                Confidential Computing: SEV-SNP & TDX Architecture                       |
+-----------------------------------------------------------------------------------------+
    [ Untrusted Cloud Host / Hypervisor (KVM) ]
             |
             | Memory Snooping / Re-mapping Attack? ---> BLOCKED by Hardware!
             v
    +-------------------------------------------------------------+
    | AMD EPYC Processor / PSP (Platform Security Processor)      |
    |  * Memory Encryption: AES-128/256-XTS engine (Per-ASID Key) |
    |  * Reverse Map Table (RMP): Hardware Ownership Enforcement  |
    |  * Hardware Chip Key: VCEK (Versioned Chip Endorsement Key) |
    +-------------------------------------------------------------+
             ^
             |
    [ Confidential VM (Guest) ]
     * Step 1: Boot OVMF Firmware + Kernel + Initrd
     * Step 2: PSP computes Launch Digest (SHA-384 Measurement)
     * Step 3: RMPUPDATE maps physical SPA -> GPA (PVALIDATE verifies)
     * Step 4: SNP_GET_REPORT generates hardware-signed Attestation Report
             |
             | Attestation Report (Nonce + Measurement + Signature)
             v
    [ Remote Relying Party / User Client ]
     * Verifies AMD Root Key (ARK) -> ASK -> VCEK certificate chain
     * Verifies ECDSA signature over report
     * Verifies Nonce freshness (Anti-replay)
     * Verifies Launch Digest matches Golden Image (Firmware/Kernel intact)
     * Verifies debug_allowed == False & TCB version >= minimum threshold
     * SUCCESS ---> Releases confidential TLS keys / AI weights to Guest VM!
```

### 핵심 보안 메커니즘:
1. **기동 측정값 (Launch Digest / Measurement)**:
   - 가상머신 기동 시 게스트 펌웨어(OVMF), 커널, 초기 램디스크(initrd), 커널 커맨드라인의 암호화 해시(SHA-384)를 PSP 하드웨어가 직접 측정합니다.
   - 단 1비트라도 펌웨어가 변조되면 측정값이 변경되어 원격 증명 검증에서 즉시 탄로납니다.
2. **역방향 매핑 테이블 (Reverse Map Table, RMP)**:
   - 하이퍼바이저의 악의적인 페이지 재매핑 공격(Re-mapping Attack: 서로 다른 가상 주소를 동일한 물리 주소로 조작하거나 타 게스트의 메모리를 가로채는 공격)을 막기 위해, 하드웨어가 물리 주소(SPA)마다 소유 가상머신(ASID)과 가상 주소(GPA)를 1:1로 독점 기록합니다.
   - 불법적인 중복 매핑 시도 시 하드웨어는 즉시 `#NPF` (Nested Page Fault with RMP violation) 예외를 발생시키고 실행을 중단합니다.
3. **게스트 페이지 검증 (`PVALIDATE`)**:
   - 게스트 OS는 하이퍼바이저가 할당한 물리 페이지를 사용하기 전 `PVALIDATE` 명령어를 실행하여 RMP 테이블의 유효성을 하드웨어적으로 확인하고 검증 비트를 활성화합니다.
4. **원격 증명 (Remote Attestation / `SNP_GET_REPORT`)**:
   - 게스트는 신선한 일회용 난수(Nonce / `user_data`)를 담아 하드웨어에 증명 보고서를 요청합니다.
   - 프로세서 고유 하드웨어 키(VCEK)로 서명된 보고서에는 기동 측정값, 보안 정책(`debug_allowed` 비활성화 여부), 하드웨어 펌웨어 버전(`tcb_version`)이 기록됩니다.
   - 원격 검증자는 AMD 루트 인증기관(ARK) 체인을 확인하고 보고서 서명과 측정값을 검증하여, 하드웨어 레벨의 완벽한 기밀성이 증명될 때에만 기밀 키를 프로비저닝합니다.

주어진 신뢰 기준(골든 측정값, 루트 CA 키링, 최소 TCB 버전)과 일련의 가상머신 기동, RMP 업데이트, 원격 증명 생성 및 검증 시퀀스를 시뮬레이션하고 상세 이력(`history`)과 요약 통계(`summary`)를 산출하는 엔진을 구현하십시오.

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "trusted_golden_measurements": [
      "785274ff451e735d9082535c30e5b51dc138991b1c81f5653b160ae38892d5e6e944cda8468d4e5658997d77ea25b75f"
    ],
    "trusted_root_ca_keys": ["amd_ark_root_2026"],
    "min_tcb_version": 10
  },
  "operations": [
    {
      "op": "LAUNCH_VM",
      "vm_id": "cvm_01",
      "asid": 1,
      "firmware": "OVMF_SECURE_BOOT_v2",
      "kernel": "vmlinuz_6.8_signed",
      "initrd": "initrd_sealed",
      "cmdline": "console=ttyS0 quiet",
      "policy": {"debug_allowed": false, "smt_allowed": true},
      "host_tcb_version": 12
    },
    {"op": "RMPUPDATE", "vm_id": "cvm_01", "spa": 1048576, "gpa": 4096, "page_type": "PAGE_TYPE_NORMAL"},
    {"op": "PVALIDATE", "vm_id": "cvm_01", "spa": 1048576, "gpa": 4096},
    {"op": "SNP_GET_REPORT", "vm_id": "cvm_01", "user_data": "challenge_nonce_xyz123"},
    {"op": "VERIFY_ATTESTATION", "expected_user_data": "challenge_nonce_xyz123"}
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다 (`separators=(',', ':')`).
```json
{
  "history": [
    {
      "op": "LAUNCH_VM",
      "vm_id": "cvm_01",
      "asid": 1,
      "status": "SUCCESS",
      "measurement": "785274ff451e735d9082535c30e5b51dc138991b1c81f5653b160ae38892d5e6e944cda8468d4e5658997d77ea25b75f",
      "debug_allowed": false,
      "detail": "SEV-SNP confidential VM cvm_01 launched with measurement=785274ff451e735d..."
    },
    ...
  ],
  "summary": {
    "vms_running": 1,
    "rmp_entries_active": 1,
    "rmp_violations_blocked": 0,
    "attestation_summary": {
      "requests": 1,
      "verified": 1,
      "rejected": 0
    }
  }
}
```
