# 이론: Linux Kernel OverlayFS NFS Export 및 Origin 인덱스 아키텍처

## 1. 유니온 파일시스템과 NFS 무상태성의 구조적 충돌

전통적인 단일 볼륨 파일시스템(ext4, XFS, Btrfs)은 단일 네임스페이스와 고유한 inode 공간을 가집니다. 따라서 NFS 데몬(`nfsd`)이 클라이언트에게 파일 핸들을 발급할 때 단순히 `(ino, generation)`을 64비트 정수 쌍으로 인코딩하여 제공하면, 이후 언제든지 `exportfs` 인터페이스(`fh_to_dentry`)를 통해 해당 파일을 O(1)에 식별할 수 있습니다.

그러나 **OverlayFS**와 같은 다층 유니온 파일시스템에서는 다음과 같은 치명적인 구조적 모순이 발생합니다:
1. **서로 다른 물리 디바이스와 Inode 충돌**:
   - `lower` 디렉터리와 `upper` 디렉터리는 완전히 서로 다른 물리 디바이스(예: lower는 `/dev/sda1`의 읽기 전용 SquashFS/ext4, upper는 `/dev/nvme0n1p1`의 ext4)에 존재할 수 있습니다.
   - lower 계층의 파일 A와 upper 계층의 파일 B가 우연히 동일한 inode 번호 `12345`를 가질 수 있어, 단순 `(ino)`만으로는 고유성을 보장할 수 없습니다.
2. **Copy-Up으로 인한 동적 Inode 교체 (Dynamic Inode Mutation)**:
   - 클라이언트가 lower 계층의 `/app/config.ini`를 조회하여 파일 핸들을 수신합니다.
   - 이후 파일에 쓰기(write)가 발생하면 OverlayFS는 COW(Copy-on-Write) 정책에 따라 파일을 upper 계층으로 복사하고, upper 계층 파일시스템에 의해 **완전히 새로운 inode**가 할당됩니다.
   - 기존의 파일 핸들은 여전히 이전 lower 계층의 inode를 가리키고 있으므로, 이를 그대로 역참조하면 상위 계층의 수정 사항이 반영되지 않은 과거 데이터를 읽거나 `ESTALE` (Stale File Handle) 에러로 실패합니다.

---

## 2. OverlayFS 파일 핸들 포맷 (`struct ovl_fh`)

리눅스 커널 소스 `fs/overlayfs/ovl_entry.h` 및 `fs/overlayfs/export.c`에 정의된 OverlayFS 전용 파일 핸들은 다층 구조를 식별할 수 있도록 헤더를 포함합니다:

```c
struct ovl_fh {
    u8 version;          /* OVL_FH_VERSION (0) */
    u8 magic;            /* OVL_FH_MAGIC (0x4f) */
    u8 len;              /* 전체 핸들 바이트 길이 */
    u8 flags;            /* OVL_FH_FLAG_PATH_UPPER 등 레이어 플래그 */
    u8 fb[0];            /* 하위 실제 파일시스템의 struct fid 바이너리 */
} __packed;
```

- `flags` 필드의 비트 플래그를 통해 해당 파일 핸들이 `upper` 계층에서 직접 생성된 파일인지, 아니면 `lower` 계층에서 발급된 파일인지를 즉시 판별합니다.
- `fb[]` 바이트 배열에는 하부 파일시스템의 실제 `fid`가 캡슐화되어 보관됩니다.

---

## 3. `index=on` 디렉터리와 `trusted.overlay.origin` 확장 속성

이 문제를 해결하기 위해 도입된 핵심 기법이 바로 **Origin Indexing** 메커니즘입니다:

```
 [Lower Layer]                                [Upper Layer]
  +---------------+                            +----------------------------+
  | Inode: 1001   | <----+ Origin Link         | Inode: 50000 (copied-up)   |
  | /etc/hosts    |      |                     | /etc/hosts                 |
  +---------------+      |                     | xattr: trusted.overlay.origin
                         |                     +----------------------------+
                         |                                   ^
                         +-------+                           | Hardlink
                                 |                           |
                       +-------------------+                 |
                       | index/            |                 |
                       | [OVL:LOWER:1001:1] -----------------+
                       +-------------------+
```

1. **Copy-Up 발생 시점**:
   - 커널은 파일을 upper로 복사한 후, lower 파일의 파일 핸들을 바이너리로 직렬화하여 upper 파일의 확장 속성 `trusted.overlay.origin`에 기록합니다.
   - 동시에 OverlayFS 작업 디렉터리 내의 `index/` 디렉터리에 lower 파일 핸들의 16진수 해시 문자열을 이름으로 하는 **상위 파일의 하드링크(Hardlink)**를 원자적으로 생성합니다.
2. **파일 핸들 디코딩 시점 (`ovl_fh_to_dentry`)**:
   - NFS 클라이언트가 lower 파일 핸들을 제출하면:
     1. 먼저 `index/` 디렉터리에서 해당 lower 파일 핸들 이름의 엔트리가 존재하는지 확인합니다.
     2. 존재한다면, 이 파일은 이미 Copy-Up되었음을 의미하므로, 하드링크가 가리키는 **상위 계층의 dentry(inode 50000)**를 즉시 반환합니다.
     3. 존재하지 않는다면, 아직 Copy-Up되지 않은 순수 lower 파일이므로 하위 계층 dentry를 반환합니다.
   - 이 과정을 통해 클라이언트는 파일이 하위에서 상위로 물리적 이주를 마쳤더라도 단 한 번의 끊김이나 `ESTALE` 없이 최신 상위 파일에 접근할 수 있습니다.

---

## 4. 화이트아웃(Whiteout)과 NFS 캐시 무효화

OverlayFS에서 하위 계층에 존재하는 파일을 사용자가 삭제하면, 물리적으로 읽기 전용인 하위 계층의 파일을 지울 수 없으므로 상위 계층에 동일한 이름의 **화이트아웃(Whiteout, `mknod(dir, S_IFCHR, makedev(0, 0))` 특수 캐릭터 디바이스)**을 생성합니다.

NFS export 환경에서:
- 삭제된 파일의 이전 파일 핸들로 요청이 들어왔을 때, `index`나 하위 계층에 파일 메타데이터가 남아 있더라도 상위 계층에 화이트아웃 마커가 존재하는지 반드시 확인해야 합니다.
- 화이트아웃이 발견되면 커널은 즉시 `ESTALE`을 반환하여 원격 클라이언트의 파일 캐시를 즉각 무효화시키고 파일이 소멸되었음을 알립니다.

이 정교한 Origin 색인과 화이트아웃 배리어 아키텍처 덕분에 Linux OverlayFS는 엔터프라이즈급 컨테이너 이미지 공유 및 다중 노드 NFS 스토리지 환경에서 락-프리 무결성을 유지할 수 있습니다.
