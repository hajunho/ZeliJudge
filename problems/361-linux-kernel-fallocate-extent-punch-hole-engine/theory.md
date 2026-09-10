# Linux Kernel Ext4 Extent Tree & Fallocate 심층 이론

## 1. 전통적인 간접 블록 매핑(Indirect Block Mapping)의 한계와 Extent Tree

초기 유닉스 및 ext2/ext3 파일시스템은 아이노드(inode) 내부에 직접 블록(Direct Blocks, 12개), 단일 간접(Single Indirect), 이중 간접(Double Indirect), 삼중 간접(Triple Indirect) 블록 포인터 배열을 유지했습니다.

### 1.1 간접 블록의 문제점
- **메타데이터 비대화**: 수 기가바이트 이상의 대용량 파일을 표현할 때, 데이터 블록 하나마다 4바이트의 포인터를 간접 블록에 일일이 저장해야 하므로 메타데이터 공간 낭비가 극심했습니다.
- **연속 읽기/쓰기 성능 저하**: 파일 블록들이 디스크 상에서 연속되어 있더라도, 포인터 블록들을 거쳐야만 주소를 해석할 수 있어 I/O 지연이 컸습니다.

### 1.2 Ext4 Extent 아키텍처
ext4(리눅스 2.6.28+)는 간접 블록 대신 **익스텐트(Extent)** 방식을 도입했습니다:
```c
struct ext4_extent {
    __le32 ee_block;    /* logical block extent covers */
    __le16 ee_len;      /* number of blocks covered by extent */
    __le16 ee_start_hi; /* high 16 bits of physical block */
    __le32 ee_start_lo; /* low 32 bits of physical block */
};
```
단 하나의 12바이트 구조체로 최대 $32,768$개의 연속된 물리 블록(4KB 블록 기준 128MB)을 표현할 수 있어 메타데이터가 수천 배 이상 압축됩니다.

---

## 2. Fallocate 시스템 콜과 제로-카피 익스텐트 조작

`int fallocate(int fd, int mode, off_t offset, off_t len);`

### 2.1 주요 플래그와 동작 메커니즘
1. **`FALLOC_FL_KEEP_SIZE` (0x01)**:
   - 공간을 사전 할당하더라도 파일 크기(`i_size`)를 확장하지 않습니다. 파일 끝(EOF) 너머에 공간을 미리 확보하여 추후 `append` 시 단편화(Fragmentation)를 방지합니다.
2. **`FALLOC_FL_PUNCH_HOLE` (0x02)**:
   - 반드시 `FALLOC_FL_KEEP_SIZE`와 함께 사용됩니다.
   - 디스크의 실제 물리 블록을 반환(Free)하고, 해당 범위를 익스텐트 트리 상에서 빈 공간(Hole / Sparse)으로 전환합니다.
   - 가상화 하이퍼바이저(KVM/QEMU)에서 게스트 OS가 `fstrim`을 호출할 때 호스트 이미지 파일의 미사용 공간을 디스크로 즉시 환원하는 핵심 기술입니다.
3. **`FALLOC_FL_ZERO_RANGE` (0x10)**:
   - 물리 블록을 할당된 상태로 유지하면서 데이터를 0으로 초기화합니다.
   - 디스크 I/O를 발생시키지 않고 메타데이터의 `ee_len`에 비기록 플래그(Unwritten Bit: 최상위 비트 1)를 설정하여, 읽을 때 0을 반환하도록 만듭니다.
4. **`FALLOC_FL_COLLAPSE_RANGE` (0x08)**:
   - 파일 중간의 특정 바이트 범위를 완전히 잘라내고, 뒤따르는 모든 블록을 앞으로 당겨 파일 크기를 줄입니다.
   - 데이터 복사(read & write) 없이 B-Tree 상의 `ee_block` 오프셋만 감산하므로 O(1) 수준의 메타데이터 작업만으로 즉각 완료됩니다.
5. **`FALLOC_FL_INSERT_RANGE` (0x20)**:
   - 파일 중간에 빈 구멍(Hole)을 삽입하고 뒤쪽 익스텐트들을 뒤로 밀어 파일 크기를 늘립니다.

---

## 3. 익스텐트 병합(Coalescing) 알고리즘

익스텐트 트리의 탐색 효율을 극대화하기 위해, 인접한 두 익스텐트는 다음 불변식을 만족할 때 즉시 하나로 병합되어야 합니다:
$$E_1.lblk + E_1.len = E_2.lblk$$
$$E_1.state = E_2.state$$
$$\text{If } state \ne \text{HOLE}: \quad E_1.pblk + E_1.len = E_2.pblk$$
만약 물리 블록이 연속되지 않으면 병합될 수 없으며, 이는 파일의 물리적 단편화(Fragmentation)를 반영합니다.
