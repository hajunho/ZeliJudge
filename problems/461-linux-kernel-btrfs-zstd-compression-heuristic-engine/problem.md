# 문제 461: Linux Kernel Btrfs ZSTD 투명 압축 및 엔트로피 휴리스틱 엔진

## 문제 설명

리눅스 커널의 현대적 CoW(Copy-on-Write) 파일시스템인 **Btrfs**(`fs/btrfs/`)는 디스크 I/O 대역폭을 절약하고 플래시 스토리지의 수명을 연장하기 위해 파일 익스텐트(Extent) 수준의 투명 압축(Transparent Compression: ZSTD, LZO, zlib)을 지원합니다 (`fs/btrfs/compression.c`, `fs/btrfs/zstd.c`).

그러나 압축 알고리즘을 맹목적으로 모든 쓰기 I/O에 적용하면 다음과 같은 치명적인 성능 저하가 발생합니다:
1. **CPU 사이클 낭비**: 이미 압축된 파일(JPEG, MP4, zip)이나 암호화된 데이터에 ZSTD/LZO를 적용하면 CPU만 100% 소모하고 압축률은 0%에 수렴합니다.
2. **압축 확장(Expansion) 문제**: 압축 후 크기가 오히려 원본보다 커질 수 있습니다.

Btrfs는 이 문제를 해결하기 위해 **2단계 휴리스틱 및 디스크 섹터 절약 검증 파이프라인**을 운영합니다:

```
+-----------------------------------------------------------------------------------------+
|                  Btrfs Transparent Extent Compression Pipeline                          |
+-----------------------------------------------------------------------------------------+

 [Incoming 128KB Extent Chunk]
               |
               v
 [Step 1: Shannon Entropy Heuristic (btrfs_compress_heuristic)]
               |
      +--------+--------+
      |                 |
  Entropy >= 6.5    Entropy < 6.5 (Compressible)
  (Incompressible)      |
      |                 v
      |          [Step 2: Run ZSTD Compression]
      |                 |
      |          Compressed size check:
      |          compressed_sectors < uncompressed_sectors ?
      |                 |
      |           +-----+-----+
      |           |           |
      |          YES          NO (Insufficient savings)
      |           |           |
      v           v           v
 [Write RAW]  [Write ZSTD] [Write RAW]
 (Disk blocks (Disk blocks (Disk blocks
  uncompressed) saved!)     uncompressed)
```

### 핵심 메커니즘
1. **섀넌 엔트로피 휴리스틱 (`btrfs_compress_heuristic`)**:
   - 데이터 청크의 바이트 빈도수를 분석하여 섀넌 엔트로피($H$)를 계산합니다:
     $$H = -\sum_{i} P(b_i) \log_2 P(b_i)$$
   - 엔트로피가 임계값(`entropy_threshold`, 기본 6.5) 이상인 경우, 커널은 해당 청크를 비압축 가능(`HEURISTIC_INCOMPRESSIBLE`)으로 판정하여 고비용 압축을 즉각 생략하고 원시(Raw) 익스텐트로 기록합니다.
2. **최소 1섹터(4KB) 절약 조건**:
   - 엔트로피 테스트를 통과하여 ZSTD 압축을 수행했더라도, 디스크 할당 단위인 4KB 섹터 기준으로 최소 1섹터 이상의 절약이 발생하지 않으면(`compressed_sectors >= uncompressed_sectors`), 압축 결과를 폐기하고 원시 데이터를 기록합니다 (`INSUFFICIENT_SPACE_SAVINGS`).
3. **디스크 익스텐트 매핑 및 압축 해제 읽기 (`read_extent`)**:
   - 압축된 익스텐트(`is_compressed = True`)에서 읽기를 수행할 때, 커널은 디스크에서 압축된 섹터(`disk_num_bytes`)를 인출하여 임시 작업 버퍼에서 압축을 해제한 후 요청된 오프셋 슬라이스를 반환합니다 (`decompression_reads += 1`).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:
- `config`:
  - `entropy_threshold`: float (기본값: 6.5)
  - `compression_ratio_factor`: float (기본값: 0.3)
- `operations`: 일련의 연산 배열.

지원되는 연산:
1. `{"op": "SET_CONFIG", "entropy_threshold": float|null, "compression_ratio_factor": float|null}`
   - 휴리스틱 임계값 및 압축 비율 인수를 설정합니다.
2. `{"op": "WRITE_EXTENT_CHUNK", "inode_id": int, "file_offset": int, "data_str": str}`
   - 지정된 inode 및 오프셋에 청크를 기록합니다.
   - 엔트로피 판정 및 압축 절약 검증 후 익스텐트를 생성하여 상태를 반환합니다.
3. `{"op": "READ_EXTENT", "inode_id": int, "file_offset": int, "length": int}`
   - 파일 오프셋에서 데이터를 읽어옵니다. 미존재 inode 시 `ENOENT_INODE_NOT_FOUND`, 매핑되지 않은 오프셋 시 `ENXIO_OFFSET_NOT_MAPPED`.
4. `{"op": "QUERY_BTRFS_STATE"}`
   - inode별 파일 바이트 및 디스크 바이트 요약, 통계(`stats`)를 반환합니다.

---

## 출력 형식

표준 출력(stdout)으로 각 연산의 결과를 담은 JSON을 한 줄(compact)로 출력합니다:
```json
{"results": [...]}
```
