# Problem #296: Linux Btrfs Copy-on-Write (CoW) Tree-Log Fast fsync & Crash Replay

## 1. 개요 및 배경 (Overview & Background)

리눅스 차세대 파일 시스템인 **Btrfs (B-tree File System)**는 데이터와 메타데이터의 완전한 **Copy-on-Write (CoW)**를 통해 스냅샷 생성, 자가 복구 체크섬(CRC32c/xxhash), 서브볼륨 분할 등 강력한 스토리지 기능을 제공합니다.

그러나 순수 CoW 파일 시스템에는 치명적인 I/O 병목이 존재합니다:
- 파일의 단 1바이트만 수정되더라도 새로운 리프 블록(Leaf)을 할당해야 하며, 부모 노드부터 파일시스템 최상위 루트 트리(Root Tree)와 슈퍼블록(Superblock)까지 모든 포인터를 재작성해야 합니다.
- 만약 데이터베이스(PostgreSQL, SQLite)나 메시지 큐(Kafka)가 `fsync()`를 빈번하게 호출할 때마다 전체 파일시스템 트랜잭션을 디스크에 커밋(`btrfs_commit_transaction`)한다면, 디스크 헤드 탐색(Head Thrashing)과 슈퍼블록 플러시 오버헤드로 인해 초당 트랜잭션 수(TPS)가 90% 이상 폭락합니다.

이를 해결하기 위해 Btrfs는 커널(`fs/btrfs/tree-log.c`)에 **트리 로그(Tree Log / Fast Intent Log)** 서브시스템을 구축했습니다.

```
+-------------------------------------------------------------------------------+
|                      Linux Btrfs Tree-Log Fast fsync Architecture             |
+-------------------------------------------------------------------------------+
  [ Userspace Process ] (e.g. PostgreSQL WAL write)
            |
            | 1. write(fd, buf, 4096)
            v
  [ Memory Page Cache & Subvol Inode ] (Dirty Extent created)
            |
            | 2. fsync(fd)
            v
  +-----------------------------------------------------------------------------+
  | btrfs_sync_log(trans, root, inode) [Fast Path]                              |
  +-----------------------------------------------------------------------------+
    - 슈퍼블록/전체 트랜잭션 커밋 생략!
    - 오직 해당 inode의 변경된 익스텐트(EXTENT_DATA)만 독립된 Log Tree에 추가 기록
    - log_transid = transid 마킹 후 초고속 디스크 플러시 (1~2 I/O만 소요)
            |
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  [ Power Cut / Sudden Kernel Panic! ]
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            |
            v
  [ System Reboot & Mount: btrfs_replay_log() ]
    - Superblock transid와 Log Tree log_transid 일치 확인
    - Log Tree의 익스텐트들을 메인 Subvolume B-Tree로 즉시 병합(Replay)
    - 미완료 트랜잭션의 비fsync 익스텐트는 안전하게 롤백(Clean Rollback)
```

### 핵심 아키텍처 원리
1. **패스트 패스 (`btrfs_sync_log`)**:
   - `fsync()` 호출 시 무거운 전체 트랜잭션을 커밋하지 않고, 수정된 inode 메타데이터와 신규 익스텐트만 전용 **Log Tree**에 가볍게 기록합니다.
2. **트랜잭션 주기적 커밋 (`btrfs_commit_transaction`)**:
   - 수 초(기본 `commit_sec=30`)마다 전체 파일시스템 변경사항을 메인 B-Tree에 플러시하고, `transid`를 증가시키며, 임무를 다한 Log Tree를 해제(Free)합니다.
3. **크래시 리플레이 (`btrfs_replay_log`)**:
   - 마운트 시 유효한 Log Tree(`log_transid == transid`)가 발견되면 익스텐트를 메인 트리로 복원하여 파일 손실을 0으로 만듭니다.
4. **풀 커밋 폴백 (`BTRFS_NEED_TRANS_COMMIT`)**:
   - 크로스 디렉토리 리네임(Rename) 등 복잡한 디렉토리 종속성이 얽힌 경우, 안전을 위해 즉시 전체 트랜잭션 커밋으로 폴백합니다.

이 문제에서는 Btrfs 커널 드라이버의 핵심 CoW 및 Tree-Log 메커니즘을 정밀 시뮬레이션하여, 빠른 fsync 기록, 전체 트랜잭션 커밋, 불시 전원 장애 후 마운트 리플레이 복구 및 미-fsync 롤백 상태 머신을 구현합니다.

