# 문제 410: Linux 커널 ext4 Fast Commit(fast_commit.c) 델타 저널링 및 JBD2 풀 커밋 폴백 엔진

## 문제 설명

리눅스 커널의 기본 파일 시스템인 ext4는 수십 년간 **JBD2(Journaling Block Device 2, `fs/jbd2/`)** 계층을 통해 시스템 비정상 종료(Crash/Power Loss) 시에도 메타데이터의 일관성을 완벽히 보장해 왔습니다.

그러나 전통적인 JBD2 저널링은 **전체 블록 저널링(Full Block Journaling)** 방식을 사용합니다. 예를 들어 데이터베이스가 트랜잭션 로그(WAL) 파일에 단 100바이트의 데이터를 추가(`append`)하고 `fsync()` 시스템 콜을 호출하더라도, JBD2는 다음과 같은 전체 4KB 파일 시스템 블록들을 통째로 저널 영역에 기록해야 합니다:
1. 아이노드 테이블 블록 (4096 바이트)
2. 블록 할당 비트맵 블록 (4096 바이트)
3. 익스텐트 트리 블록 (4096 바이트)
4. 저널 디스크립터 및 커밋 블록 (4096 바이트)

이로 인해 단 몇 십 바이트의 파일 메타데이터 변경에도 최소 16KB~32KB에 달하는 엄청난 쓰기 증폭(Write Amplification)과 I/O 지연(Latency Spike)이 발생합니다. 초당 수백만 IOPS와 마이크로초(µs) 대역의 초저지연을 자랑하는 현대의 고속 NVMe SSD 및 영구 메모리(PMEM) 환경에서는 이러한 JBD2 블록 저널링 오버헤드가 스토리지 전체의 심각한 성능 병목이 되었습니다.

이를 극복하기 위해 구글(Google)의 Harshad Shirwadkar에 의해 개발되어 리눅스 커널 5.10에 공식 도입된 기능이 바로 **ext4 Fast Commit (`fs/ext4/fast_commit.c`, `CONFIG_EXT4_FAST_COMMIT`)**입니다.

### Fast Commit의 핵심 아키텍처

1. **인메모리 델타 트래킹 (In-Memory Delta Tracking)**:
   - 파일 생성, 추가, 절단, 삭제 등의 파일 시스템 조작이 일어날 때, 전체 블록을 더티(Dirty)로 마킹하는 대신 변경된 내용만을 나타내는 초경량 델타(Delta) 엔트리를 인메모리 리스트에 수집합니다:
     - `EXT4_FC_TAG_ADD_RANGE`: 새로 할당된 익스텐트 범위(`ino`, `lblk`, `pblk`, `len`) - 24바이트.
     - `EXT4_FC_TAG_DEL_RANGE`: 펀치 홀/절단된 익스텐트 범위(`ino`, `lblk`, `len`) - 20바이트.
     - `EXT4_FC_TAG_CREAT`: 새로 생성된 파일 엔트리(`parent_ino`, `ino`, `name`) - 16바이트 + 이름 길이.
     - `EXT4_FC_TAG_UNLINK`: 삭제된 파일 엔트리(`parent_ino`, `ino`, `name`) - 16바이트 + 이름 길이.
     - `EXT4_FC_TAG_INODE`: 변경된 아이노드 메타데이터(`ino`, `size`) - 32바이트.
     - `EXT4_FC_TAG_TAIL`: 패스트 커밋 시퀀스 번호 및 체크섬 - 16바이트.

2. **초저지연 512B 섹터 정렬 패스트 커밋 (`FAST_COMMIT`)**:
   - 애플리케이션이 `fsync()`를 호출하면, 누적된 델타 엔트리들과 TAIL 태그의 합산 크기를 계산하고 하드웨어 디스크 섹터 크기(`fast_commit_sector_size`, 512바이트) 단위로 올림 정렬하여 저널의 전용 패스트 커밋 링 버퍼에 단 한 번의 순차 I/O로 기록합니다.
   - 전통적인 JBD2의 16KB~32KB 블록 쓰기 대비 1섹터(512바이트)만의 기록으로 커밋이 완료되어, `fsync()` 지연 시간을 최대 200%~300% 이상 단축시킵니다.

3. **적격성 판정(Eligibility) 및 JBD2 풀 커밋 폴백 (Fallback)**:
   - 모든 메타데이터 변경이 패스트 커밋 델타로 표현될 수 있는 것은 아닙니다. 다음과 같은 복잡한 연산이 발생하면 커널은 해당 트랜잭션을 즉시 **비적격(Ineligible)**으로 선언(`ext4_fc_mark_ineligible()`)합니다:
     - **`CROSS_DIR_RENAME`**: 서로 다른 상위 디렉터리 간의 파일 이름 변경.
     - **`XATTR_MODIFIED`**: 보안 레이블이나 사용자 확장 속성(xattr) 변경.
     - **`FC_AREA_EXHAUSTED`**: 패스트 커밋 전용 저널 영역(`fc_journal_capacity_bytes`)의 잔여 공간이 부족한 경우.
   - 비적격 상태에서 `fsync()`가 호출되면, 파일 시스템은 자동으로 전통적인 **JBD2 풀 커밋(Full Commit)**을 발동합니다.
   - 풀 커밋은 `jbd2_full_commit_block_overhead`개의 전체 블록(예: 16KB)을 메인 저널에 기록하며, 완료 후 패스트 커밋 저널 사용 공간을 0으로 리셋하고 적격성 상태를 다시 `True`로 회복시켜 다음 트랜잭션부터 패스트 커밋이 재개되도록 만듭니다.

