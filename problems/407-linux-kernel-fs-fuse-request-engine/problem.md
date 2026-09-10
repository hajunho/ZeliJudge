# 문제 407: Linux 커널 FUSE(Filesystem in Userspace) 4대 요청 큐 및 하이브리드 캐시 플로우 엔진

## 문제 설명

전통적인 유닉스/리눅스 파일 시스템(ext4, XFS, Btrfs 등)은 고성능을 위해 커널 공간(Ring 0) 내부에서 직접 드라이버로 동작합니다. 그러나 클라우드 스토리지(Amazon S3, Google Cloud Storage), 분산 파일 시스템(Ceph, GlusterFS), 네트워크 마운트(SSHFS), 그리고 모바일 OS(Android Storage Access Framework) 등 복잡한 비즈니스 로직과 네트워크 프로토콜을 가진 현대 스토리지 시스템을 커널 모듈로 작성하는 것은 시스템 안정성에 치명적인 위협이 됩니다. 커널 공간의 사소한 메모리 오류 하나가 OS 전체의 커널 패닉(Kernel Panic)을 유발하기 때문입니다.

이를 해결하기 위해 Miklos Szeredi에 의해 고안되어 리눅스 커널 2.6.14에 공식 도입된 **FUSE (Filesystem in Userspace, `fs/fuse/`, `CONFIG_FUSE_FS`)**는 파일 시스템의 핵심 로직을 완전히 비특권 사용자 공간(User Space, Ring 3) 프로세스로 구현할 수 있게 해주는 혁신적인 커널-유저 공간 브릿지 프레임워크입니다.

FUSE 프레임워크의 심장은 가상 파일 시스템(VFS) 계층과 유저스페이스 데몬 프로세스를 매개하는 **`/dev/fuse` 캐릭터 디바이스**와, 이를 지탱하는 **4대 전용 요청 큐(4 Dedicated Request Queues, `struct fuse_conn`, `struct fuse_iqueue`)**입니다:

1. **대기 큐 (Pending Queue, `fiq->pending`)**:
   - 일반 사용자 애플리케이션이 `read()`, `write()`, `lookup()`, `open()` 등 VFS 시스템 콜을 호출했을 때 생성되는 FUSE 요청들이 적재되는 FIFO 큐입니다.
   - 유저스페이스 데몬이 `read(/dev/fuse)` 시스템 콜을 호출하여 요청을 꺼내갈 때까지 대기합니다.
2. **처리 큐 (Processing Queue, `fc->processing`)**:
   - 데몬의 워커 스레드가 `read(/dev/fuse)`로 대기 큐에서 꺼내가서 현재 사용자 공간에서 I/O 작업을 수행 중인 활성 요청들입니다.
   - 데몬이 스토리지 I/O를 마치고 `write(/dev/fuse)`로 응답(Reply)을 전달할 때까지 커널에서 요청 컨텍스트를 보존합니다.
3. **백그라운드 큐 (Background Queue, `fc->bg_queue`) 및 BDI 혼잡 제어**:
   - 비동기 파일 읽기(Readahead)나 더티 페이지 라이트백(`FUSE_WRITE` in Writeback Cache Mode), 비동기 해제(Release) 등 사용자 프로세스가 직접 결과를 기다리지 않는 요청들이 거쳐가는 큐입니다.
   - 커널은 동시 실행 가능한 최대 백그라운드 요청 수(`max_background`)를 제한하여 사용자 데몬의 과부하를 방지합니다.
   - 활성 백그라운드 작업과 대기 큐의 합이 혼잡 임계값(`congestion_threshold`)을 초과하면, FUSE는 백킹 디바이스(BDI)를 **혼잡(CONGESTED)** 상태로 선언하여 VFS 플러시 스레드의 쓰기 요청을 쓰로틀링(Throttling)합니다.
4. **인터럽트 큐 (Interrupt Queue, `fiq->interrupts`)**:
   - FUSE I/O 완료를 기다리며 슬립 중이던 유저 프로세스가 `SIGINT` (Ctrl+C), `SIGKILL` 등의 시그널을 수신했을 때 발동합니다.
   - 요청이 아직 대기 큐에 있다면 즉시 취소(`INTERRUPTED`)되지만, 이미 데몬의 처리 큐(`processing`)로 넘어간 경우 커널은 최우선 순위로 **`FUSE_INTERRUPT`** 요청을 발행하여 데몬에게 해당 작업을 조기 중단하도록 명령합니다.
