# 리눅스 커널 6.1+ Multi-Gen LRU (MGLRU): 세대별 노화(Aging) 및 빈도(Tier) 승격을 통한 페이지 캐시 쓰레싱(Thrashing) 방어 엔진

## 문제 설명

수십 년간 리눅스 커널의 페이지 회수(Page Reclaim) 메커니즘을 지탱해 온 전통적인 **2-List LRU (Active / Inactive)** 모델은 고성능 서버 환경 및 모바일 환경에서 치명적인 아킬레스건을 노출해 왔습니다.

대규모 데이터베이스나 웹 서버가 메모리에 핫 워킹셋(Working Set)을 안정적으로 유지하고 있는 상태에서, 백업 스크립트(`tar`, `rsync`), 로그 분석기, 바이러스 스캐너, 혹은 대용량 미디어 스트리밍(`readahead`)과 같은 **단발성 대용량 순차 파일 읽기(Single-pass Sequential Streaming Scan)**가 유입되면 어떻게 될까요?

전통적인 2-List LRU에서는 새롭게 유입된 스트리밍 페이지들이 Inactive 리스트로 폭포수처럼 쏟아져 들어옵니다. 비활성 리스트가 급격히 차오르면 커널의 회수 스레드(`kswapd`)는 활성/비활성 리스트의 균형을 맞추기 위해 `shrink_active_list()`를 호출하여 **Active 리스트에 상주하던 고빈도 워킹셋 페이지들을 강제로 Inactive 리스트 끝단으로 강등(Demote)**시킵니다. 그 결과, 한 번 읽고 버려질 스트리밍 페이지들에 밀려 핵심 데이터베이스 워킹셋이 모조리 디스크로 축출(Eviction)되는 참사, 즉 **페이지 캐시 쓰레싱(Page Cache Thrashing)**과 연쇄적인 디스크 I/O 폭풍이 발생합니다.

이를 근본적으로 해결하기 위해 리눅스 커널 6.1에 구글(Google)의 Yu Zhao 주도로 업스트림된 혁신 기술이 바로 **Multi-Gen LRU (MGLRU, 다세대 LRU)**입니다.

MGLRU는 단 2개의 활성/비활성 리스트 대신 다음과 같은 다차원 아키텍처를 도입합니다:
1. **세대화(Generations)**: 시간의 흐름에 따라 증가하는 시퀀스 번호(`min_seq` ~ `max_seq`)를 부여하여 페이지를 여러 세대(Generation) 코호트로 분할 관리합니다.
2. **다중 빈도 티어(Multi-Tier Frequency Buckets)**: 각 세대 내부에서 페이지의 실제 접근 횟수(PTE 참조 비트)에 따라 Tier 0(비참조)부터 Tier 3(초고빈도 핫 페이지)까지 세밀한 빈도 등급을 부여합니다.
3. **워킹셋 보호 및 축출 분리(Working-set Protection & Eviction)**:
   - 메모리 압박이 발생하여 페이지를 회수할 때, MGLRU는 가장 오래된 세대(`min_seq`)의 **Tier 0(미참조 페이지)**만을 엄격하게 선별 축출합니다.
   - 오래된 세대에 머물고 있더라도 참조 빈도가 높은(`tier >= 1`) 페이지는 축출 대상에서 제외되며, 가장 젊은 최신 세대(`max_seq`)로 **구출 승격(Promotion)**되어 워킹셋을 100% 보존합니다!
   - 단발성 스트리밍 페이지는 Tier 0에만 머물기 때문에, 유입되더라도 워킹셋을 전혀 밀어내지 못하고 스스로 축출됩니다.

당신은 리눅스 커널 메모리 관리 서브시스템의 핵심 엔진을 설계하는 수석 엔지니어로서, **MGLRU 시뮬레이터**와 **전통적인 2-List LRU 시뮬레이터**를 정밀 구현하고, 동일한 페이지 접근 트레이스 워크로드 하에서 두 아키텍처의 워킹셋 보존율, 페이지 폴트율, 디스크 쓰기(Writeback) 횟수 및 쓰레싱 방어 메커니즘을 비교 분석하는 평가 엔진을 완성해야 합니다.

---

## 시스템 상세 사양 및 상태 전이 규칙

### 1. 전역 시스템 파라미터
- `capacity`: 시스템 물리 메모리가 수용할 수 있는 최대 페이지 개수 (정수).
- `max_nr_gens`: MGLRU가 동시에 유지할 수 있는 최대 활성 세대 윈도우 크기 (기본값 4, 즉 `max_seq - min_seq + 1 <= max_nr_gens`).
- `max_tiers`: 세대 당 유지되는 빈도 티어 개수 (기본값 4: Tier 0, 1, 2, 3).

---

