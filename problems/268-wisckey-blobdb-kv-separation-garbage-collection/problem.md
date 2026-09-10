# [Pro #268] WiscKey / RocksDB BlobDB: 대용량 값 키-값 분리(Key-Value Separation), 가비지 컬렉션(GC) 및 LSM 인덱스 재배치 엔진

## 문제 설명

전통적인 **LSM-Tree(Log-Structured Merge-tree)** 기반 스토리지 엔진(LevelDB, RocksDB 등)은 높은 쓰기 처리량과 순차 I/O의 장점을 제공하지만, **쓰기 증폭(Write Amplification, WA)**이 극심하다는 고질적인 한계를 지닙니다. LSM-Tree에서는 상위 레벨에서 하위 레벨로 넘어갈 때마다 키와 값이 여러 차례 읽히고, 정렬되고, 다시 디스크에 쓰이는 다단계 컴팩션(Compaction) 과정을 거칩니다. 이때 값(Value)의 크기가 수 KB~수 MB 이상으로 커지면 실제 유의미한 데이터 변경 없이도 거대한 페이로드가 수십 번씩 디스크에 재기록되면서 SSD의 수명을 급격히 갉아먹고 I/O 대역폭을 독점합니다($WA \approx 10\sim50\times$).

이 문제를 혁신적으로 해결한 패러다임이 바로 FAST '16 명저이자 RocksDB Integrated BlobDB 및 TiKV Titan의 근간이 된 **WiscKey (Key-Value Separation for SSDs)**입니다. WiscKey의 핵심 원리는 단순하면서도 강력합니다:
1. **키-값 분리(KV Separation)**: 작은 메타데이터나 키는 여전히 LSM-Tree(SST 파일)에 저장하여 정렬 및 인덱싱 효율을 유지하되, 임계값(`min_blob_size`) 이상의 대용량 값(Blob)은 오직 순차 추가(Append-only) 방식으로 **블롭 파일(Blob Files / Value Log, vLog)**에 기록합니다.
2. **블롭 인덱스(Blob Index)**: LSM-Tree 내부에는 값 원본 대신 블롭의 위치를 가리키는 경량 레퍼런스 `(file_number, offset, size, crc32)`만을 저장합니다. 이를 통해 컴팩션 시 오직 수십 바이트짜리 인덱스만 이동하므로 쓰기 증폭을 $O(1)$ 수준으로 극적으로 낮춥니다.
3. **블롭 가비지 컬렉션(Blob GC)**: 키가 갱신(`PUT`)되거나 삭제(`DELETE`)되어도 블롭 파일은 불변(Immutable)이므로 이전 블롭은 디스크에 그대로 남아 데드 바이트(Garbage)가 됩니다. 유효 데이터 대비 가비지 비율이 임계값(`blob_garbage_threshold`)을 초과한 블롭 파일은 GC 대상이 되어, **현재 LSM-Tree를 역조회하여 여전히 유효(Live)한 블롭만을 활성 블롭 파일(Active File)로 복사(Relocation)**하고 LSM 인덱스 포인터를 갱신한 뒤 기존 블롭 파일을 통째로 안전하게 삭제(`PURGED`)합니다.

당신은 차세대 고성능 분산 스토리지 및 임베디드 데이터베이스 코어 엔진 개발팀의 시니어 시스템 엔지니어로서, RocksDB Integrated BlobDB 규격의 **키-값 분리 스토리지 및 가비지 컬렉션 전산 시뮬레이션 엔진**을 구현해야 합니다.

---

## 시스템 사양 및 세부 처리 규칙

### 1. 설정 매개변수 (`config`)
- `min_blob_size` (정수, 바이트 단위, 기본값 128): 값의 UTF-8 바이트 크기가 이 값 이상이면 Blob 파일에 분리 저장하며, 미만이면 LSM-Tree에 `INLINE`으로 직접 내장합니다.
- `max_blob_file_size` (정수, 바이트 단위, 기본값 4096): 현재 쓰기 중인 활성 블롭 파일(`ACTIVE`)에 새 레코드를 추가했을 때 파일의 총 바이트가 이 제한을 초과하게 되면, 현재 파일을 `IMMUTABLE`로 닫고 다음 번호(`file_number + 1`)의 새 활성 파일을 생성합니다. (단, 현재 파일이 비어있는 상태(`total_bytes == 0`)라면 크기와 무관하게 최소 1개의 레코드는 수용합니다.)
- `blob_garbage_threshold` (실수, 예: 0.30): 닫힌 블롭 파일(`IMMUTABLE`) 중 $\text{garbage\_ratio} = \frac{\text{garbage\_bytes}}{\text{total\_bytes}} \ge \text{blob\_garbage\_threshold}$ 조건을 만족하는 파일이 GC 수거 대상이 됩니다.
- `enable_gc_on_write` (불리언, 기본값 false): `true`인 경우 매 쓰기 연산(`PUT`, `DELETE`) 직후 자동으로 GC 조건을 점검하여 대상 파일들을 즉시 정리합니다.
- `lsm_benchmark_wa` (실수, 기본값 15.0): 대용량 값을 분리하지 않는 전통적인 순수 LSM-Tree의 기준 쓰기 증폭 계수입니다.

