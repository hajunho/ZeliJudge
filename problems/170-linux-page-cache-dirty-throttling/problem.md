# 디스크 용량도 넉넉한데 왜 갑자기 write() 시스템 콜이 15초 동안 굳어버려요?!: Linux 페이지 캐시 더티 스로틀링(Dirty Throttling)과 `vm.dirty_ratio` vs 바이트 단위 튜닝 & `sync_file_range`

## 1. 장애 현장: 64GB 메모리 서버에서 터진 68초간의 D-State 동결 참사

글로벌 핀테크 결제 플랫폼의 실시간 트랜잭션 수집 및 대규모 배치 덤프 서비스에서 기이하고 치명적인 장애가 발생했습니다.

최근 서버 하드웨어를 64GB RAM과 고성능 NVMe SSD로 업그레이드한 후, 새벽 정산 배치 작업이나 대규모 로그 압축 덤프가 실행될 때마다 멀쩡하던 백엔드 프로세스의 `write()` 시스템 콜이 10초에서 최대 **68초간 완전히 먹통(Hang)**이 되는 현상이 발생했습니다:

```
[User App: Batch Ingest / WAL Writer]
      |
      | 1. write(fd, buf, 800MB/s) -> Linux Kernel Page Cache (초고속 RAM 복사 0.5ms)
      v
[Linux Page Cache (Dirty Pages Accumulation)]
      | 2. 더티 페이지 폭증 (1GB -> 5GB -> 10GB -> 13GB!)
      |    (vm.dirty_ratio = 20% -> 64GB의 20% = 13.1GB 누적 허용)
      v
[Kernel: balance_dirty_pages_ratelimited()]
      | 3. 임계치(13.1GB) 도달 경고!
      |    "더티 페이지가 너무 많다! 사용자 프로세스는 즉시 쓰기를 멈추고 디스크에 직접 동기 플러시하라!"
      v
[Process State: TASK_UNINTERRUPTIBLE (D-State Freeze!)]
      - write() 시스템 콜 내부에서 68.4초간 슬립! (Kill 신호도 안 먹힘!)
      - Kubernetes Liveness Probe Timeout! (3회 연속 실패로 Pod 강제 Kill)
      - 서비스 다운타임 발생 및 타임아웃 캐스케이딩 장애!
```

시스템 엔지니어들은 의아해했습니다:
> "디스크 남은 용량도 테라바이트 단위로 넉넉하고, I/O 대역폭도 남아있는데 왜 write()가 68초 동안 멈출까요? 게다가 프로세스가 `kill -9`조차 먹히지 않는 `D` 상태(TASK_UNINTERRUPTIBLE)로 뻗어버립니다!"

사후 커널 프로파일링(`perf`, `ftrace`) 결과, 원인은 Linux 가상 메모리 관리자의 **더티 페이지 스로틀링(Dirty Throttling)** 메커니즘이었습니다.
RAM 용량이 4GB~8GB이던 시절에 설정된 기본값 `vm.dirty_ratio = 20`이, 64GB~128GB의 현대 대용량 메모리 서버에서는 **13GB~25GB**라는 어마어마한 양의 더티 데이터를 RAM에 쌓아두도록 방치했던 것입니다.
결국 임계치를 넘는 순간 커널은 I/O 붕괴를 막기 위해 사용자 프로세스를 강제로 `D-state`로 재우고 초당 100MB/s 속도로 수 기가바이트의 데이터를 직접 디스크에 배출하도록 강제했습니다.

또한, 나이브하게 버퍼링 쓰기 후 마지막에 호출하는 `fsync()` 역시 수 기가바이트의 더티 페이지를 한꺼번에 디스크에 쓸어 넣느라 수십 초간 블로킹되는 **fsync 절벽(fsync latency cliff)**을 유발했습니다.

