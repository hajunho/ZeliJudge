# 이론: Linux Kernel XFS 지연 할당 (Delalloc) 및 투기적 EOF 사전 할당 아키텍처

## 1. 전통적 즉시 할당의 병목과 XFS 지연 할당의 철학

1990년대 초 SGI(Silicon Graphics)가 IRIX 운영체제를 위해 개발하고 이후 2001년 리눅스 커널에 메인라인으로 기증된 **XFS**는 고성능 슈퍼컴퓨팅 및 대규모 미디어 스트리밍 스토리지를 위해 탄생했습니다.

고전적인 Unix 파일시스템은 `write()` 시스템 콜이 실행되는 순간 파일시스템 블록 할당자를 호출하여 디스크 LBA(Logical Block Address)를 확정했습니다:
- 단점: 파일이 얼마나 커질지 모르는 상태에서 블록을 즉시 할당하면, 디스크 조각화가 발생하여 파일 하나가 수만 개의 불연속 청크로 쪼개집니다.
- **XFS의 패러다임 전환 (Delayed Allocation)**:
  "데이터가 실제로 디스크 플래터/플래시에 쓰여지기 직전(Page Cache Flush / Writeback)까지 블록 할당을 최대한 늦춘다(Delay)!"

---

## 2. 인코어 B+트리와 센티넬 블록 (`DELAYSTARTBLOCK`)

XFS는 메모리 내부의 익스텐트 리스트(`struct xfs_ifork` / `xfs_iext_tree`)에서 아직 디스크 번호가 부여되지 않은 지연 할당 익스텐트를 다음과 같은 특별한 센티넬 값으로 식별합니다:

```c
#define DELAYSTARTBLOCK ((xfs_fsblock_t)-2LL) /* 0xFFFFFFFFFFFFFFFE */

struct xfs_bmbt_irec {
    xfs_fileoff_t   br_startoff;  /* 파일 내부 논리 블록 오프셋 */
    xfs_fsblock_t   br_startblock; /* 물리 디스크 시작 블록 번호 (or DELAYSTARTBLOCK) */
    xfs_filblks_t   br_blockcount; /* 블록 개수 */
    xfs_exntst_t    br_state;      /* XFS_EXT_NORM 또는 XFS_EXT_UNWRITTEN */
};
```

1. `buffered_write()`가 호출되면:
   - 디스크 B+트리(Alloc AG B+tree)를 건드리지 않고, 전역 자유 블록 카운터(`xfs_mount->m_fdblocks`)에서 예약(`resv`)만 걸어둡니다.
   - 메모리 내 익스텐트 레코드에 `br_startblock = DELAYSTARTBLOCK` 상태의 익스텐트를 삽입합니다.
   - 메타데이터 I/O나 저널 로깅이 일체 발생하지 않으므로 VFS 쓰기 지연 시간이 마이크로초 단위로 단축됩니다.

---

## 3. 투기적 EOF 사전 할당 (Speculative EOF Preallocation)

순차적으로 파일에 데이터를 덧붙이는 로그 수집기나 비디오 레코더 프로세스는 작은 단위(예: 4KB~64KB)로 `write()`를 수없이 반복합니다.
- 매번 4KB씩 delalloc 익스텐트를 만들면 인메모리 B+트리가 비대해집니다.
- XFS는 파일의 끝을 확장하는 쓰기(`is_extending`)가 감지되면, 현재 요청된 블록 수에 비례하여(또는 여유 공간에 따라 최대 64MB까지) 뒤쪽 공간을 **투기적으로 사전 할당(Speculative Preallocation)**합니다 (`xfs_iomap_prealloc_size`).
- 결과적으로 후속 `write()`는 이미 예약된 delalloc 범위에 적중(Hit)하여 아무런 추가 할당 비용 없이 완벽하게 단일 거대 연속 익스텐트로 결합됩니다.

---

## 4. 라이트백 변환과 잉여 블록 트림 (`xfs_free_eofblocks`)

1. **플러시 시점 (`xfs_iomap_write_allocate`)**:
   - 커널 플러셔 스레드가 dirty 페이지를 디스크로 내보낼 때, XFS는 비로소 최적의 연속된 물리 블록 범위를 검색하여 단 한 번의 디스크 할당으로 수 메가바이트~수 기가바이트의 delalloc 익스텐트를 `REAL` 익스텐트로 변환합니다.
2. **트림 시점 (`xfs_free_eofblocks`)**:
   - 투기적 사전 할당으로 인해 파일의 실제 크기(`size`)를 넘어선 잉여 블록이 디스크/메모리에 예약된 채 남아 있을 수 있습니다.
   - 파일 디스크립터가 닫힐 때(`xfs_release`)나 시스템에 여유 블록이 부족해질 때, XFS 백그라운드 워커가 `EOF` 너머의 블록들을 원자적으로 잘라내어(`TRIM`) 전역 가용 풀로 환원시킵니다.

이 정교한 메커니즘을 통해 XFS는 극한의 동시 쓰기 환경에서도 파편화를 방지하고 고성능 스토리지의 한계 대역폭을 100% 이끌어냅니다.
