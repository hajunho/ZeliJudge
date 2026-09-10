# 리눅스 커널 OverlayFS (fs/overlayfs): 내부 아키텍처 및 시스템 공학 이론

## 1. 유니언 파일시스템과 컨테이너 런타임의 진화

리눅스 컨테이너 기술(LXC, Docker, containerd)의 눈부신 발전 뒤에는 이미지 계층 구조를 효율적으로 병합하고 실행 시 쓰기 가능한 격리 환경을 제공하는 **유니언 마운트(Union Mount)** 기술이 있습니다.

과거에는 외부 커널 패치 형태로 유지되던 **AUFS(Advanced Multi-Layered Unification Filesystem)**나 장치 기반의 **DeviceMapper thin-provisioning**이 사용되었으나, 복잡한 락킹 구조와 유지보수의 어려움으로 인해 리눅스 커널 3.18(2014년)에 미카엘 로슈크비츠(Miklos Szeredi)에 의해 **OverlayFS**가 메인라인 커널에 공식 병합되었습니다.

OverlayFS는 가상 파일시스템(VFS) 계층 위에 얇은 래퍼(Stackable Filesystem)로 동작하며, 물리 블록 계층에 직접 관여하지 않고 하부 파일시스템(ext4, XFS 등)의 디렉터리들을 결합하여 동작하므로 오버헤드가 극히 적고 구조가 매우 간결합니다.

---

## 2. OverlayFS 핵심 아키텍처 및 서브시스템

### (1) 4대 디렉터리 구성 요소
마운트 시 OverlayFS는 다음과 같은 인자를 요구합니다:
```bash
mount -t overlay overlay -o lowerdir=/lower1:/lower2,upperdir=/upper,workdir=/work /merged
```
- **`lowerdir`**: 하나 이상의 읽기 전용 레이어 스택입니다. 콜론(`:`)으로 구분되며 왼쪽 레이어가 오른쪽 레이어보다 상위에 위치하여 동일한 이름의 파일이나 디렉터리를 가립니다(Shadowing).
- **`upperdir`**: 유일한 읽기-쓰기 레이어입니다. 사용자가 통합 뷰(`/merged`)에서 생성, 수정, 삭제한 모든 변경 사항이 물리적으로 저장됩니다.
- **`workdir`**: `upperdir`와 동일한 파일시스템 내에 위치해야 하는 빈 작업 디렉터리입니다. 파일 복제(Copy-up) 도중 시스템 크래시나 전원 차단이 발생하더라도 원자성(Atomicity)을 보장하기 위해 임시 파일을 생성한 후 `rename()`을 수행하는 공간입니다.
- **`merged`**: 사용자 공간에 노출되는 최종 합성 뷰(Mount Point)입니다.

---

### (2) 카피업 (Copy-Up) 메커니즘 (`ovl_copy_up`)
하위 레이어(`lowerdir`)는 항상 읽기 전용이므로, 사용자가 하위 파일에 대해 쓰기 모드(`O_WRONLY`, `O_RDWR`, `truncate`)로 `open()`을 시도하는 순간 커널은 즉시 카피업을 트리거합니다:
1. 상위 파일시스템의 `workdir`에 임시 파일을 생성합니다.
2. 하위 레이어의 파일 데이터(Blocks)와 메타데이터(UID, GID, Mode, Extended Attributes, Timestamps)를 임시 파일로 복제합니다.
3. 원자적 `renameat()` 시스템 콜을 통해 임시 파일을 `upperdir`의 실제 경로로 이동시킵니다.
4. 이후의 모든 I/O는 `upperdir`의 복제본 파일로 라우팅됩니다.

이 과정에서 수백 메가바이트 크기의 파일에 단 1바이트만 쓰더라도 전체 파일을 복제해야 하는 $O(\text{size})$ 복사 비용이 발생합니다.

---

### (3) 메타카피 (Metacopy - Linux 4.19+) 최적화
리눅스 4.19 커널에 도입된 **Metacopy** 기능(`mount -o metacopy=on`)은 컨테이너 빌드 및 패키지 설치 워크로드에서 성능을 극적으로 향상시킵니다.

