# 리눅스 커널 Bcachefs 차세대 CoW B-트리 익스텐트 및 저널 할당자 엔진 (Linux Kernel Bcachefs Copy-on-Write B-Tree Extent & Journal Allocator Engine - fs/bcachefs/)

## 문제 설명

리눅스 커널 6.7에 공식 머지된 **Bcachefs(`fs/bcachefs/`)**는 켄트 오버스트리트(Kent Overstreet)가 주도하여 개발한 차세대 Copy-on-Write(CoW) 파일 시스템입니다. 기존의 Btrfs와 OpenZFS가 가진 아키텍처적 한계를 극복하고, B-트리 중심의 순수 키-값 스토리지 아키텍처 위에 POSIX 파일 시스템을 재구축하였습니다.

Bcachefs의 핵심 설계 철학은 **"모든 것은 B-트리 키이다"**라는 원칙입니다. 전통적인 파일 시스템이 아이노드 테이블, 블록 비트맵, 익스텐트 트리를 별도로 관리했던 것과 달리, Bcachefs는 다중 버전(Multi-version) 지원 키인 `bpos = (inode, offset, snapshot_id)`를 B-트리의 기본 키로 사용합니다:

```
                  Bcachefs B-Tree Key & Multi-Version Architecture
       bpos = (inode_id: 64-bit, offset_kb: 64-bit, snapshot_id: 32-bit)
   +--------------------------------------------------------------------+
   | B-Tree Node: [ (101, 0, 0) -> ExtentPtr(Bucket 0, Off 0, Gen 0) ]  |
   |              [ (101, 0, 1) -> ExtentPtr(Bucket 0, Off 128, Gen 0)]| <= CoW Divergence!
   +--------------------------------------------------------------------+
                   |                                     ^
                   v                                     |
   +-------------------------------+   +--------------------------------+
   | Bucket Allocator (buckets.c)  |   | Journal Ring Buffer (journal.c)|
   | Fixed-size Buckets (e.g.512KB)|   | Write-Ahead Log (WAL)          |
   | Generations for Stale Guard   |   | Crash Replay & Consistency     |
   +-------------------------------+   +--------------------------------+
                   |                                     |
                   +-----------------+-------------------+
                                     v
                       [ Snapshot Inheritance Tree ]
                       Root (0) <--- Snap 1 <--- Snap 2
                       Hierarchical ancestor fallback lookup
```

Bcachefs의 4대 핵심 컴포넌트는 다음과 같습니다:
1. **다중 버전 B-트리 (`bkey`, `bpos`)**: 키는 `(inode, offset, snapshot_id)`로 정렬되며, 값은 디바이스 번호, 버킷 ID, 버킷 내 오프셋, 세대 번호(`generation`)를 담고 있는 익스텐트 포인터입니다.
2. **버킷 할당자 (Bucket Allocator - `buckets.c`)**: 디스크를 균일한 크기(예: 512KB)의 버킷(Bucket) 단위로 분할 관리하며, 각 버킷마다 세대 번호(`generation`)를 부여하여 포인터 에이징 및 댕글링 참조를 원천 차단합니다.
3. **저널 링버퍼 (Journal WAL - `journal.c`)**: B-트리 리프 노드가 디스크에 플러시되기 전 모든 메타데이터 변경 내역(`WRITE_EXTENT`, `CREATE_SNAPSHOT` 등)을 선행 기록하는 순환 저널 링버퍼로, 크래시 발생 시 미플러시 저널을 리플레이하여 100% 무손실 복구를 달성합니다.
4. **계층적 스냅샷 트리 (Snapshot Tree - `snapshot.c`)**: 스냅샷 생성 시 데이터를 복사하지 않고 부모 스냅샷 ID만을 기록합니다. 읽기 요청 시 현재 스냅샷에 익스텐트가 없으면 부모 조상(Ancestor)으로 거슬러 올라가며 데이터를 조회(Fallback Lookup)하고, 쓰기 발생 시에만 해당 스냅샷 전용 익스텐트를 새로 할당하는 진정한 제로 카피 CoW를 실현합니다.

본 문제에서는 리눅스 커널 `fs/bcachefs/`의 핵심 메커니즘을 충실히 모델링한 시뮬레이션 엔진을 구현합니다.

