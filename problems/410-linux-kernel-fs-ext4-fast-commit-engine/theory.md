# 이론 문서 410: Linux 커널 ext4 Fast Commit 아키텍처 및 NVMe 저널링 최적화

## 1. 개요 및 배경: JBD2 블록 저널링의 한계와 쓰기 증폭(Write Amplification)

전통적인 저널링 파일 시스템(ext3, ext4)은 메타데이터의 크래시 일관성(Crash Consistency)을 보장하기 위해 **JBD2 (Journaling Block Device 2, `fs/jbd2/`)** 엔진에 의존해 왔습니다. JBD2의 기본 동작 모드인 `ordered` 모드에서는 사용자의 파일 데이터 블록을 먼저 디스크에 플러시한 후, 해당 연산으로 인해 수정된 메타데이터 블록들을 트랜잭션으로 묶어 저널 영역에 기록합니다.

그러나 전통적인 JBD2 저널링의 근본적인 한계는 **블록 단위 저널링(Block-Granularity Journaling)**에 있습니다:
- ext4 파일 시스템에서 4바이트 크기의 파일 추가(Append)가 발생하여 아이노드의 파일 크기(`i_size`) 필드 하나만 변경되더라도, JBD2는 해당 아이노드가 속한 4096바이트 크기의 아이노드 테이블 블록(Inode Table Block) 전체를 저널에 기록해야 합니다.
- 새로운 물리 블록 할당이 수반되면 블록 할당 비트맵(Block Allocation Bitmap, 4KB), 익스텐트 트리 블록(Extent Tree Block, 4KB), 그리고 트랜잭션 커밋 블록(4KB)까지 추가되어, 단 한 번의 사소한 `fsync()` 호출에 최소 16KB~32KB의 쓰기가 강제됩니다.

이러한 수백 배에 달하는 **쓰기 증폭(Write Amplification)**은 고성능 NVMe SSD 및 영구 메모리(PMEM) 환경에서 심각한 플래시 메모리 수명(TBW) 단축과 더불어, 지연 시간 스파이크(P99 Latency Spike)를 유발하여 엔터프라이즈 데이터베이스(WAL, RocksDB, PostgreSQL)의 처리량을 심각하게 제한했습니다.

---

## 2. Linux 커널 ext4 Fast Commit의 설계 철학

Linux 5.10 커널에 도입된 **ext4 Fast Commit (`fs/ext4/fast_commit.c`, `CONFIG_EXT4_FAST_COMMIT`)**은 "전체 블록을 다시 쓸 필요 없이, 수정된 차이점(Delta)만 기록하면 크래시 후에도 복원할 수 있다"는 근본적 발상의 전환에서 출발했습니다.

```
+--------------------------------------------------------------------------------------------------+
| Traditional JBD2 Full Commit vs ext4 Fast Commit Comparison                                     |
|                                                                                                  |
| [ Traditional JBD2 Full Commit ]                                                                 |
|   +-------------------+-------------------+-------------------+-------------------+              |
|   | Inode Table (4KB) | Block Bitmap (4KB)| Extent Tree (4KB) | Commit Block (4KB)|  ===> 16KB!  |
|   +-------------------+-------------------+-------------------+-------------------+              |
|                                                                                                  |
| [ ext4 Fast Commit ]                                                                             |
|   +---------------------------------------------------------------+                              |
|   | TAG_ADD_RANGE (24B) + TAG_INODE (32B) + TAG_TAIL (16B) = 72B  |                              |
|   | ===> Padded to 1 Hardware Disk Sector (512 Bytes)             |  ===> 512B! (32x Reduction!) |
|   +---------------------------------------------------------------+                              |
+--------------------------------------------------------------------------------------------------+
```

### 2.1 TLV(Tag-Length-Value) 델타 레코드 포맷
Fast Commit은 저널 전용 영역의 서브셋에 다음과 같은 컴팩트한 TLV 레코드를 순차 스트리밍합니다:
1. `EXT4_FC_TAG_ADD_RANGE`: 파일에 새로 할당된 연속 블록 범위 `(ino, lblk, pblk, len)`.
2. `EXT4_FC_TAG_DEL_RANGE`: 파일에서 잘려나간 블록 범위 `(ino, lblk, len)`.
3. `EXT4_FC_TAG_CREAT`: 디렉터리에 새로 추가된 파일 엔트리 `(parent_ino, ino, name)`.
4. `EXT4_FC_TAG_LINK`: 하드 링크 생성 `(parent_ino, ino, name)`.
5. `EXT4_FC_TAG_UNLINK`: 파일 엔트리 삭제 `(parent_ino, ino, name)`.
6. `EXT4_FC_TAG_INODE`: 수정된 아이노드의 기본 메타데이터 `(ino, size, mtime, mode)`.
7. `EXT4_FC_TAG_TAIL`: 해당 패스트 커밋 배치의 무결성을 검증하기 위한 CRC32C 체크섬 및 시퀀스 번호.