### 2. MGLRU (Multi-Gen LRU) 상태 머신

#### (1) 초기 상태
- `min_seq = 1`, `max_seq = 1`.
- 세대별 페이지 리스트: 각 세대 $g$는 `max_tiers`개의 FIFO 리스트(`lists[g][0..max_tiers-1]`)를 가집니다.
- 각 상주 페이지 $P$의 메타데이터:
  - `page_id`: 고유 식별자 문자열
  - `type`: `"file"` (기본값) 또는 `"anon"`
  - `dirty`: 더티 여부 불리언 (기본값 `False`)
  - `is_working_set`: 워킹셋 여부 불리언 (기본값 `False`)
  - `gen`: 현재 소속 세대 (정수, `min_seq <= gen <= max_seq`)
  - `tier`: 현재 빈도 등급 (정수, `0 <= tier < max_tiers`)
  - `refs`: 참조 카운트

#### (2) 페이지 터치 / 접근 (`TOUCH` 또는 `ALLOC`)
- **캐시 히트 (메모리에 이미 존재하는 경우)**:
  - `hits += 1`
  - 더티 플래그가 지정된 경우 `P.dirty = True`, 워킹셋 플래그 지정 시 `P.is_working_set = True`.
  - 참조 횟수 증가: `P.refs += 1`
  - 빈도 티어 승격: 기존 리스트 위치에서 제거 후 `P.tier = min(max_tiers - 1, P.tier + 1)`.
  - 세대 승격: 만약 `P.gen < max_seq`였다면, 최신 세대로 승격(`promotions += 1`, `P.gen = max_seq`).
  - 최신 세대 리스트 `lists[max_seq][P.tier]`의 꼬리(FIFO)에 삽입.
- **페이지 폴트 / 미스 (메모리에 없는 경우)**:
  - `page_faults += 1`
  - 상주 페이지 수가 `capacity` 이상이면 즉시 1개 페이지를 축출(`evict_one()`).
  - 타겟 세대 결정: `cold=True` 힌트가 주어지면 `target_gen = min_seq`, 그렇지 않으면 `target_gen = max_seq`.
  - 신규 페이지를 `gen = target_gen, tier = 0, refs = 0`으로 생성하여 `lists[target_gen][0]`에 등록. (`cold=True`인 경우 즉시 축출 우선순위를 위해 머리에 삽입, 일반적인 경우 꼬리에 삽입).

#### (3) 세대 노화 (`AGING`)
- 백그라운드 스레드(`kswapd`)의 주기적 노화 틱 또는 세대 생성:
  - 최신 세대 증가: `max_seq += 1`. 신규 세대 리스트 생성.
  - 윈도우 크기 초과 검사: `(max_seq - min_seq + 1) > max_nr_gens`인 동안 가장 오래된 세대 `min_seq`를 정리:
    - **생존 승격(Rescue Promotion)**: `min_seq`에 존재하는 `tier >= 1`인 모든 페이지에 대해:
      - `new_tier = max(1, p.tier - 1)` (빈도 점진 감쇠, 단 최소 Tier 1 유지하여 Tier 0 즉시 축출 방지).
      - `p.gen = max_seq, p.tier = new_tier, p.refs = new_tier`.
      - `lists[max_seq][new_tier]`의 꼬리에 추가 (`promotions += 1`).
    - **미참조 콜드 페이지 이월**: `min_seq`의 Tier 0에 남아있는 페이지들은 새로운 `min_seq + 1`의 Tier 0 머리로 이월(roll over).
    - 기존 `min_seq` 리스트 삭제 후 `min_seq += 1`.

#### (4) 페이지 축출 (`evict_one()`)
- 회수가 필요할 때 `min_seq`부터 `max_seq` 방향으로 탐색:
  1. 현재 탐색 세대(`min_seq`)의 **Tier 0** 리스트가 비어있지 않으면:
     - Tier 0의 가장 오래된 페이지(머리)를 꺼내어 메모리에서 영구 축출!
     - `evictions += 1`, 축출 목록에 추가.
     - 만약 해당 페이지가 `is_working_set == True`라면 `working_set_evictions += 1`.
     - 만약 해당 페이지가 `dirty == True`라면 디스크 I/O 발생: `writebacks += 1`.
     - 축출 완료 후 즉시 반환.
  2. 만약 `min_seq`의 Tier 0이 비어있다면:
     - 만약 `min_seq < max_seq`라면:
       - `min_seq`의 Tier 1 이상에 상주하는 모든 페이지를 `max_seq`로 구출 승격:
         - `new_tier = max(1, p.tier - 1)`, `p.gen = max_seq`, `p.tier = new_tier`.
         - `lists[max_seq][new_tier]`에 추가 (`promotions += 1`).
       - `min_seq` 리스트를 삭제하고 `min_seq += 1`로 전진시킨 후 루프를 다시 돌아 새로운 `min_seq`의 Tier 0을 탐색!
     - 만약 `min_seq == max_seq` (모든 상주 페이지가 단일 최신 세대에 집중된 경우):
       - Tier 0부터 Tier `max_tiers - 1`까지 순서대로 탐색하여, 페이지가 존재하는 가장 낮은 티어의 머리에서 1개 페이지를 강제 축출.