5. **VFS 하이브리드 캐시 제어**:
   - 매번 사용자 공간으로 컨텍스트 스위칭을 하는 오버헤드를 막기 위해, Dentry 경로 조회(`FUSE_LOOKUP`)와 Inode 메타데이터 조회(`FUSE_GETATTR`) 결과를 각각 `entry_timeout_ms`, `attr_timeout_ms` 동안 커널 메모리에 캐싱하여 0초(Zero Latency) 패스트패스를 제공합니다.
   - 대용량 데이터 전송 시 Splice 파이프라인(`enable_splice`)을 통해 메모리 복사 오버헤드를 완전히 제거합니다.

여러분의 임무는 리눅스 커널 FUSE 서브시스템의 4대 요청 큐 상태 머신, BDI 혼잡 제어, 시그널 인터럽트 프로토콜, 그리고 VFS 하이브리드 캐시 엔진을 충실히 시뮬레이션하는 시스템을 구축하는 것입니다.

---

## 시스템 아키텍처 다이어그램

```
+========================================================================================+
|                       Linux Kernel FUSE Subsystem Architecture                         |
+========================================================================================+

    [ User Application Process (e.g. ls, cp, grep, cat) ]
                             |  VFS System Call (read, write, stat)
                             v
+----------------------------------------------------------------------------------------+
|  Linux VFS & Inode/Dentry Cache Layer                                                  |
|   - Check Dentry Cache (entry_timeout) & Attr Cache (attr_timeout)                     |
|     * Cache HIT  ---> Return IMMEDIATELY (0ms Latency!)                                |
|     * Cache MISS ---> Build struct fuse_req and forward to FUSE Driver                 |
+----------------------------------------------------------------------------------------+
                             |
                             v
+----------------------------------------------------------------------------------------+
|  FUSE Kernel Driver (/dev/fuse, fs/fuse/dev.c)                                         |
|                                                                                        |
|   [ Priority 1: Interrupt Queue (fiq->interrupts) ]                                    |
|     - High-priority FUSE_INTERRUPT requests to abort processing operations             |
|                                                                                        |
|   [ Priority 2: Pending Queue (fiq->pending) ]                                         |
|     - Foreground Requests waiting for daemon read(/dev/fuse)                           |
|     - Refilled from Background Queue when slots free up                                |
|                                                                                        |
|   [ Background Queue (fc->bg_queue) & BDI Congestion Controller ]                      |
|     - Async writeback / readahead throttled by max_background (e.g. 12)                |
|     - Total BG >= congestion_threshold (e.g. 9) ---> Set BDI CONGESTED!                |
|                                                                                        |
|   [ Processing Queue (fc->processing) ]                                                |
|     - Requests currently dispatched to Userspace Daemon Workers                        |
+----------------------------------------------------------------------------------------+
            |  read(/dev/fuse)                              ^  write(/dev/fuse)
            v                                               |
+----------------------------------------------------------------------------------------+
|  Userspace FUSE Daemon (e.g. S3FS, Ceph-FUSE, Go-FUSE, Passthrough)                    |
|   - Worker Thread Pool (e.g. 4 threads)                                                |
|   - Execution Latency: daemon_proc_time + (copy_overhead if !splice)                   |
|   - Backend Storage Access (S3 HTTP, Ceph RADOS, Local Ext4)                           |
+----------------------------------------------------------------------------------------+
```

---

## 입출력 형식 및 명세

### 입력 JSON 구조

표준 입력(`sys.stdin`)으로 단일 JSON 객체가 전달됩니다:

