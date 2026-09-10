# 리눅스 커널 KVM EPT 및 하드웨어 보조 2차원 페이징 이론 (KVM EPT Theory)

## 1. 섀도우 페이지 테이블(SPT)에서 하드웨어 2차원 페이징(EPT)으로

### 1.1 초기 소프트웨어 가상화의 한계: Shadow Page Tables
x86 CPU에 EPT(Intel)나 NPT(AMD)가 없던 초기 가상화 시절(2000년대 중반), KVM과 VMware는 게스트 OS의 페이지 테이블과 실제 하드웨어 MMU를 동기화하기 위해 **섀도우 페이지 테이블(Shadow Page Tables, SPT)** 기법을 사용했습니다.
- 게스트가 페이지 테이블 엔트리(CR3, PTE)를 수정할 때마다 하이퍼바이저로 Trap(VM-Exit)되어 섀도우 테이블을 일일이 패치해야 했습니다.
- 이로 인해 프로세스 생성, fork, 메모리 할당 시 수천 번의 VM-Exit가 발생하여 심각한 성능 저하가 초래되었습니다.

### 1.2 Intel EPT (Extended Page Tables)의 혁신
Intel VT-x의 EPT는 하드웨어 MMU가 2단계의 주소 변환을 직접 수행하도록 지원합니다:
1. **1단계**: GVA $	o$ GPA (Guest CR3가 가리키는 일반 4단계 페이지 테이블 워크)
2. **2단계**: GPA $	o$ HPA (하이퍼바이저가 VMCS의 EPTP에 등록한 4단계 EPT 워크)
하드웨어가 2차원 워크를 자율적으로 수행하므로 게스트의 일반 페이지 테이블 수정 시 VM-Exit가 전혀 발생하지 않습니다.

---

## 2. EPT Violation과 KVM MMU 아키텍처

### 2.1 Exit Qualification과 고속 경로(Fast Path)
게스트가 아직 EPT에 매핑되지 않은 GPA에 접근하거나, 권한이 없는 연산(예: 읽기 전용 페이지에 쓰기)을 시도하면 CPU는 하이퍼바이저로 탈출하며 **`EXIT_REASON_EPT_VIOLATION`**을 보고합니다.
- VMCS의 Exit Qualification 필드에 읽기/쓰기/실행 여부 및 EPT의 현재 권한 비트가 인코딩됩니다.
- KVM MMU(`arch/x86/kvm/mmu/mmu.c`)는 이를 수신하여 `kvm_mmu_page_fault()` 파이프라인으로 라우팅합니다.

### 2.2 클라우드 라이브 마이그레이션과 더티 페이지 트래킹
가상머신을 물리 서버 A에서 B로 무중단 이전할 때, VM이 실행 중인 상태에서 메모리 페이지를 백그라운드로 복사해야 합니다:
1. **Pre-copy 단계**: 전체 메모리를 타깃 노드로 1차 전송.
2. **Dirty Logging 활성화**: 메모리 슬롯의 모든 EPT 엔트리에서 Write 비트를 클리어(`w = 0`).
3. **Write Trap**: 게스트가 메모리를 수정하면 EPT Violation이 발생하고, KVM은 Fast Path에서 해당 프레임을 비트맵에 마킹한 후 Write 비트를 다시 열어줍니다.
4. **반복 전송**: 변경된 더티 페이지만 지속적으로 전송하여 최종 전환 지연시간(Downtime)을 수십 밀리초 이내로 단축합니다.
