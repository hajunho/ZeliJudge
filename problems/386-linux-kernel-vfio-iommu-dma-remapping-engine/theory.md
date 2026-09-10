# Theory: Linux Kernel VFIO Framework & IOMMU Hardware Isolation (`drivers/vfio/`)

## 1. 유저스페이스 디바이스 드라이버와 IOMMU의 필요성

전통적으로 디바이스 드라이버는 커널 공간(`Ring 0`)에 위치하여 하드웨어 레지스터 및 DMA를 직접 제어했습니다. 그러나 100GbE+ 초고속 네트워킹(DPDK)이나 NVMe 플래시 어레이(SPDK), 가상 머신(QEMU/KVM PCIe Passthrough) 환경에서는 커널 시스템 콜 오버헤드와 컨텍스트 스위칭 비용을 회피하기 위해 **유저스페이스 다이렉트 디바이스 드라이버**가 필수적입니다.

### 1.1 UIO의 치명적 한계와 취약점
과거 리눅스의 UIO(Userspace I/O)는 단순히 MMIO 영역을 `mmap`해주고 인터럽트를 파일 디스크립터로 전달하는 수준이었습니다.
- UIO는 **IOMMU(Input-Output Memory Management Unit)** 프로그래밍 인터페이스를 제공하지 않았습니다.
- 유저스페이스 프로그램이 디바이스 DMA 디스크립터에 임의의 물리 주소(HPA)를 기록하면, 하드웨어 디바이스는 IOMMU 변환 없이 커널 코드나 다른 프로세스의 메모리를 덮어쓸 수 있었습니다(Host Kernel Compromise).

---

## 2. VFIO(Virtual Function I/O) 아키텍처

리눅스 커널 3.6부터 도입된 **VFIO**(`drivers/vfio/`)는 하드웨어 IOMMU(Intel VT-d, AMD-Vi, ARM SMMU)를 필수 전제로 하여 설계된 안전한 유저스페이스 드라이버 프레임워크입니다.

### 2.1 IOMMU Group과 PCIe ACS 격리
- PCIe 토폴로지에서 두 개 이상의 디바이스가 동일한 다기능(Multi-Function) 브리지 아래에 있거나 PCIe 스위치가 **ACS(Access Control Services)**를 지원하지 않는 경우, 디바이스 간 직접 P2P(Peer-to-Peer) 트래픽이 상위 루트 복합체(Root Complex)의 IOMMU를 우회할 수 있습니다.
- 리눅스 커널은 물리적으로 서로를 감청할 수 있는 디바이스들을 동일한 **IOMMU Group**(`/sys/kernel/iommu_groups/<ID>/devices/`)으로 묶습니다.
- VFIO는 **그룹 단위 격리 정책(All-or-Nothing)**을 강제합니다: 그룹 내 모든 디바이스가 호스트 커널 드라이버에서 해제되어 유저스페이스 드라이버에 위임되지 않으면 해당 그룹은 활성화되지 않습니다.

### 2.2 Container와 IOMMU Type1 드라이버
- `VFIO Container`(`/dev/vfio/vfio`)는 하나 이상의 IOMMU 그룹을 담는 통합 IOMMU 페이지 테이블 도메인입니다.
- `VFIO_SET_IOMMU` ioctl을 통해 `VFIO_IOMMU_TYPE1`(x86/x86_64 표준 DMAR 드라이버)을 활성화합니다.
- `VFIO_IOMMU_MAP_DMA`: 유저스페이스 가상 주소(`vaddr`)를 디바이스 I/O 가상 주소(`iova`)에 매핑합니다. 이때 커널은 `pin_user_pages()`를 호출하여 페이지를 물리 메모리에 락(Lock)하고 호스트 스왑아웃을 차단하며, `RLIMIT_MEMLOCK` 쿼터를 차감합니다.

### 2.3 MSI/MSI-X 인터럽트와 eventfd 가속
- 디바이스의 MSI-X 인터럽트 벡터는 커널의 `eventfd` 메커니즘과 직결됩니다.
- 하드웨어 인터럽트 발생 시 커널 핸들러는 단순 카운터를 증가시키고 eventfd를 시그널링합니다.
- 유저스페이스는 `epoll_wait` 또는 비차단 폴링으로 즉각 인터럽트를 수신하므로, 무거운 시그널(`SIGIO`)이나 복잡한 IPC 없이 마이크로초 단위 초저지연 인터럽트 처리가 실현됩니다.
