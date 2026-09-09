# 리눅스 ext4 파일 시스템 저널링: JBD2 저널 모드(data=ordered vs journal vs writeback)와 정전 복구 무결성

## 문제 배경 및 개요
글로벌 핀테크 결제 원장 및 암호화폐 거래소의 핵심 트랜잭션 데이터베이스(PostgreSQL, SQLite, RocksDB)는 초당 수만 건의 잔액 변경 및 거래 체결 내역을 디스크에 영속화합니다.
데이터베이스 파일에 데이터를 쓴다는 것은 두 가지 물리적 변경을 의미합니다:
1. **파일 데이터 블록 (File Data Blocks)**: 실제 사용자가 기록한 트랜잭션 바이트 데이터.
2. **메타데이터 블록 (Metadata Blocks)**: 파일 크기(i_size), 블록 포인터/익스텐트 트리(Extent Tree), 수정 시각(mtime), 블록 할당 비트맵(Allocation Bitmap)을 담은 아이노드(Inode) 정보.

스토리지 I/O 성능을 극대화하려던 시스템 엔지니어가 리눅스 기본 ext4 마운트 옵션의 작동 원리를 간과하고 디스크 쓰기 속도만 보고 `/etc/fstab`에 `data=writeback,nobarrier` 옵션을 적용했습니다.
얼마 후 데이터센터 순간 정전(Hard Power Cut Crash)이 발생하여 서버가 불시에 강제 종료되었을 때, 두 가지 충격적인 스토리지 참사가 발생했습니다:

1. **`data=writeback` 모드의 쓰레기 데이터 노출 및 개인정보 유출 참사 (`EXT4_WRITEBACK_STALE_DATA_LEAK`)**:
   - `data=writeback` 모드는 메타데이터만 저널에 기록하고, 실제 데이터 블록이 디스크에 기록되는 순서는 전혀 보장하지 않습니다.
   - 메타데이터 트랜잭션(파일 크기 확장)은 디스크에 커밋되었으나, 실제 데이터 블록은 여전히 휘발성 RAM 캐시에 머물던 찰나 정전이 발생했습니다.
   - 재부팅 후 ext4 저널 리플레이(Journal Replay)가 완료되자 파일 크기는 확장되었지만, 그 확장된 블록에는 **방금 쓴 데이터 대신 이전에 삭제되었던 다른 파일의 조각(타 유저 세션 토큰, 암호화 키)과 널 바이트(0x00) 쓰레기 데이터가 그대로 노출**되어 데이터베이스 체크섬이 깨지고 영구 손상되었습니다.
2. **`data=journal` 모드의 2배 쓰기 증폭 및 디스크 질식 (`EXT4_DATA_JOURNAL_WRITE_AMPLIFICATION_BOTTLENECK`)**:
   - 사태를 수습하겠다고 가장 안전해 보이는 `data=journal` 모드로 마운트했더니, 메타데이터뿐만 아니라 모든 사용자 데이터 블록까지 저널 링버퍼에 1차 기록한 뒤 실제 파일 블록에 2차 기록(2x Write Amplification)하느라 SSD 수명이 절반으로 깎이고 디스크 IOPS가 고갈되어 초당 트랜잭션(TPS)이 1/3로 곤두박질쳤습니다.

리눅스 커널은 이 딜레마를 극복하기 위해 **JBD2(Journaling Block Device 2)의 기본 모드인 `data=ordered`와 하드웨어 플러시 배리어(`barrier=1`)**를 제공합니다:
- **데이터 선(先)플러시 불변식 (Ordered Invariant)**: 트랜잭션에 속한 모든 데이터 블록을 실제 디스크에 먼저 기록 완료(`blkdev_issue_flush`)한 뒤에만, 해당 트랜잭션의 커밋 블록(Commit Record)을 저널에 기록합니다.
- 데이터는 단 1번만 쓰이므로 쓰기 증폭률은 1.0x를 유지하면서도, 정전 크래시 발생 시 커밋되지 않은 메타데이터는 롤백되고 커밋된 메타데이터의 데이터 블록은 이미 디스크에 안전하게 적재되어 있음을 수학적으로 보장합니다 (`OPTIMAL_EXT4_ORDERED_JOURNAL_CONSISTENCY`).

당신은 ext4 JBD2 트랜잭션 시뮬레이터를 구현하여, 3대 저널 모드의 동작과 정전 크래시 복구 무결성을 정밀 시뮬레이션하고 진단해야 합니다.

---

## 시스템 동작 규칙 및 상태 머신

### 1. ext4 JBD2 3대 저널 모드 동작
- **`data=ordered` (리눅스 커널 기본값)**:
  - `write`: 변경된 데이터 블록을 메모리 트랜잭션에 누적하고 아이노드 메타데이터(크기 등)를 갱신합니다.
  - `commit_tick` 또는 `fsync`:
    1. 데이터 블록들을 실제 디스크 파일 위치에 **먼저 플러시**합니다 (`disk_data_bytes_written`).
    2. 데이터 플러시 완료 후 메타데이터 및 커밋 블록을 저널에 기록합니다 (`journal_metadata_bytes_written`).
    3. 저널에 커밋된 메타데이터 크기(`journaled_metadata`)를 갱신합니다.
  - 데이터는 저널에 쓰이지 않으므로 `journal_data_bytes_written = 0`입니다.
- **`data=writeback` (최대 성능, 무결성 위험)**:
  - 메타데이터만 저널에 기록하고, 데이터 블록의 플러시 순서는 강제하지 않습니다.
  - `commit_tick` 시 `barrier == False`이면 메타데이터만 저널에 커밋되고 데이터 블록은 디스크에 플러시되지 않고 남습니다.
  - `fsync`가 호출되었을 때만 데이터 블록이 강제로 디스크에 기록됩니다.