### 2. 블롭 레코드 구조 및 오프셋 계산
- 블롭 파일에 저장되는 각 레코드는 고정 16바이트 헤더와 가변 길이 페이로드로 구성됩니다:
  $$\text{record\_size} = 16 + \text{len}(key\_bytes) + \text{len}(val\_bytes)$$
- 활성 블롭 파일 내 레코드의 시작 오프셋은 해당 레코드가 추가되기 직전의 `total_bytes`입니다.
- 레코드 추가 시 파일의 `total_bytes`와 `live_bytes`가 `record_size`만큼 증가하며, 최초 디스크 쓰기 총량(`initial_blob_bytes_written`)에 합산됩니다.
- 레코드 헤더에는 무결성 검증을 위한 `crc32` (값 바이트의 표준 unsigned 32비트 CRC 체크섬 8자리 소문자 16진수 문자열)가 기록됩니다.

### 3. 작업 연산 (`operations`) 명세
- `PUT {"key": str, "value": str}`:
  - 기존에 동일한 `key`가 존재했고 이전 상태가 `BLOB_INDEX`였다면, 이전 파일 번호의 `live_bytes`를 이전 `record_size`만큼 차감하고 `garbage_bytes`를 동일하게 증가시킵니다.
  - 새 값의 바이트 길이가 `min_blob_size` 미만이면 LSM-Tree에 `{"type": "INLINE", "value": value}`로 저장합니다.
  - 새 값의 바이트 길이가 `min_blob_size` 이상이면 활성 블롭 파일에 순차 기록하고, LSM-Tree에 `{"type": "BLOB_INDEX", "file_number": fn, "offset": offset, "record_size": rec_size, "val_size": val_len, "crc32": crc}`를 등록합니다.
  - `enable_gc_on_write`가 `true`이면 즉시 GC 점검을 호출합니다.
- `DELETE {"key": str}`:
  - 키가 존재하고 `BLOB_INDEX`였다면, 해당 파일의 `live_bytes`를 차감하고 `garbage_bytes`를 증가시킵니다.
  - 키를 LSM-Tree 인덱스에서 완전히 제거합니다.
  - `enable_gc_on_write`가 `true`이면 즉시 GC 점검을 호출합니다.
- `GET {"key": str}`:
  - LSM-Tree에서 `key`를 조회합니다.
  - 존재하지 않으면: `{"op": "GET", "key": key, "found": false, "value": null}`
  - `INLINE`이면: `{"op": "GET", "key": key, "found": true, "source": "INLINE", "value": value}`
  - `BLOB_INDEX`이면: 해당 파일의 레코드에서 값을 역참조하고 CRC32 무결성을 검증하여 반환합니다:
    `{"op": "GET", "key": key, "found": true, "source": "BLOB", "file_number": fn, "offset": offset, "size": val_len, "crc_valid": true, "value": value}`
- `TRIGGER_GC {}`:
  - 명시적으로 블롭 가비지 컬렉션을 1회 트리거합니다.

