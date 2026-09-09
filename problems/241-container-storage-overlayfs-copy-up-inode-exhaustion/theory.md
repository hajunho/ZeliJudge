# Problem 241 Theory: 리눅스 VFS와 OverlayFS 심층 분석 — Copy-Up 동기 지연, Inode 가상화(`xino`), Whiteout 노드 및 클라우드 네이티브 스토리지 최적화

컨테이너 가상화 기술의 핵심은 네임스페이스(Namespace), Cgroups, 그리고 **루트 파일시스템 격리 및 공유를 담당하는 유니온 마운트(Union Mount)**입니다. 리눅스 커널 3.18부터 메인라인에 정식 포함된 **OverlayFS**는 Docker, containerd, Podman, CRI-O 등 모든 현대 컨테이너 런타임의 기본 스토리지 스냅샷터(snapshotter)로 자리 잡았습니다.

본 문서에서는 리눅스 VFS(Virtual File System) 레벨에서 OverlayFS가 동작하는 내부 메커니즘, Copy-Up으로 인한 I/O 병목 및 Inode 변이 문제, 그리고 이를 해결하기 위한 커널 고급 옵션과 프로덕션 아키텍처 패턴을 심층 분석합니다.

---

## 1. 리눅스 VFS와 OverlayFS 4계층 아키텍처

OverlayFS는 자체적인 디스크 블록 포맷을 가지지 않는 스택형(Stacking) 가상 파일시스템입니다. 기반 파일시스템(ext4, XFS 등) 위에 위치하며 다음 4가지 핵심 디렉터리로 구성됩니다.

```
                  OverlayFS의 마운트 구조 및 VFS 레이어
                  
   +-------------------------------------------------------------+
   |                VFS (Virtual File System)                    |
   +-------------------------------------------------------------+
                                  │
                                  ▼
   +-------------------------------------------------------------+
   |                 OverlayFS (fs/overlayfs/)                   |
   |   struct ovl_entry: dentry 매핑 & 레이어 병합 룩업           |
   +-------------------------------------------------------------+
          │                       │                      │
          ▼                       ▼                      ▼
   ┌──────────────┐        ┌──────────────┐       ┌──────────────┐
   │   upperdir   │        │   workdir    │       │   lowerdir   │
   │  (read-write)│        │ (atomic temp)│       │  (read-only) │
   └──────────────┘        └──────────────┘       └──────────────┘
          │                       │                      │
   +──────┴───────────────────────┴──────────────────────┴───────+
   |             Underlying Filesystem (ext4 / XFS)              |
   +-------------------------------------------------------------+
```

1. **`lowerdir` (하위 읽기 전용 레이어)**:
   - 컨테이너 이미지의 압축 해제된 레이어들입니다. 콜론(`:`)으로 구분하여 최대 500개(커널 상한)까지 다중 레이어를 역순 스택으로 쌓을 수 있습니다 (`lowerdir=layer3:layer2:layer1:layer0`).
   - 하위 레이어는 커널에 의해 엄격히 불변(Immutable)으로 보호됩니다.
2. **`upperdir` (상위 쓰기 가능 레이어)**:
   - 컨테이너마다 독립적으로 할당되는 쓰기 가능한 작업 디렉터리입니다. 컨테이너 내부에서 새로 생성되거나 수정된 파일이 여기에 기록됩니다.
3. **`workdir` (원자적 작업 디렉터리)**:
   - 파일 복사(Copy-up)나 디렉터리 생성 중 시스템 크래시가 발생하더라도 파일시스템 불일치를 방지하기 위해 임시 파일을 스테이징하는 비어 있는 디렉터리입니다 (`upperdir`와 동일한 기반 파일시스템에 존재해야 함).
4. **`mergeddir` (통합 뷰)**:
   - `mount -t overlay overlay -o lowerdir=...,upperdir=...,workdir=... /mergeddir` 마운트 명령을 통해 컨테이너 프로세스에 노출되는 최종 마운트 포인트입니다.

