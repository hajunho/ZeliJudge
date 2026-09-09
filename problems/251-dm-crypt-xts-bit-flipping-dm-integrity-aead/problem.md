# 문제 251: Linux Kernel Storage & Cryptography — Device Mapper dm-crypt (AES-XTS) 비트 플리핑 변조 취약점, dm-integrity AEAD 인증 및 저널 쓰기 스톨

## 1. 개요 (Incident Scenario)

금융권 코어 뱅킹 시스템과 정부/국방 기밀 클라우드 인프라에서는 저장 데이터(Data-at-Rest)의 기밀성을 보장하기 위해 리눅스 커널의 블록 디바이스 암호화 서브시스템인 **`dm-crypt`** (LUKS2, `aes-xts-plain64`)를 표준으로 사용합니다. `dm-crypt`는 파일시스템(Ext4, XFS) 아래의 블록 계층(Block Layer)에서 512B 또는 4096B 섹터 단위로 AES-XTS 알고리즘을 적용하여 데이터를 투명하게 암복호화합니다.

그러나 정기 보안 침투 테스트 및 하드웨어 결함 검증 과정에서 재앙적인 보안 취약점과 성능 문제가 발견되었습니다:
1. **AES-XTS 비트 플리핑 변조에 의한 침묵 데이터 오염 (Silent Data Corruption & Privilege Escalation)**: AES-XTS는 기밀성(Confidentiality)은 제공하지만 **무결성(Integrity)과 진위성(Authenticity)은 전혀 제공하지 못합니다(Unauthenticated Encryption)**. 침입자나 스토리지 하드웨어의 비트 플립(Bit-rot, 플래시 메모리 전하 누설)으로 인해 암호문 섹터의 특정 비트가 반전되었을 때, `dm-crypt`는 복호화 과정에서 아무런 오류도 감지하지 못하고 손상/변조된 평문을 상위 커널로 올려보냈습니다. 이로 인해 `/etc/sudoers`의 `uid=1000` 권한 비트가 조작되거나 데이터베이스 인덱스가 영구 파손되는 사고가 발생했습니다.
2. **리플레이 공격(Replay Attack)을 통한 과거 잔액 복원**: 이전 유효 시점의 암호문 섹터와 인증 태그를 그대로 현재 섹터에 덮어쓰는 리플레이 공격 시, 단조 증가 시퀀스 번호(Monotonic Sequence Counter) 검증이 누락된 경우 오래된 데이터가 유효한 것으로 정상 수락되었습니다.
3. **dm-integrity 저널 고갈로 인한 극심한 쓰기 정체 (Journal Exhaustion Write Stall)**: 무결성을 보장하기 위해 블록 계층에 **`dm-integrity`**(섹터당 HMAC-SHA256 태그 및 메타데이터 저널)를 도입했으나, 대규모 동기식 쓰기(`WRITE_BIO`) 워크로드가 몰리자 온디스크 저널 공간(`journal_capacity_sectors`)이 빠르게 차올랐습니다. 사용량이 워터마크(`journal_watermark_percent`)를 초과하면서 모든 쓰기 I/O가 동기식 플러시(`flush_and_commit`)로 인해 수 초간 멈추는 **저널 쓰기 스톨**이 발생했습니다.

당신은 리눅스 스토리지 및 보안 커널 엔지니어로서, 디바이스 구성, 초기 섹터 상태, 그리고 I/O 및 변조 이벤트 스트림을 바탕으로 `dm-crypt`와 `dm-integrity`의 암복호화, 무결성 태그 검증, 리플레이 감지, 저널 버퍼 상태 머신을 시뮬레이션하고, 근본 원인(Root Cause)과 엔터프라이즈 하드닝 방안을 도출해야 합니다.

---

## 2. 아키텍처 및 상태 머신 (System Architecture & State Machine)

```
 [ Filesystem / Application (Ext4 / Database) ]
                     │ Block I/O (Plaintext bio)
                     ▼
 ┌──────────────────────────────────────────────────────────┐
 │ dm-crypt Layer (crypto API: aes-xts-plain64)             │
 │ - AES-XTS encryption per sector (Sector IV)              │
 │ - VULNERABILITY: No MAC/Integrity! Malleable ciphertext! │
 └──────────────────────────┬───────────────────────────────┘
                            │ Encrypted bio
                            ▼
 ┌──────────────────────────────────────────────────────────┐
 │ dm-integrity Layer (Optional Hardware / Kernel Module)   │
 │ - Per-sector Authentication Tag (HMAC-SHA256 / Poly1305) │
 │ - On-disk Journal (Sections + Watermark Flushing)        │
 │ - Modes: 'journal' (Sync WAL) vs 'bitmap' (Async tracking)│
 └──────────────────────────┬───────────────────────────────┘
                            │ Verified Encrypted Sector + Tag
                            ▼
           [ Physical NVMe / SSD Storage Media ]
```

### (1) 무결성 및 변조 감지 규칙
- `integrity_enabled == false`:
  - 섹터에 비트 플립 또는 변조(`CORRUPT_SECTOR`)가 발생하더라도 `dm-crypt`는 복호화 시 아무런 에러도 반환하지 않음.
  - 이로 인해 상위 계층으로 손상된 데이터가 정상인 양 반환됨 $ightarrow$ **`silent_data_corruptions += 1`**.
