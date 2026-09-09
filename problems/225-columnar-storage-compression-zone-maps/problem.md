# 문제 225: 컬럼형 스토리지 엔진(Columnar Storage): 인코딩 압축(RLE/Dictionary/Bit-Packing)과 존 맵(Zone Map) 데이터 스키핑 시뮬레이터

## 1. 개요 및 배경 (Incident Scenario)

대규모 핀테크 결제 플랫폼의 실시간 거래 분석(OLAP) 클러스터에서 심각한 쿼리 지연 장애가 보고되었습니다. 일일 수억 건의 결제 트랜잭션이 유입되는 거래 이력 테이블에서 재무 분석팀이 실행하는 분기별 매출 집계 쿼리(`SELECT region, SUM(amount) FROM transactions WHERE date >= 20261001`)가 기존 관계형 행 기반 스토리지(Row-Oriented Heap Table, e.g. PostgreSQL) 환경에서 SLA 타임아웃(100ms)을 대폭 초과하여 평균 600ms 이상 소요되며 디스크 I/O 대역폭을 완전히 고갈(`ROW_STORE_SCAN_BANDWIDTH_EXHAUSTION`)시켰습니다.

원인 분석 결과, 행 기반 스토리지 엔진(NSM: N-ary Storage Model)은 쿼리에서 필요한 2~3개의 컬럼(`date`, `region`, `amount`)만을 조회하더라도 디스크 블록(Page) 단위로 행 전체(사용자 암호화 메타데이터, 페이로드 등 256바이트 이상의 비프로젝션 컬럼 포함)를 모조리 디스크에서 메모리로 읽어 들여야 했습니다. 100만 행 기준 무려 286MB 이상의 디스크 I/O가 강제 발생했습니다.

인프라 엔지니어링 팀은 분석 쿼리 워크로드를 컬럼 기반 스토리지(Columnar Storage: Apache Parquet, ClickHouse, DuckDB 형태)로 전면 마이그레이션하기로 결정했습니다.
컬럼 기반 스토리지는 다음의 세 가지 핵심 최적화를 구현합니다:
1. **컬럼 투영 프로젝션(Column Projection Pruning)**: 쿼리에서 참조하는 컬럼(`region`, `amount`, `date`)의 데이터 페이지만 선택적으로 I/O를 수행하여 불필요한 컬럼 페이로드를 원천 배제합니다.
2. **로우 그룹 존 맵(Row Group Zone Map / Min-Max Data Skipping)**: 데이터를 고정 크기(예: 64,000행) 로우 그룹 단위로 분할하고, 각 로우 그룹 메타데이터에 정렬 컬럼의 최소값(`min`)과 최대값(`max`)을 기록합니다. 쿼리 조건절(`WHERE date >= 20261001`)과 오버랩되지 않는 로우 그룹은 디스크 블록 자체를 전혀 읽지 않고 건너뜁니다(Data Skipping).
3. **특화 컬럼 인코딩(Columnar Encodings)**:
   - **RLE(Run-Length Encoding)**: 정렬되어 있거나 동일 값이 연속되는 저카디널리티 컬럼을 `(값, 반복횟수)` 튜플로 압축하여 최대 25배 이상 압축.
   - **딕셔너리 인코딩(Dictionary Encoding)**: 고유값 개수가 적은 컬럼(카디널리티 ≤ 256)에 대해 중복 문자열 대신 1바이트 정수 ID로 대체. 단, 카디널리티가 로우 그룹 크기의 80%를 초과하는 고유값 컬럼(예: UUID)에 무리하게 적용 시 메타데이터 팽창으로 인한 성능 폭망(`DICTIONARY_CARDINALITY_EXPLOSION_FALLBACK`)이 발생하므로 감지해야 합니다.
   - **비트 패킹(Bit-Packing)**: 정수 최대값 크기에 맞추어 가변 비트(예: 카디널리티 7 이하 시 3비트) 단위로 데이터를 빽빽하게 패킹.

본 문제에서는 스토리지 포맷(행 기반 vs 컬럼 기반), 존 맵 활성화 여부, 컬럼 인코딩 방식 및 디스크 I/O 대역폭을 기반으로 쿼리 실행 메트릭을 계산하고 진단 판정을 도출하는 컬럼형 스토리지 시뮬레이터를 구현합니다.

---

## 2. 아키텍처 및 데이터 흐름 (Architecture)