---

## 2. Copy-Up의 내부 메커니즘과 지연시간 스파이크

### 2.1 Copy-Up의 트리거 조건
컨테이너가 `mergeddir`에 있는 파일에 대해 쓰기 작업을 시도할 때, 해당 파일이 아직 `upperdir`에 없고 `lowerdir`에만 존재한다면 커널은 **Copy-Up (`ovl_copy_up`)**을 트리거합니다.
- `open(O_WRONLY)`, `open(O_RDWR)`
- `truncate()`, `ftruncate()`
- 메타데이터 변경: `chmod()`, `chown()`, `setxattr()`

### 2.2 `ovl_copy_up` 커널 실행 경로
```c
// fs/overlayfs/copy_up.c (커널 소스 개념도)
int ovl_copy_up(struct dentry *dentry) {
    // 1. workdir에 임시 파일 생성
    struct dentry *temp = ovl_lookup_temp(workdir);
    
    // 2. lowerdir 파일 데이터를 workdir 임시 파일로 동기 복사
    ovl_copy_up_data(lower_file, temp);
    
    // 3. 확장 속성(xattr), 권한, 타임스탬프 메타데이터 복사
    ovl_copy_up_metadata(lower_dentry, temp);
    
    // 4. workdir의 임시 파일을 upperdir의 목적지 경로로 원자적 rename()
    vfs_rename(workdir, temp, upperdir, upper_dentry);
}
```

### 2.3 프로덕션 문제점: 동기 블로킹 지연 스파이크
- 애플리케이션이 10GB 크기의 머신러닝 가중치 파일(`.bin`, `.onnx`)이나 대용량 로그/DB 파일의 끝에 단 1바이트를 추가(`append`)하려 해도, 커널은 **10GB 전체 데이터를 동기식으로 디스크에서 읽어 디스크로 쓰는 I/O를 수행**한 후에야 `write()` 시스템 콜을 리턴합니다.
- 디스크 대역폭이 200MB/s인 환경에서 이 복사는 50초가 소요됩니다.
- 이 시간 동안 애플리케이션 스레드는 커널 D 상태(Uninterruptible Sleep)에 빠지며, 쿠버네티스의 TCP/HTTP Liveness Probe에 응답하지 못해 컨테이너가 강제 재시작되는 악순환이 발생합니다.

---

## 3. POSIX 파일 동일성과 Inode 변이 (`xino`)

### 3.1 POSIX 파일 식별자 규약
POSIX 표준에 따르면, 시스템 내의 모든 파일은 `st_dev`(디바이스 식별자)와 `st_ino`(Inode 번호)의 순서쌍 `(st_dev, st_ino)`에 의해 고유하고 영구적으로 식별되어야 합니다. 파일 디스크립터가 열려 있는 동안 이 식별자는 절대 변경되어서는 안 됩니다.

### 3.2 OverlayFS의 기본 Inode 변이 함정
1. 파일이 `lowerdir`에 있을 때:
   - 애플리케이션이 `stat("/app/db.sqlite")`을 호출하면 `lowerdir`의 파일시스템 디바이스 ID($D_{\text{lower}}$)와 Inode 번호($I_{\text{lower}}$)를 반환합니다.
2. 파일에 쓰기가 발생하여 `upperdir`로 Copy-up된 후:
   - 파일은 `upperdir` 파일시스템의 새로운 디스크 블록에 위치하게 되므로, 새로운 Inode($I_{\text{upper}}$)와 디바이스 ID($D_{\text{upper}}$)를 부여받습니다.
   - 이후 애플리케이션이 다시 `stat("/app/db.sqlite")`을 호출하면 식별자가 $(D_{\text{upper}}, I_{\text{upper}})$로 완전히 달라져 있습니다!

