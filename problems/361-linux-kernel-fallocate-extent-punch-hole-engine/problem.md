# Linux Kernel VFS/ext4 Fallocate 익스텐트 트리(Extent Tree) 조작 및 펀치 홀(Punch Hole) 제로-카피 엔진

## 문제 설명

현대 리눅스 파일시스템(ext4, XFS, Btrfs / `fs/open.c`, `fs/ext4/extents.c`, `include/uapi/linux/falloc.h`)에서 **`fallocate(2)`** 시스템 콜은 단순한 사전 디스크 공간 할당을 넘어, 디스크 I/O 없이 메타데이터 레벨에서 파일의 익스텐트(Extent)를 잘라내고 붙이며 구멍을 뚫는 **초고속 제로-카피(Zero-Copy) 스토리지 조작의 핵심 기제**입니다.

가상 머신 디스크 이미지(QEMU/KVM QCOW2/RAW)의 동적 압축(TRIM/DISCARD), 대규모 분산 데이터베이스(RocksDB/Cassandra)의 WAL(Write-Ahead Log) 재사용, 고화질 비디오 편집기의 중간 프레임 잘라내기 등은 수 기가바이트의 데이터를 실제로 복사하거나 0으로 덮어쓰지 않고, 파일시스템 익스텐트 트리의 포인터만 재배열하는 `fallocate`의 특수 플래그들을 전적으로 활용합니다:

```
    [ Linux Fallocate Extent Operations & State Transitions ]

  Original File (Extents):
  ┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
  │ lblk 0..1 (4KB) │ lblk 2..3 (4KB) │ lblk 4..5 (4KB) │ lblk 6..7 (4KB) │
  │ State: WRITTEN  │ State: WRITTEN  │ State: WRITTEN  │ State: WRITTEN  │
  └─────────────────┴─────────────────┴─────────────────┴─────────────────┘

  1. PUNCH_HOLE (FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE on lblk 2..3):
  ┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
  │ lblk 0..1       │ lblk 2..3       │ lblk 4..5       │ lblk 6..7       │
  │ State: WRITTEN  │ State: HOLE     │ State: WRITTEN  │ State: WRITTEN  │
  └─────────────────┴─────────────────┴─────────────────┴─────────────────┘
                    └─ Physical blocks deallocated! (Sparse file, i_size kept)

  2. COLLAPSE_RANGE (FALLOC_FL_COLLAPSE_RANGE on lblk 2..3):
  ┌─────────────────┬─────────────────┬─────────────────┐
  │ lblk 0..1       │ lblk 2..3       │ lblk 4..5       │  (i_size reduced by 2 blocks,
  │ State: WRITTEN  │ State: WRITTEN  │ State: WRITTEN  │   subsequent extents shifted down,
  └─────────────────┴─────────────────┴─────────────────┘   Zero I/O copy!)
                    (Old lblk 4..5 -> New lblk 2..3)
```

본 과제에서는 Linux 커널 ext4의 B-Tree 형태 익스텐트 구조, 연속된 물리 블록(pblk) 간의 자동 병합(Extent Coalescing), `PREALLOCATE`, `WRITE`, `PUNCH_HOLE`, `ZERO_RANGE`, `COLLAPSE_RANGE`, `INSERT_RANGE`를 지원하는 **Linux Kernel Fallocate & Extent Management Engine**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 익스텐트(Extent) 구조 및 불변식
1. 파일은 0개 이상의 논리 익스텐트 리스트로 표현됩니다:
   - `lblk`: 시작 논리 블록 번호
   - `len`: 블록 수
   - `pblk`: 시작 물리 블록 번호 (단, `state == "HOLE"`인 경우 `None`)
   - `state`: `"WRITTEN"`, `"UNWRITTEN"`, `"HOLE"` 중 하나
2. **자동 병합 (Coalescing)**:
   - 인접한 두 익스텐트 $E_1, E_2$에 대해, $E_1.lblk + E_1.len == E_2.lblk$ 이고 $E_1.state == E_2.state$ 일 때:
     - 상태가 `"HOLE"`이면 무조건 하나로 합쳐집니다 ($len = E_1.len + E_2.len$).
     - 상태가 `"WRITTEN"` 또는 `"UNWRITTEN"`이면, 물리 블록이 연속($E_1.pblk + E_1.len == E_2.pblk$)할 때만 하나로 합쳐집니다.

### 2. 6대 스토리지 조작 연산
1. **`WRITE`**:
   - `[offset, offset + length)` 범위의 블록들을 할당하고 `"WRITTEN"` 상태로 기록합니다.
   - 새 물리 블록은 단조 증가하는 풀(`next_free_pblk`)에서 연속 할당됩니다.
   - 파일 크기를 필요시 갱신합니다.
2. **`PREALLOCATE`**:
   - 디스크 공간을 사전 할당하되 실제 데이터를 쓰지 않으므로 `"UNWRITTEN"` 상태로 생성됩니다.
   - `keep_size == false` 이고 `offset + length > file_size` 이면 `file_size`를 확장합니다.
3. **`PUNCH_HOLE`**:
   - `[offset, offset + length)` 범위에 할당되어 있던 물리 블록을 모두 해제(`total_blocks_freed`)하고, 해당 구간을 `"HOLE"`로 변환합니다.
   - `FALLOC_FL_KEEP_SIZE` 속성에 의해 파일 크기(`file_size`)는 절대 변하지 않습니다.
4. **`ZERO_RANGE`**:
   - `[offset, offset + length)` 범위를 0으로 초기화합니다.
   - 이미 할당된 물리 블록은 해제하지 않고 유지하며 상태만 `"UNWRITTEN"`으로 전환합니다. 구멍이었던 구간은 새 물리 블록을 할당하여 `"UNWRITTEN"`으로 채웁니다.
5. **`COLLAPSE_RANGE`**:
   - `[offset, offset + length)` 구간을 파일에서 완전히 제거합니다. 해당 구간 내 물리 블록은 해제됩니다.
   - 해당 구간 뒤에 있던 모든 익스텐트의 `lblk`를 제거된 블록 수만큼 앞으로 이동(Shift Down)시킵니다.
   - `file_size`가 `length`만큼 즉시 감소합니다.
6. **`INSERT_RANGE`**:
   - `offset` 위치에 `length` 크기의 구멍(`"HOLE"`)을 삽입합니다.
   - 기존 `offset` 이상의 모든 익스텐트의 `lblk`를 삽입된 블록 수만큼 뒤로 이동(Shift Up)시킵니다.
   - `file_size`가 `length`만큼 증가합니다.

---

## 입력 형식

표준 입력(`stdin`)으로 JSON 객체가 주어집니다:

```json
{
  "block_size": 4096,
  "initial_file_size": 0,
  "operations": [
    {"op": "WRITE", "offset": 0, "length": 16384},
    {"op": "PUNCH_HOLE", "offset": 4096, "length": 8192},
    {"op": "COLLAPSE_RANGE", "offset": 4096, "length": 8192}
  ]
}
```

---

## 출력 형식

표준 출력(`stdout`)으로 JSON 객체를 공백 없이 출력합니다:

```json
{
  "file_size": 8192,
  "block_size": 4096,
  "allocated_blocks": 2,
  "hole_blocks": 0,
  "extent_count": 2,
  "extents": [
    {"lblk": 0, "len": 1, "pblk": 1000, "state": "WRITTEN"},
    {"lblk": 1, "len": 1, "pblk": 1003, "state": "WRITTEN"}
  ],
  "stats": {
    "total_blocks_allocated": 4,
    "total_blocks_freed": 2
  },
  "op_log": [
    ...
  ]
}
```