```
[Row-Oriented Heap Storage (PostgreSQL style)]
Page 0: [Row 0: ID | Date | Region | Status | Amount | ExtraPayload (256B)] -> Read FULL Row
Page 1: [Row 1: ID | Date | Region | Status | Amount | ExtraPayload (256B)] -> Read FULL Row
=> Disadvantage: Massive I/O bandwidth wasted on unprojected 'ExtraPayload' column!

---------------------------------------------------------------------------------

[Columnar Storage Engine (Parquet / ClickHouse style)]
Table Schema: 1,000,000 Rows divided into Row Groups (e.g. 64,000 rows each)
+-------------------------------------------------------------------------------+
| Row Group 0 (Rows 0 ~ 63,999)                                                 |
| Zone Map Metadata: date [20260101 ~ 20260123]  <-- Predicate: date >= 20261001 |
| => [SKIP ROW GROUP 0 ENTIRELY!] (Zero Disk I/O)                              |
+-------------------------------------------------------------------------------+
| ...                                                                           |
+-------------------------------------------------------------------------------+
| Row Group 15 (Rows 960,000 ~ 999,999)                                         |
| Zone Map Metadata: date [20261015 ~ 20261231]  <-- Matches Predicate!         |
| => [READ ACCESSED COLUMNS ONLY]                                               |
|    - Column 'date'   : Evaluated via Zone Map                                 |
|    - Column 'region' : Dictionary Encoded (1 Byte IDs)                        |
|    - Column 'amount' : Bit-Packed / Plain Numeric Stream                      |
|    - Column 'payload': NOT READ! (Skipped entirely)                           |
+-------------------------------------------------------------------------------+
```

---

## 3. 입력 형식 (Input Specification)

표준 입력(stdin)으로 JSON 객체가 주어집니다:

```json
{
  "config": {
    "storage_format": "COLUMNAR",
    "row_group_size": 64000,
    "zone_maps_enabled": true,
    "disk_read_bandwidth_mbps": 500.0,
    "query_sla_timeout_ms": 100.0
  },
  "schema": {
    "total_rows": 1000000,
    "columns": [
      {
        "name": "id",
        "uncompressed_bytes_per_value": 8,
        "cardinality": 1000000,
        "is_sorted": true,
        "min_val": 1,
        "max_val": 1000000,
        "encoding": "AUTO"
      },
      {
        "name": "date",
        "uncompressed_bytes_per_value": 4,
        "cardinality": 365,
        "is_sorted": true,
        "min_val": 20260101,
        "max_val": 20261231,
        "encoding": "AUTO"
      },
      {
        "name": "region",
        "uncompressed_bytes_per_value": 16,
        "cardinality": 5,
        "is_sorted": false,
        "encoding": "AUTO"
      }
    ]
  },
  "query": {
    "projected_columns": ["region"],
    "predicate": {
      "column": "date",
      "op": ">=",
      "val": 20261001
    }
  }
}
```

- `config`:
  - `storage_format`: `"ROW_ORIENTED"` 또는 `"COLUMNAR"`
  - `row_group_size`: 로우 그룹 당 행 수 (기본 64000)
  - `zone_maps_enabled`: 존 맵 기반 데이터 스키핑 사용 여부 (boolean)
  - `disk_read_bandwidth_mbps`: 디스크 순차 읽기 대역폭 (MB/s)
  - `query_sla_timeout_ms`: 쿼리 허용 최대 지연 시간 (ms)
- `schema`:
  - `total_rows`: 전체 행 수
  - `columns`: 각 컬럼 정의 (`name`, `uncompressed_bytes_per_value`, `cardinality`, `is_sorted`, `min_val`, `max_val`, `encoding`)
    - `encoding`이 `"AUTO"`인 경우: 정렬되어 있고 카디널리티 ≤ 50이면 `"RLE"`, 카디널리티 ≤ 256이면 `"DICTIONARY"`, 카디널리티 ≤ 16이면 `"BIT_PACKING"`, 그 외에는 `"PLAIN"`.
- `query`:
  - `projected_columns`: SELECT 절에 지정된 컬럼 목록
  - `predicate` 또는 `predicates`: WHERE 조건절 (`column`, `op`, `val`). 조건 연산자는 `>=`, `<=`, `>`, `<`, `=` 지원.

---

## 4. 인코딩 및 스토리지 연산 공식

1. **로우 그룹 및 접근 컬럼 계산**:
   - $\text{num\_row\_groups} = \lceil \text{total\_rows} / \text{row\_group\_size} \rceil$
   - 접근 대상 컬럼 집합 = $\text{projected\_columns} \cup \{ p.\text{column} \mid p \in \text{predicates} \}$
2. **행 기반 스토리지 (ROW_ORIENTED)**:
   - 모든 로우 그룹을 스캔하며, 모든 컬럼(접근하지 않는 컬럼 포함)의 원시 바이트를 읽음:
     $$\text{total\_bytes\_read} = \text{total\_rows} \times \sum_{c \in \text{columns}} c.\text{uncompressed\_bytes\_per\_value}$$
   - CPU 역직렬화 시간: $\text{cpu\_time\_ms} = \text{total\_rows} \times 0.00005$ ms