```
[Inode 변이로 인한 애플리케이션 장애]
Client App ───► stat("/app/data.db") ──► Returns (dev=1, ino=777)
                ... Write 1 byte ...
                Kernel ovl_copy_up() ──► Allocates new upper inode 900001
Client App ───► stat("/app/data.db") ──► Returns (dev=99, ino=900001)
                FAIL! (rsync, git, SQLite detects inode change as file replacement)
```

### 3.3 해결책: `xino` (eXtended INO, Linux 4.17+)
커널 4.17에 도입된 **`xino=on` (또는 `xino=auto`)** 마운트 옵션은 Inode 번호의 상위 비트(High-order bits)에 레이어 식별자 번호를 인코딩하거나 커널 내의 Inode 매핑 변환 테이블을 유지합니다.
이를 통해 파일이 `upperdir`로 복사된 이후에도 유저스페이스에는 최초 `lowerdir`의 고유 Inode 번호를 변함없이 노출함으로써 완전한 POSIX 호환성을 보장합니다.

---

## 4. Whiteout과 Opaque 디렉터리 메커니즘

### 4.1 Whiteout 디바이스 노드 (`mknod c 0 0`)
컨테이너가 `lowerdir`에 존재하는 파일 `/app/lib/old.js`를 삭제(`unlink`)할 때, 커널은 읽기 전용인 `lowerdir`의 파일을 물리적으로 지울 수 없습니다.
대신 `upperdir`의 해당 경로에 메이저 번호 0, 마이너 번호 0을 가진 **특수 캐릭터 디바이스 노드(Whiteout)**를 생성합니다.

```bash
# 호스트 upperdir 내부 확인 시:
crw-r--r-- 1 root root 0, 0 Sep 10 02:30 /var/lib/docker/overlay2/.../diff/app/lib/old.js
```

OverlayFS는 경로를 조회할 때 이 노드를 만나면 "삭제되어 존재하지 않는 파일"로 간주하여 `ENOENT`를 반환합니다.

### 4.2 Whiteout 누적과 `readdir` 병목
- Dockerfile에서 `RUN apt-get update && apt-get install -y ...` 후 다음 레이어에서 `RUN rm -rf /var/lib/apt/lists/*`를 실행하면, 디스크 공간은 줄어들지 않고 수천 개의 Whiteout 노드가 생성됩니다.
- 디렉터리 목록을 읽는 `readdir()` 시스템 콜 호출 시, 커널은 모든 하위 레이어의 디렉터리 엔트리와 상위 레이어의 Whiteout 목록을 전부 읽어 메모리에서 머지(Merge) 및 차집합 연산을 수행해야 하므로 CPU 소모와 디렉터리 스캔 지연이 극심해집니다.

---

## 5. 커널 최적화 옵션 및 클라우드 네이티브 설계 패턴

| 최적화 기법 | 동작 원리 및 설정 방법 | 기대 효과 및 적용 시나리오 |
| :--- | :--- | :--- |
| **`metacopy=on`** (Linux 4.19+) | `chmod`, `chown` 등 메타데이터만 변경 시 데이터 본체 복사를 연기하고 `trusted.overlay.metacopy` 속성만 기록 | 대용량 바이너리 권한 변경 시 불필요한 수 기가바이트의 복사 지연을 0으로 제거 |
| **`index=on` & `xino=on`** | 디렉터리 인덱싱과 확장 Inode 가상화 활성화 | Copy-up 후 Inode 불변성 유지, 하드링크 깨짐 방지 |
| **PersistentVolume 분리** | 가변 대용량 데이터(DB, AI 모델 가중치, 캐시)를 컨테이너 rootfs가 아닌 외부 볼륨(`emptyDir`, PV)에 마운트 | OverlayFS Copy-up 자체를 원천 우회하여 네이티브 파일시스템 성능 확보 |
| **Multi-Stage Build & Squash** | Dockerfile 멀티스테이지 빌드로 최종 이미지에는 런타임에 필요한 파일만 남기고 중간 임시 파일 완전 배제 | Inode 낭비 및 Whiteout 노드 누적으로 인한 readdir 지연 원천 차단 |
