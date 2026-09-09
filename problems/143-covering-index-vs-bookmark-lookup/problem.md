# [인덱스를 탔는데 왜 풀 테이블 스캔보다 10배 느려요?!: 커버링 인덱스(Covering Index) vs 북마크 룩업(Bookmark Lookup)과 옵티마이저 손익분기점(Tipping Point)]

## 1. 장애 시나리오: "인덱스를 추가했더니 쿼리 응답 속도가 15배 느려져 DB가 폭사한 미스터리"

100만 건의 주문 내역이 쌓인 전자상거래 데이터베이스에서, 최근 주문 상태(`status = 'ACTIVE'`)를 조회하는 API의 응답 속도가 느려졌습니다.
백엔드 개발자는 성능을 개선하겠다고 `status` 컬럼에 B-Tree 인덱스(`idx_orders_status`)를 생성했습니다:

```sql
-- 기존 쿼리 (인덱스 없을 때): Full Table Scan으로 0.1초 소요
SELECT * FROM orders WHERE status = 'ACTIVE';

-- 인덱스 추가 후: EXPLAIN 확인 결과 key: idx_orders_status로 인덱스를 정상적으로 탐!
-- 그러나 실행 시간은 0.1초에서 1.5초(15배!)로 치솟으며 DB CPU가 100% 포화됨!
```

개발자의 당황:
> "아니, `EXPLAIN`을 보면 분명히 인덱스 레인지 스캔(Index Range Scan)을 탔다고 나오는데, 어떻게 전체 데이터를 무식하게 훑는 풀 테이블 스캔(Full Table Scan)보다 15배나 느릴 수가 있죠?!"

이 현상의 주범은 바로 **북마크 룩업(Bookmark Lookup / Table Access)에 의한 랜덤 I/O(Random I/O) 폭풍**입니다.
1. `SELECT *` 쿼리는 인덱스에 포함되지 않은 다른 모든 컬럼(`amount`, `shipping_address`, `created_at` 등)을 필요로 합니다.
2. 따라서 인덱스 리프 노드에서 일치하는 PK 목록 5,000건을 찾은 뒤, **실제 데이터 행을 가져오기 위해 클러스터드 인덱스(테이블 데이터 블록)로 5,000번의 무작위 디스크 접근(Random Fetch)**을 시도합니다.
3. 반면 풀 테이블 스캔(Full Table Scan)은 디스크 블록들을 물리적 순서대로 한 번에 연속해서 퍼 올리는 **순차 I/O(Sequential I/O - Multi-Block Read)**로 동작합니다.
4. 일반적으로 하드디스크나 SSD에서도 랜덤 I/O는 순차 I/O보다 4배~10배 이상 비쌉니다!
5. 데이터 선택도(Selectivity)가 일정 비율(손익분기점, Tipping Point: 보통 전체의 5%~20%)을 넘어가면, **인덱스를 타는 비용이 전체를 다 읽는 비용보다 훨씬 비싸지는 역전 현상**이 발생합니다.
6. 만약 필요한 모든 컬럼을 인덱스에 포함시킨 **커버링 인덱스(Covering Index)**를 구성한다면, 테이블 본문 접근(Bookmark Lookup)이 0건이 되어 초고속 조회가 가능해집니다.

---

## 2. 비용 모델 및 시뮬레이션 사양

본 문제에서는 관계형 데이터베이스 옵티마이저(CBO, Cost-Based Optimizer)의 디스크 I/O 비용 산정 모델을 시뮬레이션합니다.

### (1) 데이터 블록 및 비용 파라미터
- 전체 데이터 건수: `total_rows`
- 데이터 페이지당 행 수: `rows_per_page`
- 인덱스 리프 페이지당 항목 수: `index_rows_per_page`
- 순차 I/O 단위 비용: `sequential_io_cost_per_page` (기본 1.0)
- 랜덤 I/O 단위 비용: `random_io_cost_per_page` (기본 4.0)
- 클러스터링 팩터 비율: `clustering_factor_ratio` ($0.0 \sim 1.0$)
  - 0.0이면 완벽한 정렬(Clustered), 1.0이면 완전 무작위(Unclustered)
