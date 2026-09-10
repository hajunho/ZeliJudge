# [OLAP/빅데이터/스토리지 엔진] ClickHouse MergeTree 희소 기본 인덱스(Sparse Primary Index), 그래뉼(Granule) 범위 이진 탐색 및 마크(.mrk2) 프루닝 엔진

## 문제 설명

클라우드플레어(Cloudflare), 우버(Uber), 네이버, 카카오, 쿠팡 등 전 세계 테크 기업들의 대규모 실시간 로그 분석, 옵저버빌리티(APM/Metric/Trace), 금융 거래 체결 분석 플랫폼의 핵심 심장부에는 오픈소스 초고성능 컬럼형 OLAP 데이터베이스인 **ClickHouse**가 자리잡고 있습니다.
ClickHouse는 단일 노드에서 초당 수억 건, 분산 클러스터에서 페타바이트(PB) 규모의 데이터에 대해 0.01초 대의 서브세컨드(Sub-second) SQL 쿼리 응답을 달성합니다.

이 경이로운 쿼리 성능의 핵심 비결은 MySQL의 InnoDB나 PostgreSQL의 B-Tree와 같은 **밀집 인덱스(Dense Index)**가 아니라, ClickHouse 고유의 **MergeTree 스토리지 엔진 아키텍처**에 있습니다:
1. **희소 기본 인덱스 (Sparse Primary Index, `primary.idx`)**:
   - 기존 RDBMS는 모든 행(Row)마다 인덱스 엔트리를 생성하므로 수억 건의 데이터에서 인덱스 크기만 수십 GB에 달해 메모리(RAM)를 고갈시킵니다.
   - ClickHouse는 `ORDER BY (col1, col2, ...)` 순으로 정렬된 데이터를 **그래뉼(Granule, 기본 8,192행 단위)** 단위로 분할하고, **각 그래뉼의 첫 번째 행의 기본 키 값만 인덱스에 저장**합니다. 따라서 수십억 행의 테이블이라도 기본 인덱스 크기가 수십 MB에 불과하여 **인덱스 전체를 상시 RAM에 상주(In-Memory)**시킵니다.
2. **컬럼 압축 파일(`.bin`)과 마크 파일(`.mrk2`)의 연동**:
   - 각 컬럼 데이터는 개별 압축 블록(`.bin`)으로 나뉘어 디스크에 저장됩니다.
   - 마크 파일(`.mrk2`)은 각 그래뉼 $g$에 대해 `(compressed_offset, uncompressed_offset)` 쌍을 기록합니다.
   - 여러 개의 그래뉼이 하나의 압축 블록(최대 64KB uncompressed)을 공유할 수 있으며, 쿼리 엔진은 불필요한 압축 블록을 디스크에서 아예 읽거나 압축 해제하지 않고 완전히 건너뜁니다.
3. **사전 식별 및 범위 프루닝 (Range Pruning & Binary Search)**:
   - SQL의 `WHERE` 조건이 유입되면, ClickHouse는 디스크의 데이터 행을 읽기 전에 RAM에 있는 희소 인덱스(`primary.idx`)만을 바탕으로 각 그래뉼의 키 범위 $[P_g, P_{g+1})$와 쿼리 검색 영역 $Q$ 간의 사전 교집합(Interval Overlap)을 판별합니다.
   - 쿼리 조건과 전혀 겹치지 않는 그래뉼은 즉시 제외(**Pruned / Skipped**)되고, 오직 매칭 가능성이 있는 그래뉼의 압축 블록만 디스크에서 읽어 압축 해제합니다.
4. **보조 데이터 스킵 인덱스 (Data Skipping Indices: MinMax, Set)**:
   - 기본 키에 포함되지 않은 일반 컬럼에 대해서도 `minmax`, `set` 등의 보조 인덱스를 $K$개 그래뉼 단위(Granularity)로 구축하여, 기본 키 필터링을 통과한 그래뉼 중에서도 추가적으로 블록을 건너뜁니다.

데이터 인프라 및 분산 스토리지 엔지니어링 팀의 일원이 되어, ClickHouse MergeTree 스토리지 파트의 정렬 데이터, 희소 기본 인덱스, 마크 압축 블록 매핑 및 보조 스킵 인덱스를 구축하고, 임의의 다차원 SQL `WHERE` 필터 조건에 대해 불필요한 그래뉼과 압축 블록을 정밀하게 프루닝(Pruning)하여 디스크 I/O 절감 효과와 스캔 효율성을 계산하는 **ClickHouse MergeTree 희소 인덱스 & 그래뉼 프루닝 시뮬레이션 엔진**을 구현하십시오.

---

