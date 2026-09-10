# Linux 커널 스토리지 및 보안: fsverity 파일 레벨 머클 트리 인증 및 페이지 캐시 검증 엔진

## 문제 설명

현대 엔터프라이즈 리눅스 및 모바일 OS(Android 11+, ChromeOS, `systemd-sysext`, 보안 컨테이너)에서는 신뢰할 수 없는 로컬 스토리지에 저장된 시스템 라이브러리(`.so`), 실행 파일(ELF), 안드로이드 패키지(APK/APEX), 그리고 거대 AI 모델 가중치(`weights.bin`)가 루트킷(Rootkit)이나 오프라인 물리 공격, 디스크 비트 부패(Bit-rot)에 의해 변조되는 것을 원천 차단해야 합니다.

전통적인 무결성 검증 방식은 극단적인 딜레마를 안고 있었습니다:
1. **사용자 공간 해시 검증 (User-space Hash)**: 파일을 실행하기 전 수 기가바이트(GB)에 달하는 파일 전체를 메모리로 읽어 해시를 계산해야 하므로 부팅 및 앱 실행 지연이 수 초~수십 초씩 발생하며, 한 번 검증된 후 메모리에 상주하는 동안 디스크 블록이 변조되어도 실시간 탐지가 불가능합니다.
2. **블록 디바이스 레벨 무결성 (`dm-verity`)**: 전체 파티션을 통째로 읽기 전용으로 잠그기 때문에, 개별 파일(예: 앱 업데이트나 신규 모델 추가) 단위의 독립적인 배포와 버전 관리가 불가능합니다.

리눅스 커널 5.4부터 Eric Biggers 등에 의해 도입된 **`fsverity` 서브시스템**(`fs/verity/`)은 파일 시스템(ext4, f2fs, btrfs)의 VFS 계층에 통합되어, **파일 개별 단위로 동작하면서도 전체 파일을 미리 읽지 않고 오직 프로세스가 실제로 `read()`하거나 페이지 폴트(Page Fault)를 일으키는 4KB 페이지만 온디맨드(On-Demand)로 실시간 검증하는 머클 트리(Merkle Tree) 엔진**을 제공합니다:

```
+-----------------------------------------------------------------------------------------+
|                  Linux Kernel fsverity File Integrity Architecture                      |
+-----------------------------------------------------------------------------------------+
       [ Inode Metadata: fsverity_descriptor ]  <--- Root Hash (Signed by X.509 PKCS#7)
                           |
                           v
        +-------------------------------------+
        | Level 2: Top Hash Block             |
        +-------------------------------------+
          /                 |                        v                  v                v
  +--------------+   +--------------+   +--------------+
  | Level 1 Hash |   | Level 1 Hash |   | Level 1 Hash | (128 hashes per 4KB Block)
  +--------------+   +--------------+   +--------------+
         |                  |                  |
         v                  v                  v
  +--------------+   +--------------+   +--------------+
  | Level 0 Hash |   | Level 0 Hash |   | Level 0 Hash | (SHA-256 over 4KB Data Page)
  +--------------+   +--------------+   +--------------+
         |                  |                  |
         v                  v                  v
  [ 4KB Data Page 0] [ 4KB Data Page 1] [ 4KB Data Page 2] ... [ 4KB Data Page N-1 ]
         |
         v
   [ read() / mmap Page Fault ]
    * Step 1: Read 4KB into Page Cache
    * Step 2: PageChecked bit already set? ---> YES: Skip hashing! (0 CPU penalty)
    * Step 3: NO: Compute SHA-256(Salt + Data)
    * Step 4: Verify against Merkle parent hash in Level 0
    * Step 5: Matches? ---> YES: Mark PageChecked, Return to user!
                         -> NO : Abort with -EIO! Emit kernel security audit event!
```

