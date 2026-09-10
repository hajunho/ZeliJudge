# 문제 456: Linux Kernel OverlayFS NFS Export 및 Origin 파일 핸들 디코딩 엔진

## 문제 설명

리눅스 커널의 **OverlayFS**(`fs/overlayfs/`)는 복수의 디렉터리 계층(하위 읽기 전용 계층 `lower`와 상위 쓰기 가능 계층 `upper`)을 결합하여 단일 파일시스템 뷰를 제공하는 유니온 파일시스템(Union Filesystem)입니다.

이러한 OverlayFS를 분산 파일시스템인 **NFS(Network File System)** 서버를 통해 원격 클라이언트에 내보낼 때(`export`), 치명적인 아키텍처적 난제가 발생합니다:
1. **NFS의 무상태성(Statelessness)과 파일 핸들(File Handle)**:
   - NFS 클라이언트는 열린 파일 디스크립터(fd) 대신 64/128비트 바이너리 토큰인 파일 핸들(`struct fid` / `struct ovl_fh`)을 통해 서버에 I/O 요청을 보냅니다.
   - 전통적인 파일시스템(ext4, XFS)은 파일 핸들에 `(inode 번호, generation)`를 기록하여 이를 디코딩합니다.
2. **Copy-Up으로 인한 Inode 불일치 및 `ESTALE` 재앙**:
   - 클라이언트가 `lower` 계층에 존재하는 파일(예: inode 1001)을 열람하면, NFS 서버는 lower inode 기반의 파일 핸들을 인코딩하여 반환합니다.
   - 이후 로컬 프로세스나 NFS 클라이언트가 해당 파일에 쓰기(write)를 수행하면 OverlayFS는 파일을 `upper` 계층으로 **Copy-Up**합니다. 이 과정에서 파일은 완전히 새로운 상위 inode(예: inode 50000)를 부여받게 됩니다.
   - 클라이언트가 이전에 발급받은 lower 파일 핸들(inode 1001)로 후속 읽기/쓰기를 시도하면, 파일시스템은 상위 계층의 새 inode와 연결고리를 찾지 못해 **`ESTALE` (Stale File Handle)** 에러를 내며 파일 접근이 완전히 파괴됩니다.

```
+-----------------------------------------------------------------------------------------+
|                  OverlayFS NFS Export & Origin Handle Resolution                        |
+-----------------------------------------------------------------------------------------+

 [NFS Client]                                       [OverlayFS Export Engine]
      |                                                        |
      | 1. encode_fh("/etc/hosts")                             |
      +------------------------------------------------------->| Read lower file (ino: 1001)
      | <--- File Handle: "OVL:LOWER:1001:1"                   | Return lower handle
      |                                                        |
      | [Write occurs -> Copy-Up to Upper!]                    |
      |                                                        | Create upper file (ino: 50000)
      |                                                        | Store index entry:
      |                                                        |   index_dir["OVL:LOWER:1001:1"] = "/etc/hosts"
      |                                                        |
      | 2. decode_fh("OVL:LOWER:1001:1")                       |
      +------------------------------------------------------->| Check index directory:
      |                                                        |   Match found! -> Links to upper ino 50000
      | <--- Return upper dentry (ino: 50000)                  | Zero ESTALE! Seamless resolution!
      |                                                        |
      v                                                        v
```

리눅스 커널 4.16은 이를 해결하기 위해 **`index=on,nfs_export=on`** 아키텍처(`fs/overlayfs/export.c`)를 도입하였습니다:
- **`index_dir` 및 Origin Xattr**:
  Copy-Up 시 상위 파일에 하위 파일의 파일 핸들을 가리키는 `trusted.overlay.origin` 확장 속성을 저장하고, `index/` 디렉터리에 하위 파일 핸들을 이름으로 하는 하드링크를 생성합니다.
- **오리진 디코딩 파이프라인**:
  클라이언트가 하위 파일 핸들을 제시하면, 먼저 `index/` 디렉터리를 조회하여 이미 Copy-Up된 상위 파일이 있는지 확인합니다. 인덱스 매칭 성공 시 상위 inode를 반환함으로써 `ESTALE` 없이 투명하게 연결합니다.
- **화이트아웃(Whiteout) 감지**:
  하위 파일이 삭제되면 상위 계층에 화이트아웃(특수 캐릭터 디바이스)이 생성되므로, 삭제된 파일의 핸들 디코딩 시 즉시 `ESTALE_WHITEOUT_DELETED`를 반환합니다.
- **인덱스 부재 시의 실패**:
  `index_enabled = False`인 상태에서 Copy-Up이 발생하면, 하위 핸들은 새 상위 파일을 찾을 수 없어 `ESTALE_UNINDEXED_COPYUP` 에러가 발생합니다.

당신은 리눅스 커널 OverlayFS의 NFS 파일 핸들 인코딩, Origin 인덱스 디렉터리 기반 무상태 디코딩, 화이트아웃 무효화 엔진을 시뮬레이션해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `config`:
  - `index_enabled`: bool (기본값 True)
  - `nfs_export_enabled`: bool (기본값 True)
- `operations`: 실행할 연산 배열.

지원되는 연산:
1. `{"op": "INIT_OVERLAY", "lower_files": [{"path": str, "ino": int, "gen": int, "size": int}, ...], "upper_files": [...]}`
   - 하위 계층 파일 및 초기 상위 계층 파일을 초기화합니다.
2. `{"op": "ENCODE_FH", "path": str}`
   - 파일 경로에 대해 OverlayFS 파일 핸들을 인코딩합니다 (`OVL:UPPER:<ino>:<gen>` 또는 `OVL:LOWER:<ino>:<gen>`).
   - `nfs_export_enabled`가 False이면 `EOPNOTSUPP_NFS_EXPORT_DISABLED` 반환.
   - 파일이 없거나 화이트아웃 상태이면 `ENOENT_FILE_NOT_FOUND` 반환.
3. `{"op": "DECODE_FH", "fh": str}`
   - 주어진 파일 핸들을 현재 유효한 dentry로 디코딩합니다.
   - 핸들 손상/형식 오류 시: `EINVAL_CORRUPT_FH`.
   - 하위 핸들이고 인덱스에 존재 시: `FH_DECODED_VIA_INDEX` (상위 inode 반환, `stats.index_hits += 1`).
   - 화이트아웃으로 삭제된 경우: `ESTALE_WHITEOUT_DELETED`.
   - 인덱스 꺼짐 상태에서 Copy-Up된 경우: `ESTALE_UNINDEXED_COPYUP`.
   - 삭제되거나 존재하지 않는 경우: `ESTALE_FILE_REMOVED`.
4. `{"op": "COPY_UP", "path": str, "new_size": int|null}`
   - 하위 파일을 상위 계층으로 복사하고 새 상위 inode(50000부터 증가)를 발급하며, 인덱스가 켜진 경우 `index_dir`에 등록합니다.
5. `{"op": "CREATE_UPPER", "path": str, "size": int}`
   - 상위 계층에 순수 신규 파일을 생성합니다.
6. `{"op": "DELETE_FILE", "path": str}`
   - 파일을 삭제합니다 (하위 파일이 존재하면 상위 계층에 화이트아웃 생성, 순수 상위 파일이면 제거).
7. `{"op": "QUERY_EXPORT_STATE"}`
   - 인덱스 항목 수, 상위 파일 수, 통계(`stats`)를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
