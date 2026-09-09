# Problem 243: 리눅스 커널 I/O: 페이지 캐시 리드어헤드(Readahead) I/O 증폭, 캐시 오염 및 `posix_fadvise` / `O_DIRECT` 바이패스 최적화

## 1. 개요 및 배경 시나리오

초당 수만 건의 트랜잭션을 처리하는 대규모 데이터베이스(PostgreSQL, RocksDB, ClickHouse, Elasticsearch) 및 고성능 스토리지 엔진은 리눅스 커널의 **페이지 캐시(Page Cache)**를 통해 디스크 I/O를 가속합니다.

리눅스 커널은 기본적으로 파일 I/O가 순차적(Sequential)일 가능성이 높다고 가정하고, **온디맨드 리드어헤드(`ondemand_readahead`)** 알고리즘을 가동합니다. 프로세스가 4KB 블록을 요청하더라도 커널은 내부 선독 윈도우(`default_ra_pages = 32`, 즉 128KB)만큼 디스크에서 투기적(Speculative)으로 미리 읽어 페이지 캐시에 적재합니다.

```
                      리눅스 커널 페이지 캐시 리드어헤드와 I/O 증폭
                      
 [B-Tree/LSM 인덱스 포인트 룩업: 애플리케이션은 4KB만 필요]
 Application ──► read(fd, buf, 4KB) ──► Linux VFS Page Cache
                                              │ (Cache Miss!)
                                              ▼
                                 [ondemand_readahead 가동]
                                 4KB 요청에 대해 128KB(32 Pages)를 디스크에서 투기적 프리페치!
                                              │
               ┌──────────────────────────────┴──────────────────────────────┐
               ▼                                                             ▼
     [유용한 데이터 (Useful)]                                      [낭비된 데이터 (Wasted)]
     4KB 블록 (1 Page)                                             124KB 블록 (31 Pages)
     애플리케이션이 실제 사용                                          한 번도 읽히지 않고
                                                                   페이지 캐시 LRU에 방치!
                                                                             │
                                                                             ▼
                                                                [페이지 캐시 오염 (Pollution)]
                                                                기존의 핫(Hot) 인덱스/데이터를
                                                                메모리 밖으로 강제 축출(Evict)!
```

그러나 무작위 포인트 룩업(Random Point Lookup)이 지배적인 OLTP 데이터베이스 환경에서 커널의 기본 리드어헤드는 다음과 같은 재앙적인 I/O 병목을 초래합니다:

1. **무작위 룩업 시 $32\times$ I/O 증폭 및 디스크 대역폭 고갈 (`READAHEAD_IO_AMPLIFICATION_WASTE`)**:
   - B-Tree 인덱스 탐색이나 LSM-Tree SSTable 포인트 조회를 위해 4KB 블록을 읽을 때마다, 커널이 불필요하게 128KB를 읽어들임으로써 **I/O 증폭비(I/O Amplification)가 $32\times$**에 달합니다.
   - 읽어 들인 디스크 대역폭의 96.8%가 버려지며, 고성능 NVMe SSD 또는 클라우드 블록 스토리지(AWS EBS io2/gp3)의 IOPS와 대역폭 한도를 조기에 고갈시켜 쿼리 지연시간이 수십 배 폭증합니다.

2. **벌크 스캔 및 백업으로 인한 페이지 캐시 오염과 워킹셋 축출 (`PAGE_CACHE_POLLUTION_WORKING_SET_EVICTION`)**:
   - 대규모 배치 분석 쿼리나 백업 덤프(`BULK_EXPORT`)가 수백 메가바이트의 콜드 데이터를 순차적으로 읽어들임.
   - 이때 유입된 일회성 콜드 페이지들이 페이지 캐시 LRU 리스트를 가득 채우면서, 정작 자주 조회되던 핫 인덱스 페이지들을 RAM 밖으로 밀어내어(Eviction) 전체 DB의 캐시 히트율이 95%에서 30%대로 급락합니다.

3. **최적화 기법의 부재**:
   - **`posix_fadvise(fd, offset, len, POSIX_FADV_RANDOM)`**: 리드어헤드 윈도우를 0(`ra_pages = 0`)으로 비활성화하여 오직 필요한 4KB만 정확히 읽도록 지시.
   - **`posix_fadvise(fd, offset, len, POSIX_FADV_DONTNEED)`**: 벌크 스캔 후 해당 페이지를 페이지 캐시에서 즉시 해제하여 핫 워킹셋을 보존.
   - **`O_DIRECT`**: 페이지 캐시를 아예 거치지 않고 사용자 공간 메모리 버퍼로 직접 DMA 전송하여 이중 버퍼링과 캐시 오염을 원천 차단.

본 과제에서는 리눅스 커널 페이지 캐시의 LRU 동작, 리드어헤드 I/O 증폭, `posix_fadvise` 힌트 및 `O_DIRECT`의 동작을 정밀하게 시뮬레이션하고 문제를 진단해야 합니다.

---

## 2. 상태 머신 및 동작 명세

시뮬레이터는 스토리지 설정(`storage_config`)과 쿼리 워크로드(`workload`)를 순차적으로 실행합니다.

