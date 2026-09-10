# 이론: Linux Kernel VFS New Mount API (`fs_context`) 내부 아키텍처 및 원자적 마운트 메커니즘

## 1. 기존 `mount(2)` 시스템 콜의 한계와 New Mount API의 탄생

전통적인 유닉스 및 리눅스 커널의 마운트 인터페이스는 1980년대 BSD/SysV 시절 설계된 `mount(2)` 단일 시스템 콜에 기반했습니다:
```c
int mount(const char *dev_name, const char *dir_name,
          const char *type, unsigned long flags,
          void *data);
```

이 고전적 인터페이스는 현대 분산/컨테이너 환경에서 다음과 같은 치명적인 병목과 설계상 결함을 안고 있었습니다:
1. **단일 버퍼 크기 제한 (4KB)**: 커널은 사용자 공간의 `data` 포인터를 커널 페이지(`PAGE_SIZE = 4096`) 하나로 복사합니다. 대규모 분산 파일시스템(Ceph, Lustre)이나 복잡한 Btrfs 서브볼륨 마운트 옵션, 다중 IP 주소, TLS 인증서 및 보안 키를 전달할 때 버퍼 오버플로가 발생합니다.
2. **불투명한 에러 피드백**: 쉼표로 구분된 문자열(`"rw,relatime,data=ordered,errors=remount-ro,commit=30"`) 중 어떤 옵션의 문법이 잘못되었는지, 아니면 디바이스 오픈에 실패했는지 `EINVAL` 단일 errno만 반환되어 디버깅이 불가능했습니다.
3. **슈퍼블록 생성과 VFS 트리 결합의 결합(Coupling)**: 기존 `mount(2)`는 디바이스로부터 슈퍼블록(`struct super_block`)을 생성하는 단계와, 이를 현재 프로세스의 마운트 네임스페이스 트리에 삽입(`attach_recursive_mnt()`)하는 단계가 하나로 묶여 있었습니다. 이로 인해 마운트 파라미터가 잘못되었을 때 이미 할당된 슈퍼블록과 디바이스 버퍼를 롤백하는 과정에서 레이스 컨디션 및 보안 취약점(TOCTOU)이 발생했습니다.

리눅스 커널 5.2에서 David Howells와 Al Viro에 의해 도입된 **New Mount API**는 이 모든 과정을 파일 디스크립터(File Descriptor) 기반의 독립적인 5단계 시스템 콜 파이프라인으로 완전히 분리했습니다.

---

## 2. New Mount API 시스템 콜 인터페이스

| 시스템 콜 | 기능 | 반환 객체 |
| :--- | :--- | :--- |
| `fsopen(const char *fs_name, unsigned int flags)` | 지정된 파일시스템 유형의 초기화 컨텍스트(`fs_context`) 할당 | 컨텍스트 파일 디스크립터 (`fs_fd`) |
| `fsconfig(int fs_fd, unsigned int cmd, const char *key, const void *val, int aux)` | 개별 설정 키-값 쌍 전달, 바이너리 객체 주입, 파일 트리 생성 지시 | 정수 상태 코드 (`0` 또는 음수 errno) |
| `fsmount(int fs_fd, unsigned int flags, unsigned int attr_flags)` | 완성된 컨텍스트로부터 분리된 익명 마운트 트리 생성 및 컨텍스트 소멸 | 마운트 파일 디스크립터 (`mnt_fd`) |
| `move_mount(int from_dfd, const char *from_path, int to_dfd, const char *to_path, unsigned int flags)` | 분리된 마운트 트리를 지정된 네임스페이스 경로에 원자적으로 삽입/이동 | 성공 여부 (`0` 또는 음수 errno) |
| `fspick(int dfd, const char *path, unsigned int flags)` | 이미 마운트된 파일시스템을 열어 리마운트(Reconfigure)용 컨텍스트 획득 | 리컨피그 컨텍스트 (`reconfig_fs_fd`) |

---

## 3. `struct fs_context` 생명주기와 상태 전이 다이어그램

커널 소스 `include/linux/fs_context.h` 및 `fs/fs_context.c`에서 정의하는 `fs_context`의 생명주기는 엄격한 유한 상태 머신(Finite State Machine)을 따릅니다:

