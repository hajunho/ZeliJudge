# 리눅스 커널 ext4 JBD2 저널링 트랜잭션 수명주기 및 충돌 복구 엔진 (Linux Kernel ext4 JBD2 Journaling Engine)

## 문제 설명

리눅스 시스템에서 가장 널리 사용되는 기본 파일 시스템인 **ext4**는 예기치 못한 정전(Power Outage), 하드웨어 리셋, 혹은 커널 패닉(Kernel Panic) 발생 시 파일 시스템 메타데이터의 불일치(Inconsistency)와 심각한 데이터 손상을 방지하기 위해 **JBD2(Journaling Block Device 2, `fs/jbd2/`)** 서브시스템을 사용합니다.

고전적인 파일 시스템(`ext2`)은 디렉토리 생성이나 파일 추가 시 여러 개의 연관된 메타데이터(아이노드 비트맵, 블록 비트맵, 아이노드 테이블, 디렉토리 엔트리 블록)를 디스크에 직접 씁니다. 만약 블록 비트맵만 기록된 직후 전원이 차단되면 파일 시스템은 영구적인 고아 블록(Orphan Block)과 비트맵 불일치 상태에 빠져, 부팅 시 수 시간에 달하는 전체 디스크 검사(`fsck`)를 강제받게 됩니다.

JBD2는 **선행 기록 로깅(Write-Ahead Logging, WAL)** 원칙에 따라 메타데이터 변경 사항을 디스크의 원래 위치에 직접 기록하기 전에, 전용 원형 링 버퍼(Circular Ring Buffer)인 **저널(Journal)** 영역에 원자적(Atomic) 트랜잭션 단위로 먼저 기록합니다.

```
+-----------------------------------------------------------------------------------+
|                        ext4 JBD2 트랜잭션 저널링 및 체크포인트 파이프라인           |
+-----------------------------------------------------------------------------------+
| 1. Running Transaction (T_RUNNING)                                                |
|    - 프로세스들의 VFS 파일 작업(create, unlink, write)을 핸들(handle)로 수용       |
|    - dirty_metadata (아이노드, 비트맵) 및 dirty_data (사용자 데이터) 버퍼 등록     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v (jbd2_journal_commit_transaction)
+-----------------------------------------------------------------------------------+
| 2. Commit Transaction (T_COMMIT)                                                  |
|    - data=ordered 모드: 파일 데이터 블록을 메인 파일 시스템에 선행 플러시!          |
|    - Descriptor Block: 트랜잭션에 포함된 메타데이터 블록 태그 목록 기록             |
|    - Metadata Data Blocks: 수정된 블록 원본 내용을 저널 링 버퍼에 순차 기록        |
|    - Revoke Block (선택): 재할당된 블록의 과거 메타데이터 재생 방지 블랙리스트 기록 |
|    - Commit Block: TID 및 CRC32 체크섬 기록 -> 이 순간 트랜잭션 영속성(Durability) 확보!
+-----------------------------------------------------------------------------------+
                                         |
                                         v (체크포인트 큐 t_checkpoint_list 진입)
+-----------------------------------------------------------------------------------+
| 3. Checkpoint (T_CHECKPOINT / jbd2_log_do_checkpoint)                             |
|    - 저널에 커밋된 메타데이터 블록을 메인 파일 시스템 최종 위치로 안전하게 복사    |
|    - 복사 완료 후 저널 테일(journal_tail)을 전진시켜 저널 링 버퍼 여유 공간 회수!  |
+-----------------------------------------------------------------------------------+
```

특히 JBD2의 **취소 블록(Revoke Block)** 메커니즘은 매우 치명적인 동시성 버그를 방지합니다. 디렉토리 블록이 삭제된 후 해당 물리 블록이 일반 사용자의 데이터 블록으로 재할당되었을 때, 충돌 복구(Replay) 과정에서 과거 저널에 남아있던 오래된 디렉토리 메타데이터가 새로운 사용자 데이터를 덮어써버리는 참사를 막기 위해, 저널에 `JBD2_REVOKE_BLOCK`을 기록하여 복구 엔진이 해당 블록의 재생을 건너뛰도록 강제합니다.

