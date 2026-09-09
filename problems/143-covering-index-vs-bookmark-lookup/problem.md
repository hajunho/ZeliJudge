# #143 인덱스를 탔는데 왜 풀 테이블 스캔보다 10배 느려요?!: 커버링 인덱스(Covering Index) vs 북마크 룩업(Bookmark Lookup / Random I/O)과 옵티마이저 손익분기점(Tipping Point)

## 1. 실무 장애 시나리오: "인덱스를 걸었는데 서버가 더 느려졌어요!"

온라인 커머스 플랫폼 백엔드 팀의 신입 엔지니어 호준이는 주문 관리 백오피스에서 '배송 완료(SHIPPED)' 상태의 주문을 조회하는 화면이 1~2초씩 버벅거린다는 CS 제보를 받았습니다.

호준이는 데이터베이스 쿼리를 확인했습니다:
```sql
SELECT * 
FROM orders 
WHERE status = 'SHIPPED';
```

전체 10만 건 주문 중 '배송 완료' 주문은 약 5,000건(5%)이었습니다.
"아! `status` 컬럼에 인덱스가 없어서 풀 테이블 스캔(Full Table Scan)을 하느라 느렸구나!"

호준이는 즉시 프로덕션 데이터베이스에 세컨더리 B-Tree 인덱스를 생성했습니다:
```sql
CREATE INDEX idx_orders_status ON orders(status);
```

그리고 뿌듯한 마음으로 `EXPLAIN` 실행 계획을 확인했습니다. 그런데 이상하게도 옵티마이저가 인덱스를 타지 않고 여전히 **`type: ALL` (Full Table Scan)**을 선택하고 있었습니다.

"인덱스를 만들어 줬는데 왜 안 타지? 옵티마이저가 멍청한가 보네!"  
호준이는 자신만만하게 쿼리에 **`FORCE INDEX`** 힌트를 때려 박았습니다:
```sql
SELECT * 
FROM orders FORCE INDEX (idx_orders_status)
WHERE status = 'SHIPPED';
```

배포 직후, 기적(?)이 일어났습니다.  
기존 풀 테이블 스캔 시 0.2초 걸리던 쿼리가 **무려 1.5초 이상으로 7~8배 느려졌고**, 데이터베이스 서버의 **디스크 I/O 대기율(iowait)과 CPU 사용률이 100%로 치솟으며** 백오피스뿐만 아니라 쇼핑몰 전체 주문 결제 시스템이 올스톱되는 전사 장애가 터졌습니다!

황급히 달려온 시니어 DBA 지우 님이 `FORCE INDEX`를 즉시 제거하여 급한 불을 끈 뒤 호준이에게 모니터를 보여주었습니다:

> "호준 님, 세컨더리 인덱스는 인덱스 키(`status`)와 프라이머리 키(PK)만 들고 있어요. `SELECT *`로 모든 컬럼을 조회하면, 인덱스에서 찾은 5,000건의 행마다 실제 데이터 페이지를 읽으러 디스크 헤드가 이리저리 널뛰는 **북마크 룩업(Bookmark Lookup / Random I/O)**이 5,000번 발생합니다!  
> 풀 테이블 스캔은 디스크 블록을 쭉쭉 연속으로 긁어오는 **순차 I/O(Sequential Read)**라서 1,000페이지만 읽으면 끝나는데, 인덱스를 강제하면 무작위로 수천 번 디스크를 때리니 당연히 10배 느려지죠!  
> 옵티마이저는 이 **손익분기점(Tipping Point)**을 정확히 알고 풀 스캔을 선택했던 겁니다.  
> 이 쿼리를 진짜 100배 빠르게 만들려면, 테이블 방문 자체를 0회로 없애버리는 **커버링 인덱스(Covering Index)**를 써야 합니다!"

DBA 지우 님이 필요한 컬럼을 모두 포함하는 복합 커버링 인덱스를 생성하자, 북마크 룩업이 **정확히 0회**로 소멸하며 쿼리는 0.002초 만에 초고속으로 완료되었습니다.

---

## 2. 핵심 이론: 북마크 룩업과 옵티마이저 손익분기점

### (1) 클러스터드 인덱스 vs 세컨더리 인덱스 구조
* **클러스터드 인덱스 (Clustered Index, 주로 PK)**:
  * 리프 노드(Leaf Node) 자체가 실제 행의 **모든 데이터 컬럼(Row Data)**을 직접 보관하고 있습니다.
* **세컨더리 인덱스 (Secondary Index / Non-Clustered Index)**:
  * 리프 노드에 **인덱스 컬럼 값**과 해당 행을 식별할 수 있는 **북마크(Bookmark, 클러스터드 인덱스 PK 값 또는 RID)**만 보관합니다.
  * 따라서 인덱스에 포함되지 않은 컬럼을 `SELECT`하려면, 인덱스 리프 노드에서 PK를 꺼내 테이블(클러스터드 인덱스) 데이터 페이지를 다시 조회하는 **북마크 룩업(Bookmark Lookup / Table Access by Index RowID)**을 거쳐야 합니다.

