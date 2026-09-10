# Problem #430: 리눅스 커널 메모리 관리: 페이지 캐시 섀도우 엔트리(Shadow Entries) & 리폴트 거리(Refault Distance) 기반 활성 워킹셋(Working Set) 복원 및 스래싱 방어 엔진

## 🌟 개요 (Executive Summary)
현대 리눅스 커널(Linux Kernel 3.14+ 및 6.x)의 메모리 관리 서브시스템(`mm/workingset.c`, `mm/filemap.c`)은 대규모 파일 I/O 및 데이터베이스 워크로드에서 성능의 핵심 축을 담당합니다. 전통적인 2계층 LRU(Active 및 Inactive LRU List) 모델은 순차적 대용량 파일 스캔이나 메모리 압박이 발생했을 때, 실제 빈번하게 재참조되어야 하는 **핵심 활성 워킹셋(Active Working Set)** 페이지들을 Inactive 리스트로 밀어내어 퇴출(Eviction)시키는 고질적인 결함을 안고 있었습니다.

퇴출된 페이지가 얼마 지나지 않아 다시 요청(Page Fault / Refault)될 때, 이를 단순히 일반 Inactive 리스트의 끝자락에 다시 삽입하게 되면 다음 번 메모리 회수(Reclaim) 사이클에서 또다시 즉각 퇴출당하는 치명적인 **페이지 캐시 스래싱(Cache Thrashing)**이 발생하며, 디스크 I/O 대기율이 100%로 치솟게 됩니다.

리눅스 커널은 이를 해결하기 위해 요하네스 바이너(Johannes Weiner)가 설계한 **섀도우 엔트리(Shadow Entries)**와 **리폴트 거리(Refault Distance)** 메커니즘을 도입했습니다:
1. 페이지가 XArray(기존 Radix Tree)에서 메모리 회수기에 의해 퇴출될 때, 슬롯을 비우는 대신 해당 시점의 단조 증가 퇴출 시퀀스(`eviction_counter`)와 cgroup ID를 인코딩한 소형 포인터인 **섀도우 엔트리(Shadow Entry)**를 기록합니다.
2. 이후 해당 페이지가 다시 적재(Refault)될 때, 커널은 섀도우 엔트리를 언팩하여 **리폴트 거리($\Delta_E = E_{\text{current}} - E_{\text{evict}}$)**를 산출합니다.
3. 산출된 거리가 현재의 **활성 파일 페이지 수($|\text{LRU}_{\text{active}}|$)** 이하일 경우, 이는 해당 페이지가 활성 워킹셋 크기 내에서 퇴출된 직후 재참조되었음을 수학적으로 증명하므로, Inactive 단계를 건너뛰고 **Active LRU로 즉각 복귀 승격(`SetPageActive`)**시킵니다.
4. 반대로 거리가 활성 리스트 크기를 초과하면 콜드(Cold) 데이터로 판단하여 Inactive 리스트로 배치합니다.
5. 유휴 섀도우 엔트리가 슬랩 메모리를 잠식하지 않도록 허용 마진(Slack Margin)을 초과한 노후 섀도우 엔트리를 정밀하게 정리(Pruning)하고, 워킹셋 재진입 비율을 감시하여 cgroup 메모리 증설 권고를 발행합니다.

본 문제에서는 리눅스 커널 `mm/workingset.c`의 내부 동작 원리를 완벽히 시뮬레이션하는 고성능 워킹셋 탐지 및 스래싱 방어 엔진을 구현합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
                       [ User / Process File I/O ]
                                    │
                                    ▼
                         [ ALLOC_PAGE Request ]
                                    │
                       (inode, offset) in XArray?
                        ┌───────────┴───────────┐
                        │                       │
                 [ SHADOW Entry ]        [ Empty / New ]
                        │                       │
             Calculate Refault Dist             ▼
           ΔE = E_curr - E_evict        [ FRESH_PAGE_INSERT ]
                        │               Insert to INACTIVE LRU
           ┌────────────┴────────────┐
           ▼                         ▼
   ΔE <= active_pages         ΔE > active_pages
   (Working Set Hit!)         (Cold Page Refault)
           │                         │
           ▼                         ▼
[ WORKINGSET_REFAULT_ACTIVATE ]  [ INACTIVE_REFAULT_INSERT ]
  Direct to ACTIVE LRU             Insert to INACTIVE LRU
  workingset_activations++         workingset_refaults++
                                             │
─────────────────────────────────────────────┼──────────────────────────────
                                             │
       [ ACCESS_PAGE ]                       │
              │                              │
     Page in ACTIVE? ──Yes──► [ ACTIVE_REFERENCED_HIT ] (Keep Active)
              │ No
     Page in INACTIVE?
              │
     entry.referenced == True?
         ┌────┴────┐
        Yes        No
         │         └─► [ INACTIVE_REFERENCED_MARKED ] (Set referenced=True)
         ▼
  [ SECOND_CHANCE_PROMOTED_ACTIVE ]
  (Promote to ACTIVE LRU, clear referenced)

────────────────────────────────────────────────────────────────────────────
       [ EVICT_PAGE (kswapd / direct reclaim) ]
              │
  Increment eviction_counter++
  Store SHADOW Entry with eviction_timestamp in XArray slot
  Remove page from LRU queue (ACTIVE or INACTIVE)