여러분은 리눅스 커널 ext4 Fast Commit의 인메모리 델타 수집기, 512B 섹터 정렬 커밋 라이터, 적격성 상태 머신 및 JBD2 풀 커밋 자동 폴백 엔진을 충실히 모델링하는 시뮬레이터를 구현해야 합니다.

---

## 시스템 아키텍처 다이어그램

```
+==================================================================================================+
|                         Linux Kernel ext4 Fast Commit Architecture                               |
+==================================================================================================+

   [ Application Process (e.g. MySQL / RocksDB WAL append) ]
                     |
                     | VFS File Operations & fsync()
                     v
+--------------------------------------------------------------------------------------------------+
| ext4 Filesystem Core (fs/ext4/fast_commit.c, fs/ext4/ext4.h)                                     |
|                                                                                                  |
|  [ In-Memory Fast Commit Delta Tracker ]                                                         |
|   - CREATE_FILE      ---> Record EXT4_FC_TAG_CREAT (parent_ino, ino, name)                       |
|   - APPEND_DATA      ---> Record EXT4_FC_TAG_ADD_RANGE (lblk, pblk, len) + TAG_INODE (size)      |
|   - TRUNCATE_DATA    ---> Record EXT4_FC_TAG_DEL_RANGE (lblk, len) + TAG_INODE (size)            |
|   - UNLINK_FILE      ---> Record EXT4_FC_TAG_UNLINK (parent_ino, ino, name)                       |
|                                                                                                  |
|  [ Eligibility Monitor ]                                                                         |
|   - CROSS_DIR_RENAME ---> ext4_fc_mark_ineligible("CROSS_DIR_RENAME")                            |
|   - SET_XATTR        ---> ext4_fc_mark_ineligible("XATTR_MODIFIED")                              |
|   - fc_journal_full  ---> ext4_fc_mark_ineligible("FC_AREA_EXHAUSTED")                           |
|                                                                                                  |
|  [ fsync() Commit Dispatcher ]                                                                   |
|   - Check: fc_eligible == TRUE AND fc_space_available == TRUE ?                                  |
|                                                                                                  |
|     * YES: ===> [ FAST COMMIT PATH ]                                                             |
|                 - Aggregate deltas + EXT4_FC_TAG_TAIL (16B)                                      |
|                 - Align up to 512-byte sectors (Zero Block Journaling!)                          |
|                 - Write to Dedicated Fast Commit Ring Buffer                                     |
|                 - Advance fc_seq, clear in-memory deltas, latency is MINIMAL!                    |
|                                                                                                  |
|     * NO:  ===> [ JBD2 FULL COMMIT FALLBACK PATH ]                                               |
|                 - Flush entire 4KB metadata blocks (Inode, Bitmap, Extent Tree, Commit Block)    |
|                 - Write full blocks (e.g. 16KB ~ 32KB) to Main Journal Area                      |
|                 - Reset Fast Commit Journal Used Space to 0                                      |
|                 - Reset fc_eligible to TRUE for the next transaction                             |
+==================================================================================================+
```

---

## 상세 요구사항 및 동작 규칙

### 1. 시스템 설정 파라미터 (`config`)
- `fc_journal_capacity_bytes`: 패스트 커밋 전용 저널 영역의 최대 바이트 용량 (기본값: `65536`)
- `block_size`: 파일 시스템 기본 블록 크기 (기본값: `4096`)
- `jbd2_full_commit_block_overhead`: JBD2 풀 커밋 시 기록되는 메타데이터 블록 수 (기본값: `4`)
- `fast_commit_sector_size`: 패스트 커밋 기록 정렬 섹터 단위 (기본값: `512`)

### 2. 이벤트 트레이스 연산 (`trace`)

1. **`CREATE_FILE`**:
   - `time`, `parent_ino`, `ino`, `name`, `is_dir` (선택적, 기본값 `False`).
   - 새 아이노드 객체를 생성하여 등록합니다.
   - `EXT4_FC_TAG_CREAT` 델타(`size_bytes = 16 + len(name)`)를 기록합니다.

2. **`APPEND_DATA`**:
   - `time`, `ino`, `lblk`, `pblk`, `len`.
   - 지정된 아이노드의 익스텐트 목록에 `{"lblk": lblk, "pblk": pblk, "len": len}`을 추가하고, 파일 크기를 `max(size, (lblk + len) * block_size)`로 갱신합니다.
   - `EXT4_FC_TAG_ADD_RANGE` 델타(24바이트) 및 `EXT4_FC_TAG_INODE` 델타(32바이트)를 순차적으로 기록합니다.

