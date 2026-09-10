# Linux 커널 디바이스 드라이버: dma-buf 제로카피 버퍼 공유 및 dma_fence 명시적 동기화 엔진

## 문제 설명

현대 이기종 컴퓨팅(Heterogeneous Computing) 시스템—스마트폰(Android SurfaceFlinger), Wayland 그래픽 컴포지터, 자율주행 센서 퓨전 파이프라인, AI 비전 가속 노드—에서는 카메라 센서(V4L2), 신경망 가속기(NPU), 그래픽스 처리 장치(GPU), 그리고 디스플레이 컨트롤러(DRM/KMS)가 하나의 물리 프레임 버퍼를 실시간으로 공유하며 파이프라인을 형성합니다.

전통적인 유닉스 I/O 모델에서 디바이스 간 데이터를 교환하려면 사용자 공간으로 `read()`한 뒤 타 디바이스로 `write()`해야 하며, 이는 초당 수 기가바이트(GB/s)의 메모리 대역폭 낭비와 극심한 CPU 캐시 오염, 그리고 레이턴시 폭증을 유발합니다.

리눅스 커널의 **`dma-buf` 서브시스템**(`drivers/dma-buf/dma-buf.c`)은 이 문제를 해결하기 위해 물리 메모리를 단 한 번만 할당하고 모든 하드웨어 디바이스가 동일한 물리 메모리 버퍼를 직접 DMA(Direct Memory Access) 방식으로 액세스하는 **제로카피(Zero-Copy) 버퍼 공유 프레임워크**를 제공합니다:

```
+-----------------------------------------------------------------------------------------+
|                  Linux Kernel dma-buf & dma_fence Synchronization Engine                |
+-----------------------------------------------------------------------------------------+
    [ Exporter Device: V4L2 Camera ]
                   |
                   | dma_buf_export()  ---> [ File Descriptor: /dev/dma_buf ]
                   v
         +--------------------+
         |   dma_buf Object   | <--- Physical RAM (CMA Contiguous or Scatterlist sg_table)
         +--------------------+
          /         |         dma_buf_attach()   |         dma_buf_attach()
        v           |                 v
 [ Importer: NPU ]  |       [ Importer: DRM/KMS Display Panel ]
 (IOMMU: 64-bit)    |       (No IOMMU: Requires Contiguous Physical RAM!)
                    v
         [ CPU Access: DMA_BUF_IOCTL_SYNC ]
          - START: Cache Invalidate / Flush
          - END: Restore Hardware Device Ownership

 +---------------------------------------------------------------------------------------+
 | Explicit Synchronization: dma_fence & sync_file                                       |
 |  * Hardware Job A (Camera DMA) ---> creates fence_cam                                 |
 |  * Hardware Job B (NPU Inference) -> WAITING on fence_cam, signals fence_npu          |
 |  * sync_file_merge()            ---> Merges fence_cam + fence_depth into composite    |
 |  * Deadlock Detection           ---> Intercepts circular dependencies (ERR_DEADLOCK)  |
 +---------------------------------------------------------------------------------------+
```

### 핵심 아키텍처 및 커널 메커니즘:
1. **버퍼 송출자 (Exporter) 및 연속 메모리 할당자 (CMA)**:
   - 송출자 디바이스는 물리 메모리 풀(`total_cma_memory_bytes`)에서 연속 메모리(CMA) 또는 분산 페이지(`sg_table`)를 할당하여 `dma_buf` 객체를 생성합니다.
   - 용량 초과 시 `-ENOMEM` 에러를 반환합니다.
2. **버퍼 수입자 (Importer) 및 IOMMU 하드웨어 제약**:
   - 수입자 디바이스는 `dma_buf_attach()`를 통해 버퍼를 연결합니다.
   - IOMMU 하드웨어가 없는 레거시 디바이스(`iommu_supported == false`)는 비연속 분산 버퍼(`contiguous == false`)를 매핑할 수 없으며, 시도 시 `ERR_CONTIGUOUS_REQUIRED` 오류가 발생합니다.