- **`data=journal` (최대 안전, 극심한 오버헤드)**:
  - 사용자 데이터 블록과 메타데이터 블록 **모두를 저널에 1차 기록**합니다 (`journal_data_bytes_written += data_len`, `journal_metadata_bytes_written`).
  - 저널 커밋 후, 실제 파일 블록에 **2차 기록**합니다 (`disk_data_bytes_written += data_len`).
  - 따라서 데이터 쓰기 증폭률은 정확히 `2.0x`가 됩니다.

### 2. 정전 크래시(`power_cut_crash`) 및 저널 리플레이 복구 규칙
- 정전 발생 시 진행 중이던 미커밋 트랜잭션은 폐기됩니다 (`aborted_transactions += 1`).
- **저널 리플레이 (Journal Replay)**:
  - 디스크에 유효하게 커밋된 최신 저널 메타데이터(`journaled_metadata`)를 읽어 파일의 아이노드 크기를 복구합니다.
  - 만약 저널 메타데이터 상의 크기(`j_sz`)가 디스크에 실제로 기록된 바이트 수(`cur_disk_len`)보다 크다면:
    - 데이터 블록이 디스크에 쓰이기 전에 메타데이터만 커밋된 상태에서 정전이 발생한 것입니다!
    - 실제 디스크 파일의 누락된 구간은 널 바이트(`\x00`) 또는 이전 디스크 쓰레기 블록으로 채워집니다.
    - 누락된 4KB 블록 수만큼 `stale_data_leaks_detected += (j_sz - cur_disk_len + 4095) // 4096`이 집계됩니다.

---

## 판정 기준 (System Status)

1. `EXT4_WRITEBACK_STALE_DATA_LEAK`:
   - `stale_data_leaks_detected > 0`: `data=writeback` 모드 등에서 데이터 플러시 전 메타데이터만 저널에 커밋된 상태로 크래시되어 쓰레기 데이터/널 블록 누출이 발생한 상태.
2. `EXT4_DATA_JOURNAL_WRITE_AMPLIFICATION_BOTTLENECK`:
   - `journal_mode == "data=journal"`이고 데이터 쓰기 증폭률 `data_write_amplification_ratio >= 1.90`으로 디스크 IOPS 낭비 및 SSD 수명 저하 병목이 발생한 상태.
3. `OPTIMAL_EXT4_ORDERED_JOURNAL_CONSISTENCY`:
   - `data=ordered` 모드에서 데이터 선플러시 불변식이 보장되어 쓰기 증폭 1.0x 및 정전 크래시 시에도 쓰레기 누출 0건(100% 무결점 크래시 일관성)을 완수한 상태.

---

## 입력 형식
표준 입력(`sys.stdin`)으로 다음 필드를 갖는 단일 JSON 객체가 주어집니다:
- `mount_config`: ext4 파일 시스템 마운트 설정
  - `journal_mode`: `"data=ordered"`, `"data=writeback"`, 또는 `"data=journal"`
  - `barrier`: 하드웨어 캐시 플러시 배리어 활성화 여부 (boolean, 기본 true)
- `files`: 초기 파일 상태 맵 (파일명 -> `{"content": string}`)
- `operations`: 시간순 파일 연산 및 시스템 이벤트 목록
  - `op`: `"write"`, `"fsync"`, `"commit_tick"`, 또는 `"power_cut_crash"`
  - `file`: 대상 파일명
  - `offset`: 쓰기 시작 바이트 오프셋 (정수)
  - `data`: 기록할 문자열 데이터
  - `timestamp_ms`: 연산 타임스탬프 (밀리초, 실수)

---

## 출력 형식
표준 출력(`sys.stdout`)으로 다음 필드를 갖는 단일 JSON 객체를 인덴트 2칸(`indent=2`)으로 출력해야 합니다:
- `status`: 판정 결과 문자열 (`EXT4_WRITEBACK_STALE_DATA_LEAK` | `EXT4_DATA_JOURNAL_WRITE_AMPLIFICATION_BOTTLENECK` | `OPTIMAL_EXT4_ORDERED_JOURNAL_CONSISTENCY`)
- `metrics`:
  - `total_user_bytes_written`: 유저가 요청한 순수 쓰기 바이트 합
  - `disk_data_bytes_written`: 실제 파일 데이터 블록으로 디스크에 쓰인 바이트 수
  - `journal_data_bytes_written`: 저널 링버퍼에 기록된 데이터 바이트 수
  - `journal_metadata_bytes_written`: 저널 링버퍼에 기록된 메타데이터 및 커밋 블록 바이트 수
  - `data_write_amplification_ratio`: 데이터 쓰기 증폭률 (`(disk_data_bytes + journal_data_bytes) / total_user_bytes`, 소수점 2자리 반올림)
  - `unflushed_dirty_data_bytes`: 디스크에 플러시되지 않고 남은 더티 데이터 바이트 수
  - `committed_transactions`: 정상 커밋 완료된 트랜잭션 수
  - `aborted_transactions`: 크래시로 롤백/폐기된 미커밋 트랜잭션 수
  - `stale_data_leaks_detected`: 복구 후 노출된 쓰레기/널 데이터 블록 수 (4KB 단위)
  - `recovered_files_count`: 크래시 복구 후 유효한 파일 개수
- `root_cause_analysis`: 한국어 원인 분석 및 아키텍처 진단 메시지
