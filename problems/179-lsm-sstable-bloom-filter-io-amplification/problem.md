# Problem 179: LSM-Tree SSTable 블룸 필터(Bloom Filter)와 포인트 룩업(Point Lookup) 읽기 증폭(Read Amplification) 최적화

## 문제 설명

글로벌 소셜 미디어 플랫폼의 NoSQL 스토리지 클러스터는 초당 수백만 건의 쓰기를 처리하기 위해 **LSM-Tree(Log-Structured Merge-tree)** 기반 스토리지 엔진을 운용하고 있습니다.
그러나 사용자 프로필 조회 서비스에서 최근 탈퇴했거나 존재하지 않는 무작위 유저 ID에 대한 단건 포인트 조회(`GET user:{id}`)가 급증하자, **수십 개의 SSTable을 최신순부터 가장 오래된 것까지 모조리 디스크에서 읽어 들이느라 NVMe SSD I/O가 100% 포화되고 전체 API 응답 시간이 10ms 이상으로 치솟는 심각한 읽기 증폭(Read Amplification) 장애**가 발생했습니다.

스토리지 인프라 팀은 각 SSTable마다 메모리 상주형 **블룸 필터(Bloom Filter)**를 탑재하고, **Kirsch-Mitzenmacher 더블 해싱** 및 **블록 캐시(LRU Block Cache)**를 결합하여 부존재 키의 불필요한 디스크 I/O를 원천 차단하는 최적화 엔진을 구축하기로 결정했습니다.

당신은 SSTable의 키 범위 검사, 블룸 필터 평가, 블록 캐시 히트, 실제 디스크 블록 조회를 거치는 3단계 포인트 룩업 파이프라인을 정밀하게 시뮬레이션하고 복합 지표를 산출하는 시스템을 구현해야 합니다.

---

## 핵심 처리 규칙

### 1. SSTable 구조 및 키 범위 검사 (Range Check)
각 SSTable은 정렬된 키-값 쌍(`kv_pairs`)과 정렬된 키 리스트 기준 `min_key`, `max_key` 메타데이터를 가집니다:
- 쿼리 키가 `min_key <= key <= max_key` 범위를 벗어나면, 블룸 필터 검사조차 건너뛰고 즉시 다음 SSTable로 넘어갑니다.

### 2. 블룸 필터 평가 (Bloom Filter Evaluation)
`enable_bloom_filter == True`인 경우, 범위 내에 있는 키에 대해 블룸 필터를 검사합니다:
- **비트 크기 및 해시 함수 개수**:
  - $m = \max(64, \lfloor n \times \text{bits\_per\_key} \rfloor)$
  - $k = \max(1, \min(30, \text{round}((m / n) \times \ln 2)))$
- **Kirsch-Mitzenmacher 더블 해싱 (`use_double_hashing == True`)**:
  - SHA-256 해시의 전반부 8바이트를 $h_1$, 후반부 8바이트를 $h_2$로 취합니다 ($h_2 == 0$이면 1로 보정).
  - $i$번째 비트 인덱스: $g_i(x) = (h_1 + i \times h_2) \pmod m \quad (i = 0, 1, \dots, k-1)$
- **필터 검사 비용**: `filter_check_latency_us` ($0.5\,\mu\text{s}$) 누적.
- **True Negative 판정**:
  - 비트 배열 중 단 하나라도 0인 비트가 발견되면 해당 SSTable에 키가 존재하지 않음이 100% 보장됩니다.
  - `true_negatives_filtered` 카운터를 1 증가시키고 디스크 읽기 없이 즉시 다음 SSTable로 넘어갑니다.

### 3. 블록 캐시 및 디스크 읽기 (Cache Hit vs Disk I/O)
블룸 필터를 통과했거나 필터가 비활성화된 경우:
- 캐시 키 `f"{sstable_id}:{key}"`가 블록 캐시에 존재하면:
  - `cache_hits` 1 증가, `cache_read_latency_us` ($5.0\,\mu\text{s}$) 누적.
- 캐시에 없으면:
  - `disk_io_reads` 1 증가, `disk_read_latency_us` ($200.0\,\mu\text{s}$) 누적.
  - 캐시 용량(`block_cache_capacity_blocks`)에 여유가 있다면 캐시 키를 추가합니다.

### 4. 적중 판정 (True Positive vs False Positive)
- 실제로 SSTable의 `kv_pairs`에 키가 존재하면:
  - `true_positives` 1 증가, 값을 반환하고 탐색을 즉시 성공 종료합니다 (최신 SSTable 우선).
- 실제로는 키가 없는데 블룸 필터가 통과시킨 경우:
  - 필터가 켜져 있다면 **`false_positives_wasted_io`** 카운터를 1 증가시킵니다 (헛걸음 디스크 I/O 발생!).

---

## 입력 형식

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "system": {
    "enable_bloom_filter": true,
    "bits_per_key": 10.0,
    "use_double_hashing": true,
    "block_cache_capacity_blocks": 50,
    "disk_read_latency_us": 200.0,
    "cache_read_latency_us": 5.0,
    "filter_check_latency_us": 0.5
  },
  "sstables": [
    {
      "id": "sst_01",
      "data": {
        "item_0100": "val_100",
        "item_0102": "val_102"
      }
    }
  ],
  "workload": [
    {"key": "item_0100"},
    {"key": "item_0101"}
  ]
}
```

---

## 출력 형식

표준 출력(stdout)으로 다음 형식의 JSON 객체를 들여쓰기 2칸(`indent=2`)으로 출력합니다:

```json
{
  "status": "SUCCESS",
  "summary": {
    "enable_bloom_filter": true,
    "bits_per_key": 10.0,
    "use_double_hashing": true,
    "total_sstables": 1,
    "theoretical_fpr": 0.0082,
    "empirical_fpr": 0.0
  },
  "metrics": {
    "total_queries": 2,
    "range_checks": 2,
    "filter_checks": 2,
    "true_negatives_filtered": 1,
    "false_positives_wasted_io": 0,
    "true_positives": 1,
    "disk_io_reads": 1,
    "cache_hits": 0,
    "total_latency_us": 201.0,
    "average_latency_us": 100.5,
    "verdict": "PERFECT_NEGATIVE_FILTERING"
  },
  "sample_queries": [
    {
      "key": "item_0100",
      "found": true,
      "value": "val_100",
      "latency_us": 200.5,
      "sstable_lookups": 1
    },
    {
      "key": "item_0101",
      "found": false,
      "value": null,
      "latency_us": 0.5,
      "sstable_lookups": 1
    }
  ]
}
```

### 최종 판정 (Verdict) 규칙
1. `CATASTROPHIC_READ_AMPLIFICATION_NO_FILTER`: `enable_bloom_filter == false`인 경우.
2. `HIGH_FALSE_POSITIVE_CACHE_POLLUTION`: `enable_bloom_filter == true`이고 `bits_per_key < 4.0`인 경우.
3. `OPTIMAL_BLOOM_FILTER_BOUNDED_FPR`: `false_positives_wasted_io > 0`인 경우.
4. `PERFECT_NEGATIVE_FILTERING`: `true_negatives_filtered > 0`이고 위양성이 0건인 경우.
5. `ALL_TRUE_POSITIVES`: 검색된 모든 키가 실제로 존재하여 음성 필터링이 발생하지 않은 경우.
