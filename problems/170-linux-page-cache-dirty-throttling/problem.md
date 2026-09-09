# 디스크 용량도 넉넉한데 왜 갑자기 write() 시스템 콜이 15초 동안 굳어버려요?!: Linux 페이지 캐시 더티 스로틀링과 `vm.dirty_ratio` vs 바이트 단위 튜닝 & `sync_file_range`

## 1. 장애 현장: 빅데이터 파이프라인에서 발생한 의문의 60초 D-State 멈춤

64GB 메모리를 장착한 최신 Linux 서버에서 대규모 로그 수집 파이프라인을 운영하던 중 기이한 장애가 발생했습니다.

디스크 사용량은 40% 미만으로 넉넉했고 메모리 역시 80% 이상 여유로웠는데, 애플리케이션의 평소 0.1ms 미만이던 `write()` 시스템 콜이 갑자기 **15초에서 길게는 60초 이상 커널 내부에서 굳어버리는 치명적인 동결 현상**이 주기적으로 발생했습니다.

시스템 콜 트레이스(`strace`)와 커널 스택(`cat /proc/<pid>/stack`)을 추적한 결과, 충격적인 커널 스택이 포착되었습니다:
```
[kworker/flush] Waking up as dirty pages exceed 10% (6.5 GB)...
[App Thread] write(fd, buf, 800MB) -> Kernel Page Cache...
[App Thread] Dirty pages reached 20% (13.1 GB)!
[Kernel Panic-level Throttle] Calling balance_dirty_pages_ratelimited()!
[Kernel] Forcing user application thread into TASK_UNINTERRUPTIBLE (D-state)!
[Kernel] User thread sleeping and doing synchronous disk writeback for 68,470 ms!
[Kubernetes] Liveness probe failed 3 times! Pod killed: OOMKilled/Deadlock suspected!
```

기본값인 `vm.dirty_ratio = 20` 때문에 64GB 머신에서 무려 13.1GB의 더티 페이지가 쌓였고, 100 MB/s 속도의 디스크가 이를 소화하느라 유저 프로세스가 커널 내부에서 68초 동안 감옥에 갇힌 것입니다!

리눅스 커널의 페이지 캐시 메커니즘(`vm.dirty_background_ratio`, `vm.dirty_ratio`, `vm.dirty_bytes`, `sync_file_range`, `O_DIRECT`)을 정밀하게 모사하는 스토리지 시뮬레이션 엔진을 구현하여, 이 재앙적 스톨을 진압하고 고성능 스토리지 I/O를 달성하세요!

---

## 2. 요구 사항 및 시뮬레이션 규칙

입력으로 주어지는 시스템 환경(`system`)과 시간순 워크로드(`workload`)를 이산 초 단위(1 tick = 1초)로 시뮬레이션하여 메트릭과 타임라인을 산출해야 합니다.

### 2.1 시스템 파라미터 및 임계치 도출
- `total_memory_mb`: 전체 시스템 RAM 크기 (MB)
- `disk_write_speed_mb_s`: 물리 디스크의 초당 지속 쓰기 대역폭 (MB/s)
- **더티 백그라운드 임계치(`effective_dirty_bg_threshold_mb`)**:
  - `dirty_background_bytes_mb`가 주어지면 해당 값을 직접 사용.
  - 그렇지 않으면 `int(total_memory_mb * dirty_background_ratio)`로 계산 (기본 비율 0.10).
- **더티 스로틀링 임계치(`effective_dirty_throttle_threshold_mb`)**:
  - `dirty_bytes_mb`가 주어지면 해당 값을 직접 사용.
  - 그렇지 않으면 `int(total_memory_mb * dirty_ratio)`로 계산 (기본 비율 0.20).
- `io_mode`: `"BUFFERED"`, `"STREAMING_SYNC"`, 또는 `"DIRECT_IO"`.
- `streaming_sync_chunk_mb`: 스트리밍 동기화 청크 단위 (기본값: 64 MB).

### 2.2 I/O 모드별 동작 규칙

#### [A] Direct I/O (`io_mode == "DIRECT_IO"`)
- 페이지 캐시를 100% 우회합니다 (`dirty_memory_mb = 0`).
- `WRITE` 요청 시 지연 시간은 디스크 물리 속도에 정확히 비례합니다:
  $$\text{latency\_ms} = \frac{\text{size\_mb}}{\text{disk\_write\_speed\_mb\_s}} \times 1000$$
