# Problem 241: 컨테이너 스토리지: OverlayFS Copy-Up 지연 스파이크, Inode 고갈 및 파일 식별자 변이 (`xino`, `metacopy` vs Persistent Volume)

## 1. 개요 및 배경 시나리오

쿠버네티스(Kubernetes) 및 도커/컨테이너디(Docker/containerd, CRI-O) 기반 클라우드 네이티브 인프라에서 컨테이너의 루트 파일시스템(rootfs)은 리눅스 커널의 유니온 파일시스템인 **OverlayFS** 스토리지 드라이버를 통해 마운트됩니다.

OverlayFS는 이미지의 읽기 전용 레이어들(**`lowerdir`**) 위에 컨테이너 전용의 쓰기 가능한 임시 레이어(**`upperdir`**)를 겹쳐 통합 뷰(**`mergeddir`**)를 제공합니다. 이를 통해 수백 개의 컨테이너가 동일한 베이스 이미지를 메모리와 디스크에서 안전하게 공유할 수 있습니다.

```
                   OverlayFS 4계층 스토리지 아키텍처
                   
┌─────────────────────────────────────────────────────────────┐
│                       mergeddir                             │  Container View
│    (애플리케이션이 실제로 보는 통합 단일 마운트 포인트)            │  (/, /app, /models)
└──────────────────────────────┬──────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
    ┌──────────────────────┐        ┌──────────────────────┐
    │       upperdir       │        │       workdir        │
    │ (컨테이너 전용 쓰기 계층)│        │ (원자적 파일 교체용     │
    │  - 신규 생성 파일     │        │  임시 스테이징 계층)   │
    │  - Copy-up 복사본    │        └──────────────────────┘
    │  - Whiteout 특수노드 │
    └──────────┬───────────┘
               │ (읽기 전용 참조)
    ┌──────────▼──────────────────────────────────────────────┐
    │                      lowerdir                           │
    │  Layer N-1 (애플리케이션 코드 및 가중치 파일)               │  Read-Only Image
    │  Layer ...                                              │  Layers
    │  Layer 0   (Base OS: Ubuntu / Alpine)                   │
    └─────────────────────────────────────────────────────────┘
```

그러나 프로덕션 AI 서빙 및 대규모 마이크로서비스 환경에서 다음과 같은 치명적인 스토리지 장애가 빈번하게 발생하고 있습니다:

1. **대용량 파일 수정 시 Copy-Up 지연시간 폭증 (`OVERLAYFS_COPY_UP_LATENCY_SPIKE`)**:
   - 컨테이너 이미지 레이어(`lowerdir`)에 포함된 5GB 크기의 AI 모델 체크포인트 또는 임베디드 SQLite 파일에 대해 애플리케이션이 단 1바이트의 쓰기(`write()` 또는 `O_WRONLY`)를 시도함.
   - OverlayFS는 쓰기 권한을 반환하기 전에 `lowerdir`에 있던 **5GB 전체 파일을 `upperdir`로 동기식(Synchronous) 전체 복사(`ovl_copy_up`)**합니다.
   - 디스크 I/O 대역폭(예: 200MB/s) 한계로 인해 첫 번째 쓰기 시스템 콜이 25초 동안 블로킹되어 스레드가 멈추고, 쿠버네티스 Liveness Probe 타임아웃으로 컨테이너가 무한 재시작(CrashLoopBackOff)되는 대형 장애가 발생합니다.

2. **파일 식별자 변이로 인한 데이터 일관성 파괴 (`OVERLAYFS_INODE_MUTATION_ANOMALY`)**:
   - POSIX 표준에서는 프로세스가 파일을 다룰 때 `(st_dev, st_ino)`(디바이스 번호와 Inode 번호 쌍)가 파일의 고유 식별자로서 불변(Immutable)이어야 합니다.
   - 기본 설정의 OverlayFS(`xino=off`, `index=off`)에서는 읽기 전용 상태에서 `stat()`을 호출하면 `lowerdir` 파일시스템의 `(dev_id, inode)`를 반환합니다.
   - 그러나 해당 파일에 쓰기가 발생하여 `upperdir`로 Copy-up된 직후 다시 `stat()`을 호출하면 `upperdir`의 완전히 새로운 `(dev_id, inode)`로 바뀝니다.
   - 이로 인해 Inode 번호 기반으로 파일 변경을 추적하거나 락을 관리하는 데이터베이스, Git, Rsync, 파일 감시 데몬이 파일 동일성 검증에 실패하여 데이터 정합성 오류나 중복 동기화 버그를 유발합니다.

