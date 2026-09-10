# 397: 리눅스 커널 메모리 관리 — Multi-Gen LRU(MGLRU) 세대별 에이징 및 워킹 세트 보호 회수 엔진

## 1. 개요 (Overview)

수십 년간 리눅스 커널의 페이지 회수 서브시스템은 1990년대 후반에 고안된 **2-리스트 LRU (Active List & Inactive List, `mm/vmscan.c`)** 에 기반해 왔습니다. 그러나 수십 기가바이트에서 수 테라바이트에 달하는 현대 대규모 클라우드 서버와 데이터 집약적 워크로드에서 2-리스트 LRU는 다음과 같은 치명적인 한계를 노출했습니다:
1. **조잡한 입도(Coarse Granularity)**: 활성(Active)과 비활성(Inactive) 단 2개의 상태만 존재하여 페이지의 정밀한 연령(Age)과 재접근 주기(Recency vs Frequency)를 구별할 수 없음.
2. **글로벌 락 병목 (`lru_lock`)**: 수많은 CPU 코어가 단일 LRU 리스트 락을 경합하여 확장성 저하 발생.
3. **대규모 파일 스트리밍에 의한 캐시 오염 (Cache Thrashing)**: 대용량 파일 복사나 순차 스캔 발생 시 비활성 리스트의 기존 워킹 세트가 순식간에 강제 퇴출되는 메모리 역전 현상.

이 문제를 해결하기 위해 구글의 자오 유(Yu Zhao) 엔지니어가 개발하여 리눅스 커널 6.1에 공식 머지된 **Multi-Gen LRU (MGLRU, `CONFIG_LRU_GEN`)** 는 단일/이중 큐 방식을 탈피하고 **다세대 세대별 링 버퍼(Generational Ring Buffer)** 아키텍처를 도입했습니다.

MGLRU는 가장 오래된 세대인 `min_seq`부터 가장 최근 생성된 세대인 `max_seq`까지의 여러 세대($	ext{max\_seq} - 	ext{min\_seq} + 1 \le 	ext{MAX\_NR\_GENS}$)를 유지하며, 정주기 에이징(Aging) 스텝을 통해 접근된 페이지를 최신 세대로 승격시키고, 세대 내부의 다중 티어(Tier 0~3) 보호 메커니즘을 통해 빈번히 사용되는 핫 페이지를 퇴출(Eviction)로부터 강력히 보호합니다.

본 문제에서는 리눅스 커널 MGLRU의 세대 인덱스 관리(`min_seq`, `max_seq`), 에이징 틱(Aging Tick) 기반 세대 승격, 다중 티어 보호/강등 상태 머신, 회수 예산(Byte Budget) 기반 `min_seq` 퇴출 시뮬레이션 엔진을 설계 및 구현합니다.

---

## 2. MGLRU 아키텍처 다이어그램

```
+========================================================================================+
|                             Multi-Gen LRU Ring Buffer                                  |
|                                                                                        |
|  Oldest / Coldest (Eviction Front)                     Youngest / Hottest (Alloc Front)|
|       [ Generation min_seq ]          ... ...               [ Generation max_seq ]     |
|   +-----------------------------+                       +----------------------------+ |
|   | Folio A (Tier 0, unref)     |                       | Folio X (Tier 0, new)      | |
|   | Folio B (Tier 1, unref)     |                       | Folio Y (Tier 2, promoted) | |
|   | Folio C (Tier 0, REFERENCED)|                       | Folio Z (Tier 1, promoted) | |
|   +-----------------------------+                       +----------------------------+ |
+========================================================================================+
                ||                                                      ^
                || (Eviction Step: try_evict_from_min_seq)              | (Aging Step: inc_max_seq)
                VV                                                      |
+------------------------------------+              +------------------------------------+
| 1. If page is REFERENCED:          |              | 1. Open new generation max_seq + 1 |
|    -> Clear ref & Promote to max_seq==============> 2. Scan all existing generations:  |
| 2. If page.tier > 0:               |              |    - If page.referenced:           |
|    -> Demote tier-- & Keep in gen  |              |      Promote to new max_seq!       |
| 3. If page.tier == 0 & unreferenced|              | 3. If (max_seq - min_seq + 1)      |
|    -> EVICT from memory!           |              |       > max_nr_gens:               |
| 4. When min_seq empty -> min_seq++ |              |    - Force evict oldest min_seq!   |
+------------------------------------+              +------------------------------------+
```

