# 398: 리눅스 커널 메모리 관리 — ZSWAP 압축 캐시 풀 관리, LRU 라이트백 퇴출 및 입출력 지연시간 극소화 엔진

## 1. 개요 (Overview)

운영체제에서 물리 메모리(RAM)가 부족해지면 커널의 페이지 회수 서브시스템은 비활성 익명 메모리(Anonymous Pages)를 디스크 스왑(Swap) 파티션으로 방출합니다. 그러나 물리적 NVMe SSD나 HDD에 스왑 I/O를 직접 수행하는 것은 **수백 마이크로초에서 수 밀리초에 달하는 치명적인 I/O 지연(Latency)** 을 유발하며, 서버 애플리케이션의 테일 레이턴시 스파이크 및 낸드 플래시 메모리의 쓰기 증폭(Write Amplification)과 수명 단축을 초래합니다.

이를 해결하기 위해 리눅스 커널에 도입된 **ZSWAP (`mm/zswap.c`)** 은 페이지가 물리적 스왑 디스크로 이동하기 전, 커널 내 가상 메모리 압축 캐시 풀(Compressed Cache Pool)로 가로채는 서브시스템입니다:
1. **인메모리 고속 압축**: 4KB 페이지를 LZ4/Zstandard/LZO 알고리즘으로 압축하여 RAM 내의 동적 zpool(`zsmalloc`, `zbud`)에 저장합니다.
2. **동일 바이트/영 페이지 최적화 (Same-Filled Optimization)**: 모든 바이트가 동일한 페이지(예: 4096바이트가 모두 0x00인 Zero Page)는 압축 연산조차 생략하고 단 1바이트 메타데이터로 기록하여 풀 용량을 0바이트 소모합니다.
3. **불량 압축 배제 (Bad Compression Ratio Bypass)**: 압축 후 크기가 원본 크기(4096 바이트)의 임계치(예: 80%)를 초과하는 고엔트로피 난수/암호화 데이터는 zswap 캐싱을 거부하고 물리 스왑 디스크로 즉시 직행시킵니다.
4. **LRU 라이트백 (Writeback to Storage)**: zswap 풀이 설정된 최대 용량(`max_pool_percent`)을 초과하면, 가장 오래된(Coldest) 압축 페이지를 백그라운드에서 해제하여 물리 디스크로 퇴출(Writeback)시킴으로써 풀 메모리를 확보합니다.
5. **초고속 스왑 인 (Zswap Hit)**: 스왑된 페이지를 다시 읽을 때 디스크 I/O 없이 RAM 버스 속도(수십 나노초)로 즉시 압축 해제하여 제공합니다.

본 문제에서는 리눅스 커널 ZSWAP의 동일 바이트 감지, 압축률 임계치 필터링, zpool 용량 관리, LRU 순환 갱신, 물리 스왑 디스크 계층 라이트백 및 히트/미스 통계 엔진을 설계 및 구현합니다.

---

## 2. Zswap 아키텍처 다이어그램

```
+========================================================================================+
|                        Linux Kernel Memory Subsystem (mm/vmscan.c)                     |
|                                [swap_writepage() Intercept]                            |
+========================================================================================+
                                            ||
                                            VV
+----------------------------------------------------------------------------------------+
| 1. Same-Filled Check: Are all 4096 bytes identical (e.g., 0x00 Zero Page)?             |
|    - [YES] -> Store same_byte metadata (Zero Pool Space Used!)                         |
|    - [NO]  -> Compress using zlib/lz4 (comp_bytes)                                     |
+----------------------------------------------------------------------------------------+
                                            ||
                                            VV
+----------------------------------------------------------------------------------------+
| 2. Compression Ratio Check: comp_bytes <= 4096 * max_compression_ratio (e.g. 80%)?     |
|    - [NO]  -> REJECT_POOR_COMPRESSION: Direct write to Physical Swap Disk!             |
|    - [YES] -> Proceed to Zswap Pool Storage                                            |
+----------------------------------------------------------------------------------------+
                                            ||
                                            VV
+----------------------------------------------------------------------------------------+
| 3. Pool Capacity & LRU Eviction: current_pool_bytes + comp_bytes <= max_pool_bytes?    |
|    - [NO]  -> Pop Coldest entry from LRU -> Decompress & WRITEBACK to Physical Disk!  |
|               Reclaim pool bytes until space is available.                             |
|    - [YES] -> Store into Zswap Pool, Append to LRU Front.                              |
+----------------------------------------------------------------------------------------+
                                            ||
                        +===================+===================+
                        ||                                      ||
                        VV                                      VV
           [ Zswap Hit (Fast RAM Path) ]             [ Disk Hit (Slow Storage Path) ]
           - Latency: ~50 nanoseconds                - Latency: ~500 microseconds
           - Zero Disk IO                            - NAND Flash Wear / Storage IO
```