3. **`TRUNCATE_DATA`**:
   - `time`, `ino`, `lblk`, `len`.
   - `[lblk, lblk + len)` 범위와 겹치는 기존 익스텐트를 제거/축소하고, 크기를 `lblk * block_size`로 갱신합니다.
   - `EXT4_FC_TAG_DEL_RANGE` 델타(20바이트) 및 `EXT4_FC_TAG_INODE` 델타(32바이트)를 기록합니다.

4. **`UNLINK_FILE`**:
   - `time`, `parent_ino`, `ino`, `name`.
   - 아이노드를 삭제하고 `EXT4_FC_TAG_UNLINK` 델타(`size_bytes = 16 + len(name)`)를 기록합니다.

5. **`CROSS_DIR_RENAME`**:
   - `time`, `old_parent_ino`, `new_parent_ino`, `ino`, `old_name`, `new_name`.
   - 파일의 상위 디렉터리와 이름을 갱신합니다.
   - 패스트 커밋 미지원 연산이므로 `fc_eligible = False`로 설정하고 사유 `CROSS_DIR_RENAME`을 기록합니다.

6. **`SET_XATTR`**:
   - `time`, `ino`, `name`, `value`.
   - 확장 속성 변경은 패스트 커밋 미지원 연산이므로 `fc_eligible = False`로 설정하고 사유 `XATTR_MODIFIED`를 기록합니다.

7. **`FSYNC`**:
   - `time`, `ino`.
   - 현재 누적된 델타들의 총 바이트 수 + TAIL 태그(16바이트)를 합산합니다.
   - 합산 크기를 `fast_commit_sector_size` (512바이트) 단위로 올림하여 `fc_write_bytes`를 계산합니다 (델타가 0이어도 최소 512바이트).
   - **패스트 커밋 적격성 검사**:
     - 조건: `fc_eligible == True` AND `fc_journal_used_bytes + fc_write_bytes <= fc_journal_capacity_bytes`.
     - **조건 만족 시 (`FAST_COMMIT`)**:
       - `fc_commit_count` 1 증가, `fc_seq` 1 증가.
       - `fc_journal_used_bytes += fc_write_bytes`
       - `total_journal_written_bytes += fc_write_bytes`
       - 델타 리스트를 비우고 커밋 기록을 저장합니다.
     - **조건 불만족 시 (`JBD2_FULL_COMMIT`)**:
       - 사유 판정: `not fc_eligible`이면 첫 번째 비적격 사유, 공간 부족이면 `FC_AREA_EXHAUSTED`.
       - 기록 바이트 수: `jbd2_full_commit_block_overhead * block_size` (예: 16384바이트).
       - `jbd2_full_commit_count` 1 증가, `total_journal_written_bytes`에 가산.
       - 패스트 커밋 저널 사용량을 0으로 초기화(`fc_journal_used_bytes = 0`).
       - `fc_eligible = True`로 리셋하고 사유 리스트와 델타 리스트를 클리어합니다.

---

## 입출력 형식 (JSON)

### 입력 형식 (Standard Input)

```json
{
  "config": {
    "fc_journal_capacity_bytes": 65536,
    "block_size": 4096,
    "jbd2_full_commit_block_overhead": 4,
    "fast_commit_sector_size": 512
  },
  "trace": [
    {
      "time": 0,
      "type": "CREATE_FILE",
      "parent_ino": 2,
      "ino": 100,
      "name": "app.log"
    },
    {
      "time": 1,
      "type": "APPEND_DATA",
      "ino": 100,
      "lblk": 0,
      "pblk": 5000,
      "len": 2
    },
    {
      "time": 2,
      "type": "FSYNC",
      "ino": 100
    }
  ]
}
```

### 출력 형식 (Standard Output)

공백 없이 압축된 단일 라인 JSON 문자열(`separators=(',', ':')`, `ensure_ascii=False`)로 출력해야 합니다:

```json
{
  "summary": {
    "fc_commit_count": 1,
    "jbd2_full_commit_count": 0,
    "total_journal_written_bytes": 512,
    "fc_journal_used_bytes": 512,
    "fc_seq": 1,
    "current_fc_eligible": true
  },
  "inodes": {
    "2": {
      "ino": 2,
      "parent_ino": 2,
      "name": "/",
      "size": 4096,
      "extents": [],
      "is_dir": true
    },
    "100": {
      "ino": 100,
      "parent_ino": 2,
      "name": "app.log",
      "size": 8192,
      "extents": [
        {
          "lblk": 0,
          "pblk": 5000,
          "len": 2
        }
      ],
      "is_dir": false
    }
  },
  "commit_history": [
    {
      "time": 2,
      "commit_type": "FAST_COMMIT",
      "fc_seq": 1,
      "written_bytes": 512,
      "journal_used_bytes": 512,
      "deltas_committed": 3
    }
  ],
  "event_logs": [ ... ]
}
```
