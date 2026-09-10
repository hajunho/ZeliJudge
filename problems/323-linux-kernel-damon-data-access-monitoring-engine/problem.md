# Linux Kernel DAMON: 데이터 접근 모니터링 및 DAMOS 적응형 메모리 작업 집합 최적화 엔진 (Data Access Monitoring & DAMOS Engine)

## 문제 개요

현대 하이퍼스케일러 및 클라우드 인프라(AWS, Google Cloud, Meta)에서 서버 DRAM은 전체 하드웨어 비용의 30~50%를 차지하는 가장 값비싼 자원 중 하나입니다. 그러나 대규모 데이터베이스, 머신러닝 워크로드, 웹 서비스 컨테이너에서 실제로 활발히 참조되는 **작업 집합(Working Set)**은 할당된 가상/물리 메모리의 10~30%에 불과하며, 나머지 70% 이상의 메모리는 수 시간 혹은 며칠 동안 한 번도 읽히거나 쓰이지 않는 **콜드 메모리(Cold Memory)**로 방치됩니다.

전통적인 리눅스 커널의 페이지 회수 서브시스템(`vmscan.c`, 활성/비활성 LRU 리스트)은 메모리 압박이 한계치(`watermark_min`)에 도달했을 때에만 사후 반응적(Reactive)으로 작동합니다. 또한, 전체 페이지 테이블을 스캔하며 PTE의 `Accessed`/`Young` 비트를 검사하고 클리어하는 과정에서 극심한 **페이지 테이블 락 경합(PTE lock contention)**, CPU 캐시 라인 무효화, 메모리 버스 트래픽 폭증이라는 치명적인 성능 저하(Direct Reclaim Latency Spike)를 야기합니다.

이 문제를 해결하기 위해 리눅스 5.15 커널에 정식 머지된 **DAMON(Data Access MONitoring framework: `mm/damon/core.c`)**과 이를 기반으로 한 정책 집행 엔진 **DAMOS(DAMON-based Operation Schemes)**는 획기적인 패러다임 전환을 제시합니다:
1. **적응형 영역 분할 및 병합(Adaptive Region Split & Merge)**: 모니터링 대상 주소 공간을 인접한 메모리 영역(Region)들로 분할하고, 접근 빈도가 균일한 영역들은 하나로 병합(`damon_merge_regions_of`)하며, 접근 빈도가 높거나 거대한 영역은 분할(`damon_split_regions_at`)하여 최소한의 CPU 오버헤드로 핫스팟의 경계를 정밀하게 포착합니다.
2. **상한/하한 경계 보장(`[min_nr_regions, max_nr_regions]`)**: 시스템 부하와 무관하게 메모리 영역 개수를 일정 범위 내로 고정하여 커널 모니터링 오버헤드를 $O(N_{regions})$ 상수로 통제합니다.
3. **선제적 DAMOS 정책(Proactive Operation Schemes)**: 영역의 접근 빈도(`nr_accesses`), 크기(`size`), 안정성 나이(`age`)에 기반하여 콜드 메모리를 백그라운드에서 스왑아웃(`PAGEOUT`)하거나, 핫 메모리를 활성 LRU 헤드로 보호(`LRU_PRIO`)하고, 웜 메모리를 강등(`LRU_DEPRIO`)하며, 엄격한 바이트 할당량(`sz_quota_bytes`)과 가중치 우선순위 점수를 통해 워크로드 스래싱을 방어합니다.

당신은 리눅스 커널 메모리 서브시스템의 핵심 엔지니어로서, `mm/damon/core.c`의 핵심 메커니즘을 완벽히 모사하는 **DAMON & DAMOS 시뮬레이션 엔진**을 구현해야 합니다.

---

## 아키텍처 및 시스템 흐름도

```
+-----------------------------------------------------------------------------------+
|                        Linux Kernel DAMON / DAMOS Framework                       |
|                          (mm/damon/core.c, mm/damon/sysfs.c)                      |
+-----------------------------------------------------------------------------------+
                                          |
                    [ 1. Sampling Phase (sample_interval_us) ]
                                          |
   Target Virtual / Physical Address Space: [0x10000000, 0x50000000)
   +-----------------------+-----------------------+-----------------------+
   | Region 0 [0x10..0x20) | Region 1 [0x20..0x30) | Region 2 [0x30..0x50) |
   +-----------------------+-----------------------+-----------------------+
              | (Hit!)                | (Miss)                | (Hit!)
       nr_accesses += 1        nr_accesses += 0        nr_accesses += 1
                                          |
                   [ 2. Aggregation Phase (aggr_interval_us) ]
                                          |
      +-----------------------------------+-----------------------------------+
      |                                                                       |
 [ Age Calculation ]                                            [ Dynamic Merge & Split ]
 |r.nr_acc - r.last| <= 1 ?                                      - Merge: adjacent delta <= thres
   age += 1 : age = 0                                            - Split: score = sz * (last_acc + 1)
 last_acc = nr_acc; nr_acc = 0                                   - Bounds: [min_regions, max_regions]
                                          |
                   [ 3. DAMOS Schemes Evaluation (damos_apply_scheme) ]
                                          |
   +--------------------------------------------------------------------------+
   | Filter: min_sz <= sz <= max_sz & min_acc <= acc <= max_acc & min_age <= age  |
   +--------------------------------------------------------------------------+
                                          |
                        [ Priority Score Calculation ]
          Score = weight_sz * (sz / 4096) + weight_acc * acc + weight_age * age
                                          |
                          Sort Candidates Descending By Score
                                          |
             [ Quota Enforcement (sz_quota_bytes) & Action Execution ]
             +-----------------------+-----------------------+
             | Action == "PAGEOUT"   | Action == "LRU_PRIO"  | ...
             | (Proactive Reclaim)   | (Working Set Protect) |
             +-----------------------+-----------------------+
```

