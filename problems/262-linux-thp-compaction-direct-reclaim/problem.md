# [리눅스 커널/메모리 서브시스템] Linux Transparent Huge Pages(THP) Direct Reclaim 레이턴시 스파이크와 kswapd/kcompactd 메모리 단편화 제어

## 문제 설명

대규모 인메모리 데이터베이스(Redis, MongoDB, Cassandra, RocksDB 등)와 고성능 분산 캐시 시스템을 운영하는 엔지니어링 조직에서 가장 악명 높은 장애 중 하나는 **간헐적으로 발생하는 극심한 꼬리 지연시간(Tail Latency Spike, 수백 ms 단위의 프로세스 스톨 현상)**입니다.

이 현상의 핵심 원인은 리눅스 커널의 **투명한 거대 페이지(Transparent Huge Pages, THP)**와 **메모리 컴팩션(Memory Compaction)** 및 **직접 회수(Direct Reclaim)** 알고리즘의 상호작용에 있습니다.
x86-64 아키텍처에서 기본 페이지 크기는 4KB이며, 2MB 거대 페이지를 할당하기 위해서는 버디 할당자(Buddy Allocator)에서 연속된 512개의 4KB 물리 페이지 프레임(Order-9, 512-page aligned block)이 필요합니다.

그러나 시스템이 장시간 구동되면 메모리 단편화(Memory Fragmentation)가 발생하여 총 여유 메모리가 충분하더라도 연속된 2MB 공간이 고갈됩니다.
이때 커널의 THP 정책이 기본값인 `always` 및 `defrag=always`로 설정되어 있으면, **메모리를 할당하려는 사용자 스레드의 호출 경로(Synchronous Allocation Path)에서 즉시 직접 컴팩션(Direct Compaction)과 직접 회수(Direct Reclaim)가 트리거**됩니다!
결과적으로 데이터베이스 쿼리를 처리하던 워커 스레드가 커널 공간에서 수백 개의 페이지를 복사·이주시키고, 더티 페이지(Dirty Page Cache)를 동기식으로 디스크에 플러시하느라 수십~수백 밀리초 동안 얼어붙으며(Freeze), 하트비트 타임아웃 및 서비스 장애로 이어집니다.

리눅스 커널 메모리 서브시스템(`mm/compaction.c`, `mm/vmscan.c`, `mm/page_alloc.c`) 엔지니어가 되어, 워터마크($W_{\min}, W_{\text{low}}, W_{\text{high}}$) 기반 메모리 압박 상태를 판정하고, 2MB THP 할당 시 직접 컴팩션과 직접 회수의 레이턴시 영향을 정밀 시뮬레이션하며, SLA 위반을 방지하기 위한 **커널 튜닝 권고안(`madvise`, `defer`, 워터마크 조정)**을 도출하는 **리눅스 THP 메모리 컴팩션 제어 엔진**을 구현하십시오.

---

## 핵심 시스템 모델 및 규칙

### 1. 물리 페이지 프레임 및 버디 블록 (PFN & Order-9 Block)
- 물리 메모리는 $N$개의 4KB 페이지 프레임(PFN: $0 \le \text{pfn} < N$)으로 관리됩니다.
- 2MB 거대 페이지(Order-9)는 정확히 512개의 연속된 4KB 페이지($2^9 = 512$)로 구성되며, PFN 인덱스가 512의 배수로 정렬된 블록 $[512 \cdot B, 512 \cdot (B+1) - 1]$ 단위로만 할당될 수 있습니다.
- 각 페이지 프레임의 상태:
  - `FREE`: 여유 페이지 프레임.
  - `MOVABLE_CLEAN`: 파일 기반 클린 페이지 캐시 등. 이주 가능하며, 회수 시 즉시 폐기(I/O 없음).
  - `MOVABLE_DIRTY`: 수정된 더티 페이지 캐시 또는 익명 메모리. 이주 가능하며, 회수 시 디스크 플러시 I/O 필요.
  - `UNMOVABLE`: 커널 슬랩(Slab), DMA 버퍼, mlock된 메모리, 이미 할당된 THP 등. **이주나 회수가 절대 불가능**합니다.

