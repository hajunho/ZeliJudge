# Linux 커널 메모리 관리: ZRAM 압축 인메모리 스왑 디바이스 및 zsmalloc 슬랩 엔진

## 문제 설명

리눅스 커널의 **ZRAM**(구 `compcache`, `drivers/block/zram/zram_drv.c`)은 물리 RAM의 일부를 동적으로 할당받아 고속의 압축 블록 디바이스(Compressed In-RAM Block Device)로 제공하는 혁신적인 가상 메모리 서브시스템입니다. 안드로이드 모바일 기기, 임베디드 리눅스 라우터, 그리고 대규모 하이퍼스케일러 컨테이너 노드에서 ZRAM은 느린 플래시/디스크 I/O 없이 물리 메모리 용량을 가상으로 1.5배~3배까지 확장하여 OOM(Out of Memory) 킬러의 무차별적인 프로세스 강제 종료를 방어합니다.

ZRAM 디바이스는 페이지 단위($4096\text{ 바이트}$)로 들어오는 스왑-아웃(Swap-out) 요청(`bio`)을 처리하며, 내부 전용 메모리 할당자인 **`zsmalloc`**(`mm/zsmalloc.c`)과 긴밀하게 연동됩니다:
1. **동일 페이지 중복 제거 (Same-Page Deduplication / `ZRAM_SAME`)**:
   - 모든 바이트가 0(`0x00`)이거나 동일한 32비트 패턴(예: `0xFFFFFFFF`)으로 채워진 페이지는 압축 알고리즘을 거치지 않고 플래그와 4바이트 패턴 값만 메타데이터에 기록하며, `zsmalloc` 물리 풀에서 **0 바이트**를 소비합니다.
2. **`zsmalloc` 크기 클래스 및 zspage 슬랩 할당**:
   - 가변 길이로 압축된 데이터는 스텝 크기(`class_step_bytes`, 기본 32바이트) 단위로 올림된 크기 클래스($C \in [32, 64, \dots, 4096]$)에 매핑됩니다.
   - 크기 클래스 $C$는 내부 단편화 낭비($(p \times 4096) \pmod C$)를 최소화하는 최적의 물리 연속 페이지 개수 $p \in [1, 4]$를 계산하여 다중 페이지 묶음인 `zspage`를 형성합니다.
   - 슬롯 사용량에 따라 `ALMOST_FULL`, `ALMOST_EMPTY`, `EMPTY`, `FULL` 상태로 관리되어 재할당 효율을 극대화합니다.
3. **비압축 거대 페이지 방어 (`ZRAM_HUGE`)**:
   - 암호화 데이터나 무작위 바이너리처럼 압축 후 크기가 임계치($4096 - 64 = 4032\text{ 바이트}$) 이상인 페이지는 압축 효율이 없으므로 `ZRAM_HUGE`로 표시하고 비압축 원본 크기($4096\text{ 바이트}$)로 슬랩에 저장합니다.
4. **엄격한 메모리 제한 한도 (`mem_limit_bytes`)**:
   - ZRAM 풀이 차지하는 물리 메모리 총합(`total_physical_mem`)이 사전에 설정된 상한선(`mem_limit_bytes`)을 초과하여 새로운 `zspage`를 할당해야 하는 경우, 시스템 안정성을 위해 즉각 `-ENOMEM` 에러를 반환합니다.
5. **유휴 페이지(IDLE) 및 거대 페이지(HUGE) 보조 저장소 라이트백 (Writeback)**:
   - 보조 블록 장치(`backing_device`)가 활성화된 경우, 접근되지 않고 방치된 유휴 페이지(`SET_IDLE`로 마킹)나 RAM을 과도하게 점유하는 `HUGE` 페이지를 보조 저장소로 축출(Evict)하여 물리 RAM을 회수합니다.
6. **메모리 단편화 압축 해소 (Compaction / `echo 1 > /sys/block/zram0/compact`)**:
   - 페이지 삭제(`DISCARD`)나 라이트백으로 인해 발생한 슬랩 단편화를 해소하기 위해, 동일 크기 클래스 내에서 사용 슬롯이 적은 기증자(Donor) `zspage`의 객체들을 수용 가능한 수신자(Receiver) `zspage`로 이주 통합하고, 완전히 비워진 `zspage`의 물리 프레임들을 버디 할당자(Buddy Allocator)로 즉각 반환합니다.