- `integrity_enabled == true`:
  - 섹터 읽기(`READ_BIO`) 시 저장된 태그와 현재 암호문에 대해 재계산된 HMAC 태그를 비교.
  - 태그 불일치 또는 섹터 손상 발견 시 즉시 커널 I/O 에러(`-EIO`)를 발생시키고 요청을 차단함 $ightarrow$ **`integrity_checksum_failures += 1`**.

### (2) 리플레이 공격(Replay Attack) 검증 규칙
- 공격자가 이전 커밋 시점의 유효한 암호문, 태그, 시퀀스를 특정 섹터에 덮어씀(`REPLAY_SECTOR`).
- `replay_protection_enabled == true`:
  - 이전 시퀀스(`old_seq`)가 현재 기록된 시퀀스(`curr_seq`)보다 작으면 리플레이 공격으로 간주하여 차단 $ightarrow$ `replay_attacks_detected += 1`, `integrity_checksum_failures += 1`.
- `replay_protection_enabled == false`:
  - 오래된 태그가 오래된 암호문과 수학적으로 일치하므로 검증을 통과하여 비정상 수락됨 $ightarrow$ **`replay_attacks_succeeded += 1`**.

### (3) 저널 용량 및 쓰기 스톨 규칙
- `journal_mode == "journal"`인 경우:
  - 매 쓰기 시 저널 사용량(`journal_used`)이 1씩 증가.
  - 임계치: $	ext{threshold} = rac{	ext{journal\_watermark\_percent}}{100} 	imes 	ext{journal\_capacity\_sectors}$.
  - `journal_used > threshold`에 도달하면 디스크로의 동기식 플러시가 강제되어 **`journal_write_stalls += 1`**이 발생하고 `journal_used = 0`으로 리셋됨.
- `journal_mode == "bitmap"`인 경우:
  - 비동기 비트맵 추적 방식으로 저널 포화에 의한 쓰기 스톨이 발생하지 않음.

---

## 3. 입력 사양 (Input Specification)

표준 입력(`sys.stdin`)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "device_config": {
    "cipher": "aes-xts-plain64",
    "sector_size_bytes": 4096,
    "integrity_enabled": false,
    "integrity_algorithm": "none",
    "journal_mode": "journal",
    "journal_capacity_sectors": 2048,
    "journal_watermark_percent": 80.0,
    "replay_protection_enabled": false
  },
  "initial_sectors": [
    {"sector_num": 500, "plaintext": "sudoers_file_entry_uid_1000", "commit_seq": 5}
  ],
  "events": [
    {"time_sec": 1, "type": "CORRUPT_SECTOR", "sector_num": 500},
    {"time_sec": 2, "type": "READ_BIO", "sector_num": 500}
  ]
}
```

---

## 4. 출력 사양 (Output Specification)

표준 출력(`sys.stdout`)으로 다음 필드를 포함하는 JSON 객체를 출력합니다:

```json
{
  "final_state": {
    "sectors_count": 1,
    "journal_used_sectors": 0,
    "current_commit_seq": 1
  },
  "metrics": {
    "successful_reads": 0,
    "successful_writes": 0,
    "integrity_checksum_failures": 0,
    "silent_data_corruptions": 1,
    "replay_attacks_detected": 0,
    "replay_attacks_succeeded": 0,
    "journal_write_stalls": 0
  },
  "root_cause": "SILENT_DATA_CORRUPTION_UNAUTHENTICATED_AES_XTS",
  "recommendations": [
    "ENABLE_DM_INTEGRITY_WITH_HMAC_OR_AEAD",
    "ENABLE_REPLAY_PROTECTION_SEQUENCE_COUNTER"
  ]
}
```

### 진단 규칙 (Root Cause Hierarchy)
1. `silent_data_corruptions > 0` $ightarrow$ `"SILENT_DATA_CORRUPTION_UNAUTHENTICATED_AES_XTS"`
2. `replay_attacks_succeeded > 0` $ightarrow$ `"REPLAY_ATTACK_ACCEPTED_DUE_TO_MISSING_SEQUENCE_CHECK"`
3. `integrity_checksum_failures > 0` $ightarrow$ `"INTEGRITY_TAMPER_DETECTED_AND_BLOCKED"`
4. `journal_write_stalls >= 2` $ightarrow$ `"DM_INTEGRITY_JOURNAL_EXHAUSTION_WRITE_STALL"`
5. 기타 정상 상태 $ightarrow$ `"STABLE_AUTHENTICATED_ENCRYPTED_STORAGE"`

### 권고사항 도출 규칙
- `not integrity_enabled`: `"ENABLE_DM_INTEGRITY_WITH_HMAC_OR_AEAD"`
- `replay_attacks_succeeded > 0` 또는 `not replay_protection_enabled`: `"ENABLE_REPLAY_PROTECTION_SEQUENCE_COUNTER"`
- `journal_write_stalls > 0` 또는 (`integrity_enabled and journal_mode == "journal" and journal_capacity <= 2048`): `"INCREASE_JOURNAL_SIZE_OR_SWITCH_TO_BITMAP"`
- 해당 사항이 없으면: `["MAINTAIN_CURRENT_AUTHENTICATED_CRYPTO_SETTINGS"]`
