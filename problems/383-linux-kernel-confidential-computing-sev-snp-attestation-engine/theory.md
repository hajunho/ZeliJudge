# Linux 커널 가상화 및 하드웨어 보안: 컨피덴셜 컴퓨팅 AMD SEV-SNP & Intel TDX 아키텍처

## 1. 개요 및 패러다임 전환: Zero-Trust Hypervisor

전통적인 클라우드 가상화 기술(Xen, KVM, ESXi)에서 가상머신(VM)과 하이퍼바이저 사이의 보안 모델은 절대적인 계층적 신뢰에 기반했습니다:
- CPU 링 구조에서 하이퍼바이저는 최고 특권 수준인 Ring -1 (Root VMX/SVM 모드)에서 동작하고, 게스트 VM은 Ring 0 (Non-root 모드)에서 동작합니다.
- 따라서 하이퍼바이저는 게스트의 모든 중첩 페이지 테이블(NPT / EPT)과 물리 메모리 매핑을 전적으로 제어하며, 임의로 게스트의 메모리를 읽거나(`peek`) 수정(`poke`)할 수 있었습니다.

그러나 정부 규제 준수(GDPR, HIPAA, 금융 망분리 규제)와 클라우드 공급자 내부자 위협, 그리고 하이퍼바이저 자체의 제로데이 취약점(Cloud-escape)으로 인해, **"클라우드 호스트 하이퍼바이저조차 신뢰하지 않고(Zero-Trust Hypervisor), 오직 하드웨어 CPU 실리콘만을 신뢰하는"** 패러다임인 **컨피덴셜 컴퓨팅(Confidential Computing)**이 태동했습니다.

이 분야의 양대 하드웨어 표준은 AMD의 **SEV-SNP (Secure Encrypted Virtualization - Secure Nested Paging, Zen 3/4 EPYC)**와 Intel의 **TDX (Trust Domain Extensions, Emerald Rapids/Granite Rapids Xeon)**입니다.

---

## 2. SEV 계보와 SEV-SNP의 혁신

AMD의 기밀 가상화 기술은 3세대에 걸쳐 발전했습니다:
1. **SEV (2016)**:
   - 메모리 컨트롤러에 하드웨어 AES 암호화 엔진을 탑재.
   - 각 VM(ASID)마다 고유한 AES-128 키를 부여하여 메모리를 암호화.
   - 한계: 기밀성(Confidentiality)은 제공하지만 무결성(Integrity)이 없어, 하이퍼바이저가 메모리 블록을 재배치하거나 복제하는 메모리 주입 공격(Memory Replay/Corruption)에 취약함.
2. **SEV-ES (2017)**:
   - VMSA(Virtual Machine Save Area) 암호화 도입.
   - VM-Exit 발생 시 CPU 레지스터(RAX, RIP, RSP 등)를 암호화하여 하이퍼바이저가 레지스터를 훔쳐보는 것을 차단.
3. **SEV-SNP (2020+)**:
   - **SNP (Secure Nested Paging)** 도입으로 강력한 하드웨어 메모리 무결성(Integrity) 및 상태 전이 보호 완성.
   - 하이퍼바이저의 메모리 재매핑(Re-mapping), 메모리 복제(Memory Aliasing), 메모리 폐기(Drop-out) 공격을 하드웨어 레벨에서 100% 원천 차단.

---

## 3. 핵심 아키텍처 컴포넌트

### 3.1 RMP (Reverse Map Table)
- CPU 하드웨어 메모리 컨트롤러가 직접 참조하는 전역 물리 메모리 소유권 테이블입니다.
- 물리 시스템 메모리(SPA: System Physical Address)의 모든 4KB 페이지마다 하나의 RMP 엔트리가 매핑됩니다.
- RMP 엔트리 필드:
  - `Assigned ASID`: 이 물리 페이지를 소유한 기밀 가상머신의 고유 ID.
  - `GPA`: 이 물리 페이지가 게스트 내에서 매핑되어야 하는 가상 물리 주소.
  - `Page Type`: 일반 메모리(`PAGE_TYPE_NORMAL`), 레지스터 상태(`PAGE_TYPE_VMSA`), 공유 메모리(`PAGE_TYPE_SHARED`) 등.
  - `Validated Bit`: 게스트 커널이 `PVALIDATE`를 통해 승인했는지 여부.
