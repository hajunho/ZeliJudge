# Linux Kernel Multi-Gen LRU (MGLRU) 세대별 노화 및 빈도(Tier) 승격 쓰레싱 완화 엔진

## 문제 설명

리눅스 커널 6.1에 정식 머지된 **Multi-Gen LRU (MGLRU, Multi-Generational Least Recently Used / `mm/vmscan.c`, `include/linux/mmzone.h`)**는 지난 수십 년간 사용되어 온 전통적인 2-List LRU(Active / Inactive LRU)의 근본적인 한계를 해결하기 위해 구글(Google)의 Yu Zhao 등에 의해 개발된 차세대 페이지 회수(Page Reclaim) 서브시스템입니다.

전통적인 2-List LRU는 다음과 같은 고질적인 시스템 성능 저하 문제를 안고 있었습니다:
1. **`lru_lock` 스핀락 병목**: 대규모 다중 코어 시스템에서 모든 메모리 할당/해제/회수가 단일 LRU 락을 두고 경합하여 심각한 CPU 오버헤드를 유발.
2. **스캔 저항성(Scan Resistance)의 취약성**: 대용량 백업, 데이터베이스 풀스캔 등의 대규모 1회성 순차 I/O가 유입될 때, 활성(Active) 리스트의 핫 워킹셋(Hot Working Set) 페이지들이 순식간에 비활성(Inactive) 리스트로 밀려나 디스크로 방출되는 **캐시 쓰레싱(Cache Thrashing)** 발생.
3. **거친 시간 및 빈도 해상도**: 최근성(Recency)과 접근 빈도(Frequency)를 단 2단계(Active/Inactive)로만 구분하여, 실제 워킹셋의 크기와 노화 속도를 세밀하게 추적하지 못함.

MGLRU는 이를 극복하기 위해 메모리 페이지들을 다중 세대(Multiple Generations)로 나누어 환형 링 버퍼(`generations[MAX_NR_GENS]`)로 관리하며, 세대 내에서도 접근 빈도에 따라 4단계 티어(`Tier 0 ~ Tier 3`)로 세분화합니다:

```
    [ MGLRU Ring Buffer Architecture & Tier Flow ]

   Youngest Generation (max_seq)                    Oldest Generation (min_seq)
  ┌─────────────────────────────┐                  ┌─────────────────────────────┐
  │ Generation: max_seq         │                  │ Generation: min_seq         │
  │                             │   AGING (Tick)   │                             │
  │ [Allocations & Promotions]  │ ───────────────> │ [Eviction Candidates Scan]  │
  │  ├─ Tier 3: Very Hot (3+)   │                  │  ├─ Tier 3 ──┐ (Promote to  │
  │  ├─ Tier 2: Hot (2)         │                  │  ├─ Tier 2 ──┤  max_seq)    │
  │  ├─ Tier 1: Warm (1)        │                  │  ├─ Tier 1 ──┘              │
  │  └─ Tier 0: Cold (0)        │                  │  └─ Tier 0 ─────────────────┼──> Evict!
  └─────────────────────────────┘                  └─────────────────────────────┘
                ▲                                                 │
                │        Promotion (Working Set Protection)       │
                └─────────────────────────────────────────────────┘
                               (Tier - 1, Clear Accessed)
```

본 과제에서는 Linux 커널 MGLRU의 세대 시퀀스(`max_seq`, `min_seq`), 환형 링 버퍼 제약, 페이지 테이블 워크(PTE Scan)를 통한 티어 승격, 최소 세대 회수 스캐너의 핫 워킹셋 보호 승격 및 쓰레싱 감지 텔레메트리를 완벽하게 시뮬레이션하는 **Linux Kernel MGLRU Generation Aging & Reclaim Engine**을 구현합니다.

---

## 핵심 엔진 아키텍처 및 규칙

### 1. 세대 시퀀스 및 환형 링 버퍼 제약
1. 세대는 64비트 단조 증가 정수 시퀀스 `max_seq`(최신 세대)와 `min_seq`(최소 세대)로 관리됩니다.
2. 환형 링 버퍼 크기는 `max_nr_gens` (기본값: 4)입니다.
3. 세대 간격 제약:
   $$\text{spread} = \max\_seq - \min\_seq + 1 \le \text{max\_nr\_gens}$$
4. `AGING` 연산 수행 시:
   - `max_seq += step`
   - 만약 `(max_seq - min_seq + 1) > max_nr_gens` 이면, `min_seq = max_seq - max_nr_gens + 1` 로 전진하여 링 버퍼 제약을 강제합니다.

### 2. 페이지 티어(Tier) 및 접근 비트
1. 각 페이지는 4단계 티어(`tier \in \{0, 1, 2, 3\}`)를 가집니다:
   - `Tier 0`: 0회 접근 (Cold)
   - `Tier 1`: 1회 접근 (Warm)
   - `Tier 2`: 2회 접근 (Hot)
   - `Tier 3`: 3회 이상 접근 (Very Hot)