---

## 상세 기술 사양

### 1. 메모리 영역(Region) 모델
- 각 영역 $R_i$는 반개구간 $[start, end)$로 정의되며, 주소 공간은 빈틈없이 연속됩니다.
  - $size = end - start$ (항상 4KB = 4096바이트의 배수)
  - `nr_accesses`: 현재 집계 윈도우 내에서 샘플링 히트된 횟수 (정수)
  - `last_nr_accesses`: 직전 집계 윈도우에서 확정된 접근 빈도
  - `age`: 접근 빈도가 안정적으로 유지된 연속 집계 윈도우 수
- **초기 분할**:
  - `initial_regions`가 주어지면 해당 영역들로 초기화합니다.
  - 주어지지 않으면 $[base\_addr, limit\_addr)$ 범위를 `min_nr_regions` 개수의 균등한 크기(마지막 영역이 나머지 보정)로 4KB 정렬 분할합니다.

### 2. 샘플링 페이즈 (`sample_tick`)
- 한 번의 샘플링 틱마다 접근된 메모리 주소 리스트 `accessed_addrs`가 주어집니다.
- 각 영역 $R_i$에 대해, 주어진 주소 중 **하나라도** $[R_i.start, R_i.end)$ 범위에 포함되면 해당 틱에서 $R_i.nr\_accesses$를 1 증가시킵니다. (동일 영역에 여러 주소가 적중해도 틱당 최대 1만 증가).
- 총 틱 수가 `samples_per_aggr = aggr_interval_us // sample_interval_us`의 배수가 될 때마다 자동으로 **집계 페이즈(Aggregation Phase)**를 실행합니다.

### 3. 집계 페이즈 (`_do_aggregation`)
집계 페이즈는 다음 4단계 순서로 결정론적으로 수행됩니다:
1. **나이(Age) 및 접근 빈도 갱신**:
   - 각 영역 $R$에 대해, $|R.nr\_accesses - R.last\_nr\_accesses| \le 1$이면 $R.age \leftarrow R.age + 1$, 그렇지 않으면 $R.age \leftarrow 0$.
   - $R.last\_nr\_accesses \leftarrow R.nr\_accesses$, $R.nr\_accesses \leftarrow 0$.
2. **영역 병합 (`damon_merge_regions_of`)**:
   - 영역 수가 `min_nr_regions`보다 클 때만 병합을 시도합니다.
   - 인접한 두 영역 $R_i, R_{i+1}$에 대해:
     - $|R_i.last\_nr\_accesses - R_{i+1}.last\_nr\_accesses| \le merge\_threshold$
     - $|R_i.age - R_{i+1}.age| \le age\_merge\_threshold$
     - $R_i.size + R_{i+1}.size \le max\_region\_size$
     - 위 3조건을 모두 만족하면 $R_i$와 $R_{i+1}$을 하나로 병합합니다.
       - 병합 영역의 start = $R_i.start$, end = $R_{i+1}.end$.
       - 가중 평균 접근 빈도: $\lfloor rac{R_i.last \cdot R_i.size + R_{i+1}.last \cdot R_{i+1}.size}{R_i.size + R_{i+1}.size} floor$.
       - 병합 나이: $\min(R_i.age, R_{i+1}.age)$.
       - 병합 후 현재 인덱스에서 다음 인접 영역과의 병합 가능성을 재검사합니다.