---

## 3. 핵심 수리 및 알고리즘 규칙

### 3.1 동일 바이트 최적화 (Same-Filled Optimization)
4KB 바이트 열 $B = [b_0, b_1, \dots, b_{4095}]$에 대해:
$$orall i \in [0, 4095]: b_i = b_0 \implies 	ext{comp\_bytes} = 0, \quad 	ext{same\_byte} = 	ext{"0x" + hex}(b_0)$$
동일 바이트 페이지는 `comp_bytes = 0`으로 기록되며, `current_pool_bytes`를 일절 소모하지 않습니다.

### 3.2 압축 효율성 검증 (Compression Ratio Rejection)
압축된 데이터 크기가 설정된 임계치(기본 $80\%$, $4096 	imes 0.8 = 3276 	ext{ 바이트}$)를 초과할 경우:
$$	ext{comp\_bytes} > \lfloor 4096 	imes 	ext{max\_compression\_ratio} floor \implies 	ext{REJECT}$$
zswap 풀에 적재되지 않고 물리 스왑 디스크(`disk_swap`)로 즉시 직행합니다 (`rejected_poor_compression` 카운터 증가).

### 3.3 풀 용량 한계 및 LRU 라이트백 (Writeback Eviction)
새로운 압축 페이지를 적재할 공간이 부족할 때($	ext{current\_pool\_bytes} + 	ext{comp\_bytes} > 	ext{max\_pool\_bytes}$):
1. `lru_list`의 가장 오래된(인덱스 0) 항목을 추출(Pop)합니다.
2. 해당 엔트리를 물리 스왑 디스크(`disk_swap`)에 기록합니다.
3. $	ext{current\_pool\_bytes} \leftarrow 	ext{current\_pool\_bytes} - 	ext{entry.comp\_bytes}$로 풀 용량을 회수합니다.
4. 공간이 확보될 때까지 위 과정을 반복합니다.

### 3.4 페이지 로드 (Page Fault) 및 LRU 터치
- `LOAD` 요청 시:
  - `entries`에 존재하면 **`ZSWAP_HIT`**: `zswap_hits` 카운터 증가, 해당 페이지를 `lru_list`의 최신 위치(맨 뒤)로 갱신.
  - `disk_swap`에 존재하면 **`DISK_HIT`**: `disk_hits` 카운터 증가.

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
```json
{
  "config": {
    "max_pool_bytes": 100,
    "max_compression_ratio": 0.8
  },
  "operations": [
    {"action": "STORE", "page_id": "P1", "data_hex": "00..."},
    {"action": "LOAD", "page_id": "P1"}
  ]
}
```

### 4.2 출력 형식 (Output Format)
```json
{
  "current_pool_bytes": 41,
  "max_pool_bytes": 100,
  "pool_compression_ratio": 0.01,
  "stats": {
    "stored_pages": 1,
    "same_filled_pages": 0,
    "rejected_poor_compression": 0,
    "rejected_pool_full": 0,
    "written_back_to_disk": 0,
    "zswap_hits": 1,
    "disk_hits": 0,
    "reclaimed_pool_bytes": 0
  },
  "stored_in_zswap": ["P1"],
  "stored_on_disk": [],
  "lru_order": ["P1"]
}
```
