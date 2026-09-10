# 문제 422: 리눅스 커널 메모리 관리 서브시스템: CXL.mem 이종 메모리 티어링(Memory Tiering) 및 Cold Page 강등·Hot Page 승격 엔진

## 1. 개요 (Overview)

데이터 센터 및 고성능 컴퓨팅(HPC) 환경에서 메인 메모리 대역폭과 용량의 수요는 기하급수적으로 폭증하고 있습니다. 그러나 전통적인 CPU 다이(Die)의 메모리 컨트롤러 채널 수 증가는 물리적 패키징 및 핀(Pin) 제약으로 인해 한계에 직면했습니다. 이를 극복하기 위해 도입된 차세대 개방형 표준 인터커넥트가 바로 **CXL(Compute Express Link)**입니다. CXL은 PCIe 물리 계층 위에서 초저지연 캐시 일관성(Cache Coherency) 및 메모리 트랜잭션을 제공하며, 특히 **CXL Type 3 장치(CXL.mem)**를 통해 호스트 프로세서에 확장 메모리 풀을 제공합니다.

리눅스 커널은 커널 5.18 및 6.x 시리즈에 걸쳐 **메모리 계층화 서브시스템(`mm/memory-tiers.c`)**과 페이지 회수(`mm/vmscan.c`), 그리고 커널 NUMA 밸런싱(`CONFIG_NUMA_BALANCING`)을 대대적으로 개편하였습니다. 이를 통해 고속 로컬 DDR5/HBM 메모리는 **최상위 티어(Top-Tier, Tier 0)**로 설정하고, 상대적으로 지연 시간이 길지만 대용량이자 저전력인 CXL 확장 메모리는 **하위 티어(Slow-Tier, Tier 1)**로 관리합니다.

본 과제에서는 리눅스 커널의 CXL 이종 메모리 티어링 엔진을 모델링합니다. DDR5 메모리 풀의 압박(High Watermark 도달) 시 콜드 페이지(Cold Page)를 디스크 스왑(Swap-out) 대신 CXL 메모리로 실시간 강등(Demotion)하고, CXL 티어에 상주하는 페이지 중 접근 빈도가 급증한 핫 페이지(Hot Page)를 인터럽트/힌팅 폴트(NUMA Hinting Fault)를 통해 상위 티어로 자동 승격(Promotion)하는 시뮬레이터를 구현합니다.

---

## 2. 시스템 아키텍처 및 하드웨어 토폴로지 (System Architecture)

```
+-------------------------------------------------------------------------+
|                              Host CPU Core                              |
|   +-----------------------------------------------------------------+   |
|   |                        MMU / TLB Engine                         |   |
|   |   (PROT_NONE NUMA Hinting Fault Detection: mm/memory-tiers.c)   |   |
|   +-----------------------------------------------------------------+   |
+------------------------------------+------------------------------------+
                                     |
                +--------------------+--------------------+
                |                                         |
     [Local DDR5 Memory Bus]                    [PCIe Gen5 / CXL Bridge]
                |                                         |
+---------------+---------------+         +---------------+---------------+
|     Tier 0: Top-Tier RAM      |         |     Tier 1: Slow-Tier CXL     |
|   (Fast, Low Latency ~60ns)   |         |  (CXL.mem Type 3, ~150-200ns) |
|   Capacity: TopTierCap            |         |  Capacity: SlowTierCap        |
|                               |         |                               |
|   [Active / Pinned / Clean]   |         |   [Demoted Cold Pool]         |
|   - mlock / DMA-pinned pages  |         |   - AutoNUMA scan target      |
+---------------+---------------+         +---------------+---------------+
                |                                         ^
                |  Demote (kswapd / alloc pressure)       |
                +-----------------------------------------+
                |
                v  Promote (NUMA Hinting Fault > Threshold)
                +-----------------------------------------+
```

---

## 3. 세부 동작 명세 (Operational Specifications)

엔진은 구성 매개변수(`config`)와 시간 순서대로 발생하는 이벤트 트레이스(`trace`)를 입력받아 처리합니다.

### 3.1 구성 매개변수 (`config`)
- `top_tier_capacity`: Tier 0(고속 DDR5)에 보관 가능한 최대 페이지 수 ($N_0$).
- `slow_tier_capacity`: Tier 1(CXL.mem)에 보관 가능한 최대 페이지 수 ($N_1$).
- `high_watermark`: Tier 0의 메모리 압박 임계 비율 (부동소수점, 예: 0.8).
- `low_watermark`: Tier 0의 메모리 회수 목표 임계 비율 (부동소수점, 예: 0.5).
- `promotion_threshold`: Tier 1에 위치한 페이지가 Tier 0으로 승격되기 위해 필요한 최소 누적 접근 횟수 ($K_{promo}$).

### 3.2 페이지 상태 (Page State)
각 페이지는 다음 속성을 유지합니다:
- `page_id`: 페이지 고유 식별자 문자열.
- `tier`: 현재 상주 중인 티어 (`0` = Top-Tier DDR5, `1` = Slow-Tier CXL).
- `access_count`: 누적 접근 횟수 (초기값 `0`).
- `last_access_time`: 마지막으로 접근된 시각 ($t$, 초기 할당 시 할당 시각).
- `is_pinned`: 고정 여부 (`True`/`False`). 핀 고정된 페이지(커널 버퍼, DMA, `mlock`)는 Tier 0에서 절대로 강등(Demotion)될 수 없습니다.

### 3.3 이벤트 처리 규칙

