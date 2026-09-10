# 문제 462: Linux Kernel XFS 지연 할당 (Delalloc) 및 투기적 사전 할당 엔진

## 문제 설명

엔터프라이즈 리눅스(RHEL, Rocky, AlmaLinux)의 기본 고성능 파일시스템인 **XFS**(`fs/xfs/`)는 수억 개의 파일과 페타바이트급 볼륨을 고속으로 처리하도록 설계되었습니다.

전통적인 파일시스템이 `write()` 시스템 콜마다 즉시 물리 디스크 블록을 할당하던 방식은 두 가지 치명적인 병목을 유발했습니다:
1. **극심한 파일 단편화(Fragmentation)**: 애플리케이션이 4KB 단위로 반복 쓰기를 수행하면, 디스크 상에 수천 개의 불연속적인 1블록 익스텐트가 흩뿌려져 읽기 성능이 수직 낙하합니다.
2. **저널링 및 할당 락 경합**: 쓰기마다 메타데이터 저널 트랜잭션과 할당 그룹(AG, Allocation Group) 락을 획득해야 하므로 멀티코어 확장성이 제한됩니다.

XFS는 이를 극복하기 위해 **인코어 지연 할당(Delayed Allocation: Delalloc)** 및 **투기적 EOF 사전 할당(Speculative EOF Preallocation)** 기법(`fs/xfs/xfs_iomap.c`, `fs/xfs/libxfs/xfs_bmap.c`)을 구현하였습니다:

```
+-----------------------------------------------------------------------------------------+
|                  XFS Delayed Allocation & Speculative Preallocation                     |
+-----------------------------------------------------------------------------------------+

 [User Application: write(8KB)]
               |
               v
 [Step 1: In-Core Delalloc Reservation]
  - Does NOT allocate physical disk blocks!
  - Reserves total_needed = needed(2 blocks) + speculative(2 blocks) in global counter.
  - Inserts DELALLOC extent into in-memory B+tree:
    [offset: 0, startblock: DELAYSTARTBLOCK, blockcount: 4, state: "DELALLOC"]

 [User Application: Next write(8KB) at offset 8KB]
               |
               v
 [Step 2: Preallocation Hit!]
  - Checks in-memory extent: block 2..4 is ALREADY covered by [0, 4)!
  - ZERO new disk reservation needed! Seamless coalescing!

 [Page Cache Flusher: sync() / xfs_iomap_write_allocate()]
               |
               v
 [Step 3: Conversion to REAL Extent]
  - Allocates 8 contiguous physical blocks on disk:
    [offset: 0, startblock: 1000, blockcount: 8, state: "REAL"]

 [File Close: close() / xfs_free_eofblocks()]
               |
               v
 [Step 4: Trim Speculative EOF Blocks]
  - File size is 24KB (6 blocks).
  - Trailing 2 unused speculative blocks trimmed and returned to free pool!
```

### 핵심 메커니즘
1. **지연 할당(Delalloc) 예약**:
   - `BUFFERED_WRITE` 시 실제 물리 블록 대신 가상 센티넬 블록(`DELAYSTARTBLOCK = 0xFFFFFFFFFFFFFFFE`)을 가지는 인메모리 익스텐트를 생성하고, 전역 예약 카운터(`reserved_blocks`)만 증가시킵니다.
2. **투기적 사전 할당(Speculative Preallocation)**:
   - 파일 크기를 확장하는 쓰기가 발생하면, 향후 이어질 순차 추가 쓰기를 대비하여 `needed_blocks * prealloc_multiplier`만큼의 추가 블록을 선제적으로 예약합니다.
   - 후속 쓰기가 이미 예약된 사전 할당 범위 내에 들어오면(`DELALLOC_HIT_PREALLOC`), 새로운 블록 예약 없이 기존 익스텐트를 재사용합니다.
3. **물리 블록 변환 및 익스텐트 병합 (`FLUSH_WRITEBACK`)**:
   - 더티 페이지 플러시 시 인메모리 delalloc 익스텐트에 연속된 실제 물리 디스크 블록을 할당하여 `REAL` 상태로 전환합니다.
   - 파일 오프셋과 물리 블록이 연속된 인접 익스텐트들은 단일 거대 익스텐트로 자동 병합(`extents_merged += 1`)됩니다.
4. **EOF 블록 회수 (`TRIM_EOF_BLOCKS`)**:
   - 파일이 닫히거나 메모리 압박 시, 실제 파일 크기(`size`)를 초과하는 미사용 투기적 사전 할당 블록을 잘라내어 디스크 가용 공간으로 환원합니다 (`eof_trimmed_blocks`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `config`:
  - `total_disk_blocks`: int (기본값: 100000)
  - `prealloc_multiplier`: int (기본값: 1)
- `operations`: 일련의 연산 배열.

지원되는 연산:
1. `{"op": "BUFFERED_WRITE", "inode_id": int, "file_offset": int, "length": int}`
   - 지연 할당 쓰기를 수행합니다. 공간 부족 시 `ENOSPC_DISK_FULL`.
2. `{"op": "FLUSH_WRITEBACK", "inode_id": int}`
   - 지정된 inode의 모든 delalloc 익스텐트를 실제 물리 디스크 익스텐트로 변환하고 인접 익스텐트를 병합합니다.
3. `{"op": "TRIM_EOF_BLOCKS", "inode_id": int}`
   - 파일 끝(EOF)을 초과하는 잉여 사전 할당 블록을 해제합니다.
4. `{"op": "QUERY_XFS_STATE"}`
   - 잔여 디스크 블록, 예약 블록, inode별 익스텐트 목록, 통계(`stats`)를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
