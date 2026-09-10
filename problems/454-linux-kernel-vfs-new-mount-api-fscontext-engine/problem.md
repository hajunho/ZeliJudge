# 문제 454: Linux Kernel VFS New Mount API (`fs_context`) 상태 머신 및 원자적 마운트 엔진

## 문제 설명

리눅스 커널 5.2 이전의 전통적인 `mount(2)` 시스템 콜은 모든 마운트 파라미터(디바이스 경로, 타깃 마운트 포인트, 파일시스템 유형, 마운트 플래그, 쉼표로 구분된 임의의 텍스트 옵션 등)를 단일 시스템 콜 호출 시 4KB 페이지 버퍼 하나에 밀어 넣는 모놀리식(monolithic) 구조였습니다. 이로 인해 다음과 같은 심각한 아키텍처적 한계가 존재했습니다:
1. **임의 크기 옵션 불가**: 4096바이트를 초과하는 복잡한 옵션(예: 암호화 키, 다중 서브볼륨 및 네트워크 옵션) 전달 불가.
2. **원자성 부재 및 상태 추적 불가**: 파라미터 파싱 오류 시 어떤 옵션에서 실패했는지 식별하기 어렵고, 커널 내부 슈퍼블록 할당 및 디바이스 열기 과정에서 실패 시 롤백이 복잡함.
3. **네임스페이스 및 컨테이너 보안**: 권한이 분리된 비특권 사용자 네임스페이스(`userns`) 환경에서 슈퍼블록 생성과 네임스페이스 트리에 마운트를 부착(attach)하는 권한의 세밀한 위임 불가.

이 문제를 근본적으로 해결하기 위해 리눅스 VFS 서브시스템은 **New Mount API**(`fsopen`, `fsconfig`, `fsmount`, `move_mount`, `fspick`)를 도입하였습니다 (`fs/fs_context.c`, `fs/namespace.c`). New Mount API는 마운트 과정을 명확한 파일 디스크립터 기반의 상태 머신(State Machine)으로 분리합니다:

```
+-----------------------------------------------------------------------------------------+
|                        Linux VFS New Mount API State Machine                            |
+-----------------------------------------------------------------------------------------+

 [User Space]                                              [Kernel VFS fs_context]
      |                                                              |
      | 1. fsopen("ext4")                                            |
      +------------------------------------------------------------->| alloc_fs_context()
      | <--- fs_fd (3)                                               | state = FS_CONTEXT_CREATED
      |                                                              |
      | 2. fsconfig(fs_fd, FSCONFIG_SET_STRING, "source", "/dev/..") |
      +------------------------------------------------------------->| validate_parameter()
      | <--- status: PARAM_SET                                       | ctx->params[key] = val
      |                                                              |
      | 3. fsconfig(fs_fd, FSCONFIG_CMD_CREATE)                      |
      +------------------------------------------------------------->| vfs_get_tree() -> alloc sb
      | <--- status: SUPERBLOCK_CREATED                              | state = FS_CONTEXT_AWAITING_MOUNT
      |                                                              |
      | 4. fsmount(fs_fd, flags)                                     |
      +------------------------------------------------------------->| vfs_create_mount() -> detached
      | <--- mnt_fd (4)                                              | free fs_context (fs_fd closed)
      |                                                              |
      | 5. move_mount(mnt_fd, AT_FDCWD, "/target")                  |
      +------------------------------------------------------------->| attach to VFS mount tree
      | <--- status: MOUNT_ATTACHED                                  | mount_table["/target"] = mnt
      |                                                              |
      v                                                              v
```

당신은 리눅스 커널 VFS 계층의 New Mount API 파일시스템 컨텍스트(`fs_context`) 상태 전이 및 익명 분리 마운트(Anonymous Detached Mount) 엔진을 시뮬레이션해야 합니다.

### 지원 파일시스템 사양 (`SUPPORTED_FS`)
1. **`ext4`**:
   - `is_pseudo`: `False` (반드시 `"source"` 파라미터 필요)
   - 허용 키:
     - `"source"`: `str`
     - `"ro"`: `bool`
     - `"errors"`: `["continue", "remount-ro", "panic"]`
     - `"data"`: `["journal", "ordered", "writeback"]`
     - `"commit"`: `int`
2. **`xfs`**:
   - `is_pseudo`: `False` (반드시 `"source"` 파라미터 필요)
   - 허용 키:
     - `"source"`: `str`
     - `"ro"`: `bool`
     - `"logbufs"`: `int`
     - `"allocsize"`: `int`
3. **`tmpfs`**:
   - `is_pseudo`: `True` (`"source"` 파라미터 불필요)
   - 허용 키:
     - `"size"`: `str`
     - `"nr_blocks"`: `int`
     - `"nr_inodes"`: `int`
     - `"mode"`: `int`

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.
- `operations`: 일련의 VFS Mount API 연산 배열.

지원되는 연산(`op`):
1. `{"op": "FSOPEN", "fs_name": str, "fs_fd": int}`
   - 파일시스템 컨텍스트를 생성합니다.
   - `fs_name`이 미지원 시: `{"status": "ENODEV_UNKNOWN_FS", "fs_name": fs_name}`
   - `fs_fd`가 이미 활성 컨텍스트에 존재 시: `{"status": "EBADF_DUPLICATE_FD", "fs_fd": fs_fd}`
   - 성공 시: `{"status": "FS_CONTEXT_CREATED", "fs_fd": fs_fd, "fs_name": fs_name}` 및 `stats.contexts_created += 1`.