---

## 2. 입출력 규격 (Input & Output Specification)

### 입력 형식 (Standard Input)
표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {},
  "initial_files": [
    {"inode_id": 101, "size": 0}
  ],
  "events": [
    {
      "type": "WRITE",
      "time_us": 10.0,
      "inode_id": 101,
      "offset": 0,
      "len": 4096,
      "block": 50001
    },
    {
      "type": "FSYNC",
      "time_us": 20.0,
      "inode_id": 101,
      "force_full_commit": false
    },
    {
      "type": "CRASH",
      "time_us": 30.0
    }
  ]
}
```

- `config`: 파일시스템 환경 설정.
- `initial_files`: 초기 생성 파일 목록 (`inode_id`, `size`).
- `events`: 시간순 파일시스템 이벤트 목록.
  - `type`:
    - `"WRITE"`: 파일 익스텐트 쓰기 (`inode_id`, `offset`, `len`, `block`).
    - `"TRUNCATE"`: 파일 크기 축소 (`inode_id`, `new_size`).
    - `"FSYNC"`: 파일 동기화 (`inode_id`, `force_full_commit`).
    - `"COMMIT_TRANSACTION"`: 전체 트랜잭션 커밋.
    - `"CRASH"`: 불시 전원 차단 및 마운트 리플레이.

### 처리 규칙 (Processing Rules)

1. **파일 쓰기 (`WRITE`) 및 축소 (`TRUNCATE`)**:
   - 메모리 상의 파일 구조체(`memory_tree`)에 익스텐트를 추가하거나 크기를 변경합니다.
2. **파일 동기화 (`FSYNC`)**:
   - `force_full_commit == true`인 경우: 전체 트랜잭션을 즉시 커밋합니다.
   - `force_full_commit == false`인 경우: **Tree-Log 빠른 경로**를 실행합니다:
     - `has_log_tree = true`, `log_transid = transid`.
     - 해당 `inode_id`의 현재 메모리 상태(크기, 익스텐트 목록)를 `log_tree`에 복사 기록합니다.
     - `fast_fsync_log_count += 1`.
3. **전체 트랜잭션 커밋 (`COMMIT_TRANSACTION`)**:
   - 현재 메모리의 모든 파일 상태를 메인 커밋 트리(`committed_tree`)로 플러시합니다.
   - `log_tree`를 비우고 `has_log_tree = false`로 리셋합니다.
   - `transid += 1`, `full_trans_commit_count += 1`.
4. **전원 차단 및 마운트 리플레이 (`CRASH`)**:
   - 메모리 상태는 완전히 소실되므로 `committed_tree` 상태로 초기화됩니다.
   - `log_tree`가 존재하고 `log_transid == transid`인 경우:
     - Log Tree에 기록된 모든 파일의 크기와 익스텐트를 `committed_tree` 및 `memory_tree`로 병합(Replay)합니다.
     - `recovered_files_count` 및 `replayed_extents_count`를 갱신하고 Log Tree를 정리합니다.
   - fsync되지 않고 메모리에만 머물던 익스텐트들은 유실되므로 `unfsynced_lost_extents`에 가산합니다.

### 출력 형식 (Standard Output)
단일 행의 표준 JSON 형식으로 출력합니다.
```json
{
  "metrics": {
    "fast_fsync_log_count": 1,
    "full_trans_commit_count": 0,
    "replayed_extents_count": 1,
    "recovered_files_count": 1,
    "unfsynced_lost_extents": 0
  },
  "current_transid": 1,
  "committed_files": {
    "inode_101": {
      "size": 4096,
      "extents_count": 1,
      "extents": [
        {"offset": 0, "len": 4096, "disk_block": 50001}
      ]
    }
  },
  "diagnostics": {
    "status": "HEALTHY_CONSISTENT",
    "anomalies": []
  },
  "event_log_sample": []
}
```

---

## 3. 제약 사항 (Constraints)
- `events` 수: $1 \le N \le 5,000$
- `inode_id`: $1 \le ID \le 100,000$
- 익스텐트 오프셋 및 길이: $0 \le \text{offset} \le 10^{9}$, $1 \le \text{len} \le 10^{7}$
- Python 3 표준 라이브러리만 사용합니다 (`json`, `sys`).
