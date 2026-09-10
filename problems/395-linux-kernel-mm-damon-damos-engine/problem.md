# 395: 리눅스 커널 메모리 관리 — DAMON(Data Access Monitoring) 적응형 다중 영역 샘플링 및 DAMOS 선제적 메모리 회수 엔진

## 1. 개요 (Overview)

수십 기가바이트에서 수 테라바이트에 달하는 현대 대규모 클라우드 서버 워크로드(대규모 데이터베이스, LLM 추론, 컨테이너화된 마이크로서비스 등)에서 프로세스의 실제 메모리 접근 패턴(Working Set Size, Hot/Cold 영역)을 추적하는 것은 성능 최적화와 메모리 비용 절감의 핵심 과제입니다.

전통적인 방식인 페이지 테이블 접근 비트(`PTE_ACCESSED`) 전수 스캔(예: `/proc/PID/smaps` 정주기 탐색이나 `clear_refs`)은 가상 주소 공간의 전체 크기 $N$에 비례하는 **$O(N)$ CPU 오버헤드**를 유발하며, 캐시 오염(Cache Pollution)과 심각한 테일 레이턴시(Tail Latency) 스파이크를 발생시켜 프로덕션 환경에서 실시간 사용이 불가능했습니다.

이 문제를 해결하기 위해 AWS의 박성재(SeongJae Park) 엔지니어가 설계하고 리눅스 커널 5.15+에 정식 도입된 **DAMON(Data Access Monitoring Framework, `mm/damon/core.c`)** 은 주소 공간 전체를 유연하게 결합/분할하는 **적응형 영역 조정(Adaptive Regions Adjustment)** 기법을 사용하여, 메모리 크기와 무관하게 모니터링 CPU 오버헤드를 사전에 정의된 상한선($[N_{min}, N_{max}]$ 영역 개수) 내로 엄격히 제한($O(1)$)하는 혁신적인 서브시스템입니다.

나아가 **DAMOS(DAMON-based Operation Schemes)** 는 DAMON이 수집한 접근 빈도(`nr_accesses`) 및 지속 연령(`age`) 정보를 기반으로, 장기간 접근되지 않은 콜드 메모리를 선제적으로 스왑아웃(`madvise(MADV_PAGEOUT)`)하거나 핫 메모리를 미리 인출(`madvise(MADV_WILLNEED)`)하고, 메모리 압박 워터마크 및 처리량 쿼터(Quota)를 통해 시스템 I/O 폭주를 통제합니다.

본 문제에서는 리눅스 커널 DAMON의 3단계 주기 루프(샘플링, 집계, 적응형 갱신), 동적 영역 분할·병합 상태 머신, DAMOS 규칙 기반 선제적 회수 및 워터마크 제어 엔진을 직접 설계 및 구현합니다.

---

## 2. DAMON & DAMOS 아키텍처 다이어그램

```
+========================================================================================+
|                    Target Virtual Address Space [start_addr, end_addr)                 |
|                                                                                        |
|   +-------------------+  +-------------------+  +-------------------+  +------------+  |
|   | Region 0 [0x1000] |  | Region 1 [0x2000] |  | Region 2 [0x3000] |  | Region 3   |  |
|   | (nr_acc=0, age=3) |  | (nr_acc=8, age=2) |  | (nr_acc=0, age=4) |  | (nr_acc=0) |  |
|   +-------------------+  +-------------------+  +-------------------+  +------------+  |
+========================================================================================+
             ||                      ||                      ||                 ||
             || (Sampling Interval)  ||                      ||                 ||
             VV                      VV                      VV                 VV
+----------------------------------------------------------------------------------------+
| 1. Sampling Step: Test random page access in each region (PTE Access Bit Sampling)    |
|    - If accessed: region.nr_accesses++                                                 |
+----------------------------------------------------------------------------------------+
             ||
             || (Aggregation Interval: aggr_interval)
             VV
+----------------------------------------------------------------------------------------+
| 2. Aggregation Step & DAMOS Execution:                                                 |
|    - Evaluate DAMOS Schemes against (nr_accesses, age, size_bytes)                     |
|    - Watermark Check: If free_mem_pct >= High Watermark -> Bypass Reclamation          |
|    - Apply Action: PAGEOUT / WILLNEED / COLD up to quota_bytes                         |
|    - Update Age: if |nr_accesses - last_nr_accesses| <= threshold: age++ else age = 0  |
|    - Reset nr_accesses = 0 for next interval                                           |
+----------------------------------------------------------------------------------------+
             ||
             || (Update Interval: update_interval)
             VV
+----------------------------------------------------------------------------------------+
| 3. Adaptive Adjustment Step (Region Merging & Splitting):                              |
|    - Merge: Adjacent regions with |last_nr_accesses difference| <= threshold           |
|             Coalesce while keeping regions_count >= min_regions                        |
|    - Split: Split largest regions into half while regions_count < max_regions          |
|    - Maintain strictly bounded regions count in [min_regions, max_regions]             |
+----------------------------------------------------------------------------------------+
```

---

## 3. 핵심 수리 및 알고리즘 명세 (Algorithmic & Mathematical Specification)