## 입력 형식

표준 입력(stdin)으로 단일 JSON 객체가 주어집니다.

```json
{
  "config": {
    "primary_key": ["tenant_id", "event_time"],
    "granule_size": 4,
    "marks_per_compressed_block": 2,
    "data_skipping_indices": [
      {
        "name": "idx_latency_minmax",
        "column": "latency_ms",
        "type": "minmax",
        "granularity": 2
      }
    ],
    "rows": [
      {"tenant_id": 1, "event_time": 100, "latency_ms": 15},
      {"tenant_id": 1, "event_time": 105, "latency_ms": 25}
    ]
  },
  "queries": [
    {
      "query_id": "Q1",
      "where": {
        "tenant_id": {"eq": 1},
        "event_time": {"gte": 100, "lte": 110}
      }
    }
  ]
}
```

### 사양 설명
- `config` (Object):
  - `primary_key` (Array of String): 정렬 및 기본 인덱스의 기준 컬럼 튜플 목록 (예: `["tenant_id", "event_time"]`).
  - `granule_size` (Integer): 한 그래뉼에 포함되는 최대 행 수 (기본 8192, 테스트 환경에서는 가변).
  - `marks_per_compressed_block` (Integer): 하나의 압축 블록에 담기는 그래뉼 수 (기본 2).
  - `data_skipping_indices` (Array of Object): 보조 데이터 스킵 인덱스 정의 목록:
    - `name` (String): 인덱스 이름
    - `column` (String): 대상 컬럼명
    - `type` (String): 인덱스 타입 (`"minmax"` 또는 `"set"`)
    - `granularity` (Integer): 인덱스 한 엔트리가 커버하는 그래뉼 블록 크기
  - `rows` (Array of Object): 테이블 파트에 적재된 레코드 목록.
- `queries` (Array of Object):
  - `query_id` (String): 쿼리 고유 식별자
  - `where` (Object): 컬럼별 조건 맵. 지원 연산자:
    - `eq`: 등가 비교 ($=$)
    - `neq`: 부등 비교 ($\neq$)
    - `gt`, `gte`: 초과($>$), 이상($\ge$)
    - `lt`, `lte`: 미만($<$), 이하($\le$)
    - `in`: 집합 포함 ($\in$)

---

## 출력 형식

표준 출력(stdout)으로 파트 요약 및 각 쿼리별 그래뉼 프루닝, 압축 블록 I/O 분석, 스캔 결과가 포함된 JSON 객체를 한 줄(Single-line)로 출력합니다.

```json
{
  "part_summary": {
    "total_rows": 20,
    "granule_size": 4,
    "total_granules": 5,
    "total_compressed_blocks": 3,
    "primary_key": ["tenant_id", "event_time"],
    "primary_index_entries": 5
  },
  "query_evaluations": [
    {
      "query_id": "Q1",
      "total_granules": 5,
      "granules_read_count": 1,
      "granules_skipped_count": 4,
      "granules_read": [0],
      "granules_skipped": [1, 2, 3, 4],
      "skip_ratio": 0.8,
      "compressed_blocks_loaded": [0],
      "compressed_blocks_count": 1,
      "total_compressed_blocks": 3,
      "rows_scanned": 4,
      "matching_rows_count": 2,
      "pruning_efficiency": 0.8,
      "matching_rows": [
        {"tenant_id": 1, "event_time": 100, "latency_ms": 15},
        {"tenant_id": 1, "event_time": 105, "latency_ms": 25}
      ]
    }
  ]
}
```

### 지표 정의
- `total_granules`: $M = \lceil \text{total\_rows} / \text{granule\_size} \rceil$.
- `total_compressed_blocks`: $\lceil M / \text{marks\_per\_compressed\_block} \rceil$.
- `granules_read` / `granules_skipped`: 프루닝 후 실제 읽은 그래뉼 ID 목록 및 건너뛴 그래뉼 ID 목록.
- `skip_ratio`: 건너뛴 그래뉼 비율 $\frac{\text{granules\_skipped\_count}}{\text{total\_granules}}$ (소수점 4자리 반올림).
- `compressed_blocks_loaded`: 디스크에서 실제로 로드 및 압축 해제해야 하는 압축 블록 번호 목록 (중복 제거).
- `rows_scanned`: 실제 읽은 그래뉼들에 포함된 행 수의 합.
- `pruning_efficiency`: 행 스캔 회피 효율 $1.0 - \frac{\text{rows\_scanned}}{\text{total\_rows}}$ (소수점 4자리 반올림).
- `matching_rows`: 읽은 그래뉼 중에서 실제 `where` 조건을 충족하는 최종 결과 행 목록.