- `FSYNC` 요청 시 이미 디스크에 기록되었으므로 1.0ms 즉시 반환.

#### [B] 버퍼링 I/O (`io_mode == "BUFFERED"` 또는 `"STREAMING_SYNC"`)
매 1초(Tick)마다 다음 순서로 실행됩니다:
1. **백그라운드 디스크 플러시**:
   디스크 컨트롤러는 현재 더티 메모리에서 최대 `disk_write_speed_mb_s`만큼을 물리 디스크로 비동기 배출합니다.
2. **`WRITE` 작업 처리**:
   - `total_written_mb += size_mb`, `dirty_mb += size_mb`.
   - **`STREAMING_SYNC` 모드**:
     누적 미동기화 크기가 `streaming_sync_chunk_mb` 이상이면, 해당 분량을 즉시 디스크로 플러시하고 그에 비례하는 지연 시간(`drain / disk_speed * 1000 ms`)을 소모하며 `STREAMING_SYNC_DRAIN` 상태가 됩니다.
   - **`BUFFERED` 모드**:
     - 만약 `dirty_mb >= throttle_threshold_mb`이면:
       커널의 `balance_dirty_pages_ratelimited`가 발동하여 **더티 페이지가 백그라운드 임계치(`bg_threshold_mb`) 이하로 떨어질 때까지 유저 스레드가 동기 블로킹**됩니다:
       $$\text{excess} = \text{dirty\_mb} - \text{bg\_threshold\_mb}$$
       $$\text{latency\_ms} = \frac{\text{excess}}{\text{disk\_write\_speed\_mb\_s}} \times 1000$$
       `d_state_stall_count += 1`, 상태는 `"D_STATE_THROTTLED"`가 됩니다.
     - 임계치 미만이면 빠른 메모리 복사 지연 시간인 **0.5ms**만 소모하며 정상 반환합니다.
3. **`FSYNC` 작업 처리**:
   - 현재 페이지 캐시에 남아있는 모든 `dirty_mb`를 물리 디스크로 전부 비워낼 때까지 동기 블로킹됩니다:
     $$\text{fsync\_stall\_ms} = \frac{\text{dirty\_mb}}{\text{disk\_write\_speed\_mb\_s}} \times 1000$$
   - `dirty_mb`는 0으로 초기화됩니다.

### 2.3 판정 기준 (`verdict`)
- `io_mode == "DIRECT_IO"` $\to$ `"DIRECT_IO_PREDICTABLE"`
- `max_write_stall_ms >= 5000.0` (5초 이상 정지) $\to$ `"CATASTROPHIC_DIRTY_STALL"`
- `1000.0 <= max_write_stall_ms < 5000.0` $\to$ `"MODERATE_THROTTLE_SPIKE"`
- 그 외 더티 메모리가 존재했던 경우 $\to$ `"SMOOTH_BACKGROUND_WRITEBACK"`
- 그 외 $\to$ `"IDLE_CLEAN"`

---

## 3. 입출력 포맷

### 입력 형식 (JSON on stdin)
```json
{
  "system": {
    "total_memory_mb": 65536,
    "disk_write_speed_mb_s": 100,
    "dirty_background_ratio": 0.10,
    "dirty_ratio": 0.20,
    "io_mode": "BUFFERED"
  },
  "workload": [
    {"tick": 1, "op": "WRITE", "size_mb": 800},
    {"tick": 2, "op": "WRITE", "size_mb": 800}
  ]
}
```

### 출력 형식 (JSON on stdout)
```json
{
  "status": "SUCCESS",
  "summary": {
    "total_memory_mb": 65536,
    "disk_write_speed_mb_s": 100,
    "effective_dirty_bg_threshold_mb": 6553,
    "effective_dirty_throttle_threshold_mb": 13107,
    "io_mode": "BUFFERED"
  },
  "metrics": {
    "total_written_mb": 1600,
    "total_flushed_mb": 200,
    "max_dirty_memory_mb": 1500,
    "max_write_stall_ms": 0.5,
    "total_stall_time_ms": 1.0,
    "d_state_stall_count": 0,
    "fsync_stall_ms": 0.0,
    "p99_latency_ms": 0.5,
    "verdict": "SMOOTH_BACKGROUND_WRITEBACK"
  },
  "sample_timeline": [...]
}
```
