# 리눅스 Btrfs 파일시스템 (fs/btrfs): 서브볼륨 스냅샷, Tree-Log 빠른 fsync 및 Send/Receive 증분 백업 스트림 엔진

## 문제 설명

리눅스 커널의 차세대 CoW(Copy-on-Write) 파일시스템인 **Btrfs(`fs/btrfs/`)**는 고성능 서버 및 스토리지 시스템에서 무중단 스냅샷, 원자적 트랜잭션, 서브볼륨 관리, 그리고 서브볼륨 간 차분만을 전송하는 초고속 증분 백업(`btrfs send/receive`) 메커니즘을 제공합니다.

Btrfs는 B-Tree 기반의 다중 서브볼륨 아키텍처와 경량 저널링 트리인 **Tree-Log(Log Tree, `fs/btrfs/tree-log.c`)**를 통해 성능과 내구성을 동시에 달성합니다:

```
           [ Btrfs Root Tree / Superblock ]
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
┌──────────────────┐            ┌──────────────────┐
│ Subvolume Tree   │            │ Subvolume Tree   │
│ (Subvol #5: Prod)│            │(Subvol #256: Snap│
└────────┬─────────┘            └────────┬─────────┘
         │                               │
         ├───────────────┐               │
         ▼               ▼               ▼
   [ Extent A ]    [ Extent B ]    [ Extent A (공유) ]
   (CoW 신규 할당) (기존 유지)     (스냅샷 포인터 복제)
         ▲
         │ (fsync 격리 로깅)
┌──────────────────┐
│ Tree-Log (Log)   │ ──► 빠른 fsync 시 전체 트랜잭션 커밋 없이
│ (Subvol #5 전용) │     수정된 inode/extent만 격리 기록 후 크래시 리플레이
└──────────────────┘
```

Btrfs의 핵심 아키텍처와 동작 규칙은 다음과 같습니다:

1. **서브볼륨 및 $O(1)$ CoW 스냅샷 (Subvolume & Snapshots)**:
   - 각 서브볼륨은 고유한 `subvol_id`를 갖는 독립된 B-Tree 루트입니다.
   - 스냅샷 생성(`create_snapshot`) 시, 원본 서브볼륨의 전체 데이터를 복제하는 것이 아니라 **루트 노드 포인터만을 복제**하여 새로운 서브볼륨 트리를 구성합니다.
   - 모든 데이터 익스텐트(Extent)는 원본과 스냅샷 간에 공유되며, 복제 소요 시간은 $O(1)$입니다.
   - 읽기 전용 스냅샷(`is_readonly: true`)에 대한 쓰기 시도는 `-EROFS` 오류로 차단됩니다.

2. **Tree-Log를 통한 초고속 `fsync` (Fast fsync via Tree-Log)**:
   - Btrfs에서 전체 트랜잭션 커밋(`btrfs_commit_transaction`)은 파일시스템 전체의 더티 메타데이터(Chunk Tree, Extent Tree, Checksum Tree, Root Tree)를 디스크에 플러시하므로 I/O 오버헤드가 매우 큽니다.
   - 개별 파일의 내구성을 보장하는 `fsync(fd)` 호출 시:
     - 서브볼륨 전용의 임시 B-Tree인 **Tree-Log(Log Tree)**에 변경된 inode 항목과 해당 익스텐트 정보만을 격리하여 기록합니다.
     - 시스템 비정상 종료(크래시) 발생 시, 마운트 단계에서 `btrfs_recover_log_trees`가 실행되어 Tree-Log에 기록된 내역을 본 서브볼륨 트리로 리플레이(Replay)합니다.
     - 추후 전체 트랜잭션 커밋(`commit_transaction`)이 실행되면 Tree-Log는 폐기(Discard)되고 세대(Generation)가 증가합니다.

