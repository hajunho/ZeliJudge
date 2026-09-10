# Problem #296: Btrfs Copy-on-Write B-Tree와 Tree Log 빠른 fsync 이론

## 1. 순수 CoW 파일시스템의 딜레마: 포인터 버블링(Pointer Bubbling)

Btrfs와 OpenZFS 같은 Copy-on-Write 파일시스템은 데이터 덮어쓰기(In-place Overwrite)를 절대 수행하지 않습니다. 파일의 일부가 변경되면 항상 새로운 디스크 블록에 데이터를 기록합니다.

그러나 이는 **포인터 버블링(Pointer Bubbling)** 문제를 필연적으로 수반합니다:
1. 리프 노드 $L$의 주소가 $A_1$에서 $A_2$로 바뀝니다.
2. 부모 내부 노드 $P$는 $L$을 가리키던 포인터를 $A_2$로 수정해야 하므로, $P$ 역시 새로운 블록 $P_2$로 CoW 복사됩니다.
3. 이 수정은 상위 부모를 거쳐 루트 트리(Root Tree), 청크 트리(Chunk Tree), 그리고 최종적으로 디스크의 고정 위치에 있는 **슈퍼블록(Superblock)**까지 연쇄적으로 전파됩니다.

만약 데이터베이스가 매 트랜잭션마다 `fsync()`를 호출할 때마다 전체 트랜잭션을 디스크에 커밋한다면, 수 메가바이트의 메타데이터와 슈퍼블록이 매번 동기식으로 기록되어 디스크 IOPS가 심각하게 낭비됩니다.

---

## 2. Btrfs Tree Log의 아키텍처와 경량 동기화

Btrfs 커널 개발자 크리스 메이슨(Chris Mason)은 이를 해결하기 위해 **Tree Log (Fast Intent Log: `fs/btrfs/tree-log.c`)**를 설계했습니다.

```mermaid
graph TD
    subgraph Main_Filesystem [메인 Btrfs B-Tree]
        Super[Superblock transid=10] --> RootTree[Root Tree]
        RootTree --> Subvol[Subvolume Tree root]
        Subvol --> InodeItem[Inode 101 Item]
        InodeItem --> ExtentData[Extent 0..4KB]
    end

    subgraph Tree_Log [전용 Tree Log B-Tree]
        LogRoot[Log Root Tree transid=10] --> LogSubvol[Log Subvolume]
        LogSubvol --> LogInode[Log Inode 101]
        LogInode --> NewExtent[New Extent 4..8KB]
    end

    App[App: fsync fd 101] -->|btrfs_sync_log| Tree_Log
    Note over Tree_Log: 메인 B-Tree와 Superblock 수정 없이<br/>오직 Log Tree에만 익스텐트 기록!
```

### 1) 빠른 fsync 경로 (`btrfs_sync_log`)
- `fsync()` 대상이 되는 inode의 메타데이터(`INODE_ITEM`)와 변경된 익스텐트(`EXTENT_DATA`)만 서브볼륨 전용 Log Tree에 추가(Append)합니다.
- 슈퍼블록을 건드리지 않고 Log Tree의 루트 블록만 디스크에 기록하므로 단 1~2회의 순차 I/O만으로 fsync가 완료됩니다.
- 응답 속도는 기존 ext4의 저널링 jbd2 속도와 대등해집니다.

### 2) 주기적 트랜잭션 커밋 (`btrfs_commit_transaction`)
- Btrfs는 백그라운드 스레드(`cleaner` / `transaction-kthread`)를 통해 30초마다 전체 메인 B-Tree를 일괄 CoW 커밋합니다.
- 트랜잭션이 안전하게 디스크에 영구 고정되면, Log Tree의 내용은 메인 트리에 완전히 포함되었으므로 Log Tree의 모든 블록을 해제(Free)하고 `transid`를 1 증가시킵니다.

---

## 3. 크래시 복구: `btrfs_replay_log()`

전원 장애나 커널 패닉으로 비정상 종료된 후 시스템이 다시 마운트될 때:
1. 슈퍼블록의 `generation(transid)`과 Log Tree의 `log_transid`를 비교합니다.
2. 두 값이 일치하면, 마지막 전체 트랜잭션 커밋 이후 `fsync()`로 보호된 유효한 데이터가 Log Tree에 남아있음을 의미합니다.
3. 마운트 복구 스레드는 Log Tree의 익스텐트들을 메인 B-Tree로 신속하게 복사(Replay)한 뒤 Log Tree를 삭제합니다.
4. 만약 fsync되지 않고 메모리에만 있던 쓰기는 깨끗하게 폐기되어 이전 트랜잭션 상태로 완전한 일관성(Consistency)을 유지합니다.
