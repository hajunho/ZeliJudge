# 문제 424 심층 이론: ARM CCA(Confidential Compute Architecture) RME와 하드웨어 과립 보호 아키텍처

---

## 1. 하이퍼바이저 불신(Zero-Trust Hypervisor)과 기밀 컴퓨팅의 패러다임 전환

전통적인 서버 가상화 모델에서 하이퍼바이저(KVM, Hyper-V, ESXi)는 최상위 특권 계층(EL2 / Ring -1)에서 동작하며, 모든 게스트 가상 머신의 물리 메모리(GPA)와 CPU 레지스터 컨텍스트에 대한 무제한적인 읽기 및 쓰기 권한을 보유합니다.
그러나 공용 클라우드(Public Cloud) 환경에서는 다음과 같은 심각한 위협이 존재합니다:
1. **악의적인 클라우드 운영자 또는 관리자 권한 탈취**: 관리자 셸을 통해 게스트 RAM을 덤프하거나 변조.
2. **호스트 리눅스 커널 취약점**: 하이퍼바이저 RCE(Remote Code Execution) 익스플로잇을 통한 크로스 테넌트 공격.
3. **물리적 메모리 스누핑(Bus Snooping / Cold Boot Attack)**: 하드웨어 인터포저를 통한 DRAM 버스 도청.

이를 해결하기 위해 고안된 패러다임이 **기밀 컴퓨팅(Confidential Computing)**이며, 하이퍼바이저조차 신뢰하지 않는 **제로-트러스트(Zero-Trust)** 모델을 지향합니다.

---

## 2. ARMv9-A Realm Management Extension (RME) 4대 보안 세계

ARMv8까지의 TrustZone 기술은 시스템을 단지 2개의 보안 상태(Secure / Non-secure)로만 나누었기 때문에, 통신사 및 결제 서비스용 보안 OS(OP-TEE)와 클라우드 VM을 한 하드웨어에서 동시에 안전하게 격리하기 어려웠습니다.

ARMv9-A의 **RME(Realm Management Extension)**는 이를 근본적으로 혁신하여 **4대 독립 보안 세계**를 하드웨어적으로 정의합니다:

```
[Security State Mapping in ARMv9-A RME]
- ROOT World (EL3)        : SPM / Monitor Firmware (TF-A), Configures GPT
- SECURE World (S-EL0~2)  : Trusted OS, DRM, TPM, Secure Firmware
- REALM World (RL-EL0~2)  : Protected VMs (Realms), Isolated from Host
- NON-SECURE (NS-EL0~2)   : Host Linux Kernel, KVM, User Processes
```

각 세계 간의 전환은 오직 최고 특권 계층인 **EL3 Monitor**를 통해서만 안전하게 제어됩니다.

---

## 3. Granule Protection Table (GPT)과 하드웨어 GPC 필터링

RME의 하드웨어 메모리 보호의 핵심은 **과립 보호 테이블(GPT, Granule Protection Table)**입니다.

### 3.1 2단계 과립 보호 검사 (GPC, Granule Protection Check)
CPU 코어 또는 DMA 마스터 디바이스가 물리 메모리 버스(AXI/CHI)에 물리 주소(PA)를 실어 보낼 때, 하드웨어 MMU의 버스 인터페이스에 위치한 **GPC 유닛**이 해당 주소를 실시간으로 검사합니다:
1. 주소 변환(Stage 1 & Stage 2 MMU)을 거쳐 최종 물리 주소(PA)가 산출됩니다.
2. GPC 유닛은 시스템 L1/L2 GPT 캐시를 참조하여 해당 4KB 물리 과립(Granule)의 소유 상태(`GPI: Granule Protection Information`)를 조회합니다:
   - `GPI_ROOT`: 오직 Root World에서만 접근 가능.
   - `GPI_REALM`: 오직 Realm World 및 RMM에서만 접근 가능.
   - `GPI_SECURE`: 오직 Secure World에서만 접근 가능.
   - `GPI_NS`: Non-secure World(호스트 KVM)에서 접근 가능.
3. 만약 Non-secure 상태의 호스트 CPU가 `GPI_REALM`으로 표시된 물리 주소에 읽기 또는 쓰기를 시도하면, 하드웨어는 즉시 버스 트랜잭션을 거부하고 **과립 보호 폴트(Granule Protection Fault, GPF)** 동기 예외를 발생시킵니다.

---

## 4. RMI (Realm Management Interface)와 RSI (Realm Service Interface)

ARM CCA에서 호스트 KVM과 게스트 Realm은 하드웨어 모니터 계층인 **RMM(Realm Management Monitor)**을 통해 소통합니다.

### 4.1 RMI (호스트 <-> RMM)
호스트 KVM은 비신뢰 영역에 속하므로 Realm의 내부를 직접 수정할 수 없습니다. 대신 SMC 시스템 콜을 통해 RMM에 표준 요청을 전달합니다:
- `RMI_GRANULE_DELEGATE`: 호스트가 보유한 Non-secure 페이지를 RMM으로 위임(Delegate)하여 `GPI_REALM` 상태로 전이시킵니다.
- `RMI_REALM_CREATE`: 새 Realm 인스턴스 및 제어 블록(RD: Realm Descriptor)을 생성합니다.
- `RMI_RTT_MAP`: 위임된 물리 과립을 Realm의 2단계 변환 테이블(RTT)에 매핑하고 롤링 측정값에 반영합니다.
- `RMI_REALM_ACTIVATE`: Realm 생성을 확정하고 측정 해시를 영구 봉인합니다.
- `RMI_GRANULE_UNDELEGATE`: 렐름 종료 후 물리 메모리를 Non-secure로 반환하기 전, **RMM이 물리 과립 전체를 `0x00`으로 강제 스크러빙(Scrubbing)**하여 이전 테넌트의 메모리 잔존 데이터 누출을 원천 방지합니다.

### 4.2 RSI (게스트 Realm <-> RMM)
Realm 게스트 커널이 내부에서 RMM에 직접 질의하는 서비스 인터페이스입니다:
- `RSI_ATTESTATION_TOKEN`: 원격 검증자(Verifier)가 제공한 일회용 난수(Challenge Nonce)를 포함하여 하드웨어 서명된 원격 증명 토큰을 발급받습니다.

---

## 5. 원격 증명 (Remote Attestation)과 신뢰 검증

클라이언트 테넌트는 클라우드 상에서 구동 중인 Realm이 올바른 순정 OS 커널과 펌웨어로 부팅되었는지 검증하기 위해 **원격 증명(Remote Attestation)**을 수행합니다:
1. 부팅 시 RMM은 각 코드 및 데이터 페이지가 RTT에 매핑될 때마다 SHA-256 기반 롤링 해시($M$)를 누적 계산합니다:
   $$M_k = \text{Trunc}_{16} \left( \text{SHA-256} \left( M_{k-1} \parallel \text{IPA} \parallel \text{PA} \parallel \text{DataHash} \right) \right)$$
2. 활성화(`ACTIVATE`) 이후에는 어떠한 코드 변경도 허용되지 않습니다.
3. 검증자가 보낸 난수(Challenge)와 최종 측정값($M_{\text{final}}$)을 조합하여 하드웨어 퓨즈(Hardware Root Key)로 서명된 토큰을 반환합니다. 이를 통해 테넌트는 하이퍼바이저의 어떠한 간섭도 없는 순수한 실행 환경임을 수학적으로 확신할 수 있습니다.
