# 문제 425: 리눅스 커널 가상화 및 하드웨어 오프로드: vDPA(vhost Data Path Acceleration) 버스 및 VirtIO 하드웨어 가속 엔진

## 1. 개요 (Overview)

클라우드 데이터센터와 초고성능 가상화 환경에서 가상 머신(VM)과 컨테이너의 네트워크 I/O 성능은 서비스의 처리량과 지연 시간을 결정하는 핵심 지표입니다. 과거에는 소프트웨어 에뮬레이션 기반의 **VirtIO-net**(QEMU 또는 호스트 커널 vhost-net)과 물리 디바이스를 직접 가상 머신에 통과시키는 **SR-IOV(Single Root I/O Virtualization)**가 양대 축을 이루었습니다:
- **소프트웨어 VirtIO**: 하이퍼바이저 컨텍스트 스위칭(VM-Exit) 및 CPU 인터럽트 오버헤드로 인해 100GbE 이상의 초고속 라인 레이트(Line Rate) 처리에 한계가 있었습니다.
- **SR-IOV**: 하드웨어 전용 DMA를 통해 초저지연을 달성하지만, 디바이스의 내부 레지스터와 하드웨어 상태가 벤더 독점적(Proprietary)이어서 클라우드의 핵심 기능인 **가상 머신 실시간 라이브 마이그레이션(Live Migration)**이 불가능했습니다.

이를 근본적으로 해결하기 위해 리눅스 커널 5.7+ 및 6.x 시리즈에 도입된 혁신적인 표준 프레임워크가 바로 **vDPA(vhost Data Path Acceleration / `drivers/vhost/vdpa.c`, `drivers/vdpa/`)**입니다.

vDPA는 데이터 플레인(Data Plane)과 제어 플레인(Control Plane)을 엄격히 분리합니다:
1. **데이터 플레인**: 표준 OASIS VirtIO 링 버퍼(`vring`) 구조를 하드웨어(SmartNIC / DPU / FPGA)가 직접 DMA로 소비하여 0-CPU-오버헤드의 초고속 패킷 처리를 달성합니다.
2. **제어 플레인**: 리눅스 커널의 vDPA 버스 드라이버와 vhost-vdpa 서브시스템이 관리하여, 하드웨어 비종속적인 기능 협상(`VIRTIO_NET_F_*`)과 가상 IOMMU(vhost IOTLB) 매핑을 표준화합니다.
3. **무중단 라이브 마이그레이션**: 마이그레이션 시점에 **섀도우 버트큐(SVQ, Shadow Virtqueue)** 모드로 전환하여 하드웨어 링을 가로채고, DMA 변경 메모리를 **더티 페이지(Dirty Page)**로 실시간 추적함으로써 SR-IOV급 성능과 VirtIO급 마이그레이션 유연성을 동시에 보장합니다.

본 과제에서는 리눅스 커널 vDPA 서브시스템의 핵심 아키텍처를 모델링합니다. 디바이스 등록, 모던 VirtIO v1.0+ 기능 협상, IOMMU DMA 매핑/언매핑 및 결함(Fault) 탐지, 고속 패킷 DMA 전송, 멀티큐(MQ) 스케줄링, 그리고 실시간 라이브 마이그레이션(SVQ 활성화 및 더티 페이지 추적, 장치 상태 스냅샷 동결)을 완벽히 시뮬레이션하는 엔진을 구현합니다.

---

## 2. 시스템 아키텍처 및 3대 가상화 모델 비교

```
[1. Pure Software VirtIO]
 Guest VM  ──► Virtqueue ──► [VM-Exit] ──► Host QEMU/vhost ──► Host NIC
 (High CPU Overhead, Full Live Migration Support)

[2. Hardware SR-IOV]
 Guest VM  ──► Direct PCIe VF DMA ────────────────────────► Hardware NIC
 (Zero CPU Overhead, NO Live Migration Support / Hardware Lock-in)

[3. vDPA (vhost Data Path Acceleration)]
 +-------------------------------------------------------------------------+
 |                                Guest VM                                 |
 |   Standard VirtIO-Net Driver (Standard OASIS vring / descs / avail)     |
 +------------------------------------+------------------------------------+
                                      |
       [Control Plane: Standardized]  |  [Data Plane: Direct Hardware DMA]
       vhost-vdpa / drivers/vdpa/     |  Zero Hypervisor Context Switch!
                                      v
 +------------------------------------+------------------------------------+
 |                    vDPA Device (SmartNIC / DPU ASIC)                    |
 |   - Hardware VirtIO Queue Parser (vq 0, 1, ... max_vqs)                 |
 |   - IOTLB Engine (Translates Guest IOVA -> Host Physical Address HPA)   |
 |   - Shadow Virtqueue (SVQ) Engine for Live Migration & Dirty Logging    |
 +-------------------------------------------------------------------------+
```