3. **컬럼 기반 스토리지 (COLUMNAR)**:
   - 각 로우 그룹 $i$ ($i = 0, \dots, \text{num\_row\_groups}-1$)에 대해:
     - `zone_maps_enabled`가 참이고 정렬 컬럼에 대한 조건절이 존재하는 경우:
       - 해당 로우 그룹의 범위:
         $$\text{step} = \frac{\text{max\_val} - \text{min\_val}}{\text{num\_row\_groups}}$$
         $$\text{rg\_min} = \text{min\_val} + i \times \text{step}, \quad \text{rg\_max} = \text{min\_val} + (i+1) \times \text{step}$$
       - 조건절(`>=`, `<=`, `>`, `<`, `=`)과 비교하여 범위 밖이면 해당 로우 그룹은 스킵 (`skipped_row_groups += 1`).
     - 스킵되지 않은 로우 그룹만 스캔하며, 접근 대상 컬럼 집합에 속한 컬럼에 대해서만 바이트를 읽음:
       - **RLE**: $\text{rg\_rows} \times (\text{raw\_bytes} / 25.0)$
       - **DICTIONARY**:
         - 카디널리티 > $\text{rg\_rows} \times 0.8$ 이면 딕셔너리 폭발 감지 (`dict_explosion_detected = True`), $\text{col\_bytes} = \text{rg\_rows} \times \text{raw\_bytes} \times 1.25$
         - 정상 시: $\text{dict\_size} = \text{cardinality} \times \text{raw\_bytes}$, $\text{id\_size} = 1 \text{ (카디널리티} \le 256) \text{ else } 2$, $\text{col\_bytes} = \text{dict\_size} + (\text{rg\_rows} \times \text{id\_size})$
       - **BIT_PACKING**: $\text{bits} = \max(1, \lceil \log_2(\text{cardinality}+1) \rceil)$, $\text{col\_bytes} = (\text{rg\_rows} \times \text{bits}) / 8.0$
       - **PLAIN**: $\text{col\_bytes} = \text{rg\_rows} \times \text{raw\_bytes}$
   - CPU 벡터화 시간: $\text{cpu\_time\_ms} = (\text{scanned\_row\_groups} \times \text{row\_group\_size}) \times 0.00001$ ms
4. **지연 시간 및 절감율 계산**:
   - $\text{total\_bytes\_read\_mb} = \text{total\_bytes\_read} / (1024 \times 1024)$
   - $\text{io\_time\_ms} = (\text{total\_bytes\_read\_mb} / \text{disk\_bandwidth}) \times 1000$
   - $\text{total\_query\_latency\_ms} = \text{io\_time\_ms} + \text{cpu\_time\_ms}$
   - $\text{raw\_uncompressed\_mb} = (\text{total\_rows} \times \sum \text{raw\_bytes}) / (1024 \times 1024)$
   - $\text{data\_reduction\_ratio} = \max(0.0, 1.0 - (\text{total\_bytes\_read\_mb} / \text{raw\_uncompressed\_mb}))$

---

## 5. 진단 판정 (Verdict Rules)

1. `dict_explosion_detected`가 True인 경우:
   - `status`: `"FAILED"`
   - `verdict`: `"DICTIONARY_CARDINALITY_EXPLOSION_FALLBACK"`
2. `storage_format == "ROW_ORIENTED"`:
   - $\text{total\_query\_latency\_ms} > \text{sla\_timeout\_ms}$:
     - `status`: `"FAILED"`
     - `verdict`: `"ROW_STORE_SCAN_BANDWIDTH_EXHAUSTION"`
   - 그렇지 않은 경우:
     - `status`: `"SUCCESS"`
     - `verdict`: `"STANDARD_ROW_SCAN_SUCCESS"`
3. `storage_format == "COLUMNAR"`:
   - $\text{total\_query\_latency\_ms} > \text{sla\_timeout\_ms}$:
     - `status`: `"FAILED"`
     - `verdict`: `"QUERY_SLA_TIMEOUT_EXCEEDED"`
   - $\text{skipped\_row\_groups} > 0$ 이고 $\text{data\_reduction\_ratio} \ge 0.75$:
     - `status`: `"SUCCESS"`
     - `verdict`: `"OPTIMAL_COLUMNAR_VECTORIZED_SCAN"`
   - 그 외의 경우 (스킵 없이 전수 스캔되었으나 컬럼 프로젝션으로 성공한 경우 등):
     - `status`: `"SUCCESS"`
     - `verdict`: `"COLUMNAR_NO_ZONE_MAP_PARTIAL_SCAN"`

---

## 6. 출력 형식 (Output Specification)

표준 출력(stdout)으로 다음 형식의 JSON 객체를 한 줄로 출력합니다:

```json
{
  "status": "SUCCESS",
  "verdict": "OPTIMAL_COLUMNAR_VECTORIZED_SCAN",
  "metrics": {
    "storage_format": "COLUMNAR",
    "total_bytes_read_mb": 2.88,
    "raw_uncompressed_mb": 286.1,
    "data_reduction_ratio": 0.9899,
    "total_row_groups": 16,
    "skipped_row_groups": 12,
    "scanned_row_groups": 4,
    "total_query_latency_ms": 8.31
  }
}
```