### 2. 존 워터마크 (Zone Watermarks)
주어진 여유 페이지 한계치 $W_{\min}$과 백분율 스케일 팩터 $S$ (`watermark_scale_factor`, 기본 10%)에 대해:
$$W_{\min} = \text{min\_free\_pages}$$
$$W_{\text{low}} = W_{\min} + \left\lfloor \frac{W_{\min} \times S}{100} \right\rfloor$$
$$W_{\text{high}} = W_{\min} + 2 \times \left\lfloor \frac{W_{\min} \times S}{100} \right\rfloor$$

### 3. THP 할당 및 디프래그(Defrag) 정책
할당 크기가 2MB($\ge 512$ 페이지)인 요청에 대해:
1. **THP 시도 가능 여부**:
   - `thp_enabled == "always"`: 항상 2MB THP 할당 시도.
   - `thp_enabled == "madvise"`: 요청의 `madvise_hugepage == true`인 경우에만 THP 시도.
   - `thp_enabled == "never"`: 절대 THP를 시도하지 않고 즉시 4KB 기본 페이지로 폴백.
2. **패스트 패스 (Fast Path)**:
   - 512 정렬된 블록 중 512개 페이지가 모두 `FREE`인 블록이 존재하면 즉시 할당(`THP_ALLOCATED`, 512개 페이지 모두 `UNMOVABLE`로 전이), 기본 할당 오버헤드만 소요.
3. **슬로우 패스: 직접 컴팩션 (Direct Compaction)**:
   - 패스트 패스 실패 시, 동기식 컴팩션 허용 여부 판별:
     - `thp_defrag == "always"`: 동기식 직접 컴팩션 허용.
     - `thp_defrag == "madvise"`: `madvise_hugepage == true`인 경우에만 직접 컴팩션 허용.
     - `thp_defrag in ("defer", "never")`: 사용자 스레드에서 직접 컴팩션을 수행하지 않고 **즉시 기본 4KB 페이지로 폴백** (스톨 방지!).
   - **컴팩션 대상 블록 선정**:
     - `UNMOVABLE` 페이지가 1개도 없는 512 블록 중, 이주 대상 `MOVABLE` 페이지 수($M$)가 가장 적은 블록을 선택 (최소 이주 비용).
     - 해당 블록 외부의 `FREE` 페이지 슬롯 수가 $M$개 미만이면, 필요한 슬롯을 확보하기 위해 직접 회수(Direct Reclaim)를 선행 실행.
     - 외부 여유 슬롯이 확보되면, 블록 내 $M$개 페이지를 외부 여유 슬롯으로 순차 이주시키고 해당 블록 512개 페이지를 `UNMOVABLE`로 할당(`THP_ALLOCATED`).
     - 소요 지연시간: $M \times \text{cost\_migration\_us}$.
4. **기본 4KB 페이지 폴백 (Fallback to Base Pages)**:
   - THP 할당이 불가능하거나 정책상 거부된 경우, 필요한 페이지 수만큼의 4KB 분산 여유 페이지를 할당(`BASE_PAGES_ALLOCATED`, 할당된 페이지는 `MOVABLE_CLEAN`으로 전이).

### 4. 직접 회수 (Direct Reclaim)
- 여유 페이지 수가 필요한 페이지 수보다 적거나 $W_{\min}$ 미만으로 떨어지면 동기식 직접 회수가 트리거됩니다:
- 목표: 여유 페이지 수가 $W_{\text{high}} + \text{pages\_needed}$ 이상이 되도록 페이지를 방출.
- 회수 순서 (PFN 0부터 오름차순):
  1. `MOVABLE_CLEAN` 페이지를 우선 회수 (`FREE`로 전이, 페이지당 $\text{cost\_clean\_reclaim\_us}$).
  2. 여전히 부족하면 `MOVABLE_DIRTY` 페이지를 회수 (`FREE`로 전이, 디스크 동기 플러시 발생, 페이지당 $\text{cost\_dirty\_reclaim\_us}$).