1. **`ALLOC_PAGE` (`time`, `page_id`, `is_pinned` [기본 False])**:
   - 신규 페이지를 기본적으로 **Tier 0**에 할당을 시도합니다.
   - 현재 Tier 0의 사용 페이지 수가 `top_tier_capacity`에 도달한 경우:
     - Tier 0의 콜드 페이지 1개를 Tier 1으로 강등(`_demote_coldest_page`)하여 공간을 확보합니다.
     - 만약 Tier 0에 핀 고정되지 않은 페이지가 없거나, Tier 1이 가득 차서 강등에 실패한 경우:
       - Tier 1에 남은 공간이 있다면 Tier 1에 직접 할당합니다 (`target_tier = 1`).
       - Tier 1마저 가득 찼다면 할당이 실패하며, `event_logs`에 `ALLOC_FAILED_ENOMEM`을 기록하고 반환합니다.
   - 할당 성공 시 `total_allocations`를 1 증가시키고, `event_logs`에 `ALLOC_PAGE` 이벤트를 기록합니다.

2. **콜드 페이지 선정 및 강등 알고리즘 (`_demote_coldest_page`)**:
   - Tier 1의 현재 페이지 수가 `slow_tier_capacity` 이상이면 강등 불가 (`False` 반환).
   - Tier 0의 페이지 중 `is_pinned == False`인 후보군을 추출합니다. 후보군이 없으면 강등 불가 (`False` 반환).
   - 후보군 중 **콜드 페이지**를 다음 우선순위로 선정합니다:
     1. 누적 접근 횟수(`access_count`)가 가장 적은 페이지 (오름차순).
     2. 접근 횟수가 동일한 경우, 마지막 접근 시각(`last_access_time`)이 가장 오래된 페이지 (오름차순 LRU).
   - 선택된 페이지의 `tier`를 `1`로 갱신하고, `pages_demoted`와 `swap_to_disk_avoided`를 1 증가시킵니다.
   - `tier_logs`에 액션 `DEMOTE` 로그를 기록합니다.

3. **`ACCESS_PAGE` (`time`, `page_id`)**:
   - `page_id`가 존재하지 않으면 무시합니다.
   - `total_accesses`를 1 증가시키고, 해당 페이지의 `access_count`를 1 증가시키며, `last_access_time`을 현재 시각으로 갱신합니다.
   - 페이지가 현재 **Tier 1**에 위치하고, 갱신된 `access_count >= promotion_threshold`인 경우 **승격(Promotion)**을 시도합니다:
     - Tier 0이 가득 찬 상태라면, Tier 0의 가장 차가운 페이지 1개를 Tier 1으로 강등시켜 공간을 만듭니다. (강등에 실패하면 승격은 중단됩니다).
     - 승격 대상 페이지의 `tier`를 `0`으로 변경하고 `pages_promoted`를 1 증가시킵니다.
     - `tier_logs`에 액션 `PROMOTE` 로그를 기록합니다.

4. **`MEMORY_PRESSURE_RECLAIM` (`time`)**:
   - 커널 메모리 회수 쓰레드(`kswapd`)의 동작을 모사합니다.
   - Tier 0의 목표 페이지 수는 $\lfloor \text{top\_tier\_capacity} \times \text{low\_watermark} \rfloor$ 입니다.
   - Tier 0의 현재 페이지 수가 목표치 이하가 될 때까지 반복적으로 `_demote_coldest_page`를 호출하여 강등합니다. 더 이상 강등할 수 없으면 루프를 종료합니다.

5. **`FREE_PAGE` (`time`, `page_id`)**:
   - 페이지 테이블에서 해당 페이지를 즉시 해제 및 삭제합니다.
   - `event_logs`에 `FREE_PAGE` 이벤트를 기록합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 입력 형식 (Standard Input, JSON)
```json
{
  "config": {
    "top_tier_capacity": 4,
    "slow_tier_capacity": 8,
    "high_watermark": 0.75,
    "low_watermark": 0.5,
    "promotion_threshold": 3
  },
  "trace": [
    {"time": 10, "type": "ALLOC_PAGE", "page_id": "pg_01"},
    {"time": 20, "type": "ALLOC_PAGE", "page_id": "pg_02"},
    {"time": 30, "type": "ALLOC_PAGE", "page_id": "pg_03"},
    {"time": 40, "type": "ALLOC_PAGE", "page_id": "pg_04"},
    {"time": 50, "type": "ACCESS_PAGE", "page_id": "pg_01"},
    {"time": 60, "type": "ACCESS_PAGE", "page_id": "pg_02"},
    {"time": 70, "type": "ALLOC_PAGE", "page_id": "pg_05"}
  ]
}
```

### 출력 형식 (Standard Output, Compact JSON)
공백 없는 단일 라인 JSON 문자열(`separators=(',', ':')`)로 출력합니다:
```json
{"summary":{"total_allocations":5,"total_accesses":2,"pages_demoted":1,"pages_promoted":0,"swap_to_disk_avoided":1,"tier0_usage":4,"tier1_usage":1},"tier_logs":[{"time":70,"action":"DEMOTE","page_id":"pg_03","from_tier":0,"to_tier":1,"reason":"TOP_TIER_PRESSURE"}],"event_logs":[{"time":10,"event":"ALLOC_PAGE","page_id":"pg_01","tier":0,"is_pinned":false},{"time":20,"event":"ALLOC_PAGE","page_id":"pg_02","tier":0,"is_pinned":false},{"time":30,"event":"ALLOC_PAGE","page_id":"pg_03","tier":0,"is_pinned":false},{"time":40,"event":"ALLOC_PAGE","page_id":"pg_04","tier":0,"is_pinned":false},{"time":70,"event":"ALLOC_PAGE","page_id":"pg_05","tier":0,"is_pinned":false}]}
```