이에 인프라 엔지니어링 팀은:
1. 비율 기반(`vm.dirty_ratio`) 대신 절대 바이트 기반(`vm.dirty_bytes`, `vm.dirty_background_bytes`) 커널 파라미터 튜닝
2. 선제적 청크 스트리밍 동기화(`sync_file_range` / 백그라운드 주기적 배출)
3. Direct I/O(`O_DIRECT`)를 통한 예측 가능한 지연 시간 보장

을 비교 검증하는 커널 스토리지 I/O 시뮬레이터를 개발하기로 결정했습니다.

---

## 2. 요구 사항 및 알고리즘 명세

입력으로 주어지는 시스템 환경(`system`)과 시간(초 단위 틱, `workload`)별 I/O 요청을 시뮬레이션하여 커널 페이지 캐시 상태, 쓰기 지연 시간, 스톨 횟수, 최종 메트릭(`metrics`)과 타임라인(`sample_timeline`)을 산출해야 합니다.

### 2.1 시스템 파라미터 및 임계치 도출
`system` 설정 객체로부터 다음 파라미터를 파싱합니다:
- `total_memory_mb`: 전체 메모리 용량 (기본값: 16384 MB)
- `disk_write_speed_mb_s`: 디스크 물리 순차 쓰기 대역폭 (기본값: 100 MB/s)
- `io_mode`: `"BUFFERED"`, `"STREAMING_SYNC"`, `"DIRECT_IO"` 중 하나 (기본값: `"BUFFERED"`)
- `streaming_sync_chunk_mb`: 스트리밍 동기화 청크 크기 (기본값: 64 MB)

**더티 메모리 임계치 계산 규칙**:
1. 백그라운드 플러시 임계치 (`effective_dirty_bg_threshold_mb`):
   - `dirty_background_bytes_mb`가 명시되어 있다면 해당 값을 직접 사용합니다.
   - 명시되지 않았다면 `int(total_memory_mb * dirty_background_ratio)`로 계산합니다 (기본 비율: 0.10).
2. 프로세스 스로틀링 임계치 (`effective_dirty_throttle_threshold_mb`):
   - `dirty_bytes_mb`가 명시되어 있다면 해당 값을 직접 사용합니다.
   - 명시되지 않았다면 `int(total_memory_mb * dirty_ratio)`로 계산합니다 (기본 비율: 0.20).

---

### 2.2 틱(Tick, 1초 단위)별 I/O 시뮬레이션 규칙

각 틱(Tick)은 1초의 시간 단위를 나타내며, `op` (`"WRITE"`, `"FSYNC"`, `"IDLE"`), `size_mb`를 가집니다.

#### A. Direct I/O 모드 (`io_mode == "DIRECT_IO"`)
페이지 캐시를 완전히 우회(Bypass)하여 NVMe/SATA 컨트롤러로 직접 DMA 전송을 수행합니다:
- `dirty_memory_mb`는 항상 0을 유지합니다.
- `op == "WRITE"`:
  - `latency_ms = round((size_mb / disk_write_speed_mb_s) * 1000.0, 2)`
  - `total_written_mb += size_mb`, `total_flushed_mb += size_mb`
  - `state = "DIRECT_DMA"`
- `op == "FSYNC"`:
  - 플러시할 캐시가 없으므로 파일 메타데이터 동기화 지연만 발생: `latency_ms = 1.0`, `state = "FSYNC_NOOP"`
- `op == "IDLE"`:
  - `latency_ms = 0.0`, `state = "IDLE"`

---

#### B. 버퍼링 I/O 모드 (`BUFFERED`, `STREAMING_SYNC`)
1. **스텝 1: 백그라운드 플러셔 (Async Flusher) 동작**:
   - 매 1초 틱마다 디스크 하드웨어는 백그라운드에서 최대 `disk_write_speed_mb_s`만큼의 더티 페이지를 비동기로 디스크에 기록합니다:
     $$\text{flushed} = \min(\text{dirty\_mb}, \; \text{disk\_write\_speed\_mb\_s})$$
     $$\text{dirty\_mb} \leftarrow \text{dirty\_mb} - \text{flushed}, \quad \text{total\_flushed\_mb} \leftarrow \text{total\_flushed\_mb} + \text{flushed}$$
