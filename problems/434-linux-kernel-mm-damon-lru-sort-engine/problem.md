# Problem #434: 리눅스 커널 가상 메모리: mm/damon/lru_sort.c 선제적 LRU 정렬(Proactive LRU Sort) 및 핫/콜드 영역 승격·강등과 스캔 지연 방어 엔진

## 🌟 개요 (Executive Summary)
대규모 메모리를 사용하는 클라우드 데이터베이스(Redis, PostgreSQL, In-Memory Caches) 환경에서 전통적인 리눅스 커널 메모리 회수(`kswapd` 및 직접 회수 `direct reclaim`)는 **수동적(Reactive)** 방식으로 동작합니다. 즉, 여유 메모리가 임계 수위(Watermark) 이하로 떨어졌을 때 비로소 활성(Active) 및 비활성(Inactive) LRU 리스트의 수천만 개 페이지를 순회하며 페이지 테이블 엔트리(PTE)의 Accessed 비트를 스캔하고 강등/퇴출을 결정합니다.

이러한 사후 수동적 스캔은 다음과 같은 중대한 시스템 병목을 초래합니다:
1. **P99 할당 지연 스파이크 (Allocation Latency Spike)**: 애플리케이션 스레드가 `malloc`/페이지 폴트를 수행하는 도중 직접 회수기(`do_try_to_free_pages`)에 갇혀 수백 밀리초 동안 락 경합과 페이지 테이블 워크를 기다려야 합니다.
2. **워킹셋 오염(Working Set Eviction)**: 메모리 압박 순간에 시간에 쫓긴 회수기가 미처 정밀하게 분류되지 못한 활성 페이지를 무작위로 Inactive 리스트로 밀어내어 캐시 스래싱을 유발합니다.

리눅스 5.18+ 커널에 도입된 **`mm/damon/lru_sort.c` (`CONFIG_DAMON_LRU_SORT`)**는 데이터 접근 모니터(DAMON)를 기반으로 **선제적(Proactive) LRU 정렬**을 수행합니다:
- **접근 빈도(Access Frequency) 기반 핫 영역 선제 승격**:
  - 접근 카운트가 임계값($A \ge \text{hot\_thres}$) 이상인 메모리 영역을 감지하면, 회수기가 개입하기 전에 백그라운드에서 즉각 `mark_page_accessed()`를 호출하여 **Active LRU 리스트의 최상단(Head)**으로 선제 승격시킵니다.
- **체류 기간(Age) 기반 콜드 영역 선제 강등**:
  - 접근이 0회인 채로 일정 집계 주기($Age \ge \text{cold\_min\_age}$) 이상 방치된 유휴 메모리 영역을 즉각 `deactivate_page()`를 통해 **Inactive LRU 리스트의 최하단(Tail)**으로 미리 강등시킵니다.
- **CPU 쿼터 제한 (`size_quota_pages`)**: 선제적 정렬 작업이 시스템 CPU를 1% 이상 잠식하지 않도록 1회 정렬 주기당 처리할 수 있는 최대 페이지 수를 엄격히 제한합니다.
- **제로 지연 패스트패스 회수 (Fastpath Reclaim)**: 이후 급격한 메모리 압박이 발생했을 때, `kswapd`는 Active 리스트를 뒤질 필요 없이 Inactive 리스트 최하단에 미리 정렬되어 대기 중인 콜드 페이지만 즉각 방출(Evict)하여 P99 지연시간을 95% 이상 단축합니다.

본 문제에서는 리눅스 커널 `mm/damon/lru_sort.c`의 선제적 핫/콜드 영역 탐지, 쿼터 기반 정렬, 그리고 패스트패스 메모리 회수 파이프라인을 시뮬레이션합니다.

---

## 🏗️ 아키텍처 및 시스템 흐름도 (System Architecture)

```
              [ Memory Access Sampling: DAMON Core ]
                                 │
                      (PTE Accessed Bit Check)
                                 │
                                 ▼
                     [ AGGREGATE_INTERVAL ]
         For each region:
           if access_count == 0: age++
           else: age = 0
                                 │
                                 ▼
                      [ APPLY_LRU_SORT ]
              (quota_remaining = size_quota_pages)
                                 │
       ┌─────────────────────────┴─────────────────────────┐
       ▼                                                   ▼
[ Check Hot Condition ]                             [ Check Cold Condition ]
access_count >= hot_thres &&                        access_count == 0 &&
current_lru != "ACTIVE"                             age >= cold_min_age &&
       │                                            current_lru != "INACTIVE"
       ├─ Quota OK? ──Yes──► [ PROACTIVELY_ACTIVATED ]     │
       │                     current_lru = "ACTIVE"        ├─ Quota OK? ──Yes──► [ PROACTIVELY_DEACTIVATED ]
       │                     hot_promotions++              │                     current_lru = "INACTIVE"
       └─ No ──► [ HOT_THROTTLED ]                         │                     cold_demotions++
                                                           └─ No ──► [ COLD_THROTTLED ]
                                 │
─────────────────────────────────┼─────────────────────────────────────────────
                                 │
                   [ Sudden Memory Pressure: RECLAIM_PAGES ]
                                 │
                     Target: nr_to_reclaim pages
                                 │
                                 ▼
           ┌──────────────────────────────────────────────┐
           │ Fastpath: Drain pre-sorted INACTIVE regions  │ ◄── Zero Active Scan Overhead!
           │           fastpath_reclaim_hits++            │
           └─────────────────────┬────────────────────────┘
                                 │
                     Still need more pages?
                      ┌──────────┴──────────┐
                     No                    Yes (Slowpath Fallback)
                      │                     │
                      ▼                     ▼
              [ RECLAIM_DONE ]      [ Reclaim from ACTIVE regions ]
```

