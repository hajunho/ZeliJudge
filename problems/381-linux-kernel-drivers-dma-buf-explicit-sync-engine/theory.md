# Linux 커널 디바이스 드라이버: dma-buf 제로카피 버퍼 공유, dma_fence 및 sync_file 동기화 아키텍처

## 1. 개요 및 배경

현대 고성능 모바일 및 임베디드, 클라우드 AI 시스템은 CPU 단독 연산에서 벗어나 GPU, NPU, DSP, ISP(Image Signal Processor), VPU(Video Processing Unit), 디스플레이 엔진(DRM/KMS) 등 수많은 **이기종 하드웨어 가속기(Heterogeneous Hardware Accelerators)**가 협력하는 파이프라인으로 진화했습니다.

예를 들어 스마트폰에서 4K 60fps 동영상을 녹화하거나 자율주행 차량에서 전방 카메라 피드를 분석하는 상황을 가정해 봅시다:
- 4K 해상도($3840 \times 2160$)의 32비트 RGBA 단일 프레임은 약 $33.18\text{MB}$입니다.
- $60\text{fps}$로 동작할 경우 초당 발생하는 순수 원시 데이터는 약 **$2.0\text{GB/s}$**에 달합니다.
- 이 데이터를 V4L2 카메라 드라이버가 유저 공간으로 복사(`copy_to_user()`)하고, 이를 NPU 드라이버로 전달(`copy_from_user()`), 다시 GPU 및 H.265 인코더로 전달한다면:
  - 초당 $8\sim 10\text{GB/s}$의 메모리 버스 대역폭이 순수 CPU `memcpy`에 의해 고갈됩니다.
  - CPU L3 캐시가 완전히 오염되어 타 프로세스의 실행 성능이 곤두박질치고 발열과 배터리 소모가 폭증합니다.

리눅스 커널 3.3부터 Sumit Semwal 등에 의해 도입된 **`dma-buf`** 서브시스템은 메모리를 커널 물리 프레임에 단 1회만 할당하고, 각 디바이스 드라이버가 동일한 버퍼 포인터와 DMA 주소를 공유하는 **진정한 제로카피(Zero-Copy) 버퍼 공유**를 실현했습니다.

---

## 2. dma-buf 핵심 구조 및 라이프사이클

### 2.1 익스포터(Exporter)와 임포터(Importer)
- **익스포터(Exporter)**: 물리 메모리를 할당하고 관리하는 주체(예: V4L2 카메라 또는 ION/CMA 드라이버).
  - `dma_buf_ops` 가상 함수 테이블(`attach`, `detach`, `map_dma_buf`, `unmap_dma_buf`, `release`, `begin_cpu_access`, `end_cpu_access`)을 구현합니다.
  - `dma_buf_export()`를 호출하여 `struct dma_buf`를 생성하고, 이를 익명 파일 디스크립터(`fd`)로 사용자 공간에 노출합니다.
- **임포터(Importer)**: 공유된 버퍼를 소비하는 주체(예: NPU, DRM 디스플레이 드라이버).
  - 사용자 공간으로부터 전달받은 `fd`를 `dma_buf_get(fd)`로 열어 커널 포인터를 획득합니다.
  - `dma_buf_attach()`를 호출하여 디바이스와 버퍼 간의 연결 객체(`struct dma_buf_attachment`)를 생성합니다.
  - `dma_buf_map_attachment()`를 호출하여 물리 메모리 분산 리스트(`sg_table`)를 디바이스의 DMA 주소 공간에 매핑합니다.

### 2.2 IOMMU 제약과 CMA (Contiguous Memory Allocator)
- 최신 GPU나 NPU는 IOMMU(I/O Memory Management Unit)를 탑재하고 있어 물리적으로 흩어진 페이지들(Non-contiguous scatterlist)을 가상으로 연속된 주소 공간으로 매핑할 수 있습니다.
- 반면 저비용 임베디드 디스플레이 컨트롤러나 레거시 카메라 인터페이스는 IOMMU가 없으므로 **물리적으로 완전히 연속된 물리 메모리(Contiguous Physical Pages)**만을 요구합니다.
- 비연속 분산 버퍼를 IOMMU 미지원 디바이스에 연결하려 할 경우 드라이버는 즉각 에러(`ERR_CONTIGUOUS_REQUIRED`)를 반환하여 하드웨어 메모리 폴트를 방어합니다.

---

## 3. 명시적 동기화: dma_fence 및 sync_file

과거 안드로이드와 그래픽 드라이버는 하드웨어 명령을 큐잉할 때 드라이버 내부에서 커널 뮤텍스나 스핀락으로 블로킹하는 **암묵적 동기화(Implicit Synchronization)**를 사용했습니다. 그러나 이는 GPU가 렌더링하는 동안 CPU 스레드가 블로킹되어 UI 버벅임(Jank)과 우선순위 역전, 데드락을 유발했습니다.

Linux 4.9부터 도입된 **명시적 동기화(Explicit Synchronization)**는 드라이버 블로킹을 배제하고 비동기 타임라인 객체인 **`dma_fence`**(`include/linux/dma-fence.h`)를 사용합니다:

### 3.1 dma_fence 상태 전이
- `UNSIGNALED`: 하드웨어 DMA 작업(렌더링, 센서 캡처)이 진행 중인 상태.
- `SIGNALED`: 하드웨어 인터럽트 서비스 루틴(ISR)이 호출되어 작업이 완료된 상태 (`dma_fence_signal()`).

작업 $B$가 작업 $A$의 결과물을 사용해야 할 경우, 작업 $B$는 CPU를 블로킹하지 않고 $A$의 펜스를 `wait_fences`로 등록한 채 즉시 반환됩니다. 하드웨어 스케줄러는 $A$의 펜스가 시그널되는 순간 하드웨어 레벨에서 $B$를 구동합니다.

### 3.2 sync_file: 유저 공간 펜스 전달 및 병합
- `sync_file`(`drivers/dma-buf/sync_file.c`)은 커널 내부의 `dma_fence`를 유저 공간 프로세스가 Unix Domain Socket을 통해 타 프로세스(예: 앱 $\rightarrow$ SurfaceFlinger)로 전송할 수 있도록 파일 디스크립터로 래핑합니다.
- `ioctl(fd, SYNC_IOC_MERGE)`를 호출하면 커널 내부에서 `dma_fence_array`가 생성되어 복수의 펜스들을 단일 복합 펜스로 병합(Merge)합니다.

---

## 4. CPU 캐시 일관성 관리 (`DMA_BUF_IOCTL_SYNC`)

하드웨어 디바이스와 CPU가 캐시 일관성(Cache Coherency)을 하드웨어적으로 보장하지 않는 아키텍처(예: ARM Cortex-A + Mali GPU)에서는, CPU가 버퍼를 읽거나 쓸 때 CPU 캐시와 물리 DRAM 간의 불일치가 발생합니다:
- **`DMA_BUF_SYNC_START`**:
  - `READ`: CPU L1/L2 캐시 라인을 무효화(Invalidate)하여 DRAM에 기록된 하드웨어 최신 데이터를 캐시로 읽어옵니다.
  - `WRITE`: CPU 캐시 버퍼를 준비합니다.
- **`DMA_BUF_SYNC_END`**:
  - `WRITE`: CPU가 변경한 캐시 데이터를 물리 DRAM으로 플러시(Clean/Flush)하여 하드웨어 DMA 컨트롤러가 최신 데이터를 볼 수 있도록 보장합니다.