### 3.1 3대 주기 타이머 계층
- **`sample_interval` ($	au_s$)**: 각 영역의 메모리 접근 여부를 확인하고 `nr_accesses`를 증가시키는 최소 샘플링 단위.
- **`aggr_interval` ($	au_a$)**: 누적된 샘플링 카운트를 기반으로 DAMOS 정책을 수행하고, 접근 패턴 지속성(`age`)을 갱신한 후 카운트를 리셋하는 집계 단위.
- **`update_interval` ($	au_u$)**: 영역 병합(Merging) 및 분할(Splitting)을 수행하여 영역 개수를 $[N_{min}, N_{max}]$ 범위로 동적 재조정하는 단위.

### 3.2 접근 패턴 지속성 및 연령(`age`) 갱신 규칙
집계 주기마다 각 영역 $r$에 대해:
$$	ext{pattern\_persists} \iff |r.	ext{nr\_accesses} - r.	ext{last\_nr\_accesses}| \le 	ext{merge\_threshold}$$
$$r.	ext{age} \leftarrow egin{cases} r.	ext{age} + 1 & 	ext{if pattern\_persists} \ 0 & 	ext{otherwise} \end{cases}$$
이후 $r.	ext{last\_nr\_accesses} \leftarrow r.	ext{nr\_accesses}$, $r.	ext{nr\_accesses} \leftarrow 0$으로 초기화합니다.
급작스러운 접근 버스트가 발생하면 $r.	ext{age}$가 0으로 즉각 초기화되어 오판단에 의한 조기 메모리 방출을 방지합니다.

### 3.3 적응형 영역 병합 및 분할 (Adaptive Merging & Splitting)
갱신 주기마다:
1. **병합 (Merging)**:
   인접한 두 영역 $r_i, r_{i+1}$에 대해 $|r_i.	ext{last\_nr\_accesses} - r_{i+1}.	ext{last\_nr\_accesses}| \le 	ext{merge\_threshold}$이고 현재 영역 개수가 $N_{min}$ 초과일 때:
   - 두 영역을 $[r_i.	ext{start}, r_{i+1}.	ext{end})$로 병합합니다.
   - 병합된 영역의 가중 평균 접근 빈도:
     $$	ext{last\_nr\_accesses}_{	ext{new}} = 	ext{round}\left(rac{r_i.	ext{last} 	imes |r_i| + r_{i+1}.	ext{last} 	imes |r_{i+1}|}{|r_i| + |r_{i+1}|}ight)$$
   - $	ext{age}_{	ext{new}} = \min(r_i.	ext{age}, r_{i+1}.	ext{age})$
2. **분할 (Splitting)**:
   현재 영역 개수가 $N_{max}$ 미만인 동안:
   - 크기가 2바이트 이상인 영역 중 가장 크기가 큰 영역 $r_{	ext{largest}}$를 선택합니다.
   - 중앙 지점 $	ext{mid} = 	ext{start} + \lfloor 	ext{size} / 2 floor$을 기준으로 좌측 $[start, mid)$과 우측 $[mid, end)$ 영역으로 2분할합니다.

### 3.4 DAMOS 동작 및 워터마크 제어
- **워터마크 검사**:
  - $	ext{free\_mem\_pct} \ge 	ext{watermark.high}$인 경우 여유 메모리가 충분하므로 CPU 낭비를 막기 위해 DAMOS 동작을 비활성화(Skip)합니다.
- **규칙 매칭 및 쿼터 적용**:
  - 조건: $	ext{min\_access} \le r.	ext{nr\_accesses} \le 	ext{max\_access}$ AND $	ext{min\_age} \le r.	ext{age} \le 	ext{max\_age}$ AND $	ext{min\_size} \le r.	ext{size} \le 	ext{max\_size}$
  - 누적 적용 바이트 수가 `quota_bytes`에 도달할 때까지 작업(`PAGEOUT`, `WILLNEED`, `COLD`)을 실행하고 바이트 통계를 누적합니다.

---

## 4. 입출력 형식 (I/O Specification)

### 4.1 입력 형식 (Input Format)
표준 입력(stdin)으로 JSON 객체가 주어집니다:
```json
{
  "config": {
    "sample_interval": 5,
    "aggr_interval": 20,
    "update_interval": 40,
    "min_regions": 2,
    "max_regions": 4,
    "merge_threshold": 1,
    "start_addr": 4096,
    "end_addr": 20480,
    "init_regions": 4,
    "initial_free_mem_pct": 30.0,
    "watermarks": {"high": 80.0, "mid": 50.0, "low": 20.0},
    "damos_schemes": [
      {"min_access": 0, "max_access": 0, "min_age": 1, "action": "PAGEOUT", "quota_bytes": 8192}
    ]
  },
  "access_events": [
    {"time": 5, "addr": 4352},
    {"time": 10, "addr": 4608}
  ],
  "watermark_events": [
    {"time": 40, "free_mem_pct": 85.0}
  ],
  "max_time": 80
}
```

### 4.2 출력 형식 (Output Format)
표준 출력(stdout)으로 공백 없는 압축 JSON(Compact JSON)을 출력합니다:
```json
{
  "total_simulation_time": 80,
  "final_regions_count": 4,
  "final_regions": [
    {
      "start": "0x1000",
      "end": "0x2000",
      "size_bytes": 4096,
      "nr_accesses": 0,
      "age": 2
    }
  ],
  "total_bytes_paged_out": 4096,
  "total_bytes_willneed": 0,
  "total_bytes_cold": 0,
  "damos_actions_count": 1,
  "damos_actions_log": [
    {
      "timestamp": 40,
      "action": "PAGEOUT",
      "region_start": "0x2000",
      "region_end": "0x3000",
      "applied_bytes": 4096
    }
  ],
  "aggregation_snapshots_count": 4
}
```
