# Linux Kernel Zswap (Compressed Writeback Cache) 프론트스왑 훅, 압축률 거절 및 LRU 디스크 라이트백 엔진

## 문제 설명

리눅스 커널의 **zswap(`mm/zswap.c`)**은 시스템의 익명 메모리 페이지(Anonymous Pages)가 메모리 압박으로 인해 디스크로 스왑아웃(Swap-out)될 때, 이를 중간에서 가로채 압축하여 RAM 내부의 동적 압축 메모리 풀에 보관하는 **압축 기반 라이트백 스왑 캐시(Compressed Writeback Swap Cache)** 서브시스템입니다.

기존의 단순 가상 스왑 디바이스인 zram과 달리, zswap은 실제 백킹 스왑 디스크(Backing Swap Device, e.g. NVMe/SSD)와 긴밀히 연동되는 2계층(Two-Tier) 스토리지 캐시 아키텍처를 가집니다:

```
                  [ 커널 가상 메모리 관리 (mm/vmscan.c) ]
                                    |
                            (swap_writepage)
                                    v
                       [ Frontswap / Zswap 계층 ]
                                    |
       +----------------------------+----------------------------+
       |                                                         |
 (압축률 양호 & 공간 확보)                                  (압축률 불량 또는 풀 가득 참)
       v                                                         v
 [ zswap 압축 메모리 풀 ]                                 [ 물리 디스크 스왑 ]
 (zpool: zsmalloc/zbud)                                 (/dev/nvme0n1p2)
       |                                                         ^
       +--------(메모리 풀 초과 시 LRU 라이트백)------------------+
```

### 핵심 동작 메커니즘
1. **프론트스왑 가로채기 (`SWAP_STORE`)**:
   - 페이지 스왑 요청이 오면 `(swap_type, swap_offset)`을 키로 삼아 압축을 수행합니다.
   - **압축률 검사 (Compression Ratio Check)**:
     - $\text{ratio} = \text{compressed\_bytes} / \text{uncompressed\_bytes}$.
     - 만약 `ratio > max_compression_ratio_threshold`이면 압축 효율이 불량하다고 판단하여 zswap 진입을 거부(`REJECTED_POOR_COMPRESSION_TO_DISK`)하고 물리 디스크 스왑에 직접 기록합니다.
2. **LRU 디스크 라이트백 (LRU Writeback to Disk)**:
   - zswap 풀의 총 사용 바이트 수(`current_pool_bytes`)와 새로 추가될 데이터 크기의 합이 `pool_capacity_bytes`를 초과할 경우:
     - 가장 오래 참조되지 않은(LRU) 엔트리를 zswap 풀에서 꺼내어(Decompress/Writeback) 물리 디스크 스왑으로 방출(Evict)합니다.
     - 공간이 확보될 때까지 이 과정을 반복합니다.
   - 단일 엔트리가 풀 전체 용량을 초과하여 방출 후에도 수용할 수 없으면 `REJECTED_POOL_FULL_TO_DISK`로 처리됩니다.
3. **스왑 인 / 폴트 복원 (`SWAP_LOAD`)**:
   - `do_swap_page()` 페이지 폴트 시:
     - zswap 풀에 존재하면 즉시 압축 해제(`HIT_ZSWAP_DECOMPRESSED`)하여 물리 I/O 없이 0초 만에 복원하고 풀에서 엔트리를 제거합니다.
     - 물리 디스크에 존재하면 `HIT_DISK_SWAP`으로 응답합니다.
     - 둘 다 없으면 `MISS_NOT_FOUND`.
4. **스왑 무효화 (`SWAP_INVALIDATE`)**:
   - 페이지가 프로세스 종료나 새 쓰기로 인해 무효화되면 zswap 풀 또는 디스크 스왑에서 즉시 엔트리를 제거하고 메모리를 반환합니다.

본 문제에서는 zswap의 프론트스왑 훅, 압축률 임계치 필터링, LRU 큐 기반 디스크 라이트백, 2계층 스왑 탐색 및 무효화 상태 머신을 구현해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "max_pool_pages": 2,
  "page_size": 4096,
  "max_compression_ratio_threshold": 0.8,
  "operations": [
    {
      "op": "SWAP_STORE",
      "swap_type": 0,
      "swap_offset": 1,
      "compressed_bytes": 3000
    },
    {
      "op": "SWAP_STORE",
      "swap_type": 0,
      "swap_offset": 2,
      "compressed_bytes": 3000
    },
    {
      "op": "SWAP_STORE",
      "swap_type": 0,
      "swap_offset": 3,
      "compressed_bytes": 3000
    },
    {
      "op": "SWAP_LOAD",
      "swap_type": 0,
      "swap_offset": 1
    }
  ]
}
```

### 파라미터 규격
- `max_pool_pages` (정수, 기본 4): zswap 풀이 사용할 수 있는 최대 물리 페이지 수. 총 용량은 `max_pool_pages * page_size`.
- `page_size` (정수, 기본 4096): 페이지 크기 (바이트).
- `max_compression_ratio_threshold` (실수, 기본 0.8): 압축 거부 임계 비율.
- `operations` (배열): 순차 실행할 스왑 연산 목록.
  - `SWAP_STORE`: `swap_type`, `swap_offset`, `uncompressed_bytes` (기본 `page_size`), `compressed_bytes`.
  - `SWAP_LOAD`: `swap_type`, `swap_offset`.
  - `SWAP_INVALIDATE`: `swap_type`, `swap_offset`.

---

## 출력 형식

표준 출력(stdout)으로 다음 스키마의 단일 JSON 문자열(공백 없는 compact 형태)을 출력합니다:

```json
{
  "max_pool_pages": 2,
  "page_size": 4096,
  "pool_capacity_bytes": 8192,
  "current_pool_bytes": 6000,
  "pool_utilization_ratio": 0.7324,
  "active_zswap_entries": 2,
  "active_disk_entries": 1,
  "stats": {
    "store_requests": 3,
    "stored_zswap": 3,
    "rejected_poor_compression": 0,
    "rejected_pool_full": 0,
    "evicted_to_disk": 1,
    "load_requests": 1,
    "zswap_hits": 0,
    "disk_hits": 1,
    "load_misses": 0,
    "invalidations": 0
  },
  "lru_keys": ["0:2", "0:3"],
  "op_log": [
    {
      "op": "SWAP_STORE",
      "key": "0:1",
      "compressed_bytes": 3000,
      "current_pool_bytes": 3000,
      "status": "STORED_ZSWAP",
      "evicted_keys": []
    },
    {
      "op": "SWAP_STORE",
      "key": "0:2",
      "compressed_bytes": 3000,
      "current_pool_bytes": 6000,
      "status": "STORED_ZSWAP",
      "evicted_keys": []
    },
    {
      "op": "SWAP_STORE",
      "key": "0:3",
      "compressed_bytes": 3000,
      "current_pool_bytes": 6000,
      "status": "STORED_ZSWAP",
      "evicted_keys": ["0:1"]
    },
    {
      "op": "SWAP_LOAD",
      "key": "0:1",
      "status": "HIT_DISK_SWAP"
    }
  ]
}
```

---

## 제약 조건

- $1 \le \text{max\_pool\_pages} \le 256$
- $512 \le \text{page\_size} \le 65536$
- $0.1 \le \text{max\_compression\_ratio\_threshold} \le 1.0$
- $1 \le \text{len(operations)} \le 2000$
- 실행 시간 제한: 3.0초 이내
- 메모리 사용 제한: 256MB 이내