```
                  +--------------------------+
                  |  fsopen() / fspick()     |
                  +--------------------------+
                               |
                               v
               +--------------------------------+
               |       FS_CONTEXT_CREATED       | <------+
               +--------------------------------+        | fsconfig(SET)
                               |                         | (반복 설정 가능)
                               | fsconfig(CMD_CREATE)    +-------+
                               v
               +--------------------------------+
               |   FS_CONTEXT_AWAITING_MOUNT    |
               +--------------------------------+
                               |
                               | fsmount()
                               v
               +--------------------------------+
               |   MOUNT_DETACHED (struct mount)| (fs_context 소멸)
               +--------------------------------+
                               |
                               | move_mount()
                               v
               +--------------------------------+
               |   ATTACHED TO VFS HIERARCHY    |
               +--------------------------------+
```

1. **`FS_CONTEXT_CREATED`**:
   - `fsopen()` 시스템 콜에 의해 호출된 파일시스템 드라이버의 `init_fs_context()` 콜백이 호출됩니다.
   - 드라이버별 전용 구조체가 `ctx->fs_private`에 할당됩니다.
   - `fsconfig()`를 통해 `FSCONFIG_SET_STRING`, `FSCONFIG_SET_FLAG`, `FSCONFIG_SET_PATH` 등의 명령으로 파라미터가 하나씩 전달됩니다.
   - 각 파라미터는 `fs_parameter_spec` 테이블을 통해 타입, 범위, 열거형(enum) 검증을 거칩니다.

2. **`FS_CONTEXT_AWAITING_MOUNT`**:
   - `fsconfig(fs_fd, FSCONFIG_CMD_CREATE, NULL, NULL, 0)`이 호출되면 파일시스템 드라이버의 `get_tree()` 콜백이 트리거됩니다.
   - 물리 블록 디바이스를 열고 슈퍼블록(`super_block`)을 읽거나 할당하며 루트 덴트리(`root dentry`)를 초기화합니다.
   - 이 상태에서는 더 이상 파라미터를 추가하거나 변경할 수 없습니다 (`EBUSY`).

3. **익명 분리 마운트 (`struct mount`)**:
   - `fsmount()` 호출 시 `vfs_create_mount()`가 호출되어 VFS 트리에 연결되지 않은 독립적인 마운트 인스턴스가 생성됩니다.
   - 생성이 완료되면 더 이상 `fs_context`가 필요 없으므로 `put_fs_context()`에 의해 `fs_fd`와 연관된 컨텍스트 메모리가 즉시 해제됩니다.
   - 이 익명 마운트는 다른 네임스페이스나 다른 프로세스에 전달되기 전까지 파일시스템 계층에 노출되지 않으므로, 다른 프로세스의 간섭 없이 안전하게 마운트 속성(`ro`, `nodev`, `nosuid`)을 변경할 수 있습니다.

4. **원자적 결합 (`move_mount`)**:
   - `move_mount()`는 네임스페이스 락(`namespace_sem` 및 `mount_lock` seqlock)을 획득하고 분리된 트리를 단일 원자적 연산으로 대상 경로(`mount_table`)에 연결합니다.
   - 중간 단계의 노출이나 불완전한 상태가 발생하지 않으므로 TOCTOU(Time-of-Check to Time-of-Use) 보안 결함을 근본적으로 차단합니다.

---

## 4. 리컨피그레이션 (`fspick`)과 파라미터 유효성 검증 메커니즘

이미 마운트되어 실행 중인 파일시스템의 옵션을 동적으로 재설정(Remount)할 때도 New Mount API가 사용됩니다:
1. `fspick(AT_FDCWD, "/mnt", FSPICK_NO_AUTOMOUNT)`을 호출하여 마운트 포인트로부터 `FS_CONTEXT_FOR_RECONFIGURE` 상태의 `fs_context`를 얻습니다.
2. 새롭게 변경하고자 하는 옵션만 `fsconfig(SET)`으로 주입합니다.
3. `fsconfig(fs_fd, FSCONFIG_CMD_RECONFIGURE, NULL, NULL, 0)`을 호출하면 드라이버의 `reconfigure()` 콜백이 호출되어, 기존 슈퍼블록의 런타임 플래그가 안전하게 갱신됩니다.

이 설계 덕분에 파라미터 오류가 발생하더라도 실행 중인 파일시스템에 어떠한 영향도 주지 않고 안전하게 거부(reject)할 수 있습니다.