- 회수 후에도 여유 페이지가 부족하면 `"OOM"` (Out of Memory) 반환.

### 5. 통계 및 튜닝 권고안 판정
- `latency_us`: 기본 오버헤드 + 이주 비용 + 회수 비용의 합 (소수점 둘째자리 반올림).
- `latency_spike`: `latency_us > latency_sla_us` 인 경우 `true`.
- 백분위수 ($P_{50}, P_{99}$): 정렬된 지연시간 리스트에 대해 최근접 순위법 $\text{idx} = \max(0, \min(N-1, \lceil \frac{P}{100} \times N \rceil - 1))$.
- **튜닝 권고안 (`tuning_recommendation`)**:
  - 스파이크가 0건인 경우: `"PERFORMANCE_STABLE_WITHIN_SLA"`
  - 스파이크 발생 시:
    - 컴팩션 이벤트와 직접 회수 이벤트가 모두 발생: `"REMEDY_DISABLE_THP_ALWAYS_AND_INCREASE_MIN_FREE"`
    - 컴팩션 이벤트만 발생: `"REMEDY_SET_THP_DEFRAG_DEFER_OR_MADVISE"`
    - 직접 회수 이벤트만 발생: `"REMEDY_TUNE_WATERMARKS_AND_BACKGROUND_KSWAPD"`
    - 그 외: `"REMEDY_INVESTIGATE_LATENCY_SPIKES"`

---

## 입력 형식

표준 입력(`sys.stdin`)으로 시스템 설정, 초기 물리 메모리 세그먼트, 할당 요청 목록이 포함된 JSON이 주어집니다:
```json
{
  "config": {
    "total_pages": 4096,
    "min_free_pages": 256,
    "watermark_scale_factor": 10,
    "thp_enabled": "always",
    "thp_defrag": "always",
    "latency_sla_us": 300.0,
    "cost_base_alloc_us": 0.5,
    "cost_migration_us": 2.0,
    "cost_clean_reclaim_us": 1.0,
    "cost_dirty_reclaim_us": 25.0
  },
  "initial_memory": {
    "segments": [
      {"start_pfn": 0, "count": 180, "type": "MOVABLE_CLEAN"},
      {"start_pfn": 180, "count": 332, "type": "FREE"},
      {"start_pfn": 512, "count": 20, "type": "UNMOVABLE"},
      {"start_pfn": 532, "count": 492, "type": "FREE"}
    ]
  },
  "requests": [
    {"id": "REQ_01", "size_bytes": 2097152, "madvise_hugepage": false}
  ]
}
```

---

## 출력 형식

표준 출력(`sys.stdout`)으로 워터마크 정보, 종합 요약 메트릭, 요청별 할당 로그가 포함된 단일 라인 JSON을 출력합니다:
```json
{
  "watermarks": {
    "w_min": 256,
    "w_low": 281,
    "w_high": 306
  },
  "summary": {
    "total_requests": 1,
    "thp_requests": 1,
    "thp_success_count": 1,
    "thp_success_rate_pct": 100.0,
    "compaction_events": 1,
    "direct_reclaim_events": 0,
    "latency_spike_count": 1,
    "p50_latency_us": 360.5,
    "p99_latency_us": 360.5,
    "max_latency_us": 360.5,
    "tuning_recommendation": "REMEDY_SET_THP_DEFRAG_DEFER_OR_MADVISE"
  },
  "allocations": [
    {
      "id": "REQ_01",
      "status": "THP_ALLOCATED",
      "allocated_pages": 512,
      "latency_us": 360.5,
      "compacted_pages": 180,
      "reclaimed_pages": 0,
      "latency_spike": true
    }
  ]
}
```
