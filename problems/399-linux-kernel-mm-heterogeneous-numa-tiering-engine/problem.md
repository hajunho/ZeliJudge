# 399: 리눅스 커널 메모리 관리 — 이종 메모리 계층화(Heterogeneous Memory Tiering) AutoNUMA 힌팅 폴트 및 핫 페이지 승격 엔진

## 1. 개요 (Overview)

인공지능(AI) 대형 모델 학습 및 빅데이터 분산 컴퓨팅의 급격한 발전으로 인해 서버 하드웨어 아키텍처는 단일 DRAM 구조에서 **이종 메모리 계층화(Heterogeneous Memory Tiering)** 구조로 급변하고 있습니다:
- **Fast Tier 0 (고속 고대역폭 메모리)**: HBM (High Bandwidth Memory), CPU 로컬 NUMA 노드 소켓의 최신 DDR5 메모리 (대역폭 800+ GB/s, 지연시간 ~60ns).
- **Slow Tier 1 (원거리 확장 메모리)**: CXL.mem (Compute Express Link) 연결 확장 메모리 풀, PMEM (Persistent Memory), 원격 NUMA 노드 (대역폭 100~200 GB/s, 지연시간 ~180ns).

속도 차이가 3배~5배에 달하는 이종 메모리 환경에서, 어떤 페이지를 고가의 Fast Tier에 두고 어떤 페이지를 저렴한 Slow Tier에 배치할 것인가가 시스템 전체 처리량을 결정합니다.

리눅스 커널의 **AutoNUMA 및 메모리 계층화 서브시스템 (`mm/migrate.c`, `CONFIG_NUMA_BALANCING`)** 은 프로세스의 메모리 페이지를 인위적으로 언맵(Unmap / `_PAGE_PROTNONE`)하여, CPU가 해당 페이지에 접근할 때 발생하는 미세한 하드웨어 소프트웨어 트랩인 **NUMA 힌팅 폴트(NUMA Hinting Page Fault, `do_numa_page()`)** 를 계측합니다. 이를 통해 Slow Tier 1에 머무르고 있는 핫 페이지(Hot Page)를 실시간으로 탐지하여 Fast Tier 0으로 승격(**Promotion, `migrate_pages`**)시키고, Fast Tier가 포화될 경우 콜드 페이지를 Slow Tier로 강등(**Demotion**)시키는 자율 계층화 파이프라인을 운영합니다.

본 문제에서는 NUMA 힌팅 폴트 계측, 핫니스(Hotness) 임계치 평가, Fast Tier 포화 시 콜드 페이지 축출/강등(Demotion), 인터커넥트(CXL/UPI) 대역폭 포화 방지를 위한 마이그레이션 쓰로틀링(Throttling) 엔진을 설계 및 구현합니다.

---

## 2. 메모리 계층화 아키텍처 다이어그램

```
+========================================================================================+
|                     Heterogeneous Compute Node (CPU / NUMA Architecture)               |
|                                                                                        |
|  +----------------------------------------------------------------------------------+  |
|  | Fast Tier 0 (HBM / Local DDR5: ~60ns, 800GB/s)   [Capacity: fast_capacity_pages] |  |
|  |  Active Working Set: P_HOT1, P_HOT2, ...                                         |  |
|  +----------------------------------------------------------------------------------+  |
|               ^                                                   |                    |
|               | (Promotion: migrate_pages)                        | (Demotion: Cold)   |
|               | numa_hinting_faults >= hot_threshold              | Tier 0 Full        |
|               |                                                   v                    |
|  +----------------------------------------------------------------------------------+  |
|  | Slow Tier 1 (CXL.mem / Far Node: ~180ns, 150GB/s)[Capacity: slow_capacity_pages] |  |
|  |  Cold / Background Data: P_COLD1, P_COLD2, ...                                   |  |
|  +----------------------------------------------------------------------------------+  |
+========================================================================================+
                                            ^
                                            |
                         [ NUMA Hinting Fault Trapping ]
                         - Page Table unmapped with PROT_NONE
                         - CPU Read/Write -> Minor Page Fault (do_numa_page)
                         - Increment page.numa_hinting_faults counter
```

---

## 3. 핵심 수리 및 알고리즘 규칙

### 3.1 힌팅 폴트 및 핫니스 판정
- `ACCESS` 이벤트 시:
  - `is_hinting_fault == True`이면 `page.numa_hinting_faults`를 1 증가시킵니다.
  - 모든 접근 시 `page.access_count`를 1 증가시키고 `last_access_tick`을 갱신합니다.
- 승격 후보(Promotion Candidates):
  $$	ext{page} \in 	ext{Tier 1} \quad 	ext{and} \quad 	ext{page.numa\_hinting\_faults} \ge 	ext{hot\_threshold\_faults}$$

### 3.2 밸런싱 및 승격/강등 규칙 (`BALANCE`)
1. **후보 정렬**:
   Slow Tier 1의 승격 후보들을 `(numa_hinting_faults DESC, access_count DESC, page_id DESC)` 순으로 정렬합니다.
2. **마이그레이션 쿼터 제한**:
   한 번의 밸런싱 주기 동안 승격 가능한 최대 페이지 수는 `max_migrations_per_tick`으로 엄격히 제한됩니다. 초과되는 후보는 `throttled_migrations` 카운터를 증가시킵니다.
3. **Fast Tier 0 포화 시 강등(Demotion)**:
   - Fast Tier 0에 빈 공간이 없으면(`free_pages <= 0`):
     Tier 0에서 가장 차가운 페이지 $T_0^{	ext{cold}}$를 탐색합니다 (최소 `numa_hinting_faults`, 최소 `access_count`, 가장 오래된 `last_access_tick`).
     - 승격 대상 페이지가 $T_0^{	ext{cold}}$보다 명백히 핫한 경우에만 $T_0^{	ext{cold}}$를 Tier 1로 강등(Demote)합니다.
4. **승격 실행**:
   후보 페이지를 Tier 0으로 이동시키고 `numa_hinting_faults`를 0으로 리셋합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
```json
{
  "config": {
    "fast_capacity_pages": 2,
    "slow_capacity_pages": 10,
    "hot_threshold_faults": 2,
    "max_migrations_per_tick": 1
  },
  "operations": [
    {"action": "ALLOC", "page_id": "P_FAST1", "preferred_tier": 0},
    {"action": "ALLOC", "page_id": "P_SLOW1", "preferred_tier": 1},
    {"action": "ACCESS", "page_id": "P_SLOW1", "is_hinting_fault": true},
    {"action": "ACCESS", "page_id": "P_SLOW1", "is_hinting_fault": true},
    {"action": "BALANCE"}
  ]
}
```

### 4.2 출력 형식 (Output Format)
```json
{
  "fast_tier_occupancy": "2/2",
  "slow_tier_occupancy": "0/10",
  "stats": {
    "numa_hinting_faults": 2,
    "promotions_to_fast": 1,
    "demotions_to_slow": 0,
    "throttled_migrations": 0,
    "total_accesses": 2
  },
  "fast_tier_pages": ["P_FAST1", "P_SLOW1"],
  "slow_tier_pages": [],
  "migration_log": [
    {
      "tick": 3,
      "action": "PROMOTE",
      "page_id": "P_SLOW1",
      "from_tier": 1,
      "to_tier": 0
    }
  ]
}
```
