# 이론 문서 421: Linux 커널 기밀 컴퓨팅과 AMD SEV-ES/SNP GHCB 프로토콜 및 하드웨어 격리 내부 원리

## 1. 개요 및 배경 (Confidential Computing Threat Model & Motivation)

기존 가상화(Virtualization) 환경에서 보안의 최상위 권한자(Trusted Computing Base, TCB)는 하이퍼바이저였습니다.
그러나 클라우드 서비스 제공자(CSP)의 내부자 위협, 호스트 커널 익스플로잇, 그리고 하드웨어 인터페이스를 통한 메모리 도청으로부터 고객의 핵심 데이터를 보호하기 위해 **"하이퍼바이저조차 신뢰하지 않는(Untrusted Hypervisor)"** 기밀 컴퓨팅 패러다임이 등장했습니다.

### 1.1 AMD SEV 아키텍처의 진화
1. **AMD SEV (Secure Encrypted Virtualization, 2016)**:
   - 온칩 보안 프로세서(AMD-SP)가 관리하는 하드웨어 AES-128 엔진을 통해 메모리 버스 트랜잭션을 암호화(C-bit)했습니다.
   - 한계: VM-Exit 시 CPU 레지스터(RAX, RBX 등)는 일반 텍스트로 호스트 메모리(VMCB)에 저장되어 하이퍼바이저에 노출되었습니다.
2. **AMD SEV-ES (Encrypted State, 2017)**:
   - 게스트의 모든 레지스터 상태를 암호화된 VMSA(Virtual Machine Save Area) 페이지로 격리하여 하이퍼바이저의 레지스터 접근을 물리적으로 차단했습니다.
   - 통신 수단으로 `#VC` 예외 및 `VMGEXIT` 프로토콜을 공식 도입했습니다.
3. **AMD SEV-SNP (Secure Nested Paging, 2020)**:
   - 메모리 무결성(Integrity)과 재생 공격 방어(Anti-Replay)를 보장하는 역방향 매핑 테이블(RMP, Reverse Map Table)을 추가하여 하이퍼바이저가 게스트 메모리 페이지를 재배치하거나 조작하는 행위를 100% 하드웨어 차단했습니다.

---

## 2. #VC 예외와 GHCB 프로토콜 사양

### 2.1 `#VC` (VMM Communication Exception, Vector 29)
- 게스트가 하이퍼바이저 지원을 필요로 하는 비특권/특권 명령어를 실행할 때 CPU 하드웨어는 즉시 하이퍼바이저로 빠져나가지 않고, **게스트 OS 내부로 벡터 29 `#VC` 트랩**을 전달합니다.
- 리눅스 커널의 `#VC` 핸들러(`arch/x86/kernel/sev.c`)는 발생 원인(Exit Reason)을 분석하고, 노출이 허용된 최소 정보만을 선별하여 공유 메모리 블록인 GHCB에 안전하게 복사합니다.

### 2.2 GHCB (Guest-Host Communication Block) 레이아웃
GHCB는 4KB 정렬된 메모리 페이지로 다음과 같은 핵심 필드로 구성됩니다:
- **`valid_bitmap` (Bytes 392:399)**: 어떤 필드가 유효한지 나타내는 64비트 비트마스크입니다. 게스트가 요청하지 않은 필드를 하이퍼바이저가 변조하는 것을 방어합니다.
- **`sw_exit_code` (Bytes 16:23)**: 에뮬레이션 요청 코드 (e.g., `SVM_VMGEXIT_CPUID`, `SVM_VMGEXIT_MSR`).
- **`sw_exit_info1`, `sw_exit_info2`**: 서브 파라미터 및 에러 반환 코드.
- **범용 레지스터 슬롯**: `rax`, `rbx`, `rcx`, `rdx`, `rsi`, `rdi` 등.

---

## 3. SEV-SNP Page State Change (PSC) 프로토콜

기밀 가상 머신 내부의 메모리는 기본적으로 하드웨어 AES 암호화 키가 적용된 **비공개(Private) 상태**입니다.
그러나 가상 I/O(VirtIO 네트워킹, 블록 디바이스)를 수행하려면 호스트 하이퍼바이저가 패킷 버퍼를 읽고 쓸 수 있도록 특정 페이지만 선별적으로 **공유(Shared) 상태**로 전환해야 합니다.

### 3.1 PSC 상태 전이 워크플로우
```
   [ Private Page (Encrypted) ]
               |
               | 1. Guest issues PAGE_STATE_CHANGE (PKEY/PSC) via VMGEXIT
               v
   [ Hypervisor updates Page Table & Hardware RMP (Reverse Map Table) ]
               |
               v
   [ Shared Page (Unencrypted Bounce Buffer) ]
               |
               | 2. VirtIO DMA Complete -> Guest issues PSC to revoke Shared
               v
   [ Private Page (Re-encrypted & Validated in RMP) ]
```

- 게스트는 `set_memory_decrypted()`를 호출하여 바운스 버퍼(SWIOTLB)를 SHARED로 변환하고, I/O 완료 후 다시 PRIVATE로 원복하여 데이터 유출을 원천 방지합니다.

---

## 4. 보안 및 무결성 수학적 검증 모델

하이퍼바이저의 위변조 공격 시나리오를 $A$, 게스트의 검증 함수를 $V$라고 할 때:

$$\text{Valid}(GHCB) = \left( GHCB.\text{valid\_bitmap} \subseteq \text{Expected\_Mask} \right) \land \left( GHCB.\text{sw\_exit\_code} == \text{Req\_Code} \right)$$

- 만약 $GHCB.\text{valid\_bitmap} \not\subseteq \text{Expected\_Mask}$ 이면:
  $$\text{Action} \rightarrow \text{SECURITY\_TERMINATION} \quad (\text{Halt vCPU})$$
- 하이퍼바이저가 게스트의 레지스터나 흐름을 조작하려는 어떠한 시도도 게스트 커널의 결정론적 검증에 의해 즉시 발각되어 시스템이 방어적으로 자폭(Fail-Closed)합니다.