2. **스텝 2: 작업(`op`) 처리**:
   - **`op == "WRITE"`**:
     - 데이터를 페이지 캐시에 적재합니다:
       $$\text{total\_written\_mb} \mathrel{+}= \text{size\_mb}, \quad \text{dirty\_mb} \mathrel{+}= \text{size\_mb}, \quad \text{uncommitted\_sync\_mb} \mathrel{+}= \text{size\_mb}$$
     - 피크 더티 메모리 갱신: $\text{peak\_dirty\_mb} = \max(\text{peak\_dirty\_mb}, \; \text{dirty\_mb})$
     - **조건 분기**:
       1. **선제적 스트리밍 동기화 (`io_mode == "STREAMING_SYNC"` and `uncommitted_sync_mb >= streaming_sync_chunk_mb`)**:
          - 애플리케이션이 주기적으로 `sync_file_range()`를 호출하여 미커밋 청크를 동기 배출합니다:
            $$\text{drain\_flushed} = \min(\text{dirty\_mb}, \; \text{uncommitted\_sync\_mb})$$
            $$\text{latency\_ms} = \text{round}\left(\frac{\text{drain\_flushed}}{\text{disk\_write\_speed\_mb\_s}} \times 1000.0, \; 2\right)$$
            $$\text{dirty\_mb} \mathrel{-}= \text{drain\_flushed}, \quad \text{total\_flushed\_mb} \mathrel{+}= \text{drain\_flushed}, \quad \text{uncommitted\_sync\_mb} = 0$$
            $$\text{state} = \text{"STREAMING\_SYNC\_DRAIN"}$$
       2. **커널 더티 스로틀링 발동 (`dirty_mb >= effective_dirty_throttle_threshold_mb`)**:
          - 커널의 `balance_dirty_pages_ratelimited()`가 호출되어 프로세스가 `TASK_UNINTERRUPTIBLE`(D-state)로 블로킹됩니다.
          - 더티 메모리가 백그라운드 임계치(`effective_dirty_bg_threshold_mb`) 수준으로 떨어질 때까지 초과분(`excess`)을 강제 배출합니다:
            $$\text{excess} = \text{dirty\_mb} - \text{effective\_dirty\_bg_threshold\_mb}$$
            $$\text{latency\_ms} = \text{round}\left(\frac{\text{excess}}{\text{disk\_write\_speed\_mb\_s}} \times 1000.0, \; 2\right)$$
            $$\text{drained} = \min(\text{dirty\_mb}, \; \text{excess})$$
            $$\text{dirty\_mb} \mathrel{-}= \text{drained}, \quad \text{total\_flushed\_mb} \mathrel{+}= \text{drained}$$
            $$\text{d\_state\_stall\_count} \mathrel{+}= 1, \quad \text{state} = \text{"D\_STATE\_THROTTLED"}$$
       3. **백그라운드 플러시 진행 중 (`dirty_mb >= effective_dirty_bg_threshold_mb`)**:
          - 백그라운드 스레드가 플러시 중이지만 아직 스로틀링 임계치 미만이므로 쓰기 프로세스는 초고속 RAM 복사 지연만 겪습니다:
            $$\text{latency\_ms} = 0.5, \quad \text{state} = \text{"BACKGROUND\_FLUSHING"}$$
       4. **정상 고속 버퍼링 쓰기 (그 외)**:
          - $$\text{latency\_ms} = 0.5, \quad \text{state} = \text{"NORMAL\_FAST"}$$
     - 최대 쓰기 스톨 시간 갱신: $\text{max\_write\_stall\_ms} = \max(\text{max\_write\_stall\_ms}, \; \text{latency\_ms})$
   - **`op == "FSYNC"`**:
     - 현재 페이지 캐시에 남아있는 모든 더티 페이지를 디스크에 동기적으로 플러시할 때까지 대기합니다:
       - $\text{dirty\_mb} > 0$인 경우:
         $$\text{latency\_ms} = \text{round}\left(\frac{\text{dirty\_mb}}{\text{disk\_write\_speed\_mb\_s}} \times 1000.0, \; 2\right)$$
         $$\text{total\_flushed\_mb} \mathrel{+}= \text{dirty\_mb}, \quad \text{dirty\_mb} = 0, \quad \text{uncommitted\_sync\_mb} = 0$$
       - $\text{dirty\_mb} == 0$인 경우:
         $$\text{latency\_ms} = 1.0 \quad (\text{메타데이터 플러시 최소 지연})$$
     - $\text{fsync\_stall\_ms} \mathrel{+}= \text{latency\_ms}, \quad \text{state} = \text{"FSYNC\_WAIT"}$
   - **`op == "IDLE"`**:
     - 유저 I/O 없음: $\text{latency\_ms} = 0.0$
     - $\text{state} = \text{"BACKGROUND\_FLUSHING"}$ ($\text{dirty\_mb} > 0$인 경우) 또는 $\text{"IDLE"}$