주어진 ZRAM 설정 및 일련의 I/O 연산 시퀀스를 커널 명세에 따라 결정론적으로 시뮬레이션하고, 연산 이력(`history`)과 최종 메모리 상태 통계(`summary`)를 산출하는 엔진을 작성하십시오.

```
+-----------------------------------------------------------------------------------------+
|                  Linux Kernel ZRAM Compressed Swap & zsmalloc Engine                    |
+-----------------------------------------------------------------------------------------+
                                 [ bio Write Request: 4KB Page ]
                                                |
                       +------------------------+------------------------+
                       | Same Page Check? (Zero / 32-bit Fill Pattern)   |
                       +------------------------+------------------------+
                               /                                                        YES (ZRAM_SAME)                    NO (Compress)
                              |                                  |
                   [ Store 4B Pattern ]               [ LZ4 / LZO / ZSTD ]
                   [ 0 Bytes in RAM   ]                          |
                                                      +----------+----------+
                                                      | comp_len >= 4032 B? |
                                                      +----------+----------+
                                                             /                                                                YES (HUGE)       NO (COMPR)
                                                           |                |
                                                    [ alloc 4096B ]   [ round to Class C ]
                                                           \                /
                                                            +-------+------+
                                                                    |
                                                      +-------------+-------------+
                                                      | zsmalloc Allocation       |
                                                      | - Search ALMOST_FULL      |
                                                      | - Search ALMOST_EMPTY     |
                                                      | - New zspage (p*4096B)    |
                                                      |   * Check mem_limit_bytes |
                                                      +-------------+-------------+
                                                                    |
    +---------------------------------------------------------------+-----------------------------+
    | Maintenance Operations:                                                                     |
    |  * SET_IDLE  : Mark cold pages where (current_ts - last_access_ts) >= threshold             |
    |  * WRITEBACK : Evict IDLE or HUGE pages to secondary backing storage (Free RAM zspage)      |
    |  * COMPACT   : Coalesce fragmented zspages within same size classes, return pages to Buddy  |
    +---------------------------------------------------------------------------------------------+
```

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다.
```json
{
  "config": {
    "num_pages": 128,
    "mem_limit_bytes": 1048576,
    "comp_algorithm": "lz4",
    "backing_device": {
      "enabled": true,
      "capacity_pages": 32
    },
    "zsmalloc": {
      "class_step_bytes": 32,
      "max_zspage_pages": 4
    }
  },
  "operations": [
    {"op": "WRITE", "page_idx": 0, "content_type": "ZERO", "timestamp": 10},
    {"op": "WRITE", "page_idx": 1, "content_type": "PATTERN", "pattern_val": 255, "timestamp": 12},
    {"op": "WRITE", "page_idx": 2, "content_type": "DATA", "comp_bytes": 120, "timestamp": 15},
    {"op": "WRITE", "page_idx": 3, "content_type": "DATA", "comp_ratio": 0.99, "timestamp": 20},
    {"op": "READ", "page_idx": 2, "timestamp": 50},
    {"op": "SET_IDLE", "idle_age_threshold": 30, "timestamp": 60},
    {"op": "WRITEBACK", "type": "IDLE", "timestamp": 70},
    {"op": "DISCARD", "page_idx": 1, "timestamp": 80},
    {"op": "COMPACT", "timestamp": 90}
  ]
}
```

### 필드 상세 설명:
- `config`:
  - `num_pages` ($1 \le \text{num\_pages} \le 10000$): 디바이스 가상 디스크 크기(페이지 수).
  - `mem_limit_bytes`: ZRAM이 `zsmalloc` 물리 풀에 할당할 수 있는 최대 바이트 한도.
  - `comp_algorithm`: 압축 알고리즘 이름 (`"lz4"`, `"lzo"`, `"zstd"`).
  - `backing_device`:
    - `enabled`: 보조 블록 장치 활성화 여부 (`true` / `false`).
    - `capacity_pages`: 보조 저장소가 수용할 수 있는 최대 페이지 개수.
  - `zsmalloc`:
    - `class_step_bytes`: 슬랩 크기 클래스 간격 (기본 32 또는 64).
    - `max_zspage_pages`: 하나의 `zspage`를 구성하는 최대 물리 연속 페이지 수 ($1 \le p \le 4$).