### 핵심 커널 동작 메커니즘:
1. **무결성 활성화 (`ENABLE_VERITY` / `FS_IOC_ENABLE_VERITY`)**:
   - 파일 크기를 $4096\text{ 바이트}$ 블록 단위로 분할하여 최하단 리프 해시(Level 0)를 생성합니다.
   - 4KB 해시 블록 하나당 $4096 / 32 = 128\text{개}$(SHA-256 기준)의 자식 해시를 묶어 상위 레벨을 구축하며, 최종적으로 $1\text{개}$의 **루트 해시(Root Hash)**에 도달합니다.
   - 머클 트리의 메타데이터 용량 오버헤드는 원본 파일 크기의 약 $1/127 \approx 0.78\%$에 불과합니다.
   - 서명(`signature`)이 제공된 경우, 커널 신뢰 키링(`.fs-verity` 키링)에 등록된 공인 키인지 검증하며, 미등록 키이거나 위조된 서명인 경우 `-EKEYREJECTED`로 활성화를 거부합니다.
2. **온디맨드 읽기 검증 (`READ`)**:
   - 프로세스가 파일의 특정 바이트 범위(`offset`, `length`)를 읽을 때, 해당 범위가 걸쳐 있는 4KB 페이지들만 조회합니다.
   - 이미 검증되어 페이지 캐시(`verified_pages`)에 `PageChecked` 비트가 설정된 페이지는 추가적인 해시 연산 없이 즉시 반환됩니다 ($0\text{ CPU}$ 페널티).
   - 최초 접근된 페이지는 실시간으로 해시를 계산하여 머클 트리의 기대값과 대조합니다.
3. **위변조 차단 (`INJECT_TAMPER` $\rightarrow$ `-EIO`)**:
   - 디스크 섹터 결함이나 악의적인 오프라인 파일 변조가 발생한 경우, 해시 불일치를 즉각 감지하고 I/O를 중단하여 호출자에게 `-EIO` 에러를 반환합니다.
   - 악성 코드가 단 1바이트라도 유저 공간이나 CPU 레지스터로 넘어가는 것을 완벽하게 봉쇄합니다.

주어진 파일 시스템 설정과 일련의 fsverity 활성화, 오프라인 변조, 그리고 읽기 I/O 연산 시퀀스를 커널 명세에 따라 시뮬레이션하고, 상세 연산 이력(`history`)과 최종 파일 보호 및 페이지 캐시 효율 요약 통계(`summary`)를 산출하는 엔진을 구현하십시오.

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "block_size": 4096,
    "hash_algorithm": "sha256",
    "trusted_keyring_ids": ["android_system_ca"]
  },
  "operations": [
    {
      "op": "ENABLE_VERITY",
      "file_id": "app.apk",
      "file_size_bytes": 16384,
      "salt": "sec_salt_123",
      "blocks": ["code_0", "code_1", "code_2", "code_3"],
      "signature": {"signer_key": "android_system_ca", "valid": true}
    },
    {"op": "READ", "file_id": "app.apk", "offset": 0, "length": 8192},
    {"op": "READ", "file_id": "app.apk", "offset": 0, "length": 4096},
    {"op": "INJECT_TAMPER", "file_id": "app.apk", "block_index": 3, "corrupted_payload": "ROOTKIT_PAYLOAD"},
    {"op": "READ", "file_id": "app.apk", "offset": 12288, "length": 4096}
  ]
}
```

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다 (`separators=(',', ':')`).
```json
{
  "history": [
    {
      "op": "ENABLE_VERITY",
      "file_id": "app.apk",
      "status": "SUCCESS",
      "root_hash": "2d0bc90664e807a2a98d23e6fe3c9f461a76fc3fbce9f1d13b0c7d5c4b21c675",
      "num_blocks": 4,
      "tree_levels": 2,
      "tree_storage_bytes": 4096,
      "overhead_pct": 25.0,
      "detail": "fsverity enabled: root_hash=2d0bc90664e807a2... over 4 blocks (tree overhead=25.0%)"
    },
    ...
  ],
  "summary": {
    "total_files_protected": 1,
    "total_read_requests": 3,
    "pages_verified_on_demand": 2,
    "page_cache_hits_skipped": 1,
    "page_cache_skip_ratio_pct": 33.33,
    "corrupted_blocks_blocked": 1,
    "total_data_bytes_read": 12288
  }
}
```