### 2.1 스토리지 설정 (`storage_config`)
- `page_cache_capacity_mb`: 페이지 캐시 최대 수용 용량 (MB).
- `default_ra_pages`: 기본 리드어헤드 페이지 수 (기본 32페이지 = 128KB).
- `page_size_kb`: 커널 메모리 페이지 크기 (기본 4KB).

### 2.2 I/O 전략 및 연산 동작 규칙
- **`io_strategy`**:
  - `DEFAULT_KERNEL_PAGE_CACHE`: 커널 기본 온디맨드 리드어헤드 동작.
  - `POSIX_FADV_RANDOM`: 파일 전체에 리드어헤드를 끄고 요청된 페이지만 읽음.
  - `O_DIRECT`: 페이지 캐시를 우회하여 디스크에서 직접 읽음 (캐시 미할당, 히트율 0%).
- **쿼리 타입 (`queries`)**:
  - `POINT_LOOKUP`: 인덱스 기반 포인트 조회 (기본 4KB).
  - `RANGE_SCAN`: 순차 범위 스캔.
  - `BULK_EXPORT`: 대규모 배치/덤프 읽기.
  - `fadvise_hint`: 개별 쿼리 레벨의 힌트 (`POSIX_FADV_RANDOM`, `POSIX_FADV_DONTNEED`, `null`).

### 2.3 캐시 히트 및 디스크 읽기 판정
1. 요청된 페이지들이 모두 페이지 캐시에 존재하면 `cache_hits` 증가 및 LRU 최신화.
2. 하나라도 누락되면 `cache_misses` 증가 후 디스크 I/O 수행:
   - `O_DIRECT`: 캐시 갱신 없이 정확히 `read_size_kb`만 디스크에서 읽음.
   - `POSIX_FADV_RANDOM` (또는 전략 적용 시): 필요한 페이지만 읽어 캐시에 적재.
   - `DEFAULT_KERNEL_PAGE_CACHE`:
     - `POINT_LOOKUP`인 경우 최소 `default_ra_pages` (128KB)를 디스크에서 읽어 캐시에 적재.
     - `RANGE_SCAN` / `BULK_EXPORT`인 경우 2배(256KB)를 읽어 적재.
   - `fadvise_hint == "POSIX_FADV_DONTNEED"`인 경우 읽은 페이지를 캐시에 보관하지 않고 즉시 폐기.
   - 캐시가 가득 찬 경우 가장 오래된 페이지를 축출(`evictions_count` 증가).

---

### 2.4 감지해야 할 이상 징후 (`anomalies`) 및 권장안 (`recommendations`)

- `"READAHEAD_IO_AMPLIFICATION_WASTE"`:
  - I/O 증폭비($\frac{\text{total\_bytes\_read\_from\_disk}}{\text{total\_bytes\_useful}} \ge 3.0$)가 3.0 이상으로 대역폭 낭비가 발생한 경우.
  - 권장안: `"APPLY_POSIX_FADV_RANDOM_FOR_INDEX_LOOKUPS"`
- `"PAGE_CACHE_POLLUTION_WORKING_SET_EVICTION"`:
  - 사전 적재된 핫 페이지가 대량 축출(`evictions > 500`)되고 캐시 히트율이 50% 미만으로 급락한 경우.
  - 권장안: `"USE_POSIX_FADV_DONTNEED_FOR_BULK_SCANS"`

---

## 3. 입력 형식 (`sys.stdin`)

표준 입력으로 단일 JSON 객체가 주어집니다.

```json
{
  "storage_config": {
    "page_cache_capacity_mb": 256,
    "default_ra_pages": 32,
    "page_size_kb": 4
  },
  "workload": {
    "io_strategy": "DEFAULT_KERNEL_PAGE_CACHE",
    "hot_pages_preload_kb": [],
    "queries": [
      {
        "query_id": "rand-0",
        "type": "POINT_LOOKUP",
        "offset_mb": 100,
        "read_size_kb": 4,
        "fadvise_hint": null
      }
    ]
  }
}
```

---

## 4. 출력 형식 (`sys.stdout`)

표준 출력으로 JSON 객체를 단일 행으로 출력합니다 (`ensure_ascii=False`).

```json
{
  "io_strategy": "DEFAULT_KERNEL_PAGE_CACHE",
  "total_queries": 1,
  "cache_hits": 0,
  "cache_misses": 1,
  "cache_hit_ratio_pct": 0.0,
  "total_bytes_useful_mb": 0.0,
  "total_bytes_read_from_disk_mb": 0.12,
  "io_amplification_ratio": 32.0,
  "evictions_count": 0,
  "page_cache_used_mb": 0.12,
  "anomalies": [
    "READAHEAD_IO_AMPLIFICATION_WASTE"
  ],
  "recommendations": [
    "APPLY_POSIX_FADV_RANDOM_FOR_INDEX_LOOKUPS"
  ],
  "diagnosis": "랜덤 포인트 룩업 시 커널의 과도한 리드어헤드로 인해 I/O 증폭비(32.0x) 및 대역폭 낭비 발생 (디스크 0.12MB 읽음 / 실제 필요 0.0MB)."
}
```
