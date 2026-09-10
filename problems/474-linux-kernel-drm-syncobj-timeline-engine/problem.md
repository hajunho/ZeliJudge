# 리눅스 커널 DRM GPU 커맨드 스트리머 펜스 및 동기화 객체 타임라인 엔진

## 1. 개요 및 배경

현대 고성능 컴퓨터 그래픽스 및 GPGPU 컴퓨팅 API(Vulkan, Direct3D 12, WebGPU, OpenCL)는 CPU와 GPU, 그리고 GPU 내부의 다중 하드웨어 엔진(Render, Compute, DMA Copy) 간에 명시적이고 무잠금(Lockless)인 비동기 동기화를 요구합니다.
과거 전통적인 그래픽 드라이버의 암시적 동기화(Implicit Synchronization) 모델은 커널이 GEM 버퍼 객체마다 펜스를 자동 부착하여 불필요한 파이프라인 정체(Stall)를 유발하고 멀티스레드 렌더링 확장을 가로막았습니다.

이를 해결하기 위해 리눅스 커널은 **DRM Syncobj(Direct Rendering Manager Synchronization Object, `drivers/gpu/drm/drm_syncobj.c`)**를 도입하였으며, **리눅스 5.1 커널**에서 Vulkan 타임라인 세마포어(`VK_KHR_timeline_semaphore`)에 1:1로 대응되는 **타임라인 동기화 객체(Timeline Syncobj)** 아키텍처를 공식 지원하기 시작했습니다.

DRM Syncobj 타임라인의 핵심 아키텍처 원리:
1. **단조 증가 64비트 타임라인 포인트**:
   - 각 동기화 객체는 $0$부터 시작하는 단조 증가 정수 포인트($P$)를 가집니다.
   - 특정 포인트 $K$가 시그널되면, $P \le K$인 모든 선행 포인트 역시 수학적으로 완료된 것으로 간주됩니다.
2. **GPU 하드웨어 커맨드 스트리머(Command Streamer) 의존성 바인딩**:
   - GPU 작업 제출(`SUBMIT_JOB`) 시 대기 펜스 목록(`wait_dependencies: [(handle, point)]`)을 지정합니다.
   - GPU 커맨드 스트리머 하드웨어는 지정된 모든 동기화 객체의 현재 포인트가 요구치를 충족할 때까지 하드웨어 펜스에서 대기하며 실행을 보류합니다.
3. **완료 시그널 및 파이프라인 병렬성 (Cross-Engine Pipeling)**:
   - DMA Copy 엔진이 텍스처를 업로드하는 동안, Compute 엔진이 이전 프레임을 연산하고, Render 엔진이 화면을 그리는 3차원 비동기 파이프라인이 단 하나의 타임라인 객체를 통해 완벽히 조율됩니다.
4. **CPU-GPU 양방향 동기화 및 타임아웃 (`TIMELINE_WAIT`)**:
   - CPU는 `CPU_SIGNAL`을 통해 GPU 펜스를 즉시 해제할 수 있으며, `TIMELINE_WAIT`(`WAIT_ALL` / `WAIT_ANY`)를 통해 다중 GPU 펜스 완료를 타임아웃 제어 하에 폴링/대기합니다.

본 과제에서는 리눅스 커널 `drivers/gpu/drm/drm_syncobj.c` 및 `include/linux/dma-fence.h`의 타임라인 펜스 체인 메커니즘을 모델링하여 다중 GPU 엔진 스케줄러 및 동기화 엔진을 구현합니다.

---

## 2. 아키텍처 다이어그램

```
+-----------------------------------------------------------------------------------------+
|                                    Userspace (Vulkan / Mesa)                            |
|   1. Create Syncobj: handle=1, point=0                                                  |
|   2. Submit Job (COPY Engine): signals (handle=1, point=5)                              |
|   3. Submit Job (COMPUTE Engine): waits (handle=1, point=5), signals (handle=1, pt=10)   |
|   4. Submit Job (RENDER Engine): waits (handle=1, point=10), signals (handle=1, pt=15)  |
+-----------------------------------------------------------------------------------------+
                                         |
                                         | DRM IOCTL (DRM_IOCTL_SYNCOBJ_TIMELINE_*)
                                         v
+-----------------------------------------------------------------------------------------+
|                        Linux Kernel DRM (drivers/gpu/drm/drm_syncobj.c)                 |
|                                                                                         |
|   [ Timeline Syncobj Registry ]                                                         |
|   Handle 1: Timeline Point = 0 -> (Job Copy done) -> 5 -> (Compute done) -> 10 -> 15    |
|                                                                                         |
|   [ GPU Hardware Command Streamer Queues ]                                              |
|   COPY Engine    : [ Job Copy (15 cycles) ] --------> Signals point 5                   |
|   COMPUTE Engine : [ WAITING on pt 5 ] =====> Starts @ Cycle 15 -> Signals point 10     |
|   RENDER Engine  : [ WAITING on pt 10 ] ====> Starts @ Cycle 25 -> Signals point 15     |
+-----------------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------------+
|                        CPU TIMELINE_WAIT (WAIT_ALL / WAIT_ANY)                          |
|   Unblocks as soon as target timeline points are reached or times out cleanly!          |
+-----------------------------------------------------------------------------------------+
```