---

## 핵심 메커니즘 및 수리 모델

### 1. 다중 버전 B-트리 키 및 익스텐트
- 키 포맷: `bpos = (inode, offset_kb, snapshot_id)`
- 익스텐트 포인터: `ptr = {bucket_id, bucket_offset_kb, generation, size_kb}`
- 덮어쓰기(Overwrite) 발생 시 기존 익스텐트가 점유하던 버킷의 `dirty_kb`를 반환하고, 새로운 버킷 공간에 out-of-place CoW 할당을 수행합니다.

### 2. 버킷 할당자 (Bucket Allocator)
- 총 $N$개의 버킷(`bucket_id` 0 ~ $N-1$)이 존재하며, 각 버킷의 크기는 `bucket_size_kb`(기본 512KB)입니다.
- 할당 전략: 여유 공간 `free_kb >= size_kb`인 첫 번째 버킷(First-Fit)에 순차 할당합니다.
- 버킷이 가득 차면(`free_kb == 0`) `is_full = True`로 전환되어 다음 버킷으로 롤오버됩니다.

### 3. 계층적 스냅샷 조회 (Hierarchical Snapshot Lookup)
특정 스냅샷 $S$에서 `(inode, offset_kb)` 읽기 요청 시:
1. $S$에 직접 매핑된 `(inode, offset_kb, S)` 익스텐트가 존재하면 해당 데이터를 즉시 반환합니다 (`ancestor_hops = 0`).
2. 존재하지 않는다면 $S$의 부모 스냅샷 `parent_id`로 거슬러 올라가 조상 트리를 순차 탐색합니다 (`ancestor_hops` 1씩 증가).
3. 루트(0)까지 탐색해도 없다면 `NOT_FOUND`를 반환합니다.

### 4. 저널 선행 기록 및 크래시 복구 (Crash Recovery)
- 모든 B-트리 수정 연산(`WRITE_EXTENT`, `CREATE_SNAPSHOT`)은 `journal_seq`를 1씩 증가시키며 저널 링버퍼에 먼저 커밋됩니다.
- 저널 플러시(`FLUSH_JOURNAL`) 시 `flushed_journal_seq`가 현재 `journal_seq`로 동기화됩니다.
- 크래시 발생 후 복구(`CRASH_AND_RECOVER`) 시 `flushed_journal_seq` 이후 기록된 모든 미플러시 저널 엔트리를 순차 리플레이하여 B-트리와 스냅샷 트리를 완벽히 재구축합니다.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "bucket_size_kb": 512,
    "total_buckets": 8,
    "journal_capacity": 32
  },
  "operations": [
    {"op": "GET_STATE"},
    {"op": "WRITE_EXTENT", "inode": 101, "offset_kb": 0, "size_kb": 64, "snapshot_id": 0, "data_hash": "data_block_0"},
    {"op": "CREATE_SNAPSHOT", "parent_id": 0, "snapshot_name": "backup_v1"},
    {"op": "READ_EXTENT", "inode": 101, "offset_kb": 0, "snapshot_id": 1},
    {"op": "FLUSH_JOURNAL"},
    {"op": "CRASH_AND_RECOVER", "uncommitted_crash": true},
    {"op": "GET_STATE"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 수행 결과와 최종 누적 통계를 담은 JSON을 출력합니다:

```json
{
  "results": [
    {
      "op": "WRITE_EXTENT",
      "inode": 101,
      "offset_kb": 0,
      "size_kb": 64,
      "snapshot_id": 0,
      "allocated_ptr": {
        "bucket_id": 0,
        "bucket_offset_kb": 0,
        "generation": 0,
        "size_kb": 64
      },
      "journal_seq": 1
    }
  ],
  "final_summary": {
    "total_extents": 1,
    "total_snapshots": 2,
    "journal_seq": 2,
    "flushed_journal_seq": 2,
    "total_used_kb": 64,
    "total_dirty_kb": 64,
    "stats": {
      "cow_writes": 1,
      "extent_splits": 0,
      "bucket_allocations": 1,
      "snapshots_created": 1,
      "journal_commits": 2,
      "journal_replays": 0,
      "reclaimed_buckets": 0
    },
    "event_count": 3
  }
}
```
