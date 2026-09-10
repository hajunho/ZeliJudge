# 리눅스 커널 DRM 동기화 객체(Syncobj) 및 GPU 타임라인 펜스 이론

## 1. 암시적 동기화(Implicit Sync)의 종말과 명시적 동기화의 도래

전통적인 Linux 데스크톱 그래픽 스택(OpenGL, X11)은 **암시적 동기화(Implicit Sync)**를 채택했습니다:
- 사용자가 버퍼(GEM BO)를 바인딩하면, 커널 디바이스 드라이버가 버퍼의 `reservation_object`(현 `dma_resv`)에 읽기/쓰기 펜스를 내부적으로 자동 연결했습니다.
- **치명적 한계**:
  1. 유저 공간이 GPU 파이프라인의 종속 관계를 명시적으로 통제할 수 없어, 드라이버가 보수적으로 락을 잡고 파이프라인을 멈추는 오버헤드가 발생했습니다.
  2. Vulkan이나 Direct3D 12와 같이 멀티스레드에서 수천 개의 커맨드 버퍼를 비순차적으로 제출하는 현대 그래픽 엔진에서는 암시적 펜스 경합으로 인해 극심한 프레임 드랍이 유발되었습니다.

---

## 2. DRM Syncobj 및 타임라인 세마포어 (`drivers/gpu/drm/drm_syncobj.c`)

Linux 4.13에서 단일 펜스 동기화 객체로 처음 도입된 뒤, **Linux 5.1**에서 **타임라인 동기화 객체(Timeline Syncobj)**로 비약적인 진화를 이루었습니다:

```c
struct drm_syncobj_timeline_wait {
    __u64 handles;
    __u64 points;
    __u64 timeout_nsec;
    __u32 count_handles;
    __u32 flags; // DRM_SYNCOBJ_WAIT_FLAGS_WAIT_ALL 등
    __u32 first_signaled;
    __u32 pad;
};
```

### 2.1 단조 증가 타임라인 불변식
- 타임라인 객체는 64비트 정수 포인트 $P$를 관리합니다.
- `dma_fence_chain` 자료구조를 통해 여러 개의 펜스가 연결되며, 특정 포인트 $K$가 완료되면 $orall i \le K$인 모든 하위 포인트에 대한 대기 조건이 하드웨어 수준에서 즉각 해소됩니다.

---

## 3. 다중 하드웨어 엔진(Render/Compute/Copy)과 제로 스톨 파이프라인

현대 고성능 GPU는 물리적으로 분리된 하드웨어 큐를 갖추고 있습니다:
1. **Copy Engine (DMA/Blit)**: PCIe 호스트 메모리에서 VRAM으로 텍스처 및 정점 데이터 고속 업로드.
2. **Compute Engine**: GPGPU 셰이더 및 물리 시뮬레이션 연산.
3. **Render Engine**: 래스터화, 프래그먼트 셰이딩 및 디스플레이 백버퍼 합성.

타임라인 세마포어를 활용하면, Copy Engine이 프레임 $N$의 텍스처를 올리는 동안 Render Engine은 프레임 $N-1$을 렌더링하고, Compute Engine은 프레임 $N+1$의 물리 연산을 동시에 병렬 수행할 수 있습니다.
커널은 커맨드 스트리머 하드웨어 레지스터에 펜스 대기 조건을 직접 프로그래밍하여 CPU 개입 없이 GPU 하드웨어 자체적으로 완벽한 파이프라인 동기화를 달성합니다.