- 조건에 매칭되는 행 수: `matching_rows`
- 커버링 인덱스 여부: `is_covering_index` (True/False)
- 실행 계획 강제 힌트: `force_plan` (`"AUTO"`, `"FORCE_INDEX"`, `"FORCE_FTS"`)

### (2) 비용 계산 공식
1. **총 데이터 페이지 수 ($P_{data}$)**:
   $$P_{data} = \lceil 	ext{total\_rows} / 	ext{rows\_per\_page} ceil$$
2. **풀 테이블 스캔 비용 ($Cost_{FTS}$)**:
   $$Cost_{FTS} = P_{data} 	imes 	ext{sequential\_io\_cost\_per\_page}$$
3. **인덱스 스캔 비용 ($Cost_{IDX}$)**:
   - 인덱스 리프 페이지 수: $P_{leaf} = \lceil 	ext{matching\_rows} / 	ext{index\_rows\_per\_page} ceil$
   - 인덱스 리프 스캔 비용: $Cost_{leaf} = P_{leaf} 	imes 	ext{sequential\_io\_cost\_per\_page}$
   - 북마크 룩업(Bookmark Lookup) 방문 데이터 페이지 수:
     - 커버링 인덱스(`is_covering_index == True`)이거나 `matching_rows == 0`이면 $P_{lookup} = 0$.
     - 그렇지 않다면 Yao의 포뮬러 근사치:
       - $P_{clustered} = \min(P_{data}, \lceil 	ext{matching\_rows} / 	ext{rows\_per\_page} ceil)$
       - $P_{unclustered} = P_{data} 	imes (1 - e^{-	ext{matching\_rows} / P_{data}})$
       - $P_{lookup} = \min(P_{data}, \max(1, 	ext{round}((1 - 	ext{ratio}) 	imes P_{clustered} + 	ext{ratio} 	imes P_{unclustered})))$
     - 북마크 룩업 비용: $Cost_{lookup} = P_{lookup} 	imes 	ext{random\_io\_cost\_per\_page}$
   - 총 인덱스 비용: $Cost_{IDX} = Cost_{leaf} + Cost_{lookup}$

### (3) 실행 계획 선택 및 판정
- `force_plan == "AUTO"`: $Cost_{IDX} \le Cost_{FTS}$이면 인덱스 플랜, 아니면 풀 스캔 플랜 선택.
- 최종 판정(`overall_verdict`):
  - 힌트로 인덱스를 강제했는데 FTS보다 느릴 때: `"FORCED_INDEX_PERFORMANCE_DISASTER"`
  - 커버링 인덱스로 룩업 0건: `"COVERING_INDEX_ZERO_BOOKMARK_LOOKUP"`
  - 손익분기점을 초과하여 FTS가 빠를 때: `"TIPPING_POINT_EXCEEDED_FTS_FASTER"`
  - 인덱스가 최적일 때: `"OPTIMAL_INDEX_RANGE_SCAN"`

---

## 3. 입력 형식 (JSON)

표준 입력(stdin)으로 다음 파라미터를 담은 JSON 객체가 주어집니다:

```json
{
  "total_rows": 100000,
  "rows_per_page": 100,
  "index_rows_per_page": 500,
  "sequential_io_cost_per_page": 1.0,
  "random_io_cost_per_page": 4.0,
  "clustering_factor_ratio": 0.8,
  "matching_rows": 5000,
  "is_covering_index": false,
  "force_plan": "AUTO"
}
```

---

## 4. 출력 형식 (JSON)

표준 출력(stdout)으로 다음 구조의 JSON 객체를 인덴트(2칸)를 적용하여 출력합니다:

```json
{
  "summary": {
    "total_rows": 100000,
    "matching_rows": 5000,
    "selectivity_pct": 5.0,
    "total_data_pages": 1000,
    "clustering_factor_ratio": 0.8,
    "is_covering_index": false,
    "force_plan": "AUTO",
    "full_table_scan_cost": 1000.0,
    "index_scan_cost": 3230.0,
    "bookmark_lookup_pages": 805,
    "bookmark_lookup_cost": 3220.0,
    "chosen_execution_plan": "FULL_TABLE_SCAN",
    "final_execution_cost": 1000.0,
    "tipping_point_estimated_pct": 0.37,
    "overall_verdict": "TIPPING_POINT_EXCEEDED_FTS_FASTER"
  }
}
```