3. **영역 분할 (`damon_split_regions_at`)**:
   - 영역 수가 `max_nr_regions` 미만이고, 크기가 8192바이트 이상인 영역이 존재할 때 분할을 시도합니다.
   - 분할 후보 점수: $Score_{split} = size 	imes (last\_nr\_accesses + 1)$.
   - 후보들을 점수 내림차순(동점 시 $start$ 오름차순, 구현상 안정적 정렬)으로 정렬하여, 가용 슬롯 $max\_nr\_regions - len(regions)$만큼 상위 후보를 선택합니다.
   - 선택된 각 영역을 정확히 절반(4KB 단위 정렬)으로 분할합니다:
     - $half = \lfloor (size / 2) / 4096 floor 	imes 4096$ (0이면 4096).
     - 왼쪽 영역: $[start, start + half)$, 오른쪽 영역: $[start + half, end)$.
     - 두 자식 영역 모두 부모의 $last\_nr\_accesses$와 $age$를 그대로 상속합니다.
4. **DAMOS 스킴 집행 (`damos_apply_scheme`)**:
   - 등록된 스킴들을 `scheme_id` 알파벳 오름차순으로 순회하며 집행합니다.

### 4. DAMOS 스킴 집행 및 할당량(Quota) 모델
각 스킴은 다음 조건과 동작을 정의합니다:
- **필터 조건**:
  - $min\_sz \le R.size \le max\_sz$
  - $min\_nr\_accesses \le R.last\_nr\_accesses \le max\_nr\_accesses$
  - $min\_age \le R.age \le max\_age$
- **우선순위 점수 산출**:
  - $Score(R) = weight\_sz 	imes (R.size // 4096) + weight\_nr\_accesses 	imes R.last\_nr\_accesses + weight\_age 	imes R.age$.
- **정렬 및 할당량 적용**:
  - 조건을 만족하는 영역들을 $Score(R)$ 내림차순(동점 시 $start$ 오름차순)으로 정렬합니다.
  - $sz\_quota\_bytes > 0$인 경우 남은 할당량(`quota_rem`) 범위 내에서 적용합니다:
    - $R.size \le quota\_rem$: 전체 영역 적용 ($quota\_rem \leftarrow quota\_rem - R.size$, `nr_applied += 1`, `sz_applied += R.size`).
    - $R.size > quota\_rem$: 할당량이 남아있다면 부분 적용 ($sz\_applied += quota\_rem$, `nr_applied += 1`, $quota\_rem \leftarrow 0$), 그리고 `quota_exceeds += 1` 기록.
- **액션 실행 카운팅**:
  - `PAGEOUT`: `total_pageout_bytes += applied_bytes`
  - `LRU_PRIO`: `total_prio_bytes += applied_bytes`
  - `LRU_DEPRIO`: `total_deprio_bytes += applied_bytes`
  - `STAT`: 집계만 수행 (바이트 변동 없음)

---

## 입력 및 출력 형식

### 입력 JSON 스키마
```json
{
  "config": {
    "base_addr": "0x10000000",
    "limit_addr": "0x20000000",
    "min_nr_regions": 4,
    "max_nr_regions": 16,
    "sample_interval_us": 5000,
    "aggr_interval_us": 20000,
    "merge_threshold": 2,
    "age_merge_threshold": 3,
    "max_region_size": "0x08000000",
    "initial_regions": [
      {
        "start": "0x10000000",
        "end": "0x14000000",
        "nr_accesses": 0,
        "age": 0
      }
    ],
    "schemes": [
      {
        "scheme_id": "cold_reclaim",
        "action": "PAGEOUT",
        "min_sz": 4096,
        "max_sz": "0x7fffffffffffffff",
        "min_nr_accesses": 0,
        "max_nr_accesses": 0,
        "min_age": 2,
        "max_age": 100,
        "sz_quota_bytes": "0x01000000",
        "weight_sz": 1,
        "weight_nr_accesses": 1,
        "weight_age": 1
      }
    ]
  },
  "commands": [
    {
      "type": "SAMPLE",
      "ticks": 4,
      "accesses": ["0x11000000", "0x11004000"]
    },
    {
      "type": "FORCE_AGGR"
    },
    {
      "type": "UPDATE_SCHEME",
      "scheme": { ... }
    },
    {
      "type": "QUERY_REGIONS"
    },
    {
      "type": "QUERY_STATS"
    }
  ]
}
```

### 출력 JSON 스키마
```json
{
  "total_ticks": 8,
  "aggr_count": 2,
  "nr_regions": 6,
  "regions": [
    {
      "start": "0x10000000",
      "end": "0x12000000",
      "size": 33554432,
      "last_nr_accesses": 4,
      "age": 1
    }
  ],
  "schemes": {
    "cold_reclaim": {
      "scheme_id": "cold_reclaim",
      "action": "PAGEOUT",
      "nr_tried": 4,
      "sz_tried": 100663296,
      "nr_applied": 1,
      "sz_applied": 16777216,
      "quota_exceeds": 3
    }
  },
  "actions_summary": {
    "total_pageout_bytes": 16777216,
    "total_prio_bytes": 0,
    "total_deprio_bytes": 0
  },
  "query_logs": [ ... ]
}
```