3. **Send / Receive 증분 스트림 (Incremental Send/Receive)**:
   - `btrfs_send`: 두 읽기 전용 스냅샷(부모 `parent`와 대상 `target`) 사이의 B-Tree를 비교하여 차분 명령 스트림(TLV Command Stream)을 생성합니다:
     - `BTRFS_SEND_CMD_SUBVOL` / `BTRFS_SEND_CMD_SNAPSHOT`: 신규 서브볼륨/스냅샷 메타데이터.
     - `BTRFS_SEND_CMD_MKFILE` / `BTRFS_SEND_CMD_UNLINK`: 파일 생성 및 삭제.
     - `BTRFS_SEND_CMD_WRITE`: 신규/수정된 익스텐트 데이터 전송 (`offset`, `length`, `data_hash`).
     - `BTRFS_SEND_CMD_CLONE`: 부모 스냅샷에 동일하게 존재하는 익스텐트를 재참조하는 CoW 복제 명령 (대역폭 0바이트 절약).
   - `btrfs_receive`: 생성된 명령 스트림을 순차적으로 해석하여 대상 스토리지에 원본 스냅샷과 100% 동일한 복제본을 재구성합니다.

본 문제에서는 이와 같은 Btrfs 파일시스템의 **서브볼륨 스냅샷, CoW 익스텐트 공유, Tree-Log 빠른 fsync 및 증분 Send/Receive 스트림 엔진**을 구현합니다.

---

## 입력 형식

표준 입력(stdin)으로 하나의 JSON 객체가 주어집니다.

```json
{
  "filesystem_config": {
    "initial_generation": 100
  },
  "initial_subvolumes": [
    {
      "subvol_id": 5,
      "name": "root_fs",
      "generation": 100,
      "is_readonly": false,
      "files": [
        {
          "path": "/etc/fstab",
          "size": 100,
          "extents": [
            {"offset": 0, "length": 100, "generation": 100, "data_hash": "h_fstab"}
          ]
        }
      ]
    }
  ],
  "operations": [
    {
      "op": "create_snapshot",
      "source_subvol_id": 5,
      "target_subvol_id": 256,
      "target_name": "snap_base",
      "readonly": true
    },
    {
      "op": "write_file",
      "subvol_id": 5,
      "path": "/var/log/app.log",
      "offset": 0,
      "length": 4096,
      "data_hash": "h_log1"
    },
    {
      "op": "fsync_file",
      "subvol_id": 5,
      "path": "/var/log/app.log"
    },
    {
      "op": "commit_transaction"
    },
    {
      "op": "create_snapshot",
      "source_subvol_id": 5,
      "target_subvol_id": 257,
      "target_name": "snap_next",
      "readonly": true
    },
    {
      "op": "btrfs_send",
      "parent_subvol_id": 256,
      "target_subvol_id": 257
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마를 갖는 단일 JSON 객체를 압축 공백 없이 출력합니다 (`json.dumps(..., separators=(',', ':'))`).

```json
{
  "operations": [
    {
      "op": "create_snapshot",
      "source_subvol_id": 5,
      "target_subvol_id": 256,
      "status": "SUCCESS",
      "is_readonly": true,
      "files_shared_cow": 1,
      "generation": 100
    }
  ],
  "btrfs_subsystem_metrics": {
    "snapshots_created": 2,
    "cow_extents_allocated": 1,
    "fsync_log_items_written": 1,
    "tree_log_replays": 0,
    "transaction_commits": 1,
    "send_streams_generated": 1,
    "bytes_sent": 4096
  },
  "filesystem_state": {
    "current_generation": 101,
    "total_subvolumes": 3,
    "active_tree_log_inodes": 0
  }
}
```

---

## 제약 사항

- $1 \le |\text{initial\_subvolumes}| \le 10$
- $1 \le |\text{operations}| \le 50$
- 세대 번호(Generation): $1 \le \text{generation} \le 10^{6}$
- 파일 크기 및 익스텐트 길이: $0 \le \text{length} \le 10^{9}$
- 시간 복잡도: 각 연산당 $O(F + E)$ 이내 (여기서 $F$는 파일 수, $E$는 익스텐트 수)
- 공간 복잡도: $O(F + E)$ 이내