---

## 3. 핵심 수리 및 알고리즘 규칙

### 3.1 세대 및 티어 데이터 구조
- 각 페이지 폴리오(PageFolio)는 다음 속성을 보유합니다:
  - `gen`: 소속 세대 번호 (정수).
  - `tier`: 다중 티어 레벨 ($0 \le 	ext{tier} \le 3$, 빈도 기반).
  - `referenced`: 접근 플래그 (True/False).
  - `evicted`: 메모리 퇴출 여부.
- 세대 수 상한: $	ext{max\_seq} - 	ext{min\_seq} + 1 \le 	ext{max\_nr\_gens}$ (기본 4).

### 3.2 페이지 추가 및 접근 기록
- `ADD_PAGE`: 새로운 페이지는 항상 최신 세대인 $	ext{max\_seq}$에 진입합니다.
- `ACCESS`: 페이지 접근 시 `referenced = True`로 설정되며, `tier < 3`인 경우 `tier += 1`로 상승합니다.

### 3.3 에이징 스텝 (`AGING_TICK`)
1. 최신 세대 인덱스를 1 증가시킵니다: $	ext{new\_max} = 	ext{max\_seq} + 1$.
2. 기존 활성 세대($g \in [	ext{min\_seq}, 	ext{max\_seq}]$)의 모든 유효 페이지를 스캔합니다:
   - 만약 `page.referenced == True`이면:
     - `referenced = False`로 리셋.
     - 소속 세대를 $	ext{new\_max}$로 승격(Promote)시킵니다.
3. $	ext{max\_seq} \leftarrow 	ext{new\_max}$ 갱신.
4. 만약 세대 수 상한을 초과하면($	ext{max\_seq} - 	ext{min\_seq} + 1 > 	ext{max\_nr\_gens}$), $	ext{min\_seq}$ 세대의 잔여 페이지들을 강제 회수하여 $	ext{min\_seq}$를 전진시킵니다.

### 3.4 퇴출 스텝 (`EVICT`)
가장 오래된 세대 $	ext{min\_seq}$로부터 목표 바이트(`bytes`)만큼 회수할 때까지 다음 규칙을 적용합니다:
1. `page.referenced == True`:
   - 2차 기회(Second Chance) 원칙에 따라 퇴출하지 않고 `max_seq`로 즉시 승격시킵니다.
2. `page.tier > 0`:
   - 높은 접근 빈도를 가졌던 핫 페이지이므로 즉시 퇴출하지 않고 `tier -= 1`로 1단계 강등한 후 보존합니다.
3. `page.tier == 0` AND `page.referenced == False`:
   - 해당 페이지를 즉시 퇴출(`evicted = True`)하고 회수된 바이트 수를 누적합니다.
4. $	ext{min\_seq}$에 잔여 활성 페이지가 없으면 해당 세대를 닫고 $	ext{min\_seq} \leftarrow 	ext{min\_seq} + 1$로 전진시킵니다.

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
```json
{
  "config": {
    "max_nr_gens": 4
  },
  "operations": [
    {"action": "ADD_PAGE", "page_id": "P1", "tier": 0},
    {"action": "AGING_TICK"},
    {"action": "ACCESS", "page_id": "P1"},
    {"action": "AGING_TICK"},
    {"action": "EVICT", "bytes": 4096}
  ]
}
```

### 4.2 출력 형식 (Output Format)
```json
{
  "min_seq": 1,
  "max_seq": 2,
  "nr_active_gens": 2,
  "total_reclaimed_bytes": 0,
  "evicted_pages": [],
  "promoted_pages": ["P1"],
  "gen_distribution": {
    "2": ["P1"]
  },
  "pages": {
    "P1": {
      "page_id": "P1",
      "size_bytes": 4096,
      "gen": 2,
      "tier": 1,
      "referenced": false,
      "evicted": false
    }
  }
}
```