---

## 3. 핵심 규칙 및 상태 전이 사양

### 3.1 동기화 객체 관리
- `CREATE_SYNCOBJ`: `handle` 식별자로 생성, 초기 포인트는 `initial_point` (기본값 0).
- `RESET_SYNCOBJ`: `handle`의 타임라인 포인트를 0으로 초기화.
- `CPU_SIGNAL`: CPU가 직접 `handle`의 포인트를 `point`로 전진 (`point > current`일 때만 갱신).
- `TRANSFER_POINT`: `src_handle`의 포인트를 `dst_handle`로 복제 전송.

### 3.2 GPU 작업 제출 및 커맨드 스트리머
- `SUBMIT_JOB`:
  - `job_id`: 작업 고유 식별자.
  - `engine`: `"RENDER"`, `"COMPUTE"`, `"COPY"` 중 하나.
  - `execution_cycles`: 작업 실행에 소요되는 GPU 하드웨어 사이클 수.
  - `wait_dependencies`: 선행 대기 조건 리스트 `[{"handle": H, "point": P}]`.
  - `signal_fences`: 작업 완료 시 전진시킬 타임라인 목록 `[{"handle": H, "point": P}]`.
- 각 엔진은 FIFO 큐로 작업을 대기열에 보관하며, 선두 작업의 모든 `wait_dependencies`가 충족(`syncobj[H].point >= P`)되어야 `EXECUTING` 상태로 전환.
- 대기 조건을 충족하지 못한 대기 사이클마다 `pipeline_stalls` 카운터를 증가.

### 3.3 사이클 전진 및 완료 시그널 (`ADVANCE_CYCLES`)
- `delta_cycles`만큼 1사이클씩 시뮬레이션 시간을 전진.
- 실행 중인 작업의 잔여 사이클이 0이 되면:
  - 작업 상태가 `COMPLETED`로 전이되고 완료 목록에 등록.
  - 작업의 모든 `signal_fences`에 정의된 포인트를 해당 동기화 객체에 반영 (`point = max(current, P)`).

### 3.4 타임라인 대기 및 쿼리
- `TIMELINE_WAIT`:
  - `points`: 대기할 `[{"handle": H, "point": P}]` 목록.
  - `wait_all`: `true`이면 모든 포인트 만족 시 완료, `false`이면 하나라도 만족(`WAIT_ANY`) 시 즉시 완료.
  - `timeout_cycles`: 최대 대기 사이클. 초과 시 `status: "TIMEOUT"`.
- `QUERY_TIMELINE`: 지정된 핸들들의 현재 타임라인 포인트를 반환.

---

## 4. 입출력 규격

### 입력 JSON 구조
```json
{
  "config": {},
  "operations": [
    {"type": "CREATE_SYNCOBJ", "handle": 1, "initial_point": 0},
    {"type": "SUBMIT_JOB", "job_id": "job_1", "engine": "RENDER", "execution_cycles": 10, "signal_fences": [{"handle": 1, "point": 5}]},
    {"type": "ADVANCE_CYCLES", "cycles": 15},
    {"type": "QUERY_TIMELINE", "handles": [1]}
  ]
}
```

### 출력 JSON 구조
```json
{
  "operation_results": [
    {
      "op_index": 0,
      "type": "CREATE_SYNCOBJ",
      "handle": 1,
      "initial_point": 0,
      "status": "CREATED"
    },
    {
      "op_index": 1,
      "type": "SUBMIT_JOB",
      "job_id": "job_1",
      "engine": "RENDER",
      "status": "QUEUED"
    },
    {
      "op_index": 2,
      "type": "ADVANCE_CYCLES",
      "advanced_cycles": 15,
      "current_cycles": 15,
      "completed_jobs": ["job_1"]
    },
    {
      "op_index": 3,
      "type": "QUERY_TIMELINE",
      "points": {"1": 5}
    }
  ],
  "final_timeline": {"1": 5},
  "summary": {
    "total_operations": 4,
    "total_cycles": 15,
    "completed_jobs_count": 1,
    "stats": {
      "total_jobs_submitted": 1,
      "total_jobs_completed": 1,
      "total_fence_signals": 1,
      "total_cycles": 15,
      "pipeline_stalls": 0
    }
  }
}
```