```

---

## 🔢 수학적 공식 및 판정 기준 (Mathematical Formulations)

### 1. 리폴트 거리 산출 (Refault Distance Formulation)
페이지 $p$가 퇴출될 당시의 퇴출 카운터를 $E_{\text{evict}}(p)$, 현재 시점의 전역 퇴출 카운터를 $E_{\text{current}}$라 할 때:
$$\Delta_E(p) = E_{\text{current}} - E_{\text{evict}}(p)$$

### 2. 활성 워킹셋 판정 (Working Set Criterion)
현재 시스템의 활성 파일 페이지 수를 $N_{\text{active}}$라 할 때:
$$\text{IsWorkingSet}(p) = \begin{cases} \text{True} & \text{if } \Delta_E(p) \le N_{\text{active}} \\ \text{False} & \text{if } \Delta_E(p) > N_{\text{active}} \end{cases}$$
- $\text{True}$ 판정 시: 즉각 Active LRU 큐로 직행 (`WORKINGSET_REFAULT_ACTIVATE`).
- $\text{False}$ 판정 시: Inactive LRU 큐로 삽입 (`INACTIVE_REFAULT_INSERT`).

### 3. 노후 섀도우 엔트리 정리 기준 (Shadow Pruning Threshold)
섀도우 엔트리가 소비하는 슬랩 메모리를 회수하기 위한 최대 허용 유예 한계는:
$$T_{\text{prune}} = N_{\text{active}} + N_{\text{inactive}} + M_{\text{slack}}$$
만약 $\Delta_E(\text{shadow}) > T_{\text{prune}}$인 경우, 해당 섀도우 엔트리는 XArray에서 영구 삭제(Prune)됩니다.

### 4. 스래싱 비율 및 권고 판정 (Thrashing Ratio & Mitigation)
$$\rho_{\text{thrash}} = \frac{\text{workingset\_activations}}{\max(1, E_{\text{total}})}$$
- $\rho_{\text{thrash}} \ge \Theta_{\text{thrash}}$: 스래싱 감지(`thrashing_detected = true`), 추천 조치 `EXPAND_CGROUP_MEMORY`.
- $\rho_{\text{thrash}} < \Theta_{\text{thrash}}$: 정상 상태(`thrashing_detected = false`), 조치 `STEADY_STATE_NO_ACTION`.

---

## 📥 입력 형식 (Input Specification)

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "max_memory_pages": 16,
    "thrashing_threshold": 0.5,
    "default_slack_margin": 5
  },
  "trace": [
    {"op": "ALLOC_PAGE", "page_id": "P1", "inode_id": 100, "offset": 0, "memcg_id": 1},
    {"op": "ACCESS_PAGE", "page_id": "P1"},
    {"op": "ACCESS_PAGE", "page_id": "P1"},
    {"op": "EVICT_PAGE", "page_id": "P1"},
    {"op": "ALLOC_PAGE", "page_id": "P1_new", "inode_id": 100, "offset": 0, "memcg_id": 1},
    {"op": "BALANCE_LRU", "target_inactive_ratio": 0.5},
    {"op": "SHADOW_PRUNE", "max_age_margin": 4},
    {"op": "EVALUATE_THRASHING"}
  ]
}
```

### 지원 명령어 (Supported Operations):
1. `ALLOC_PAGE`:
   - 파라미터: `page_id` (str), `inode_id` (int), `offset` (int), `memcg_id` (int, optional)
   - XArray 상에 기존 섀도우가 존재하면 리폴트 거리 계산 및 판정 (`WORKINGSET_REFAULT_ACTIVATE` or `INACTIVE_REFAULT_INSERT`).
   - 없으면 신규 할당 (`FRESH_PAGE_INSERT`).
2. `ACCESS_PAGE`:
   - 파라미터: `page_id` (str)
   - Active 페이지: `ACTIVE_REFERENCED_HIT`
   - Inactive 페이지: 첫 접근 시 `INACTIVE_REFERENCED_MARKED`, 재접근(Second Chance) 시 `SECOND_CHANCE_PROMOTED_ACTIVE`.
3. `EVICT_PAGE`:
   - 파라미터: `page_id` (str, optional). 생략 시 Inactive LRU의 tail, 없으면 Active LRU의 tail 선택.
   - 퇴출 시 `eviction_counter`를 1 증가시키고 해당 슬롯을 `SHADOW` 엔트리로 치환.
4. `BALANCE_LRU`:
   - 파라미터: `target_inactive_ratio` (float, 기본 0.5)
   - Inactive 크기가 목표치 미만이면 Active tail에서 Inactive head로 강등 demotion.
5. `SHADOW_PRUNE`:
   - 파라미터: `max_age_margin` (int, optional)
   - 허용 유효 거리를 초과한 섀도우 엔트리를 일괄 회수.
6. `EVALUATE_THRASHING`:
   - 워킹셋 복원 활성화 비율 계산 및 스래싱 여부 판단.

---

## 📤 출력 형식 (Output Specification)

표준 출력(stdout)으로 공백이 없는 콤팩트 JSON 문자열을 단일 행으로 출력합니다:
```json
{"events":[{"op":"ALLOC_PAGE","page_id":"P1","status":"FRESH_PAGE_INSERT","lru":"INACTIVE","refault_occurred":false,"refault_distance":null,"active_pages":0,"inactive_pages":1}],"summary":{"total_allocs":1,"total_evictions":0,"workingset_refaults":0,"workingset_activations":0,"shadow_pruned_count":0,"active_pages":0,"inactive_pages":1,"eviction_counter":0,"thrashing_events":0}}
```

---

## 💡 제약 조건 (Constraints)
- 모든 시뮬레이션 상태는 단일 스레드 결정론적(Deterministic)으로 동작해야 합니다.
- `eviction_counter`는 초기값 0에서 시작하며, 페이지가 성공적으로 퇴출될 때마다 정확히 1씩 단조 증가합니다.
- 부동소수점 스래싱 비율(`refault_activation_ratio`)은 소수점 4자리로 반올림(`round(..., 4)`)합니다.
- 복합 명령어 시퀀스는 최대 200개 연산으로 구성될 수 있습니다.