---

## 3. 세부 동작 명세 (Operational Specifications)

### 3.1 엔진 구성 매개변수 (`config`)
- `max_vqs`: 지원 가능한 최대 버트큐 개수 (기본값 `4`).
- `features_supported`: 디바이스가 하드웨어적으로 지원하는 기능 플래그 목록 (문자열 배열, 예: `["VIRTIO_F_VERSION_1", "VIRTIO_NET_F_MRG_RXBUF", "VIRTIO_NET_F_MQ", "VIRTIO_F_LOG_ALL"]`).

### 3.2 이벤트 처리 규칙

1. **`VDPA_DEV_ADD` (`time`, `dev_name`, `mgmt_dev`)**:
   - 관리 버스(Management Device)에 신규 vDPA 디바이스를 생성 및 등록합니다.
   - `event_logs`에 `VDPA_DEV_ADD_SUCCESS` 이벤트를 기록합니다.

2. **`VDPA_SET_FEATURES` (`time`, `features`)**:
   - 게스트 드라이버와 호스트 간 기능 협상(Feature Negotiation)을 수행합니다.
   - 요청된 `features`와 `features_supported`의 교집합을 구합니다.
   - **모던 VirtIO 필수 검증**: 협상된 기능 집합에 `VIRTIO_F_VERSION_1`(VirtIO v1.0 표준)이 포함되어 있지 않으면, 레거시 비호환으로 판정하여 `VDPA_ERROR`(`LEGACY_VIRTIO_NOT_SUPPORTED`)를 기록하고 `False`를 반환합니다.
   - 통과 시 `features_negotiated`를 갱신하고 `VDPA_FEATURES_NEGOTIATED` 이벤트를 기록합니다.

3. **`VDPA_DMA_MAP` (`time`, `iova`, `hpa`, `size`, `perm` [기본 "RW"])**:
   - vhost-vdpa IOTLB 변환 테이블에 가상 IOVA 주소와 호스트 물리 주소(HPA) 간의 매핑을 등록합니다.
   - `event_logs`에 `VDPA_DMA_MAP_SUCCESS`를 기록합니다.

4. **`VDPA_DMA_UNMAP` (`time`, `iova`, `size`)**:
   - IOTLB에서 해당 `iova` 매핑을 제거합니다.
   - `event_logs`에 `VDPA_DMA_UNMAP_SUCCESS`를 기록합니다.

5. **`VDPA_SET_VRING_STATE` (`time`, `vq_idx`, `num`, `avail_idx`, `used_idx`)**:
   - 특정 버트큐(`vq_idx`)의 크기(`num`) 및 링 포인터(`avail_idx`, `used_idx`)를 설정합니다.
   - `event_logs`에 `VDPA_SET_VRING_STATE`를 기록합니다.

6. **`VDPA_SET_VRING_ENABLE` (`time`, `vq_idx`, `enable`)**:
   - 해당 버트큐의 하드웨어 활성화 상태(`enabled`)를 설정합니다.
   - `event_logs`에 `VDPA_SET_VRING_ENABLE`을 기록합니다.

7. **`VDPA_PACKET_TRANSMIT` (`time`, `vq_idx`, `desc_iova`, `len`)**:
   - 지정된 버트큐(`vq_idx`)를 통해 패킷을 하드웨어 DMA로 전송합니다.
   - 해당 큐가 비활성화(`enabled == False`) 상태이면 실패합니다.
   - **IOMMU DMA 주소 변환 (IOTLB Lookup)**:
     - `desc_iova`가 `iotlb`에 등록되어 있지 않으면, `dma_errors`를 1 증가시키고 `VDPA_DMA_FAULT` 이벤트를 기록하며 중단합니다.
     - 매핑이 존재하면 해당 엔트리의 `hpa`를 획득합니다.
   - 링 포인터 갱신: `avail_idx = (avail_idx + 1) % 65536`, `used_idx = (used_idx + 1) % 65536`.
   - `packets_transmitted`를 1 증가시킵니다.
   - **라이브 마이그레이션 더티 트래킹**:
     - 현재 라이브 마이그레이션이 진행 중(`is_migrating == True`)인 경우, 패킷이 참조한 물리 메모리 `hpa`를 `dirty_pages` 집합에 추가합니다.
   - `event_logs`에 `VDPA_PACKET_TX_SUCCESS` 이벤트를 기록합니다.