---

### 3. 전통적인 2-List LRU (Active / Inactive) 모델

- 리스트 구성: `Active` (고빈도 활성) 및 `Inactive` (저빈도 비활성).
- 목표 비활성 크기: `inactive_target = max(1, int(capacity * inactive_ratio))` (기본 `inactive_ratio = 0.5`).
- **접근 (`touch`)**:
  - 히트:
    - Inactive 리스트에 있을 때:
      - `pg_referenced == 0`이면 `pg_referenced = 1`로 설정 (Inactive 유지).
      - `pg_referenced == 1`이면 Inactive에서 제거하여 Active 머리로 승격 (`pg_referenced = 0`).
    - Active 리스트에 있을 때: `pg_referenced = 1` 설정 및 Active 머리로 이동.
  - 미스 (폴트):
    - 여유 공간 부족 시 `evict_one()` 수행.
    - Inactive 머리에 신규 삽입 (`pg_referenced = 0`).
- **축출 (`evict_one()`)**:
  - 균형 검사: `len(inactive) <= len(active)`이고 `len(active) > 0`인 경우:
    - Active 리스트 꼬리(가장 오래된 페이지)를 꺼내 `pg_referenced = 0`으로 초기화 후 Inactive 머리로 강등(`shrink_active_list`).
  - Inactive 꼬리 순회:
    - 꼬리 페이지의 `pg_referenced == 1`이면 `pg_referenced = 0`으로 클리어하고 Inactive 머리로 재삽입 (Second chance).
    - `pg_referenced == 0`이면 해당 페이지를 즉시 축출 (`evictions += 1`, 워킹셋/더티 여부 반영).
  - 만약 Inactive가 비어있다면 Active 꼬리에서 강제 축출.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다:

```json
{
  "capacity": 8,
  "max_nr_gens": 4,
  "max_tiers": 4,
  "operations": [
    {"op": "TOUCH", "page_id": "W1", "is_working_set": true},
    {"op": "MARK_DIRTY", "page_id": "W1"},
    {"op": "AGING"},
    {"op": "STREAM_READ", "pages": ["S1", "S2", "S3"]},
    {"op": "RECLAIM", "nr_to_reclaim": 2}
  ]
}
```

### 지원 연산 (`operations`)
- `TOUCH` 또는 `ALLOC`: `{"op": "TOUCH", "page_id": str, "type": str, "dirty": bool, "is_working_set": bool, "cold": bool}`
- `MARK_DIRTY`: `{"op": "MARK_DIRTY", "page_id": str}` (해당 페이지의 dirty 플래그를 True로 갱신)
- `AGING`: `{"op": "AGING"}` (MGLRU 세대 노화 틱 트리거)
- `RECLAIM`: `{"op": "RECLAIM", "nr_to_reclaim": int}` (지정된 개수만큼 페이지 명시적 축출)
- `STREAM_READ`: `{"op": "STREAM_READ", "pages": [str, ...], "cold": bool}` (연속 단발성 파일 읽기 시뮬레이션)

---

## 출력 형식

표준 출력(stdout)으로 MGLRU, Legacy 2-List의 상세 메트릭 및 비교 분석 결과를 포함하는 단일 JSON 라인을 출력합니다:

```json
{
  "mglru": {
    "hits": 10,
    "page_faults": 20,
    "evictions": 12,
    "working_set_evictions": 0,
    "writebacks": 0,
    "promotions": 12,
    "min_seq": 2,
    "max_seq": 2,
    "active_generations": 1,
    "resident_pages_count": 8,
    "generation_distribution": {
      "gen_2": {"tier_0": 3, "tier_1": 5, "tier_2": 0, "tier_3": 0}
    },
    "evicted_pages": ["S1", "S2", ...]
  },
  "legacy_2list": {
    "hits": 5,
    "page_faults": 25,
    "evictions": 17,
    "working_set_evictions": 5,
    "writebacks": 1,
    "active_pages_count": 0,
    "inactive_pages_count": 8,
    "resident_pages_count": 8,
    "evicted_pages": ["S1", "S2", "W1", "W2", ...]
  },
  "analysis": {
    "working_set_protection_delta": 5,
    "thrashing_prevented": true,
    "mglru_cache_hit_rate": 0.3333,
    "legacy_cache_hit_rate": 0.1667
  }
}
```