3. **명시적 동기화 (Explicit Synchronization) via `dma_fence`**:
   - 현대 Vulkan/Wayland/Android 렌더링 파이프라인은 암묵적 드라이버 블로킹을 배제하고 `dma_fence`를 통해 비동기 하드웨어 의존성을 표현합니다.
   - 하드웨어 작업(`QUEUE_HARDWARE_JOB`)은 선행 작업의 펜스(`wait_fences`)가 모두 시그널될 때까지 `WAITING` 상태로 대기하며, 하드웨어 인터럽트(`SIGNAL_FENCE`) 시 `RUNNING` 상태로 즉시 깨어납니다.
   - 자신이 완료할 시그널 펜스를 대기 펜스로 지정하는 순환 의존성이 감지되면 `ERR_DEADLOCK`을 발생시켜 GPU/디스플레이 프리징을 방어합니다.
4. **동기화 파일 병합 (`sync_file_merge` / `dma_fence_array`)**:
   - 다중 센서(RGB 카메라, LiDAR, Depth 센서 등)의 완료 펜스를 유저 공간에서 단일 composite 펜스로 병합하여, 모든 센서 데이터가 준비된 순간 디스플레이 컴포지터가 스캔아웃을 개시하도록 제어합니다.
5. **CPU 캐시 일관성 관리 (`DMA_BUF_IOCTL_SYNC`)**:
   - CPU가 버퍼를 직접 읽거나 쓸 때 발생하는 캐시 오염을 방지하기 위해 `START` 시 CPU L1/L2/L3 캐시 라인을 무효화/플러시하고, `END` 시 하드웨어 디바이스 소유권을 복원합니다.

주어진 장치 구성과 일련의 버퍼 익스포트, 디바이스 어태치, 펜스 동기화 및 CPU 캐시 연산 시퀀스를 시뮬레이션하고, 상세 연산 내역(`history`)과 최종 메모리/동기화 요약 통계(`summary`)를 산출하는 엔진을 구현하십시오.

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "total_cma_memory_bytes": 1073741824,
    "devices": [
      {"dev_id": "v4l2_cam", "iommu_supported": true},
      {"dev_id": "npu_core", "iommu_supported": true},
      {"dev_id": "drm_panel", "iommu_supported": false}
    ]
  },
  "operations": [
    {"op": "EXPORT_BUFFER", "buf_id": "frame_0", "exporter_dev": "v4l2_cam", "size_bytes": 33177600, "contiguous_required": true, "timestamp": 10},
    {"op": "ATTACH_DEVICE", "buf_id": "frame_0", "importer_dev": "npu_core", "direction": "DMA_TO_DEVICE", "timestamp": 12},
    {"op": "CREATE_FENCE", "fence_id": "fence_cam_ready", "device": "v4l2_cam", "buf_id": "frame_0", "timestamp": 15},
    {"op": "QUEUE_HARDWARE_JOB", "job_id": "npu_infer_1", "device": "npu_core", "wait_fences": ["fence_cam_ready"], "signal_fence": "fence_npu_done", "duration_ms": 10, "timestamp": 16},
    {"op": "SIGNAL_FENCE", "fence_id": "fence_cam_ready", "timestamp": 25},
    {"op": "RELEASE_BUFFER", "buf_id": "frame_0", "timestamp": 50}
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다 (`separators=(',', ':')`).
```json
{
  "history": [
    {
      "op": "EXPORT_BUFFER",
      "buf_id": "frame_0",
      "status": "SUCCESS",
      "allocated_bytes": 33177600,
      "exporter": "v4l2_cam",
      "detail": "dma-buf exported 33177600 bytes from v4l2_cam (contiguous=True)"
    },
    ...
  ],
  "summary": {
    "active_buffers_count": 0,
    "allocated_cma_bytes": 0,
    "peak_memory_used_bytes": 33177600,
    "total_attachments_count": 0,
    "fences_summary": {
      "created": 1,
      "signaled": 1,
      "unsignaled": 0
    },
    "deadlocks_detected": 0,
    "cpu_sync_operations": 0
  }
}
```