본 문제는 리눅스 커널 JBD2 트랜잭션 상태 머신(`T_RUNNING` $	o$ `T_LOCKED` $	o$ `T_COMMIT` $	o$ `T_COMMITTED`), `data=ordered` 선행 데이터 플러시, 원형 링 버퍼 공간 고갈 시 동기식 체크포인트, 취소 블록 필터링, 그리고 시스템 충돌 후 3-패스 저널 복구(Replay) 알고리즘을 완벽하게 모사하는 커널급 가상 저널링 엔진을 구현하는 것입니다.

```
       [ JBD2 원형 링 버퍼 관리 및 충돌 복구(Crash Recovery) 흐름도 ]

   Journal Ring Buffer (Slots 1 to N-1, Slot 0=Superblock)
   +------------------------------------------------------------------+
   | Slot 1 | Slot 2 | Slot 3 | Slot 4 | Slot 5 | Slot 6 | Slot 7 ... |
   +------------------------------------------------------------------+
        ^                                  ^
        |                                  |
   journal_tail                       journal_head
   (가장 오래된 미체크포인트 트랜잭션)  (새 트랜잭션 블록이 기록될 위치)

   [ 비정상 전원 차단 (Crash) 발생 시 복구 엔진 동작 ]
   1. Scan Pass: journal_tail부터 journal_head까지 스캔하여 유효한 Commit Block
      (TID 일치 및 CRC32 검증)을 가진 트랜잭션만을 선별 (불완전한 Torn 트랜잭션 폐기).
   2. Revoke Pass: 커밋된 트랜잭션 내의 모든 Revoke Block을 수집하여 블랙리스트 구성.
   3. Replay Pass: 유효한 메타데이터 블록을 메인 파일 시스템에 순차 기록하되,
      Revoke 블랙리스트에 포함된 블록은 안전하게 건너뜀 (Skip).
   4. 저널 포인터 초기화: journal_head = 1, journal_tail = 1로 리셋.
```

---

## 알고리즘 및 상태 전이 명세

### 1. 저널 원형 링 버퍼 및 트랜잭션 상태
- 슬롯 0: 수퍼블록용 예약 공간. 실제 로그 슬롯: $1 \sim 	ext{journal\_blocks} - 1$.
- `journal_head`: 다음 블록이 기록될 슬롯 인덱스.
- `journal_tail`: 아직 체크포인트되지 않은 가장 오래된 트랜잭션의 시작 슬롯 인덱스.
- 여유 슬롯 수:
  - $	ext{head} \ge 	ext{tail}$인 경우: $(	ext{journal\_blocks} - 1) - (	ext{head} - 	ext{tail})$
  - $	ext{head} < 	ext{tail}$인 경우: $	ext{tail} - 	ext{head}$

### 2. 트랜잭션 커밋 알고리즘 (`COMMIT_TX`)
1. **데이터 모드별 선행 처리**:
   - `data=ordered` (기본값): 트랜잭션의 `dirty_data` 블록들을 메인 파일 시스템(`fs_storage`)에 즉시 기록 (메타데이터 저널 커밋 전 데이터 영속성 보장).
   - `data=journal`: `dirty_data` 블록들도 메타데이터로 취급하여 저널 링 버퍼에 함께 기록.
2. **필요 슬롯 수 계산 및 공간 확보**:
   - $	ext{needed} = 1(	ext{Descriptor}) + |	ext{meta\_blocks}| + (1 	ext{ if revokes else } 0) + 1(	ext{Commit})$
   - 여유 슬롯이 부족한 경우: 공간이 확보될 때까지 가장 오래된 트랜잭션을 동기식으로 체크포인트(`checkpoint_oldest`)하여 `journal_tail`을 전진시킵니다.