- 하이퍼바이저가 악의적으로 두 개의 게스트 GPA를 하나의 물리 페이지에 매핑하려 하거나, 타 게스트의 메모리를 가로채려 할 경우, CPU MMU 하드웨어는 즉시 **`#NPF(Nested Page Fault)`**를 발생시켜 트랜잭션을 하드웨어적으로 차단합니다.

### 3.2 게스트 페이지 검증: PVALIDATE
- 기밀 VM의 게스트 커널은 하이퍼바이저가 페이지를 새로 할당(`RMPUPDATE`)해 줄 때마다 무조건적으로 신뢰하지 않습니다.
- 게스트 커널은 페이지에 접근하기 전 `PVALIDATE` 명령어를 실행하여:
  1. 하드웨어 RMP에 기록된 GPA와 자신의 의도된 GPA가 일치하는지 검증합니다.
  2. 페이지 메모리를 암호화 제로-패딩(Zero-fill)하여 이전 잔여 데이터를 청소합니다.
  3. 검증 비트를 `VALIDATED`로 활성화합니다.

---

## 4. 하드웨어 기반 원격 증명 (Remote Attestation)

기밀 가상머신이 클라우드에 성공적으로 부팅되었다 하더라도, 외부의 사용자(Relying Party)는 이 가상머신이 진짜 하드웨어 암호화로 보호되는 정품 AMD/Intel CPU 위에서 실행 중인지, 아니면 해커가 QEMU 에뮬레이터로 조작한 가짜 환경인지 검증해야 합니다.

### 4.1 기동 측정값 (Launch Digest)
게스트가 부팅될 때 AMD PSP(Platform Security Processor)는 다음 구성 요소를 순차적으로 해시합니다:
$$\text{Measurement} = \text{SHA-384}(\text{OVMF Firmware} \parallel \text{Kernel Image} \parallel \text{initrd} \parallel \text{cmdline})$$
이 측정값은 PSP 내부의 변조 불가능한 보안 레지스터에 영구 기록됩니다.

### 4.2 증명 보고서 생성 (`SNP_GET_REPORT`)
게스트는 사용자로부터 수신한 일회용 난수(Nonce)를 담아 하드웨어에 보고서를 요청합니다.
보고서에는 다음이 포함됩니다:
1. `Measurement`: 게스트 펌웨어/커널 해시.
2. `Policy`: 디버그 허용 여부(`debug_allowed == 0`), SMT(하이퍼스레딩) 정책.
3. `TCB Version`: 마이크로코드 및 하드웨어 보안 패치 레벨.
4. `User Data`: 세션 탈취 및 재생 공격(Replay Attack)을 방지하는 64바이트 Nonce.
5. `Signature`: CPU 칩 제조 시 하드웨어 퓨즈에 각인된 고유 비밀키로 서명된 ECDSA P-384 전자서명.

### 4.3 원격 검증 절차 (Relying Party Verification)
사용자는 다음 6단계 검증을 거칩니다:
1. AMD 공식 KDS(Key Distribution Service)의 **ARK(AMD Root Key)**로부터 이어지는 인증서 체인 검증.
2. 보고서 본문에 대한 VCEK 공개키 서명 일치 확인.
3. 요청 시 보낸 Nonce와 보고서의 `user_data` 일치 확인 (재생 공격 방어).
4. 보고서의 `measurement`가 사전에 빌드하여 검증된 골든 이미지(Golden Image)와 완벽히 일치하는지 확인 (OS 무결성 증명).
5. 디버그 모드가 비활성화되어 있는지 확인 (`debug_allowed == False`).
6. 하드웨어 TCB 버전이 최신 보안 패치 기준을 충족하는지 확인.

모든 검증이 통과되면 사용자는 해당 클라우드 인스턴스를 자신의 온프레미스 데이터센터와 동일한 신뢰 수준으로 인정하고, 디스크 복호화 키와 기밀 비즈니스 로직을 비로소 주입합니다.