3. **디스크 용량 여유에도 불구하고 발생하는 Inode 고갈 (`HOST_INODE_EXHAUSTION_ENOSPC`)**:
   - 컨테이너 내부에서 `npm install`이나 대규모 빌드를 수행하여 수십만 개의 소형 파일이 `upperdir`에 생성됨.
   - 호스트 파일시스템의 디스크 공간(`df -h`)은 75% 이상 남아있으나, Inode 테이블(`df -i`)이 100% 소진되어 호스트의 모든 컨테이너와 데몬이 `ENOSPC: No space left on device` 에러를 뿜으며 일제히 다운됩니다.

4. **하위 레이어 파일 삭제 시 Whiteout 노드 누적으로 인한 디렉터리 스캔 지연 (`WHITEOUT_ACCUMULATION_DEGRADATION`)**:
   - Dockerfile 빌드 중 이전 레이어의 임시 파일들을 `rm -rf`로 삭제하면 디스크 공간이 절약되기는커녕, `upperdir`에 수만 개의 특수 캐릭터 디바이스 노드인 **Whiteout(`c 0 0`)** 파일이 생성됩니다.
   - 이후 컨테이너가 디렉터리를 스캔(`readdir`)할 때 수많은 Whiteout과 하위 레이어를 병합 필터링하느라 `ls` 또는 파일 탐색 성능이 극도로 퇴화합니다.

본 과제에서는 OverlayFS의 파일 복사, Inode 할당, Whiteout 생성, 마운트 옵션(`xino`, `metacopy`, `index`)의 동작을 정확히 시뮬레이션하고 문제를 진단하여 올바른 클라우드 네이티브 스토리지 아키텍처 권장안을 도출해야 합니다.

---

## 2. 상태 머신 및 동작 명세

시뮬레이터는 호스트 파일시스템 환경 설정(`fs_config`), 이미지 레이어 구성(`layers`), 그리고 컨테이너 내부 연산 이벤트(`operations`)를 순차적으로 실행합니다.

### 2.1 호스트 환경 및 마운트 옵션 (`fs_config`)
- `host_total_inodes`, `host_used_inodes`: 호스트 Inode 총량 및 기사용량
- `host_disk_capacity_mb`, `host_disk_used_mb`: 호스트 디스크 용량 및 기사용량 (MB)
- `disk_io_bandwidth_mb_per_sec`: 호스트 디스크 순차 쓰기 대역폭 (MB/s)
- `overlay_mount_options`:
  - `index`: `"on"` | `"off"` (디렉터리 인덱스 및 하드링크 추적)
  - `xino`: `"on"` | `"off"` | `"auto"` (확장 Inode 변환을 통한 Copy-up 전후 Inode 불변성 보장)
  - `metacopy`: `"on"` | `"off"` (메타데이터만 변경 시 데이터 본체 복사 지연)

### 2.2 연산 동작 규칙 (`operations`)

1. **`STAT` (`path`)**:
   - `mergeddir`에서 해당 경로 파일의 `(dev_id, inode)`를 조회합니다.
   - 대상 파일이 `upperdir`에 존재하는 경우:
     - `xino=on`인 경우: `lowerdir`에서 파생된 원본 `origin_dev`, `origin_ino`를 일관되게 유지 반환합니다.
     - `xino=off`인 경우: `upperdir` 전용의 신규 `dev_id`와 신규 `inode`를 반환합니다.
   - 대상 파일이 `lowerdir`에만 존재하는 경우: 원본 `origin_dev`, `origin_ino`를 반환합니다.
   - 이전에 `STAT`으로 기록된 식별자와 현재 반환된 식별자가 상이할 경우 `inode_mutation_detected`를 `true`로 설정합니다.

2. **`WRITE` (`path`, `bytes_written_mb`, `is_metadata_only`)**:
   - 파일이 이미 `upperdir`에 있는 경우: Copy-up 없이 직접 쓰기 수행.
   - 파일이 `lowerdir`에만 존재하는 경우 (**Copy-Up 트리거**):
     - `metacopy=on`이고 `is_metadata_only=true` (예: chmod/chown)인 경우:
       - 데이터 복사량 0 MB, 지연시간 1.0 ms로 메타데이터만 즉시 상위 복사.
     - 그 외의 경우 (데이터 쓰기 또는 `metacopy=off`):
       - `lowerdir`의 파일 전체 크기(`size_mb`)를 동기 복사함.
       - 복사 소요 지연시간: $\text{lat\_ms} = \left(\frac{\text{size\_mb}}{\text{disk\_io\_bandwidth\_mb\_per\_sec}}\right) \times 1000$ ms.
       - 복사된 용량만큼 호스트 디스크 사용량 증가 및 신규 Inode 1개 소모.