2. `{"op": "FSCONFIG_SET", "fs_fd": int, "key": str, "val": any}`
   - `fs_fd`의 컨텍스트에 파라미터를 설정합니다.
   - `fs_fd`가 미존재 시: `{"status": "EBADF_UNKNOWN_FD", "fs_fd": fs_fd}`
   - 컨텍스트 상태가 `"FS_CONTEXT_CREATED"` 또는 `"FS_CONTEXT_FOR_RECONFIGURE"`가 아닐 시: `{"status": "EBUSY_INVALID_STATE", "state": state}`
   - `key`가 해당 파일시스템의 허용 키가 아닐 시: `{"status": "EINVAL_PARAM_KEY", "fs_name": fs_name, "key": key}` 및 `stats.param_errors += 1`.
   - `val`이 허용 리스트에 없을 시: `{"status": "EINVAL_PARAM_VALUE", "key": key, "val": val, "allowed": allowed_list}` 및 `stats.param_errors += 1`.
   - 성공 시: `{"status": "PARAM_SET", "fs_fd": fs_fd, "key": key, "val": val}`.
3. `{"op": "FSCONFIG_CREATE_TREE", "fs_fd": int}`
   - 슈퍼블록 및 루트 디렉터리 트리를 빌드합니다.
   - `fs_fd` 미존재 시: `{"status": "EBADF_UNKNOWN_FD", "fs_fd": fs_fd}`
   - 상태가 `"FS_CONTEXT_CREATED"`가 아닐 시: `{"status": "EBUSY_INVALID_STATE", "state": state}`
   - `is_pseudo`가 `False`인데 `"source"` 파라미터가 누락된 경우: `{"status": "EINVAL_MISSING_SOURCE", "fs_name": fs_name}`
   - 성공 시: 고유 슈퍼블록 ID(`sb_id`, 1부터 1씩 증가) 부여, 상태 `"FS_CONTEXT_AWAITING_MOUNT"`로 전이, `stats.superblocks_created += 1`, `{"status": "SUPERBLOCK_CREATED", "fs_fd": fs_fd, "sb_id": sb_id, "fs_name": fs_name}` 반환.
4. `{"op": "FSMOUNT", "fs_fd": int, "mnt_fd": int, "attrs": dict | null}`
   - 트리로부터 분리된 익명 마운트(`detached_mounts`) 객체를 생성하고 `fs_context`를 해제(소멸)합니다.
   - `fs_fd` 미존재 시: `{"status": "EBADF_UNKNOWN_FD", "fs_fd": fs_fd}`
   - `mnt_fd`가 이미 분리된 마운트 풀에 존재 시: `{"status": "EBADF_DUPLICATE_MNT_FD", "mnt_fd": mnt_fd}`
   - 컨텍스트 상태가 `"FS_CONTEXT_AWAITING_MOUNT"`가 아닐 시: `{"status": "EINVAL_NOT_AWAITING_MOUNT", "state": state}`
   - `attrs` 기본값: `{"ro": False, "nodev": False, "nosuid": False}`
   - 성공 시: `fs_fd` 컨텍스트 제거, `{"status": "MOUNT_DETACHED_CREATED", "mnt_fd": mnt_fd, "sb_id": sb_id}` 반환.
5. `{"op": "MOVE_MOUNT", "mnt_fd": int, "target_path": str}`
   - 분리된 마운트를 네임스페이스 트리의 `target_path`에 원자적으로 부착합니다.
   - `mnt_fd` 미존재 시: `{"status": "EBADF_UNKNOWN_MNT_FD", "mnt_fd": mnt_fd}`
   - 성공 시: `detached_mounts`에서 제거되어 `mount_table[target_path]`로 이동, `stats.mounts_attached += 1`, 기존에 마운트가 덮어씌워졌는지 여부(`is_over_existing`)를 포함하여 `{"status": "MOUNT_ATTACHED", "target_path": target_path, "sb_id": sb_id, "fs_name": fs_name, "is_over_existing": bool}` 반환.
6. `{"op": "FSPICK_RECONFIGURE", "target_path": str, "reconfig_fs_fd": int}`
   - 기존 부착된 마운트 포인트를 열어 리마운트/재설정 컨텍스트(`FS_CONTEXT_FOR_RECONFIGURE`)를 생성합니다.
   - `target_path`가 마운트 테이블에 없을 시: `{"status": "ENOENT_TARGET_NOT_MOUNTED", "target_path": target_path}`
   - `reconfig_fs_fd`가 이미 활성 컨텍스트에 존재 시: `{"status": "EBADF_DUPLICATE_FD", "fs_fd": reconfig_fs_fd}`
   - 성공 시: 기존 마운트의 파라미터를 복사하여 `"FS_CONTEXT_FOR_RECONFIGURE"` 상태로 생성, `{"status": "RECONFIG_CONTEXT_CREATED", "fs_fd": reconfig_fs_fd, "target_path": target_path, "sb_id": sb_id}` 반환.
7. `{"op": "FSCONFIG_APPLY_RECONFIGURE", "reconfig_fs_fd": int}`
   - 변경된 파라미터를 기존 마운트에 반영하고 리컨피그 컨텍스트를 소멸시킵니다.
   - `reconfig_fs_fd` 미존재 시: `{"status": "EBADF_UNKNOWN_FD", "fs_fd": reconfig_fs_fd}`
   - 상태가 `"FS_CONTEXT_FOR_RECONFIGURE"`가 아닐 시: `{"status": "EINVAL_NOT_RECONFIG", "state": state}`
   - 성공 시: `mount_table[target_path]["params"]` 갱신, 컨텍스트 삭제, `{"status": "RECONFIG_APPLIED", "target_path": target_path}` 반환.
8. `{"op": "QUERY_VFS_STATE"}`
   - 현재 활성 컨텍스트 수, 분리된 마운트 수, 부착된 마운트 맵(타깃 경로 오름차순 정렬), 통계 카운터를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 연산들의 실행 결과 배열을 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