### (2) 순차 I/O(Sequential I/O) vs 무작위 I/O(Random I/O)
* **풀 테이블 스캔 (Full Table Scan, FTS)**:
  * 멀티블록 읽기(Multi-Block I/O)를 통해 디스크의 연속된 데이터 블록을 한 번에 수십~수백 개씩 대량으로 읽어 들입니다.
  * 디스크 헤드의 물리적 탐색(Seek)이 거의 발생하지 않아 블록당 처리 단가가 매우 저렴합니다 ($Cost_{seq} pprox 1.0$).
* **북마크 룩업 (Bookmark Lookup)**:
  * 세컨더리 인덱스는 인덱스 키 순서대로 정렬되어 있지만, 실제 테이블의 물리 데이터 페이지 위치는 무작위로 흩어져 있습니다.
  * 인덱스에서 1건을 찾을 때마다 서로 다른 데이터 페이지로 점프하는 **싱글블록 무작위 읽기(Single-Block Random I/O)**를 유발합니다 ($Cost_{rand} pprox 4.0$).

### (3) 비용 기반 옵티마이저(CBO)의 손익분기점 (Tipping Point)
데이터베이스 옵티마이저는 두 실행 계획의 예상 I/O 비용을 계산하여 더 저렴한 쪽을 선택합니다:

$$Cost_{FTS} = TotalDataPages 	imes Cost_{seq}$$

$$Cost_{Index} = IndexLeafPages 	imes Cost_{seq} + BookmarkLookupPages 	imes Cost_{rand}$$

* **손익분기점 (Tipping Point)**:
  * 조건절을 만족하는 행의 비율(선택도, Selectivity)이 보통 **10% ~ 20%**(데이터 분포에 따라 1% ~ 25%)를 초과하면, 북마크 룩업의 랜덤 I/O 비용이 전체 테이블을 순차 스캔하는 비용을 훌쩍 넘어서게 됩니다.
  * 이 지점을 넘어가면 옵티마이저는 인덱스를 버리고 **풀 테이블 스캔(Full Table Scan)**을 채택합니다.
  * 여기에 무지성 `FORCE INDEX`를 걸면 성능이 곤두박질치는 **튜닝 참사**가 일어납니다.

### (4) 커버링 인덱스 (Covering Index / Index-Only Scan)의 기적
* 쿼리에 필요한 모든 컬럼(SELECT 절, WHERE 절, ORDER BY 절 등)이 인덱스 키에 모두 포함되어 있는 인덱스입니다.
* 데이터 행을 찾으러 테이블 데이터 페이지로 갈 필요가 전혀 없으므로, **북마크 룩업 횟수가 정확히 0회(Zero Table Access)**가 됩니다.
* 오직 인덱스 리프 페이지만 순차 스캔하므로 풀 테이블 스캔 대비 **수십~수백 배의 비약적인 성능 가속**을 달성합니다.

---

## 3. 입출력 규격 및 요구사항

여러분의 임무는 테이블 통계, I/O 비용 모델, 쿼리 조건 및 인덱스 형태가 주어졌을 때 데이터베이스 비용 기반 옵티마이저(CBO)의 동작을 정확히 시뮬레이션하고, 최적 실행 계획과 북마크 룩업 비용, 손익분기점 및 최종 진단을 도출하는 평가 엔진을 구현하는 것입니다.

### 입력 형식 (JSON)
표준 입력(stdin)으로 다음 필드를 갖는 JSON 객체가 전달됩니다:
* `total_rows`: 전체 테이블 행 수 (정수, 0 이상)
* `rows_per_page`: 데이터 페이지 1장에 담기는 행 수 (기본: 100)
* `index_rows_per_page`: 인덱스 리프 페이지 1장에 담기는 엔트리 수 (기본: 500)
* `sequential_io_cost_per_page`: 순차 I/O 1페이지당 비용 가중치 (실수, 기본: 1.0)
* `random_io_cost_per_page`: 무작위 I/O 1페이지당 비용 가중치 (실수, 기본: 4.0)
* `clustering_factor_ratio`: 데이터 물리 배치 무작위도 ($0.0 \sim 1.0$, 0.0: 완전 정렬, 1.0: 완전 무작위, 기본: 0.8)
* `matching_rows`: 조건절을 만족하는 조회 행 수 (정수, 0 이상)
* `is_covering_index`: 커버링 인덱스 적용 여부 (불리언)
* `force_plan`: 힌트 적용 모드 (`"AUTO"`, `"FORCE_INDEX"`, `"FORCE_FTS"`)

### 출력 형식 (JSON)
표준 출력(stdout)으로 다음 구조의 JSON 객체를 반환합니다:
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