3. **`DELETE` (`path`)**:
   - `lowerdir`에 존재하는 파일을 삭제하는 경우:
     - 하위 레이어는 읽기 전용이므로 실제 삭제할 수 없습니다.
     - OverlayFS는 `upperdir`에 동일한 이름의 **Whiteout 특수 캐릭터 디바이스 노드**(`mknod c 0 0`)를 생성합니다.
     - Inode 1개 소모 및 `whiteout_count` 1 증가.

4. **`CREATE_BATCH` (`file_count`, `size_per_file_kb`)**:
   - `file_count`개의 신규 소형 파일 생성.
   - 호스트 잔여 Inode를 검사하여 `current_inodes + file_count > host_total_inodes`인 경우 Inode 고갈 발생.

5. **`READDIR` (`path`)**:
   - 디렉터리 스캔 시 누적된 `whiteout_count > 50`인 경우 디렉터리 스캔 오버헤드 감지.

---

### 2.3 감지해야 할 이상 징후 (`anomalies`) 및 권장안 (`recommendations`)

- `"OVERLAYFS_COPY_UP_LATENCY_SPIKE"`:
  - Copy-up 최대 지연시간이 1000.0 ms (1초) 이상인 경우.
  - 권장안: `"USE_PERSISTENT_VOLUME_FOR_MUTABLE_LARGE_FILES"`
- `"OVERLAYFS_INODE_MUTATION_ANOMALY"`:
  - Copy-up 전후로 동일 파일의 `(st_dev, st_ino)` 식별자가 변경된 경우.
  - 권장안: `"ENABLE_OVERLAYFS_XINO_AND_INDEX_MOUNT_OPTIONS"`
- `"HOST_INODE_EXHAUSTION_ENOSPC"`:
  - 디스크 공간 여유(사용률 < 90%)가 있음에도 Inode 사용률이 99% 이상(또는 Inode 한도 초과)인 경우.
  - 권장안: `"CLEANUP_DANGLING_IMAGES_OR_USE_MULTI_STAGE_BUILD"`
- `"WHITEOUT_ACCUMULATION_DEGRADATION"`:
  - Whiteout 노드가 50개를 초과하여 readdir 성능 저하를 유발하는 경우.
  - 권장안: `"SQUASH_IMAGE_LAYERS_AND_AVOID_IN_CONTAINER_DELETION"`

---

## 3. 입력 형식 (`sys.stdin`)

표준 입력으로 단일 JSON 객체가 주어집니다.

```json
{
  "fs_config": {
    "host_total_inodes": 100000,
    "host_used_inodes": 10000,
    "host_disk_capacity_mb": 102400,
    "host_disk_used_mb": 20000,
    "disk_io_bandwidth_mb_per_sec": 200.0,
    "overlay_mount_options": {
      "index": "off",
      "xino": "off",
      "metacopy": "off"
    }
  },
  "layers": [
    {
      "layer_id": "lower-0",
      "type": "LOWER",
      "files": [
        {"path": "/models/llama.bin", "size_mb": 5000, "inode": 501, "dev_id": 1}
      ]
    }
  ],
  "operations": [
    {"time_ms": 10, "op": "WRITE", "path": "/models/llama.bin", "bytes_written_mb": 10}
  ]
}
```

---

## 4. 출력 형식 (`sys.stdout`)

표준 출력으로 JSON 객체를 단일 행으로 출력합니다 (`ensure_ascii=False`).

```json
{
  "total_operations": 1,
  "copy_up_events": 1,
  "copy_up_data_mb": 5000.0,
  "max_copy_up_latency_ms": 25000.0,
  "host_inode_utilization_pct": 10.0,
  "host_disk_utilization_pct": 24.88,
  "inode_mutation_detected": false,
  "whiteout_count": 0,
  "anomalies": [
    "OVERLAYFS_COPY_UP_LATENCY_SPIKE"
  ],
  "recommendations": [
    "USE_PERSISTENT_VOLUME_FOR_MUTABLE_LARGE_FILES"
  ],
  "diagnosis": "Lowerdir 대용량 파일 수정 시 동기 복사(Copy-up)로 인해 최대 지연시간(25000.0ms) 스파이크 발생."
}
```
