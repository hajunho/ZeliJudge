# Theory #431: 리눅스 커널 fs/iomap 아키텍처와 차세대 다이렉트 I/O (O_DIRECT) 메커니즘

## 1. 개요 및 배경 (Historical Context & Problem Definition)

### 1.1 레거시 buffer_head 구조의 한계
리눅스 초기 시절(Linux 2.x~3.x)의 VFS(Virtual File System) 계층은 모든 블록 디바이스 I/O를 `struct buffer_head`를 통해 관리했습니다. 파일이 1GB라고 가정할 때, 4KB 블록마다 하나씩 총 262,144개의 `buffer_head` 인스턴스가 할당되어야 했습니다.
이 모델의 치명적 결함은 다음과 같습니다:
1. **막대한 메모리 풋프린트**: 구조체 크기 104바이트 및 슬랩 할당자 오버헤드로 인해 페타바이트급 파일 시스템에서 테라바이트 단위의 커널 메모리가 `buffer_head`에 낭비되었습니다.
2. **다중 락 경합 및 바운싱**: 각 블록마다 독립적인 원자적 비트 락(`BH_Locked`)과 참조 카운트를 유지하여, 멀티코어 환경에서 심각한 L1/L2 캐시라인 바운싱이 일어났습니다.
3. **불연속 I/O 디스크립터**: 디스크 물리 블록이 연속적으로 배치되어 있어도 `buffer_head` 체인을 일일이 연결해야 하여 고속 DMA(Direct Memory Access) 벡터 구성이 극도로 비효율적이었습니다.

### 1.2 fs/iomap의 탄생
리눅스 4.8에서 도입된 `fs/iomap` 프레임워크는 개별 블록 단위 대신 **바이트 범위의 익스텐트(Extent)**를 기반으로 I/O를 추상화했습니다.
`struct iomap`은 스택에 값으로 전달되는 경량 구조체(64바이트 미만)로, 다음과 같은 필드를 갖습니다:
```c
struct iomap {
    u64 offset;    /* 파일 내 논리 오프셋 (바이트) */
    u64 length;    /* 익스텐트 길이 (바이트) */
    u64 addr;      /* 디바이스 물리 블록 주소 (바이트, HOLE 시 IOMAP_NULL_ADDR) */
    u16 type;      /* IOMAP_HOLE, IOMAP_MAPPED, IOMAP_UNWRITTEN 등 */
    u16 flags;     /* IOMAP_F_MERGED, IOMAP_F_SHARED 등 */
    struct block_device *bdev;
};
```
이로써 `buffer_head`를 메모리에 전혀 유지하지 않고도 테라바이트급 파일의 I/O를 단 한 번의 익스텐트 순회로 처리할 수 있게 되었습니다.

---

## 2. iomap 다이렉트 I/O (O_DIRECT) 파이프라인

### 2.1 iomap_iter 반복자 패턴
현대 파일 I/O는 `iomap_iter` 루프를 통해 구동됩니다:
```c
struct iomap_iter iter = {
    .inode = inode,
    .pos = offset,
    .len = length,
    .flags = IOMAP_DIRECT,
};

while ((ret = iomap_iter(&iter, &ops)) > 0) {
    iter.processed = iomap_dio_bio_actor(&iter);
}
```
- `iomap_iter()`는 파일 시스템 고유의 `iomap_begin()` 콜백을 호출하여 현재 `iter.pos`가 속한 익스텐트 정보를 채웁니다.
- I/O 엔진은 해당 익스텐트 범위 내에서 처리 가능한 최대 길이를 연산하고 `bio`를 조립한 뒤, 실제로 처리된 바이트 수(`iter.processed`)를 반환합니다.
- `iomap_iter()`는 내부적으로 `iter.pos += iter.processed`, `iter.len -= iter.processed`를 수행하며, 요청된 모든 바이트가 완료될 때까지 자동으로 다음 익스텐트를 질의합니다.

---

## 3. 5대 익스텐트 상태 머신과 Zero-Copy 처리

