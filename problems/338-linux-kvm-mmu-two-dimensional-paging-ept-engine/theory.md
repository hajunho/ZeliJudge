# 리눅스 커널 KVM MMU 2차원 페이징(Two-Dimensional Paging) 심층 이론

## 1. 메모리 가상화의 역사적 진화: 섀도우 페이징에서 하드웨어 2차원 페이징으로

가상화 환경에서 게스트 운영체제는 주소 변환 하드웨어(MMU)를 자신이 완전히 제어하고 있다고 신뢰합니다. 그러나 실제 물리 하드웨어의 CPU MMU는 하나뿐이므로, 게스트 가상 주소($GVA$)를 게스트 물리 주소($GPA$)로, 그리고 최종적으로 호스트 물리 주소($HPA$)로 변환하는 메커니즘이 필수적입니다.

### 1.1 소프트웨어 섀도우 페이지 테이블 (Shadow Page Table, SPT)
- 초기 x86 가상화(초기 VMware, KVM 초기 버전)에서는 하드웨어 지원이 없었기 때문에 하이퍼바이저가 게스트의 모든 페이지 테이블 수정을 감시해야 했습니다.
- 하이퍼바이저는 게스트의 페이지 테이블 페이지들을 모두 쓰기 보호(Write-Protect)로 마킹하고, 게스트가 페이지 테이블을 수정하려 할 때마다 발생하는 트랩(Page Fault VM-Exit)을 가로채어 $GVA \to HPA$를 직접 가리키는 별도의 섀도우 페이지 테이블을 실시간으로 동기화했습니다.
- **치명적 단점**: 프로세스 생성, 페이지 할당, 컨텍스트 스위칭 시 엄청난 빈도의 VM-Exit 트랩이 발생하여 CPU 사이클의 상당 부분이 하이퍼바이저 오버헤드로 낭비되었습니다.

### 1.2 하드웨어 지원 2차원 페이징 (Two-Dimensional Paging / EPT / NPT)
- 2008년 Intel의 Nehalem 아키텍처는 **EPT (Extended Page Tables)**를, AMD는 Barcelona 아키텍처에서 **NPT (Nested Page Tables)**를 도입했습니다.
- CPU 하드웨어 MMU 내부에 2차원 주소 변환 워커(Two-Dimensional Page Walker)를 내장하여, 게스트 페이지 워크 시 참조되는 모든 주소를 하드웨어가 EPT를 통해 자동으로 $GPA \to HPA$로 변환합니다.
- 하이퍼바이저는 게스트의 CR3 변경이나 페이지 테이블 조작에 개입할 필요가 없으며, 오직 EPT 트리의 누락 또는 권한 위반 시 발생하는 **EPT Violation**만을 처리하면 됩니다.

---

## 2. 2차원 주소 변환(2D Page Walk)의 비용과 TLB 아키텍처

4계층 64비트 x86 페이징 환경에서 2차원 페이징은 주소 변환 비용을 이론적으로 크게 증가시킵니다:
- 게스트가 $GVA$를 $GPA$로 변환하기 위해 4개 레벨(PML4 $\to$ PDP $\to$ PD $\to$ PT)의 게스트 페이지 테이블을 읽어야 합니다.
- 게스트 하드웨어 워커가 읽는 4개의 엔트리 주소는 모두 $GPA$입니다.
- 각 $GPA$를 읽기 위해 하드웨어 MMU는 EPTP가 가리키는 호스트 EPT 4개 레벨을 순회해야 합니다.
- 마지막으로 최종 대상 $GPA$를 $HPA$로 변환하기 위해 다시 EPT 4개 레벨을 순회합니다.

따라서 단 한 번의 TLB 미스에 대해 수행되는 메모리 접근 횟수는 다음과 같습니다:
$$N_{\text{access}} = (L_{\text{guest}} + 1) \times (L_{\text{ept}} + 1) - 1 = (4 + 1) \times (4 + 1) - 1 = 24$$

이처럼 최대 24번의 직렬 메모리 조회가 발생할 수 있으므로, 최신 프로세서는 이를 상쇄하기 위해 다음과 같은 특수 하드웨어 캐시를 탑재합니다:
1. **2D TLB / Combined TLB**: $GVA \to HPA$의 최종 변환 결과를 직접 캐싱.
2. **Paging-Structure Caches (EPT PSC)**: EPT PML4, PDP, PD의 중간 상위 엔트리를 고속 캐싱하여 EPT 워크 단계를 1~2클록으로 단축.
3. **VPID (Virtual Processor ID)**: VM-Exit/VM-Entry 시 TLB 전체를 플러시하지 않고 특정 게스트 vCPU의 TLB 엔트리를 보존.

---

## 3. 리눅스 KVM TDP MMU 아키텍처 (`arch/x86/kvm/mmu/`)

리눅스 커널의 KVM 서브시스템은 대규모 가상화 서버(수백 개의 vCPU와 수 테라바이트 RAM)를 위해 현대적인 **TDP MMU**를 탑재하고 있습니다.

### 3.1 빠른 페이지 폴트 (Fast Page Fault)
- 일반적인 EPT Violation은 커널의 무거운 `mmu_lock` 뮤텍스를 획득해야 하므로, vCPU가 많은 대형 VM에서 락 경합(Lock Contention)이 심화됩니다.
- 그러나 페이지가 이미 EPT에 사상되어 있고 단지 쓰기 권한만이 부족한 경우(예: 실시간 마이그레이션 중의 더티 로깅 또는 CoW), KVM은 `fast_page_fault` 핸들러를 실행합니다.
- `fast_page_fault`는 RCU 읽기 잠금 하에서 원자적 비교-교환(Atomic `CMPXCHG`) 명령어를 사용하여 SPTE의 쓰기 비트를 즉시 갱신하고, 전역 `mmu_lock`을 건너뛰어 초고속으로 게스트 실행을 재개합니다.

### 3.2 실시간 마이그레이션 (Live Migration)과 더티 페이지 로깅
- 가상머신을 다른 물리 노드로 무중단 이전(Live Migration)할 때, 하이퍼바이저는 게스트 메모리를 백그라운드로 전송하면서 이전 중에 게스트가 수정한 메모리 페이지를 추적해야 합니다.
- KVM은 해당 메모리 슬롯에 `KVM_MEM_LOG_DIRTY_PAGES` 플래그를 활성화하고, 모든 EPT 리프 엔트리의 쓰기 비트를 클리어(Write-Protect)합니다.
- 게스트가 페이지에 쓰기를 시도하면 EPT Violation이 발생하고, KVM은 슬롯의 더티 비트맵에 1을 기록한 후 쓰기 권한을 부여합니다.
- 사용자 공간(QEMU)이 `KVM_GET_DIRTY_LOG` ioctl을 호출하면 비트맵을 수거하고 다시 쓰기 보호를 걸어 다음 라운드의 변경분을 추적합니다.

### 3.3 2MB / 1GB 대용량 페이지 (Hugepage) 최적화
- 4KB 기본 페이지 대신 2MB 대용량 페이지를 사용하면 Level 1(PT) 테이블을 생략하고 Level 2(PD)에서 직접 $HPA$를 사상할 수 있습니다.
- 이는 EPT 테이블 메모리 풋프린트를 512분의 1로 절감하고, TLB 캐시 미스를 획기적으로 줄여 메모리 집약적 워크로드(데이터베이스, SAP 등)의 성능을 20~40% 향상시킵니다.
