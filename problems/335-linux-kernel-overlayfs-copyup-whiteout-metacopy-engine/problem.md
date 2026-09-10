# 리눅스 커널 OverlayFS (fs/overlayfs): 카피업(Copy-Up), 화이트아웃(Whiteout), 메타카피(Metacopy) 및 불투명 디렉터리(Opaque) 엔진

## 문제 설명

**OverlayFS(fs/overlayfs)**는 현대 클라우드 컴퓨팅과 컨테이너 가상화 기술(Docker, containerd, Kubernetes, Podman, CRI-O)의 핵심을 이루는 리눅스 커널 내장 유니언 파일시스템(Union Filesystem)입니다.

OverlayFS는 복수의 읽기 전용 하위 레이어(`lowerdir`)와 하나의 읽기-쓰기 가능 상위 레이어(`upperdir`), 그리고 원자적 연산을 위한 작업 디렉터리(`workdir`)를 결합하여 사용자 공간에 단일한 통합 뷰(`merged`)를 제공합니다:

```
                      [ 사용자 뷰: Merged View ]
                                 │
         ┌───────────────────────┴───────────────────────┐
         │                                               │
         ▼                                               ▼
┌──────────────────┐                           ┌──────────────────┐
│     Upperdir     │                           │     Workdir      │
│  (Read-Write)    │                           │ (Atomic Scratch) │
│ - 신규 생성 파일 │                           └──────────────────┘
│ - 수정된 파일    │
│ - Whiteout 디바이스 (CHR 0, 0)
│ - Metacopy xattr ("trusted.overlay.metacopy")
│ - Opaque xattr ("trusted.overlay.opaque")
└────────┬─────────┘
         │ (섀도잉 / Shadowing)
         ▼
┌────────────────────────────────────────────────────────┐
│ Lowerdir Stack (Read-Only)                             │
│ ┌────────────────────────────────────────────────────┐ │
│ │ Layer 0 (최상위 하위 레이어: L0)                   │ │
│ ├────────────────────────────────────────────────────┤ │
│ │ Layer 1 (중간 레이어: L1)                          │ │
│ ├────────────────────────────────────────────────────┤ │
│ │ ...                                                │ │
│ ├────────────────────────────────────────────────────┤ │
│ │ Layer K-1 (기저 베이스 레이어: LK-1)                │ │
│ └────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

현대 리눅스 커널의 OverlayFS는 다음과 같은 핵심 서브시스템과 상태 전이 규칙을 가집니다:

1. **계층적 경로 탐색 (Hierarchical Path Lookup)**:
   - 경로 조회(`lookup`) 시 먼저 `upperdir`를 검사합니다.
     - 경로가 화이트아웃(`is_whiteout`)이면 즉시 `ENOENT`(파일 없음)를 반환합니다.
     - 상위 레이어에 존재하면 상위 엔트리를 반환합니다 (`is_metacopy` 여부 식별).
   - 상위에 없으면 `lowerdir`들을 위에서부터 아래로($L_0 \to L_1 \to \dots \to L_{K-1}$) 차례대로 탐색하여 가장 먼저 발견된 엔트리를 반환합니다 (상위 하위 레이어가 하위 레이어를 섀도잉).
   - 모든 레이어에 없으면 `ENOENT`를 반환합니다.

2. **카피업 (Copy-Up) 및 메타카피 (Metacopy - Linux 4.19+) 최적화**:
   - 하위 레이어에만 존재하는 파일의 권한/소유권 변경(`chmod`, `chown`) 시:
     - `metacopy_enabled == true`인 경우: 대용량 데이터 복제를 회피하기 위해 `upperdir`에 메타데이터 전용 엔트리(`is_metacopy: true`)만을 생성합니다. 복제 바이트 수는 0이며, 데이터 조회(`read`) 시에는 하위 레이어의 원본 데이터 레이어를 직접 참조합니다.
     - `metacopy_enabled == false`인 경우: 파일의 전체 크기만큼 바이트를 실제로 복제하는 완전 카피업(Full Copy-Up)이 수행됩니다 (`bytes_copied += size`).
   - 이미 `metacopy` 상태인 파일에 대해 내용 쓰기(`write`)가 발생하면:
     - 원본 데이터의 크기만큼 풀 카피업이 트리거되어 상위 레이어의 정규 파일로 업그레이드(`metacopy_upgraded_to_full`)된 후 새 데이터가 기록됩니다 (`bytes_copied += orig_size`).

3. **화이트아웃 (Whiteout - Character Device Major 0, Minor 0)**:
   - 하위 레이어는 읽기 전용이므로 하위 레이어에 존재하는 파일을 삭제(`unlink`)할 때, 하위 레이어를 직접 지울 수 없습니다.
   - 따라서 리눅스 커널은 `upperdir`에 특수 문자 디바이스(`CHR 0, 0`)를 생성하여 하위 레이어의 동일 경로 파일을 가립니다(Whiteout).
   - 단, 상위 레이어에서만 신규 생성되었던 파일(`upper-only`)을 삭제할 때는 화이트아웃을 생성하지 않고 `upperdir`에서 완전히 삭제합니다.

4. **디렉터리 조작 및 불투명 디렉터리 (Opaque Directory)**:
   - 디렉터리 삭제(`rmdir`):
     - 통합 뷰(`merged`) 상에서 디렉터리 내에 삭제되지 않은 자식 엔트리가 남아있다면 `ENOTEMPTY` 오류를 반환합니다.
     - 비어있는 디렉터리인 경우, 하위 레이어에 존재했던 디렉터리라면 상위에 화이트아웃 디바이스를 생성하여 하위 디렉터리를 차단합니다.
   - 디렉터리 생성(`mkdir`):
     - 이미 존재하는 경로면 `EEXIST`를 반환합니다 (화이트아웃이 있던 자리는 덮어쓰기 허용).
     - `opaque == true` 옵션이 설정된 경우 디렉터리에 불투명 플래그(`is_opaque: true`)를 부여합니다.
   - 디렉터리 내용 읽기(`readdir`):
     - 상위 디렉터리의 자식들과 하위 레이어들의 자식들을 사전식 순서로 병합(Merge)합니다.
     - 상위에 등록된 화이트아웃 파일 및 중복 이름(상위가 하위를 섀도잉)은 배제됩니다.
     - 만약 상위 디렉터리가 `is_opaque == true`라면 하위 레이어들과 병합하지 않고 상위 레이어의 자식들만 반환합니다.

본 문제에서는 이와 같은 리눅스 커널의 **OverlayFS 파일시스템 카피업, 화이트아웃, 메타카피 및 불투명 디렉터리 가상화 엔진**을 구현합니다.

---

## 입력 형식

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다.

```json
{
  "config": {
    "metacopy_enabled": true,
    "num_lower_layers": 2
  },
  "initial_layers": {
    "lower_layers": [
      {
        "layer_id": "lower0",
        "entries": [
          {"path": "/bin/sh", "type": "file", "size": 120000, "mode": "0755", "uid": 0, "gid": 0, "content_hash": "hash_sh_v2"},
          {"path": "/etc/os-release", "type": "file", "size": 350, "mode": "0644", "uid": 0, "gid": 0, "content_hash": "hash_deb"}
        ]
      },
      {
        "layer_id": "lower1",
        "entries": [
          {"path": "/bin/sh", "type": "file", "size": 95000, "mode": "0755", "uid": 0, "gid": 0, "content_hash": "hash_sh_v1"}
        ]
      }
    ],
    "upper_entries": []
  },
  "operations": [
    {"op": "lookup", "path": "/bin/sh"},
    {"op": "chmod", "path": "/bin/sh", "mode": "0700"},
    {"op": "stat", "path": "/bin/sh"},
    {"op": "write", "path": "/bin/sh", "size": 125000, "content_hash": "hash_sh_v3"},
    {"op": "unlink", "path": "/etc/os-release"},
    {"op": "lookup", "path": "/etc/os-release"}
  ]
}
```

### 필드 상세 설명
1. `config`:
   - `metacopy_enabled` (불리언): 메타데이터 변경 시 데이터 복제를 지연하는 메타카피 기능 활성화 여부
   - `num_lower_layers` (정수): 하위 레이어 개수
2. `initial_layers`:
   - `lower_layers` (배열): `layer_id`와 초기 엔트리 목록(`entries`)
     - 엔트리 속성: `path`, `type` (`"file"` 또는 `"dir"`), `size`, `mode`, `uid`, `gid`, `content_hash`
   - `upper_entries` (배열): 상위 레이어의 초기 엔트리 목록 (초기 상태에 이미 존재하는 파일/화이트아웃)
3. `operations` (배열): 수행할 파일시스템 연산 시퀀스
   - 지원되는 연산:
     - `{"op": "lookup", "path": str}`
     - `{"op": "stat", "path": str}`
     - `{"op": "read", "path": str}`
     - `{"op": "chmod", "path": str, "mode": str}`
     - `{"op": "chown", "path": str, "uid": int, "gid": int}`
     - `{"op": "write", "path": str, "size": int, "content_hash": str, "mode": str, "uid": int, "gid": int}`
     - `{"op": "unlink", "path": str}`
     - `{"op": "rmdir", "path": str}`
     - `{"op": "mkdir", "path": str, "opaque": bool, "mode": str, "uid": int, "gid": int}`
     - `{"op": "readdir", "path": str}`

---

## 연산별 반환 규격 및 상태 전이 규칙

1. `lookup`:
   - 존재하지 않거나 화이트아웃인 경우:
     `{"op": "lookup", "path": path, "status": "ENOENT", "found": false}`
   - 발견된 경우:
     `{"op": "lookup", "path": path, "status": "SUCCESS", "found": true, "location": layer_id, "type": type_str, "size": size, "mode": mode, "uid": uid, "gid": gid, "is_metacopy": bool}`
     - 단, 상위에 있고 `is_metacopy == true`이면 `type`은 `"metacopy_file"`, 아니면 원래 `type`.

2. `stat`:
   - 존재하지 않거나 화이트아웃인 경우: `{"op": "stat", "path": path, "status": "ENOENT"}`
   - 존재하는 경우:
     `{"op": "stat", "path": path, "status": "SUCCESS", "type": type, "size": size, "mode": mode, "uid": uid, "gid": gid, "content_hash": content_hash, "is_metacopy": is_metacopy, "location": meta_layer, "data_origin_layer": data_layer}`

3. `read`:
   - 존재하지 않거나 화이트아웃: `{"op": "read", "path": path, "status": "ENOENT"}`
   - 디렉터리인 경우: `{"op": "read", "path": path, "status": "EISDIR"}`
   - 정규 파일: `{"op": "read", "path": path, "status": "SUCCESS", "size": size, "content_hash": content_hash, "read_from_layer": data_layer}`

4. `chmod` / `chown`:
   - 대상이 없음: `{"op": op, "path": path, "status": "ENOENT"}`
   - 이미 `upper`에 있는 경우: 인플레이스 수정
     `{"op": op, "path": path, "status": "SUCCESS", "action": "modified_in_place", "is_metacopy": is_metacopy}`
   - `lower`에 있는 경우:
     - `metacopy_enabled == true`이고 파일인 경우:
       `metacopy_creations += 1`, `bytes_copied += 0`.
       `{"op": op, "path": path, "status": "SUCCESS", "action": "metacopy_created", "bytes_copied": 0}`
     - `metacopy_enabled == false`인 경우:
       `full_copyups += 1`, `bytes_copied += file_size`.
       `{"op": op, "path": path, "status": "SUCCESS", "action": "full_copyup", "bytes_copied": file_size}`

5. `write`:
   - 경로가 미존재/화이트아웃인 경우: `upper`에 직접 신규 파일 생성
     `{"op": "write", "path": path, "status": "SUCCESS", "action": "created_in_upper", "bytes_copied": 0}`
   - 이미 `upper`에 있고 `is_metacopy == true`인 경우:
     기존 원본 크기만큼 풀 카피업 수행 후 내용 업데이트 (`metacopy_upgrades += 1`, `bytes_copied += orig_size`).
     `{"op": "write", "path": path, "status": "SUCCESS", "action": "metacopy_upgraded_to_full", "bytes_copied": orig_size}`
   - 이미 `upper`에 있고 정규 파일인 경우: 인플레이스 쓰기
     `{"op": "write", "path": path, "status": "SUCCESS", "action": "written_in_place", "bytes_copied": 0}`
   - `lower`에만 존재하는 경우: 전체 풀 카피업 및 쓰기
     `full_copyups += 1`, `bytes_copied += lower_size`.
     `{"op": "write", "path": path, "status": "SUCCESS", "action": "full_copyup_and_write", "bytes_copied": lower_size}`

6. `unlink`:
   - 미존재/화이트아웃: `{"op": "unlink", "path": path, "status": "ENOENT"}`
   - 디렉터리인 경우: `{"op": "unlink", "path": path, "status": "EISDIR"}`
   - 하위 레이어에 존재하는 파일인 경우: `upper`에 화이트아웃 디바이스 등록 (`whiteouts_created += 1`).
     `{"op": "unlink", "path": path, "status": "SUCCESS", "action": "whiteout_created"}`
   - 상위 레이어에만 존재했던 파일인 경우: `upper`에서 단순 삭제.
     `{"op": "unlink", "path": path, "status": "SUCCESS", "action": "deleted_from_upper"}`

7. `rmdir`:
   - 미존재/화이트아웃: `{"op": "rmdir", "path": path, "status": "ENOENT"}`
   - 디렉터리가 아닌 경우: `{"op": "rmdir", "path": path, "status": "ENOTDIR"}`
   - 통합 뷰 기준으로 자식 엔트리가 남아있는 경우: `{"op": "rmdir", "path": path, "status": "ENOTEMPTY"}`
   - 비어있는 경우:
     - 하위에 존재했던 디렉터리면 화이트아웃 생성 (`whiteouts_created += 1`, `action: "whiteout_created"`)
     - 상위에만 존재했던 디렉터리면 `upper`에서 삭제 (`action: "deleted_from_upper"`)

8. `mkdir`:
   - 이미 존재하는 경로 (화이트아웃 제외): `{"op": "mkdir", "path": path, "status": "EEXIST"}`
   - 화이트아웃이 있던 자리에 생성: `action: "whiteout_overwritten"`, `is_opaque: bool`
   - 신규 생성: `action: "created_in_upper"`, `is_opaque: bool`

9. `readdir`:
   - 미존재/화이트아웃: `{"op": "readdir", "path": path, "status": "ENOENT"}`
   - 디렉터리가 아닌 경우: `{"op": "readdir", "path": path, "status": "ENOTDIR"}`
   - 정상 디렉터리:
     - 직계 자식 엔트리들을 수집하여 자식 이름 사전순으로 정렬한 `entries` 목록 반환.
     - 각 항목: `{"name": str, "type": str, "layer": str}`
     - 상위 디렉터리가 `is_opaque == true`이면 하위 계층은 탐색하지 않음.
     - `{"op": "readdir", "path": path, "status": "SUCCESS", "count": int, "entries": [...], "is_opaque": bool}`

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마를 갖는 단일 JSON 객체를 압축 공백 없이 출력합니다 (`json.dumps(..., separators=(',', ':'))`).

```json
{
  "operations": [
    {
      "op": "lookup",
      "path": "/bin/sh",
      "status": "SUCCESS",
      "found": true,
      "location": "lower0",
      "type": "file",
      "size": 120000,
      "mode": "0755",
      "uid": 0,
      "gid": 0,
      "is_metacopy": false
    }
  ],
  "summary_metrics": {
    "full_copyups": 0,
    "metacopy_creations": 1,
    "metacopy_upgrades": 0,
    "whiteouts_created": 1,
    "bytes_copied": 0
  },
  "upper_layer_state": {
    "entry_count": 2,
    "whiteout_count": 1,
    "metacopy_count": 1
  }
}
```

---

## 제약 사항

- $1 \le |\text{lower\_layers}| \le 10$
- $0 \le |\text{operations}| \le 100$
- 파일 크기: $0 \le \text{size} \le 10^{9}$ (1GB)
- 경로 길이는 256자 이내의 절대 경로 (`/`로 시작)
- 시간 복잡도: 각 연산당 $O(K + D)$ (여기서 $K$는 레이어 수, $D$는 디렉터리 직계 자식 수)
- 공간 복잡도: $O(N)$ (전체 엔트리 수에 비례)