---

### 2.3 통계 및 최종 판정 (`verdict`)
- 전체 지연 시간 리스트(`latencies_ms`)의 99번째 백분위수(`p99_latency_ms`) 산출:
  $$\text{sorted\_lats} = \text{sorted}(\text{latencies\_ms}), \quad \text{idx} = \min(\text{len}-1, \; \text{int}(\text{len} \times 0.99))$$
- **최종 판정 규칙**:
  1. `io_mode == "DIRECT_IO"` $\to$ `"DIRECT_IO_PREDICTABLE"`
  2. `max_write_stall_ms >= 5000.0` (5초 이상 write() 스톨) $\to$ `"CATASTROPHIC_DIRTY_STALL"`
  3. `max_write_stall_ms >= 1000.0` (1초 이상 5초 미만 스톨) $\to$ `"MODERATE_THROTTLE_SPIKE"`
  4. `peak_dirty_mb > 0` (스톨 없이 백그라운드 원활 배출) $\to$ `"SMOOTH_BACKGROUND_WRITEBACK"`
  5. 그 외 $\to$ `"IDLE_CLEAN"`

---

## 3. 입출력 포맷

### 입력 형식 (JSON on stdin)
```json
{
  "system": {
    "total_memory_mb": 65536,
    "disk_write_speed_mb_s": 100,
    "dirty_background_ratio": 0.1,
    "dirty_ratio": 0.2,
    "io_mode": "BUFFERED"
  },
  "workload": [
    {"tick": 1, "op": "WRITE", "size_mb": 800},
    {"tick": 2, "op": "WRITE", "size_mb": 800},
    {"tick": 3, "op": "FSYNC"}
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
    "total_flushed_mb": 1600,
    "max_dirty_memory_mb": 1500,
    "max_write_stall_ms": 0.5,
    "total_stall_time_ms": 14001.0,
    "d_state_stall_count": 0,
    "fsync_stall_ms": 14000.0,
    "p99_latency_ms": 14000.0,
    "verdict": "SMOOTH_BACKGROUND_WRITEBACK"
  },
  "sample_timeline": [
    {
      "tick": 1,
      "op": "WRITE",
      "size_mb": 800,
      "dirty_memory_mb": 800,
      "latency_ms": 0.5,
      "state": "NORMAL_FAST"
    },
    {
      "tick": 2,
      "op": "WRITE",
      "size_mb": 800,
      "dirty_memory_mb": 1500,
      "latency_ms": 0.5,
      "state": "NORMAL_FAST"
    },
    {
      "tick": 3,
      "op": "FSYNC",
      "size_mb": 0,
      "dirty_memory_mb": 0,
      "latency_ms": 14000.0,
      "state": "FSYNC_WAIT"
    }
  ]
}
```
*(단, `sample_timeline`은 최대 최초 20개 틱까지만 포함합니다)*
