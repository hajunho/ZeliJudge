# Problem #389: Linux Kernel EROFS VLE In-Place Decompression & Extent Mapping Engine (`fs/erofs/`)

## 문제 설명

현대 모바일(Android 13+ 공식 기본 읽기 전용 파일시스템), 차량용 임베디드 OS 및 클라우드 네이티브 컨테이너 런타임(Nydus, Dragonfly)에서 플래시 메모리(UFS, eMMC, NVMe)에 최적화된 초고속 읽기 전용 압축 파일시스템의 필요성이 급부상했습니다.

과거 널리 쓰이던 SquashFS는 가변 크기 입력 데이터를 가변 크기 블록으로 압축하는 Fixed-Input 방식을 취하여, 임의 읽기(Random Read) 요청 시 극심한 읽기 증폭(Read Amplification)과 메모리 할당 병목(Bounce Buffer Thrashing)을 겪었습니다.

리눅스 커널 5.4부터 메인라인에 통합된 **EROFS (Enhanced Read-Only File System, `fs/erofs/`)**는 고정 출력 압축(Fixed-Output Compression)과 가변 길이 익스텐트(VLE - Variable-Length Extent) 아키텍처를 도입하여 플래시 스토리지 대역폭과 메모리 대역폭을 극대화했습니다:

```
+----------------------------------------------------------------------------------------------------+
|                                    EROFS VLE Extent Architecture                                   |
+----------------------------------------------------------------------------------------------------+
| [ Logical File: e.g. 8192 Bytes ]                                                                  |
|   | Cluster 0: [ 0 .. 4095 ] ---------> Physical Extent: EROFS_MAP_ZIPPED (csize: 1800 B <= 4KB)   |
|   | Cluster 1: [ 4096 .. 8191 ] ------> Physical Extent: EROFS_MAP_MAPPED (csize: 4096 B, Direct) |
+---+------------------------------------------------------------------------------------------------+
| [ In-Place Decompression (IPD) Engine ]                                                            |
|   | If csize <= 4096 (block_size): Decompress directly IN-PLACE inside the target page cache frame!|
|   |   -> Zero Bounce Buffer Allocations, Zero Extra memcpy Overhead!                               |
|   | If csize > 4096: Allocate temporary auxiliary bounce buffer for staged decompression.          |
+---+------------------------------------------------------------------------------------------------+
| [ Ultra-Compact Inodes ]                                                                           |
|   | Compact Inode (32 Bytes): Fits regular files <= 4GB, minimizing metadata memory footprint.     |
|   | Extended Inode (64 Bytes): Supports 64-bit sizes, nanosecond timestamps, and POSIX xattrs.     |
+----------------------------------------------------------------------------------------------------+
```

### 핵심 기능 및 아키텍처 규칙

1. **아이노드 레이아웃**:
   - `COMPACT` (32바이트): 표준 소형/중형 파일.
   - `EXTENDED` (64바이트): 4GB 초과 대용량 파일 또는 확장 속성(xattr) 지원.
2. **VLE 익스텐트 매핑 (Variable-Length Extent)**:
   - `EROFS_MAP_MAPPED`: 비압축 직접 매핑. 디바이스 물리 블록을 페이지 캐시로 제로-카피 직행 읽기.
   - `EROFS_MAP_ZIPPED`: 압축된 블록 클러스터(LZ4/MicroLZMA). 물리 압축 크기 `csize`와 논리 비압축 크기 `usize`를 가집니다.
3. **인플레이스 압축 해제 (In-Place Decompression / IPD)**:
   - 물리 압축 바이트 크기 `csize <= block_size (4096 B)`인 경우:
     - 커널은 별도의 바운스 버퍼(Bounce Buffer)를 할당하지 않고, 최종 대상 페이지 프레임 내부에서 제자리 압축 해제를 수행합니다 (`ipd_count++`).
   - `csize > block_size`인 경우 보조 버퍼를 할당합니다 (`bounce_count++`).
4. **오류 처리 및 무결성 검증**:
   - 파일 범위 내 익스텐트가 누락된 경우 `EIO_HOLE_OR_UNMAPPED` 오류 보고.
   - 원시 압축 데이터 바이트 길이가 `csize`보다 부족한 경우 `EIO_DECOMPRESSION_CORRUPT` 오류 보고.

당신은 리눅스 커널 EROFS 파일시스템의 VLE 익스텐트 매핑, 콤팩트/확장 아이노드, 인플레이스 압축 해제(IPD) 판단 및 멀티-클러스터 임의 읽기 엔진을 시뮬레이션하는 프로그램을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "config": {
    "block_size": 4096
  },
  "commands": [
    {
      "op": "CREATE_INODE",
      "ino": 101,
      "size": 4096,
      "is_extended": false,
      "extents": [
        {"logical_cluster": 0, "type": "EROFS_MAP_ZIPPED", "pblk": 10, "csize": 1800, "usize": 4096, "data": "aa..."}
      ]
    },
    {
      "op": "READ",
      "ino": 101,
      "offset": 500,
      "length": 2000
    }
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 공백 없이 컴팩트한 단일 JSON 객체를 출력합니다:

```json
{
  "total_inodes": 1,
  "total_uncompressed_bytes": 4096,
  "total_compressed_bytes": 1800,
  "total_metadata_bytes": 32,
  "compression_ratio": 0.4395,
  "total_ipd_decompressions": 1,
  "total_bounce_decompressions": 0,
  "events": [ ... ]
}
```