- `operations`: 실행할 I/O 및 관리 명령 배열:
  - `WRITE`:
    - `page_idx`: 기록할 가상 페이지 인덱스 ($0 \le \text{page\_idx} < \text{num\_pages}$).
    - `content_type`: `"ZERO"` (0 바이트 패턴), `"PATTERN"` (32비트 정수 `pattern_val`), `"DATA"` (임의 데이터).
    - `comp_bytes` 또는 `comp_ratio`: `"DATA"` 타입일 때 압축 크기 직접 지정 또는 비율 ($comp\_len = \lceil 4096 \times comp\_ratio \rceil$). $comp\_len \ge 4032$이면 `ZRAM_HUGE` 처리되어 $4096$바이트로 할당됨.
    - `timestamp`: 연산 발생 타임스탬프 (정수).
  - `READ`: `page_idx` 읽기 (해당 페이지의 `last_access_ts`를 갱신하고 `IDLE` 플래그를 해제).
  - `DISCARD`: `page_idx`를 할당 해제하고 슬롯 및 페이지 회수 (TRIM).
  - `SET_IDLE`: 현재 `timestamp` 기준 마지막 접근으로부터 `idle_age_threshold` 이상 경과한 RAM 내 페이지들에 `IDLE` 플래그 부여.
  - `WRITEBACK`: `type` (`"IDLE"`, `"HUGE"`, `"ALL"`)에 부합하는 페이지들을 `page_idx` 오름차순으로 보조 저장소로 축출.
  - `COMPACT`: `zsmalloc` 슬랩 단편화 병합 및 빈 물리 페이지 회수.

## 출력 형식

표준 출력(stdout)으로 JSON 객체를 한 줄로 출력합니다 (공백 없이 압축 포맷 `separators=(',', ':')`).
```json
{
  "history": [
    {"op": "WRITE", "page_idx": 0, "status": "SUCCESS", "detail": "same-page zero deduplicated (0 bytes RAM)"},
    ...
  ],
  "summary": {
    "total_pages_stored": 5,
    "pages_in_ram": 2,
    "pages_in_backing_dev": 3,
    "same_pages": 1,
    "huge_pages": 0,
    "orig_data_size_bytes": 20480,
    "compr_data_size_bytes": 240,
    "mem_used_total_bytes": 4096,
    "memory_savings_bytes": 16384,
    "effective_ram_ratio": 0.5,
    "pages_compacted_total": 4,
    "pages_written_back_total": 4
  }
}
```

### 요약 필드 설명:
- `total_pages_stored`: 현재 ZRAM에 유효하게 저장되어 있는 총 페이지 수 (RAM + 보조 저장소).
- `pages_in_ram`: 물리 RAM에 보관 중인 페이지 수 (동일 패턴 페이지 포함).
- `pages_in_backing_dev`: 보조 저장소로 라이트백된 페이지 수.
- `same_pages`: 패턴 중복 제거로 RAM을 0바이트 소비하는 유효 페이지 수.
- `huge_pages`: 현재 RAM에 거대 페이지(`HUGE`)로 보관 중인 페이지 수.
- `orig_data_size_bytes`: 저장된 페이지들의 비압축 원본 크기 총합 ($total\_pages\_stored \times 4096$).
- `compr_data_size_bytes`: RAM 내 압축/거대 데이터의 순수 점유 크기 합계.
- `mem_used_total_bytes`: `zsmalloc` 풀이 실제 할당한 물리 RAM 바이트 총합 (단편화 포함).
- `memory_savings_bytes`: 원본 대비 물리 RAM 절감량 ($orig\_data\_size\_bytes - mem\_used\_total\_bytes$).
- `effective_ram_ratio`: 물리 RAM 효율 압축비 ($round(mem\_used\_total\_bytes / (pages\_in\_ram \times 4096), 4)$).
- `pages_compacted_total`: `COMPACT` 연산으로 회수된 누적 물리 페이지 수.
- `pages_written_back_total`: 보조 저장소로 라이트백된 누적 페이지 수.