### 4. 가비지 컬렉션(GC) 및 유효 블롭 재배치(Relocation) 절차
1. **후보 선별**: 현재 상태가 `IMMUTABLE`이고 $\frac{\text{garbage\_bytes}}{\text{total\_bytes}} \ge \text{blob\_garbage\_threshold}$ 인 파일들을 수집합니다. (적격 파일이 없으면 즉시 종료)
2. **순차 처리**: 수집된 파일들을 `file_number` 오름차순으로 순회합니다. GC 실행 총 횟수(`gc_runs_total`)를 1 증가시킵니다.
3. **블롭 생존 검증 및 재배치**:
   - 대상 파일에 과거 기록되었던 모든 레코드를 순회합니다.
   - 현재 LSM-Tree에서 `rec.key`를 조회했을 때, 여전히 `BLOB_INDEX`이며 가리키는 위치가 정확히 현재 파일 및 오프셋과 일치하는지 확인합니다.
   - **유효(Live) 블롭인 경우**:
     - 현재 활성 파일(`active_fn`)에 여유 공간이 없으면(추가 시 `max_blob_file_size` 초과) 활성 파일을 닫고 새 활성 파일을 엽니다.
     - 활성 파일에 새 레코드로 복사(재기록)하고, `total_bytes_relocated`와 `total_blobs_relocated`를 갱신합니다.
     - LSM-Tree 인덱스의 `BLOB_INDEX` 포인터를 새 활성 파일과 새 오프셋으로 갱신합니다.
   - **데드(Dead/Garbage) 블롭인 경우**:
     - 이미 다른 값으로 덮어쓰여졌거나 삭제된 데이터이므로 아무런 복사 없이 폐기합니다.
4. **파일 폐기(`PURGED`)**:
   - 모든 유효 블롭의 이동이 끝나면 수거 대상 파일의 상태를 `PURGED`로 변경하고 `purged_files` 목록에 추가합니다.
   - 수거된 파일의 `garbage_bytes`만큼 `total_bytes_reclaimed`를 증가시킵니다.

### 5. 효율성 지표 산출
- **공간 증폭(Space Amplification)**:
  $$\text{space\_amplification} = \frac{\text{total\_blob\_bytes\_on\_disk}}{\text{total\_live\_bytes\_on\_disk}}$$
  (현재 디스크에 남아있는 비폐기 파일 기준, `total_live_bytes_on_disk == 0`이면 1.0, 소수점 4자리 반올림)
- **WiscKey 쓰기 증폭(WAF)**:
  $$\text{wisckey\_write\_amplification} = 1.0 + \frac{\text{total\_bytes\_relocated}}{\text{initial\_blob\_bytes\_written}}$$
  (`initial_blob_bytes_written == 0`이면 1.0, 소수점 4자리 반올림)
- **LSM 대비 쓰기 증폭 절감율(%)**:
  $$\text{lsm\_write\_amp\_saving\_pct} = \max\left(0.0, \frac{\text{lsm\_benchmark\_wa} - \text{wisckey\_write\_amplification}}{\text{lsm\_benchmark\_wa}} \times 100\right)$$
  (소수점 2자리 반올림)

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:
```json
{
  "config": {
    "min_blob_size": 128,
    "max_blob_file_size": 1024,
    "blob_garbage_threshold": 0.30,
    "enable_gc_on_write": false,
    "lsm_benchmark_wa": 15.0
  },
  "operations": [
    {"op": "PUT", "key": "user:1", "value": "short_str"},
    {"op": "PUT", "key": "blob:1", "value": "...대용량 텍스트..."},
    {"op": "GET", "key": "blob:1"},
    {"op": "DELETE", "key": "blob:1"},
    {"op": "TRIGGER_GC"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 단일 JSON 객체를 공백 없이(또는 표준 JSON 포맷) 한 줄로 출력합니다:
```json
{
  "query_results": [
    {
      "op": "GET",
      "key": "blob:1",
      "found": true,
      "source": "BLOB",
      "file_number": 1,
      "offset": 0,
      "size": 200,
      "crc_valid": true,
      "value": "..."
    }
  ],
  "lsm_state": {
    "total_keys": 1,
    "inline_keys": 1,
    "blob_keys": 0
  },
  "blob_storage_stats": {
    "active_file_number": 1,
    "total_files_created": 1,
    "purged_files": [],
    "active_files": [
      {
        "file_number": 1,
        "status": "ACTIVE",
        "total_bytes": 222,
        "live_bytes": 0,
        "garbage_bytes": 222,
        "garbage_ratio": 1.0
      }
    ],
    "total_blob_bytes_on_disk": 222,
    "total_live_bytes_on_disk": 0,
    "total_garbage_bytes_on_disk": 222
  },
  "gc_summary": {
    "gc_runs_total": 0,
    "total_blobs_relocated": 0,
    "total_bytes_relocated": 0,
    "total_bytes_reclaimed": 0
  },
  "efficiency_metrics": {
    "space_amplification": 1.0,
    "wisckey_write_amplification": 1.0,
    "lsm_write_amp_saving_pct": 93.33
  }
}
```