```json
{
  "config": {
    "max_background": 4,
    "congestion_threshold": 3,
    "attr_timeout_ms": 50,
    "entry_timeout_ms": 50,
    "enable_writeback_cache": true,
    "enable_splice": true,
    "daemon_workers": 2,
    "daemon_proc_time_ms": 10,
    "copy_overhead_per_kb_ms": 1
  },
  "trace": [
    {"time": 0, "type": "SUBMIT", "req_id": "r1", "opcode": "FUSE_LOOKUP", "target": "/data/file.txt"},
    {"time": 15, "type": "SUBMIT", "req_id": "r2", "opcode": "FUSE_LOOKUP", "target": "/data/file.txt"},
    {"time": 20, "type": "SUBMIT", "req_id": "r3", "opcode": "FUSE_WRITE", "target": "/data/file.txt", "size_bytes": 4096},
    {"time": 25, "type": "SIGNAL_INTERRUPT", "target_req_id": "r3"}
  ]
}
```

#### 파라미터 필드 명세:
- `max_background` (int): 동시 활성 가능한 최대 백그라운드 요청 수.
- `congestion_threshold` (int): BDI 혼잡 상태를 발동하는 백그라운드 요청 합산 임계값.
- `attr_timeout_ms` (int): Inode 속성 캐시(`FUSE_GETATTR`) 유효 시간 (ms).
- `entry_timeout_ms` (int): Dentry 경로 캐시(`FUSE_LOOKUP`) 유효 시간 (ms).
- `enable_writeback_cache` (bool): 쓰기 요청(`FUSE_WRITE`)을 비동기 백그라운드 큐로 처리할지 여부.
- `enable_splice` (bool): 제로카피 Splice 활성화 여부 (false 시 페이로드 크기 비례 복사 오버헤드 추가).
- `daemon_workers` (int): 유저스페이스 데몬의 동시 워커 스레드 수.
- `daemon_proc_time_ms` (int): 데몬 워커의 기본 I/O 처리 소요 시간 (ms).
- `copy_overhead_per_kb_ms` (int): Splice 미사용 시 KB당 추가 메모리 복사 지연 (ms).

#### 트레이스 이벤트 명세:
- `SUBMIT`: 신규 VFS 요청 발생 (`req_id`, `opcode`, `target`, `size_bytes`, `is_background`).
  - 지원 오프코드: `FUSE_LOOKUP`, `FUSE_GETATTR`, `FUSE_READ`, `FUSE_WRITE`, `FUSE_FSYNC`.
- `SIGNAL_INTERRUPT`: 대기 또는 실행 중인 요청에 대한 사용자 시그널 취소 발생 (`target_req_id`).

---

### 출력 JSON 구조

표준 출력(`sys.stdout`)으로 공백 없이 압축된 단일 JSON 문자열을 출력합니다:

```json
{
  "summary": {
    "total_simulation_time": 30,
    "total_submitted": 3,
    "completed_count": 2,
    "interrupted_count": 1,
    "cache_hits": 1,
    "cache_misses": 1,
    "avg_latency_ms": 5.0,
    "max_bg_depth": 0,
    "max_pending_depth": 1
  },
  "congestion_events": [],
  "requests": [
    {"req_id": "r1", "opcode": "FUSE_LOOKUP", "state": "COMPLETED", "latency_ms": 10},
    {"req_id": "r2", "opcode": "FUSE_LOOKUP", "state": "COMPLETED", "latency_ms": 0},
    {"req_id": "r3", "opcode": "FUSE_WRITE", "state": "INTERRUPTED", "latency_ms": 5}
  ]
}
```

---

## 핵심 큐잉 및 캐시 규칙

1. **디스패치 우선순위**:
   - 유저 데몬 워커가 가용할 때:
     - 1순위: `interrupt_queue`의 `FUSE_INTERRUPT` 요청을 최우선 처리 (소요 시간 1ms).
     - 2순위: `pending_queue`의 일반 요청 FIFO 처리.
2. **BDI 혼잡 제어**:
   - `total_bg = num_background + len(bg_queue)`.
   - `total_bg >= congestion_threshold` 도달 시 `CONGESTED` 이벤트 기록.
   - `total_bg < congestion_threshold` 회복 시 `CLEARED` 이벤트 기록.
3. **인터럽트 처리**:
   - 대기 큐 체류 중 인터럽트: 즉시 큐에서 제거하고 `INTERRUPTED`로 종료.
   - 데몬 처리 중 인터럽트: `FUSE_INTERRUPT` 요청 발행 후 데몬 응답 시 `INTERRUPTED`로 마킹.