`chmod`, `chown`, `setxattr`과 같이 파일 내용(Data Payload)은 전혀 건드리지 않고 권한이나 소유자 메타데이터만 수정하는 작업의 경우:
- 데이터를 복제하지 않고, 오직 메타데이터만 포함하는 0바이트 크기의 정규 dentry를 `upperdir`에 생성합니다.
- 해당 상위 dentry에 커널 확장 속성 `trusted.overlay.metacopy`를 부여합니다.
- 사용자가 이 파일을 `read()`할 때 커널은 메타데이터는 `upper`에서 읽고, 실제 파일 블록은 `lower` 레이어의 원본 파일 디스크립터에서 페치합니다.
- 이후 실제로 파일에 `write()`가 발생하면 그 시점에 지연된 풀 카피업(`ovl_copy_up_data`)을 수행합니다.

---

### (4) 화이트아웃 (Whiteout) 및 불투명 디렉터리 (Opaque Directory)

#### 화이트아웃 (Whiteout)
하위 레이어의 파일을 삭제(`unlink`)할 때 읽기 전용 lowerdir의 파일을 삭제할 수 없으므로, 커널은 `upperdir`의 해당 경로에 **메이저 번호 0, 마이너 번호 0을 갖는 문자 디바이스(`S_IFCHR, makedev(0, 0)`)**를 생성합니다.
OverlayFS VFS 드라이버는 경로 조회 및 디렉터리 목록 조회 시 이 특수 문자 디바이스를 감지하면 해당 파일이 삭제된 것으로 간주하고 사용자에게 은닉(`ENOENT`)합니다.

#### 불투명 디렉터리 (Opaque Directory)
하위 레이어에 `/var/log`라는 디렉터리가 있고 수많은 로그 파일들이 존재할 때, 사용자가 `/var/log`를 비우고 삭제한 후 새로운 빈 `/var/log` 디렉터리를 `mkdir`했다고 가정합시다.
일반적인 유니언 병합이 일어난다면 하위 레이어의 이전 로그 파일들이 새 디렉터리로 뚫고 올라오는(Leak through) 문제가 발생합니다.
이를 방지하기 위해 상위 디렉터리에 `trusted.overlay.opaque = "y"` 확장 속성을 기록합니다.
`readdir()` 또는 경로 탐색기는 상위 디렉터리가 Opaque 상태이면 하위 레이어의 동일 경로 디렉터리를 병합하지 않고 즉시 탐색을 종료합니다.

---

## 3. 커널 VFS 데이터 구조 매핑

| OverlayFS 개념 | 리눅스 커널 C 구조체 (`fs/overlayfs/ovl_entry.h`) | 구현 및 동작 매핑 |
| :--- | :--- | :--- |
| **`ovl_fs`** | `struct ovl_fs` | 슈퍼블록 및 마운트 옵션(`metacopy`, `lower_layers`) 보관 |
| **`ovl_entry`** | `struct ovl_entry` | dentry별 상위/하위 레이어 스택 참조 포인터 배열 |
| **`ovl_inode`** | `struct ovl_inode` | 상위 inode, 하위 inode 및 metacopy 플래그 관리 |
| **`ovl_copy_up`** | `int ovl_copy_up(struct dentry *dentry)` | workdir 기반 원자적 복제 및 xattr 복사 |
| **`ovl_whiteout`** | `mknod(dir, name, S_IFCHR, makedev(0, 0))` | 하위 파일 은닉을 위한 화이트아웃 디바이스 생성 |
| **`ovl_set_opaque`** | `vfs_setxattr(upper, OVL_XATTR_OPAQUE, "y", 1)` | 하위 디렉터리 머지 차단 속성 설정 |

이와 같은 시스템 아키텍처를 바탕으로 본 문제의 시뮬레이터는 리눅스 커널의 실제 OverlayFS 드라이버 동작을 완벽하게 재현합니다.