---

## 3. 적격성(Eligibility) 상태 머신 및 안전한 풀 커밋 폴백(Fallback)

모든 복잡한 파일 시스템 조작을 단순한 델타 몇 개로 추상화할 수는 없습니다. 복잡한 연산이 발생했을 때 일관성 유지를 위해 Fast Commit은 매우 엄격하고 보수적인 **적격성 상태 머신(Eligibility State Machine)**을 운영합니다:

```
                  +---------------------------+
                  | Transaction Running       |
                  | fc_eligible = TRUE        |
                  +---------------------------+
                                |
             +------------------+------------------+
             |                                     |
    [ Normal Supported Op ]               [ Complex Ineligible Op ]
    - File Create/Unlink                  - CROSS_DIR_RENAME
    - Extent Append/Truncate              - XATTR Modification
    - Inode Size Change                   - FC Area Exhaustion
             |                                     |
             v                                     v
    Append Delta to List                  ext4_fc_mark_ineligible()
             |                            fc_eligible = FALSE
             |                                     |
             v                                     v
    +-----------------+                   +-----------------------+
    | fsync() Called  |                   | fsync() Called        |
    +-----------------+                   +-----------------------+
             |                                     |
             v                                     v
    [ FAST COMMIT ]                       [ JBD2 FULL COMMIT ]
    - Write 512B Sectors                  - Write Full 4KB Blocks
    - Advance fc_seq                      - Reset fc_journal_used to 0
    - fc_eligible remains TRUE            - Reset fc_eligible to TRUE
```

### 3.1 비적격(Ineligible) 판정 사유
1. **디렉터리 간 이동 (`CROSS_DIR_RENAME`)**:
   - 두 개 이상의 서로 다른 디렉터리 아이노드의 잠금(Locking) 순서와 디렉터리 블록 해시 트리(HTree) 구조의 복합적 변경이 수반되므로 델타로 안전하게 분리할 수 없습니다.
2. **확장 속성 변경 (`XATTR_MODIFIED`)**:
   - 보안 xattr, POSIX ACL 등은 별도의 공유 xattr 블록을 참조할 수 있어 단일 파일 델타로 기록하기 어렵습니다.
3. **저널 링버퍼 공간 포화 (`FC_AREA_EXHAUSTED`)**:
   - 고속 NVMe 상에서 패스트 커밋이 반복되어 할당된 패스트 커밋 저널 링버퍼(`fc_journal_capacity_bytes`)가 가득 차면, 더 이상 패스트 커밋을 수용할 수 없으므로 전체 JBD2 풀 커밋을 실행하여 저널 공간을 비우고 초기화합니다.

---

## 4. 크래시 복구(Crash Recovery)와 일관성 보장

시스템 전원이 차단된 후 재부팅 시 ext4 마운트 루틴은 다음과 같은 2단계 복구(Two-Phase Recovery)를 수행합니다:
1. **1단계: JBD2 레거시 저널 리플레이**:
   - 마지막으로 기록된 유효한 JBD2 트랜잭션 커밋 블록까지의 전체 메타데이터 블록을 디스크로 리플레이합니다.
2. **2단계: Fast Commit 델타 리플레이 (`ext4_fc_replay()`)**:
   - JBD2 커밋 이후에 기록된 Fast Commit 레코드들을 스캔하여 CRC32C 체크섬을 검증합니다.
   - 유효한 델타 엔트리들(`ADD_RANGE`, `DEL_RANGE`, `CREAT`, `UNLINK` 등)을 순차적으로 파일 시스템 메모리/디스크 객체에 직접 적용(Apply)합니다.
   - 손상된 레코드가 발견되면 그 지점에서 복구를 안전하게 중단하고, 이전의 일관된 상태를 온전히 보존합니다.