### 세부 계산 규칙
1. **총 데이터 페이지 수**: $\lceil TotalRows / RowsPerPage ceil$
2. **풀 테이블 스캔 비용**: $TotalDataPages 	imes SequentialIOCost$ (소수점 둘째 자리 반올림)
3. **인덱스 리프 페이지 수**: $\lceil MatchingRows / IndexRowsPerPage ceil$
4. **북마크 룩업 방문 페이지 수 ($VisitedPages$)**:
   * `is_covering_index`가 `true`이거나 `matching_rows == 0`인 경우: $0$
   * 그 외:
     * $ClusteredPages = \min(TotalDataPages, \lceil MatchingRows / RowsPerPage ceil)$
     * $UnclusteredPages = TotalDataPages 	imes (1.0 - e^{-MatchingRows / TotalDataPages})$ (Cady/Mackert 공식)
     * $VisitedPages = 	ext{round}((1.0 - ClusteringFactor) 	imes ClusteredPages + ClusteringFactor 	imes UnclusteredPages)$
     * $VisitedPages$는 최소 1(매칭 행이 1 이상일 때), 최대 $TotalDataPages$ 범위로 제한
5. **북마크 룩업 비용**: $VisitedPages 	imes RandomIOCost$
6. **인덱스 스캔 총비용**: $IndexLeafPages 	imes SequentialIOCost + BookmarkLookupCost$ (소수점 둘째 자리 반올림)
7. **실행 계획 선택 (`chosen_execution_plan`)**:
   * `force_plan == "FORCE_INDEX"`: `is_covering_index`면 `"INDEX_ONLY_COVERING_SCAN"`, 아니면 `"INDEX_RANGE_SCAN"`
   * `force_plan == "FORCE_FTS"`: `"FULL_TABLE_SCAN"`
   * `force_plan == "AUTO"`:
     * $IndexScanCost \le FullTableScanCost$이면: 커버링 시 `"INDEX_ONLY_COVERING_SCAN"`, 비커버링 시 `"INDEX_RANGE_SCAN"`
     * 아니면: `"FULL_TABLE_SCAN"`
8. **손익분기점 추정 (`tipping_point_estimated_pct`)**:
   * 비커버링 인덱스인 경우, 이분 탐색(Binary Search, 30회)을 통해 인덱스 비용 $\ge$ 풀 스캔 비용이 되는 매칭 행 수 $M$을 찾아 $(M / TotalRows) 	imes 100.0$을 백분율(소수점 둘째 자리 반올림)로 산출.
   * 커버링 인덱스인 경우 $100.0$.
9. **종합 판정 (`overall_verdict`)**:
   * `force_plan == "FORCE_INDEX"`이면서 $IndexScanCost > FullTableScanCost$: `"FORCED_INDEX_PERFORMANCE_DISASTER"`
   * `is_covering_index == true`: `"COVERING_INDEX_ZERO_BOOKMARK_LOOKUP"`
   * `chosen_execution_plan == "FULL_TABLE_SCAN"`이면서 $SelectivityPct \ge TippingPointPct$: `"TIPPING_POINT_EXCEEDED_FTS_FASTER"`
   * `chosen_execution_plan == "INDEX_RANGE_SCAN"`: `"OPTIMAL_INDEX_RANGE_SCAN"`
   * 그 외: `"BALANCED_PLAN"`

---

## 4. 입출력 예시

### 예시 1: 5% 선택도 비커버링 인덱스 (CBO가 풀 테이블 스캔을 선택)

#### 입력
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

#### 출력
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

### 예시 2: 5% 선택도 커버링 인덱스 (북마크 룩업 0회, 100배 가속)

#### 입력
```json
{
  "total_rows": 100000,
  "rows_per_page": 100,
  "index_rows_per_page": 500,
  "sequential_io_cost_per_page": 1.0,
  "random_io_cost_per_page": 4.0,
  "clustering_factor_ratio": 0.8,
  "matching_rows": 5000,
  "is_covering_index": true,
  "force_plan": "AUTO"
}
```

#### 출력
```json
{
  "summary": {
    "total_rows": 100000,
    "matching_rows": 5000,
    "selectivity_pct": 5.0,
    "total_data_pages": 1000,
    "clustering_factor_ratio": 0.8,
    "is_covering_index": true,
    "force_plan": "AUTO",
    "full_table_scan_cost": 1000.0,
    "index_scan_cost": 10.0,
    "bookmark_lookup_pages": 0,
    "bookmark_lookup_cost": 0.0,
    "chosen_execution_plan": "INDEX_ONLY_COVERING_SCAN",
    "final_execution_cost": 10.0,
    "tipping_point_estimated_pct": 100.0,
    "overall_verdict": "COVERING_INDEX_ZERO_BOOKMARK_LOOKUP"
  }
}
```
