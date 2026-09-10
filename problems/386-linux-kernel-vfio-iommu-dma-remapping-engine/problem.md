# Problem #386: Linux Kernel VFIO Userspace Driver & IOMMU DMA Remapping Engine (`drivers/vfio/`)

## 문제 설명

고성능 클라우드 가상화(QEMU/KVM GPU/NIC PCI Passthrough) 및 유저스페이스 네트워크/스토리지 가속 프레임워크(DPDK, SPDK)에서 전통적인 유저스페이스 드라이버(UIO)는 IOMMU 보호 기능이 없어 악의적이거나 버그가 있는 장치가 호스트 물리 메모리 전역에 임의의 DMA 쓰기를 감행할 수 있는 심각한 보안 취약점을 안고 있었습니다.

리눅스 커널은 하드웨어 IOMMU(Intel VT-d, AMD-Vi, ARM SMMU)를 기반으로 유저스페이스에 안전한 다이렉트 디바이스 제어권을 위임하는 **VFIO(Virtual Function I/O, `drivers/vfio/`)** 서브시스템을 제공합니다:

```
+----------------------------------------------------------------------------------------------------+
|                                    Linux Kernel VFIO Architecture                                  |
+----------------------------------------------------------------------------------------------------+
| [ User Space / QEMU / DPDK ]                                                                       |
|   | ioctl(VFIO_IOMMU_MAP_DMA) -> Maps IOVA to Virtual Address with READ/WRITE permissions         |
|   | ioctl(VFIO_DEVICE_SET_IRQS) -> Binds MSI-X Interrupt Vectors to eventfd                        |
+---+------------------------------------------------------------------------------------------------+
| [ Kernel Space: drivers/vfio/ ]                                                                    |
|   | Container (/dev/vfio/vfio): Unified IOMMU Page Table Domain                                    |
|   | IOMMU Group (/dev/vfio/<group>): Enforces PCIe ACS Peer-to-Peer Hardware Isolation             |
|   | Page Pinning (pin_user_pages) & RLIMIT_MEMLOCK Accounting                                      |
+---+------------------------------------------------------------------------------------------------+
| [ Hardware IOMMU / DMAR ]                                                                          |
|   | PCIe Device DMA Request (Bus:Dev:Func, target_iova) -> IOMMU Page Table Translation -> HPA    |
|   | Permission Fault Check: (Unmapped IOVA / Permission Denied -> IOMMU DMA Fault Trap)            |
|   | MSI-X Hardware Interrupt -> Kernel eventfd_signal() -> Non-blocking userspace epoll wakeup     |
+----------------------------------------------------------------------------------------------------+
```

### 핵심 아키텍처 및 동작 규칙

1. **컨테이너(Container) 및 IOMMU 그룹(Group)**:
   - 각 PCIe 디바이스는 PCIe Access Control Services(ACS) 격리 경계에 따라 특정 **IOMMU Group**에 속합니다.
   - 그룹 내 모든 디바이스는 호스트 드라이버에서 언바인드된 후 동일한 VFIO 컨테이너에 바인딩되어야 IOMMU 도메인을 공유할 수 있습니다.
2. **IOMMU DMA 매핑 (`VFIO_IOMMU_MAP_DMA`)**:
   - 유저스페이스 가상 주소(`vaddr`)를 디바이스 I/O 가상 주소(`iova`)에 매핑합니다.
   - 4KB 페이지 단위(`PAGE_SIZE = 4096`) 정렬이 필수적이며, 비정렬 요청 시 `FAIL_UNALIGNED`로 거절됩니다.
   - 프로세스의 고정 메모리 상한(`RLIMIT_MEMLOCK`)을 초과하는 핀(Pin) 요청 시 `FAIL_MEMLOCK_EXCEEDED`로 거절됩니다.
   - 기존에 할당된 IOVA 구간과 겹치는 경우 `FAIL_IOVA_COLLISION`으로 거절됩니다.
3. **IOMMU DMA 접근 검증 (`DMA_ACCESS`)**:
   - 디바이스가 `target_iova`에 `length` 바이트 크기로 DMA 접근(`READ` 또는 `WRITE`)을 시도합니다.
   - 해당 주소가 컨테이너 내 IOMMU 페이지 테이블에 매핑되지 않은 경우 `IOMMU_DMA_FAULT (UNMAPPED_IOVA)`가 발생합니다.
   - 매핑은 존재하나 요청된 접근 권한이 플래그에 없는 경우(예: Read-Only 매핑에 Write 시도) `IOMMU_DMA_FAULT (PERMISSION_DENIED)`가 발생합니다.
4. **IOMMU DMA 언매핑 (`VFIO_IOMMU_UNMAP_DMA`)**:
   - 매핑을 해제하고 IOTLB를 플러시하며, 고정 메모리(`pinned_bytes`)를 회수합니다.
5. **MSI-X 인터럽트 및 eventfd 포워딩 (`CONFIG_MSIX`, `SET_IRQ_EVENTFD`, `TRIGGER_IRQ`)**:
   - 디바이스의 각 MSI-X 인터럽트 벡터를 커널 `eventfd`에 바인딩합니다.
   - 디바이스가 인터럽트를 발생시키면 해당 eventfd 카운터가 증가하여 유저스페이스 스레드를 비동기로 깨웁니다.

당신은 리눅스 커널 VFIO 서브시스템의 IOMMU 격리, DMA 페이지 매핑/검증 및 MSI-X 인터럽트 신호 전달 엔진을 시뮬레이션하는 프로그램을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "memlock_limit": 65536,
    "iommu_groups": {
      "group_1": ["0000:01:00.0", "0000:01:00.1"]
    }
  },
  "commands": [
    { "op": "CREATE_CONTAINER", "container_id": "c1" },
    { "op": "ATTACH_GROUP", "container_id": "c1", "group_id": "group_1" },
    { "op": "MAP_DMA", "container_id": "c1", "iova": 65536, "vaddr": 2130706432, "size": 8192, "flags": ["READ", "WRITE"] },
    { "op": "DMA_ACCESS", "container_id": "c1", "device_id": "0000:01:00.0", "target_iova": 65536, "length": 512, "access_type": "WRITE" }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "containers": {
    "c1": {
      "attached_groups": ["group_1"],
      "active_mappings": 1,
      "pinned_bytes": 8192
    }
  },
  "dma_faults": 0,
  "eventfd_signals": {},
  "events": [ ... ]
}
```