### 3.1 IOMAP_HOLE (희소 파일 구멍)
- 파일 시스템 내에 블록이 전혀 할당되지 않은 논리적 빈 공간입니다.
- **다이렉트 읽기**: 디스크 컨트롤러에 어떠한 I/O 명령도 전송하지 않습니다. 대신 유저 메모리 버퍼를 커널 내부에서 `memset(buf, 0, len)`으로 직접 제로화하여 NVMe/SATA 인터페이스 지연 시간을 완벽히 제거합니다.
- **다이렉트 쓰기**: 사전 할당 없는 다이렉트 쓰기가 발생하면, 파일 시스템 메타데이터 할당기(예: XFS의 B+Tree 할당자)가 즉각 물리 블록을 배정하고 `IOMAP_MAPPED`로 전환합니다.

### 3.2 IOMAP_UNWRITTEN (사전 할당된 미기록 블록)
- `fallocate(FALLOC_FL_KEEP_SIZE)` 시스템 콜 등을 통해 디스크 디스크립터는 확보되었으나, 아직 실제 데이터가 기록되지 않은 상태입니다.
- **정보 유출 방어(Security Sanitization)**: 만약 디스크에 이전 사용자의 삭제된 데이터가 물리적으로 남아있더라도, 커널이 이를 읽지 못하도록 `IOMAP_UNWRITTEN` 범위에 대한 다이렉트 읽기는 무조건 0으로 채워 반환합니다.
- **쓰기 완료 시의 상태 전이 (Unwritten Conversion)**:
  - 유저가 UNWRITTEN 익스텐트의 일부에 쓰기를 수행하면, 데이터 쓰기 자체는 물리 주소로 전송됩니다.
  - I/O가 하드웨어에서 성공적으로 커밋되면(`end_io` 인터럽트), 파일 시스템 트랜잭션 저널을 열어 쓰기가 완료된 바이트 범위만 정확히 `IOMAP_MAPPED`로 승격하고, 앞뒤 미기록 구간은 `IOMAP_UNWRITTEN`으로 분할 보존합니다.

---

## 4. 하드웨어 바운더리와 Bio Splitting

현대 스토리지 컨트롤러는 단일 DMA 트랜잭션으로 전송할 수 있는 최대 페이지 수(Scatter-Gather List 크기) 또는 바이트 상한(`max_sectors`, `max_bio_size`)을 갖습니다.
- 만약 유저가 1MB 다이렉트 쓰기를 요청하고 하드웨어의 `max_bio_size`가 64KB라면, `iomap` 계층은 1MB 물리 연속 익스텐트라 할지라도 16개의 64KB `bio` 인스턴스로 분할하여 블록 레이어 큐(`blk-mq`)에 인큐합니다.
- 각 `bio`는 비동기 완료 콜백(`iomap_dio_bio_end_io`)을 공유하며, 모든 분할 `bio`가 성공했을 때 최종 유저스페이스 시스템 콜이 반환되거나 `io_uring` CQE가 발행됩니다.

---

## 5. 섹터 정렬과 커널-하드웨어 협약 (Sector Alignment)

`O_DIRECT`의 본질은 **"커널 페이지 캐시를 완전히 우회(Bypass)하고, 유저 공간의 가상 메모리 버퍼를 직접 PCIe 버스를 통해 스토리지 컨트롤러의 DMA 엔진에 매핑하는 것"**입니다.
- 스토리지 하드웨어는 바이트 단위의 임의 오프셋 DMA를 지원하지 않으며, 컨트롤러의 하드웨어 섹터 크기(512B 또는 4096B Advanced Format) 경계에 정확히 정렬된 I/O만 수락합니다.
- 따라서 `offset` 또는 `length`가 섹터 크기의 정수배가 아닌 경우, 커널은 데이터 손상과 하드웨어 DMA 오류를 방지하기 위해 POSIX 표준에 따라 즉각 `-EINVAL` 오류를 반환합니다.