3. **저널 블록 순차 기록**:
   - **디스크립터 블록 (`JBD2_DESCRIPTOR_BLOCK = 1`)**: 커밋 대상 메타데이터 블록 ID 목록 태그 기록.
   - **데이터 블록 (`DATA`)**: 각 메타데이터 블록의 내용 기록.
   - **취소 블록 (`JBD2_REVOKE_BLOCK = 5`)**: 취소된 블록 ID 목록 기록 (존재 시).
   - **커밋 블록 (`JBD2_COMMIT_BLOCK = 2`)**: `crc32_be(f"{tid}:{len(meta_blocks)}")` 체크섬 기록.
4. 트랜잭션을 `checkpoint_list`에 등록하고 `current_tx = None`으로 전환.

### 3. 충돌 복구 알고리즘 (`RECOVER`)
전원 차단(`CRASH`) 후 마운트 시 실행되는 3-패스 복구 알고리즘:
1. **스캔 패스**:
   - `journal_tail`부터 링 버퍼를 순회하며 디스크립터, 데이터, 취소, 커밋 블록을 파싱합니다.
   - 커밋 블록의 CRC32가 정확하게 일치하는 트랜잭션만을 `valid_transactions` 목록에 추가합니다.
   - 커밋 블록이 없거나 CRC가 손상된 불완전(Torn) 트랜잭션은 즉시 폐기됩니다.
2. **취소 패스**:
   - 유효한 트랜잭션 내에 존재하는 모든 `JBD2_REVOKE_BLOCK`의 블록 번호를 수집하여 `revoked_blocks` 집합에 추가합니다.
3. **재생(Replay) 패스**:
   - 유효한 트랜잭션들의 메타데이터 블록을 메인 파일 시스템(`fs_storage`)에 기록합니다.
   - 단, 블록 ID가 `revoked_blocks`에 포함된 경우 재생을 생략(Skip)합니다.
4. 저널 상태 초기화: `journal_head = 1`, `journal_tail = 1`.

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 전달됩니다:

```json
{
  "config": {
    "journal_blocks": 32,
    "journal_mode": "ordered"
  },
  "initial_fs": {
    "1": "inode_root",
    "10": "old_file_data"
  },
  "operations": [
    {"op": "START_TX"},
    {"op": "DIRTY", "block_id": 10, "data_hex": "new_file_data_v1", "is_metadata": false},
    {"op": "DIRTY", "block_id": 1, "data_hex": "updated_inode_root", "is_metadata": true},
    {"op": "COMMIT_TX"},
    {"op": "CHECKPOINT", "all": true}
  ],
  "dump_blocks": [1, 10]
}
```

---

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다:

```json
{
  "journal_head": 1,
  "journal_tail": 1,
  "stats": {
    "transactions_committed": 1,
    "blocks_journaled": 1,
    "blocks_checkpointed": 1,
    "blocks_revoked": 0,
    "recoveries_performed": 0
  },
  "history": [
    {
      "op": "COMMIT_TX",
      "status": "SUCCESS",
      "tid": 1,
      "slots_written": [1, 2, 3],
      "meta_blocks_count": 1,
      "journal_head": 4,
      "journal_tail": 1
    },
    {
      "op": "CHECKPOINT",
      "checkpointed_tids": [1],
      "new_tail": 4
    }
  ],
  "filesystem_dump": {
    "1": "updated_inode_root",
    "10": "new_file_data_v1"
  },
  "event_log": [
    "JBD2 START_TRANSACTION tid=1",
    "JBD2 DIRTY_DATA tid=1 block=10",
    "JBD2 DIRTY_METADATA tid=1 block=1",
    "JBD2 T_LOCKED tid=1",
    "JBD2 ORDERED_DATA_FLUSH block=10",
    "JBD2 T_COMMITTED tid=1 slots=[1, 2, 3] head=4",
    "JBD2 CHECKPOINT tid=1 new_tail=4"
  ]
}
```