2. `ACCESS_PAGE`: 대상 페이지의 `accessed = True`로 설정하고 `tier = min(3, tier + count)`로 갱신합니다.
3. `PAGE_TABLE_SCAN`: 페이지 테이블 워커가 PTE를 스캔합니다.
   - `accessed == True`인 모든 페이지에 대해 `tier = min(3, tier + 1)`로 승격하고, `accessed = False`로 리셋합니다.

### 3. 페이지 회수(RECLAIM) 및 핫 워킹셋 승격
`RECLAIM` 연산은 가장 오래된 세대(`min_seq`)에서 목표 수량(`nr_to_reclaim`)만큼의 페이지를 회수합니다:
1. `min_seq`에 속한 페이지 중 지정된 `type`("all", "file", "anon")의 후보들을 선정합니다.
2. 후보들을 우선순위 `(tier, accessed, page_id)` 오름차순으로 정렬하여 콜드 페이지(`tier == 0, accessed == False`)부터 먼저 탐색합니다.
3. 각 후보 페이지에 대해:
   - **승격 대상 (`tier > 0` 또는 `accessed == True`)**:
     - `min_seq < max_seq`인 경우:
       - 해당 페이지는 회수되지 않고 최신 세대(`max_seq`)로 **승격(Promote)**됩니다.
       - `tier = max(0, tier - 1)`, `accessed = False`로 갱신됩니다.
       - `promoted_count += 1`
     - `min_seq == max_seq`인 경우 (더 이상 젊은 세대가 없음):
       - 제자리 노화: `accessed = False` 처리하거나 `tier -= 1` 감등. 만약 `tier == 0`이고 `accessed == False`가 되면 회수됩니다.
   - **회수 대상 (`tier == 0` 및 `accessed == False`)**:
     - 페이지를 메모리에서 제거(Evict)하고 기록합니다.
     - `file` 페이지이고 `dirty == False`: `evicted_clean_file += 1` (무비용 즉시 해제)
     - `file` 페이지이고 `dirty == True`: `evicted_dirty_file += 1` (디스크 라이트백 후 해제)
     - `anon` 페이지: `evicted_anon_swap += 1` (스왑 디바이스 아웃)
4. `min_seq`에 남은 페이지가 없고 `min_seq < max_seq`이면 `min_seq`를 1씩 증가시켜 다음 세대로 이동합니다.

### 4. 쓰레싱(Thrashing) 및 워킹셋 텔레메트리
1. **워킹셋 크기(WSS, Working Set Size)**:
   - 최신 세대들에 속한 페이지(`gen > min_seq`) 전체 + `min_seq`에 남아있지만 핫한 페이지(`tier > 0`)의 총합.
2. **리폴트(Refault) 및 쓰레싱 감지**:
   - 이전에 회수(Evict)된 적이 있는 `page_id`가 다시 `ALLOC_PAGE`되면 `refault_count += 1`.
   - `refault_ratio = refault_count / max(1, total_evictions)`.
   - `refault_count >= 2` 이고 `refault_ratio >= 0.25` 이면 `thrashing_detected = True`.

---

## 입력 형식

표준 입력(`stdin`)으로 JSON 객체가 주어집니다:

```json
{
  "max_nr_gens": 4,
  "initial_pages": [
    {"page_id": "file_1", "type": "file", "dirty": false, "gen": 0, "tier": 0},
    {"page_id": "anon_1", "type": "anon", "dirty": true, "gen": 0, "tier": 2}
  ],
  "operations": [
    {"op": "ACCESS_PAGE", "page_id": "file_1", "count": 1},
    {"op": "PAGE_TABLE_SCAN"},
    {"op": "ALLOC_PAGE", "page_id": "file_2", "type": "file", "dirty": false, "tier": 0},
    {"op": "AGING", "step": 1},
    {"op": "RECLAIM", "nr_to_reclaim": 1, "type": "all"}
  ]
}
```

---

## 출력 형식

표준 출력(`stdout`)으로 JSON 객체를 공백 없이 출력합니다:

```json
{
  "max_seq": 1,
  "min_seq": 0,
  "active_page_count": 2,
  "working_set_size": 2,
  "generation_distribution": {"0": 1, "1": 1},
  "tier_distribution": {"tier_0": 0, "tier_1": 1, "tier_2": 1, "tier_3": 0},
  "stats": {
    "allocated_count": 1,
    "promoted_count": 0,
    "evicted_clean_file": 1,
    "evicted_dirty_file": 0,
    "evicted_anon_swap": 0,
    "refault_count": 0
  },
  "thrashing_analysis": {
    "total_evictions": 1,
    "refault_count": 0,
    "refault_ratio": 0.0,
    "thrashing_detected": false
  },
  "op_log": [
    ...
  ]
}
```