---

## 🔢 수학적 공식 및 판정 기준 (Mathematical Formulations)

### 1. 핫 영역 선제 승격 판정 (Hot Promotion Condition)
메모리 영역 $R$의 샘플링 접근 횟수를 $A(R)$, 핫 임계치를 $\Theta_{\text{hot}}$이라 할 때:
$$\text{IsHot}(R) = (A(R) \ge \Theta_{\text{hot}}) \land (\text{LRU}(R) \neq \text{"ACTIVE"})$$

### 2. 콜드 영역 선제 강등 판정 (Cold Demotion Condition)
메모리 영역 $R$의 비활성 체류 주기(Age)를 $\text{Age}(R)$, 콜드 최소 연령을 $\Theta_{\text{cold\_age}}$라 할 때:
$$\text{IsCold}(R) = (A(R) = 0) \land (\text{Age}(R) \ge \Theta_{\text{cold\_age}}) \land (\text{LRU}(R) \neq \text{"INACTIVE"})$$

### 3. 정렬 쿼터 제약 (Size Quota Bounding)
단일 주기에서 처리되는 승격/강등 총 페이지 수 $N_{\text{sorted}}$는 설정된 할당량 $Q_{\text{pages}}$를 초과할 수 없습니다:
$$N_{\text{sorted}} = \sum_{R \in \text{Promoted}} |R| + \sum_{R \in \text{Demoted}} |R| \le Q_{\text{pages}}$$
남은 쿼터가 부족한 영역은 정렬 대상에서 제외되고 `THROTTLED_BY_QUOTA` 이벤트를 기록합니다.

---

## 📥 입력 형식 (Input Specification)

표준 입력(stdin)으로 단일 JSON 객체가 전달됩니다:
```json
{
  "config": {
    "hot_thres": 5,
    "cold_min_age": 3,
    "size_quota_pages": 50,
    "initial_regions": [
      {"region_id": "R1", "start_addr": 4096, "end_addr": 8192, "nr_pages": 20, "initial_lru": "INACTIVE"},
      {"region_id": "R2", "start_addr": 8192, "end_addr": 12288, "nr_pages": 20, "initial_lru": "ACTIVE"}
    ]
  },
  "trace": [
    {"op": "SAMPLE_ACCESS", "samples": {"R1": 10}},
    {"op": "AGGREGATE_INTERVAL"},
    {"op": "AGGREGATE_INTERVAL"},
    {"op": "AGGREGATE_INTERVAL"},
    {"op": "APPLY_LRU_SORT"},
    {"op": "RECLAIM_PAGES", "nr_to_reclaim": 20},
    {"op": "GET_STATISTICS"}
  ]
}
```

### 지원 명령어 (Supported Operations):
1. `SAMPLE_ACCESS`:
   - 파라미터: `samples` (`region_id` $\to$ 접근 횟수 딕셔너리)
   - 각 영역의 접근 카운터를 누적합니다.
2. `AGGREGATE_INTERVAL`:
   - 0회 접근 영역의 `age`를 1 증가시키고, 접근이 발생한 영역의 `age`를 0으로 리셋합니다.
3. `APPLY_LRU_SORT`:
   - 핫 영역 선제 승격 및 콜드 영역 선제 강등을 쿼터 내에서 수행합니다.
4. `RECLAIM_PAGES`:
   - 파라미터: `nr_to_reclaim` (int)
   - 사전 정렬된 INACTIVE 영역에서 우선 회수(Fastpath)하고, 부족 시 ACTIVE에서 회수합니다.
5. `GET_STATISTICS`:
   - 현재 활성/비활성 페이지 수, 누적 승격/강등 횟수, 쿼터 제한 횟수, 패스트패스 히트 수를 반환합니다.

---

## 📤 출력 형식 (Output Specification)

표준 출력(stdout)으로 공백이 없는 콤팩트 JSON 문자열을 단일 행으로 출력합니다:
```json
{"events":[{"op":"SAMPLE_ACCESS","status":"SAMPLES_RECORDED","sampled_regions":1}],"summary":{"hot_promotions":1,"cold_demotions":1,"quota_throttled_events":0,"fastpath_reclaim_hits":1,"total_reclaims":1,"reclaimed_pages":20,"final_active_pages":20,"final_inactive_pages":0}}
```

---

## 💡 제약 조건 (Constraints)
- 모든 연산은 단일 스레드 결정론적(Deterministic)으로 동작해야 합니다.
- 영역 정렬 순서는 `region_id` 사전순으로 평가됩니다.
- 쿼터는 핫 승격을 먼저 소진한 후 남은 쿼터로 콜드 강등을 처리합니다.