8. **`VDPA_LIVE_MIGRATE_START` (`time`, `use_svq` [기본 True])**:
   - 실시간 라이브 마이그레이션을 개시합니다.
   - `is_migrating = True`, `svq_active = use_svq`, 모든 큐의 `svq_enabled = use_svq`로 설정합니다.
   - `migration_logs`에 `LIVE_MIGRATION_STARTED`를 기록하고, `event_logs`에 `VDPA_MIGRATION_START`를 기록합니다.

9. **`VDPA_SUSPEND_AND_SAVE_STATE` (`time`)**:
   - 마이그레이션 최종 전환(Switchover) 단계에서 장치 링을 일시 중단(Suspend)하고 하드웨어 상태를 스냅샷합니다.
   - `is_migrating = False`, `migration_checkpoints`를 1 증가시킵니다.
   - 각 큐의 최종 링 인덱스(`avail_idx`, `used_idx`) 및 누적된 `dirty_pages`를 수집하여 스냅샷 딕셔너리를 생성합니다.
   - `migration_logs`에 `DEVICE_SUSPENDED_STATE_SAVED`를 기록하고, `event_logs`에 성공을 기록합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 입력 형식 (Standard Input, JSON)
```json
{
  "config": {
    "max_vqs": 4,
    "features_supported": ["VIRTIO_F_VERSION_1", "VIRTIO_NET_F_MRG_RXBUF", "VIRTIO_NET_F_MQ", "VIRTIO_F_LOG_ALL"]
  },
  "trace": [
    {"time": 10, "type": "VDPA_DEV_ADD", "dev_name": "vdpa0", "mgmt_dev": "pci/0000:03:00.0"},
    {"time": 20, "type": "VDPA_SET_FEATURES", "features": ["VIRTIO_F_VERSION_1", "VIRTIO_NET_F_MRG_RXBUF"]},
    {"time": 30, "type": "VDPA_DMA_MAP", "iova": "0x1000", "hpa": "0x80001000", "size": 4096, "perm": "RW"},
    {"time": 40, "type": "VDPA_SET_VRING_STATE", "vq_idx": 1, "num": 256, "avail_idx": 0, "used_idx": 0},
    {"time": 50, "type": "VDPA_SET_VRING_ENABLE", "vq_idx": 1, "enable": true},
    {"time": 60, "type": "VDPA_PACKET_TRANSMIT", "vq_idx": 1, "desc_iova": "0x1000", "len": 1514}
  ]
}
```

### 출력 형식 (Standard Output, Compact JSON)
공백 없는 단일 라인 JSON 문자열(`separators=(',', ':')`)로 출력합니다:
```json
{"summary":{"packets_transmitted":1,"dma_errors":0,"migration_checkpoints":0,"dirty_pages_logged":0,"features_negotiated":["VIRTIO_F_VERSION_1","VIRTIO_NET_F_MRG_RXBUF"],"iotlb_entries":1},"vqs":{"vq_0":{"num":256,"avail_idx":0,"used_idx":0,"enabled":false,"svq_enabled":false},"vq_1":{"num":256,"avail_idx":1,"used_idx":1,"enabled":true,"svq_enabled":false},"vq_2":{"num":256,"avail_idx":0,"used_idx":0,"enabled":false,"svq_enabled":false},"vq_3":{"num":256,"avail_idx":0,"used_idx":0,"enabled":false,"svq_enabled":false}},"migration_logs":[],"event_logs":[{"time":10,"event":"VDPA_DEV_ADD_SUCCESS","dev_name":"vdpa0","mgmt_dev":"pci/0000:03:00.0"},{"time":20,"event":"VDPA_FEATURES_NEGOTIATED","features":["VIRTIO_F_VERSION_1","VIRTIO_NET_F_MRG_RXBUF"]},{"time":30,"event":"VDPA_DMA_MAP_SUCCESS","iova":"0x1000","hpa":"0x80001000","size":4096,"perm":"RW"},{"time":40,"event":"VDPA_SET_VRING_STATE","vq_idx":1,"num":256,"avail_idx":0,"used_idx":0},{"time":50,"event":"VDPA_SET_VRING_ENABLE","vq_idx":1,"enable":true},{"time":60,"event":"VDPA_PACKET_TX_SUCCESS","vq_idx":1,"hpa":"0x80001000","len":1514,"svq_forwarded":false}]}
```
