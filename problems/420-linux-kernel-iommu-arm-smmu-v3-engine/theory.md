# 이론 문서 420: Linux 커널 ARM64 SMMUv3 가상화 아키텍처 및 하드웨어 I/O 메모리 격리 내부 원리

## 1. 개요 및 배경 (Hardware I/O Virtualization & Motivation)

과거의 컴퓨터 아키텍처에서 주변 장치는 물리 주소 공간(Physical Address Space)에 직접 메모리 트랜잭션을 발행했습니다.
이 방식은 단일 운영체제 환경에서는 단순하고 빨랐으나, 다음과 같은 현대 클라우드 가상화 및 보안 요구사항을 충족할 수 없었습니다:
- **메모리 침범 방어 (Memory Isolation)**: 신뢰할 수 없는 써드파티 PCIe 카드나 펌웨어가 커널 메모리를 불법으로 읽거나 쓰는 버스 마스터 공격(DMA 공격)을 하드웨어적으로 차단할 수단이 없었습니다.
- **가상 머신 직접 패스스루 (SR-IOV / VFIO)**: KVM 하이퍼바이저 환경에서 가상 머신(VM)에 물리 NIC이나 GPU를 직결할 때, 게스트 OS는 자신의 연속된 주소 공간(GPA)을 디바이스에 프로그래밍하므로 호스트 물리 메모리(HPA)로의 동적 변환이 필수적입니다.
- **공유 가상 메모리 (SVM / SVA)**: CPU 프로세스와 가속기(GPU/NPU)가 단일 가상 주소 포인터를 복사 없이 직접 공유(`PASID` / `SubstreamID`)하기 위해 CPU MMU와 동기화되는 I/O 변환 유닛이 필요합니다.

이 모든 요구를 만족하기 위해 ARMv8/v9 서버 아키텍처에 정의된 표준이 바로 **ARM SMMUv3 (System MMU Architecture v3)**입니다.

---

## 2. 2단계 주소 변환 (Two-Stage Translation) 아키텍처

SMMUv3는 CPU의 가상화 확장(Virtualization Extensions, EL2)과 정확히 일치하는 **2단계 변환 파이프라인**을 제공합니다:

```
                      [ Stage 1 Translation ]                 [ Stage 2 Translation ]
 [ Device IOVA / GVA ] ======================> [ IPA / GPA ] =======================> [ Physical Address (PA) ]
                       (Context Descriptor CD)                (Stage 2 Page Table)
                       Controlled by Guest OS                 Controlled by Host Hypervisor
```

### 2.1 4대 변환 모드
1. **`BYPASS`**:
   - 모든 DMA 트랜잭션을 변환 없이 물리 메모리로 직통 통과시킵니다.
   - 드라이버 초기화 및 펌웨어 부팅 단계에서 사용됩니다.
2. **`STAGE1` (Host SVA Mode)**:
   - 디바이스 가상 주소($IOVA$)를 중간 물리 주소($IPA$) 또는 호스트 물리 주소($PA$)로 변환합니다.
   - 호스트 리눅스 커널의 프로세스 페이지 테이블을 공유하는 데 사용됩니다.
3. **`STAGE2` (Hypervisor VM Mode)**:
   - 가상 머신이 생성한 게스트 물리 주소($GPA$)를 호스트 물리 주소($PA$)로 변환합니다.
   - 하이퍼바이저(KVM)가 관리하며, VM 간의 완전한 메모리 격리를 강제합니다.
4. **`NESTED` (Two-Stage Nested Mode)**:
   - 1단계($IOVA \to GPA$)와 2단계($GPA \to PA$)가 결합된 모드입니다.
   - 게스트 OS가 자신의 IOMMU 드라이버를 통해 Stage 1을 제어하고, 호스트 KVM이 Stage 2를 제어함으로써 클라우드 게스트 VM 내부에서도 디바이스 제로-카피 가속(DPU, GPU Direct)을 누릴 수 있습니다.

---

## 3. 링 버퍼 기반 하드웨어 큐 아키텍처

SMMUv3는 레지스터 폴링으로 인한 CPU 낭비를 제거하기 위해 메모리 기반의 원형 큐(Circular Ring Buffer)를 사용합니다:

### 3.1 명령 큐 (Command Queue, `CMDQ`)
- 소프트웨어(리눅스 커널)가 생산자(Producer, `PROD` 레지스터)이고 SMMU 하드웨어가 소비자(Consumer, `CONS` 레지스터)입니다.
- 주요 명령:
  - `CMDQ_OP_CFGI_STE`: 스트림 테이블 엔트리 변경 시 SMMU 내부 캐시를 무효화합니다.
  - `CMDQ_OP_TLBI_NH_VA`: 주소 변환 해제(`iommu_unmap`) 시 SMMU TLB를 무효화합니다.
  - `CMDQ_OP_CMD_SYNC`: 이전의 모든 명령이 물리적으로 완료되었음을 확인하는 하드웨어 동기화 배리어입니다.

### 3.2 이벤트 큐 (Event Queue, `EVTQ`)
- SMMU 하드웨어가 생산자이고 리눅스 커널이 소비자입니다.
- DMA 에러 발생 시 장애 원인과 주소를 기록합니다:
  - `F_TRANSLATION`: 페이지 테이블에 매핑되지 않은 주소 접근 (I/O Page Fault).
  - `F_PERMISSION`: 쓰기 금지 페이지에 DMA 쓰기 시도.
  - `F_STREAM_DISABLED`: 허가되지 않은 PCIe 디바이스 트랜잭션 차단.

---

## 4. 리눅스 커널 드라이버 구현 (`drivers/iommu/arm/arm-smmu-v3/`)

1. **`arm_smmu_write_strtab_ent()`**:
   - `struct arm_smmu_master`의 StreamID를 기반으로 메모리의 64바이트 크기 STE 구조체를 작성합니다.
   - `arm_smmu_cmdq_issue_cmd()`를 호출하여 `CFGI_STE` 및 `CMD_SYNC`를 발주합니다.

2. **`arm_smmu_unmap_pages()`**:
   - IOMMU 페이지 매핑 해제 시 `TLBI_NH_VA` 명령을 CMDQ에 큐잉하고 동기화하여 이전 DMA가 잔여 캐시로 오염되는 것을 차단합니다.

3. **`arm_smmu_evtq_thread()`**:
   - 인터럽트 발생 시 EVTQ 링 버퍼를 스캔하여 불법 DMA 공격이나 I/O 에러를 `dmesg`에 기록하고 디바이스 트랜잭션을 격리합니다.
