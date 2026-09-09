# Problem 067: DB 인덱스와 SARGable 쿼리 최적화 (B-Tree Indexing & SARGable Queries)

## 문제 설명

이커머스 서비스의 백엔드를 운영하던 당신의 팀에서 블랙 프라이데이 세일 도중 치명적인 DB 장애가 발생했습니다:
> "분명히 `price`, `created_date`, `sku` 컬럼에 B-Tree 인덱스를 걸어두었는데, 상품 검색 API가 호출될 때마다 DB CPU가 100%로 치솟고 타임아웃이 터집니다!  
> 실행 계획(`EXPLAIN`)을 확인해보니 인덱스를 전혀 타지 않고 **전체 1,000만 건을 전수 조사하는 Full Table Scan**이 돌고 있습니다!"

원인은 주니어 개발자들이 편리함 때문에 쿼리 조건절의 좌변(컬럼 쪽)을 함수나 산술 연산자로 감싸버린 **Non-SARGable 쿼리 안티패턴**이었습니다:
- `WHERE price * 1.1 >= 55000`: 부가세를 계산하겠다고 컬럼에 곱셈 연산을 걸어버려 B-Tree 정렬 순서가 무력화되었습니다.
- `WHERE YEAR(created_date) = 2026`: 연도만 추출하겠다고 날짜 함수(`YEAR()`)를 씌워 모든 레코드의 날짜를 일일이 파싱해야 했습니다.
- `WHERE SUBSTRING(sku, 1, 4) = 'ELEC'`: 접두어를 확인하겠다고 문자열 슬라이싱 함수를 호출하여 인덱스를 무용지물로 만들었습니다.

전화번호부에서 "성(姓)이 '김'씨인 사람"을 찾을 때는 'ㄱ' 색인을 펼쳐 0.1초 만에 직행할 수 있지만, "끝 글자가 '우'인 사람"을 찾으려면 100만 명의 전화번호부를 1페이지부터 끝까지 한 장씩 넘겨야 하는 것과 같습니다.

B-Tree 인덱스를 정상적으로 활용하려면 조건절 좌변의 컬럼을 순수하게 유지하고, 연산과 함수를 우변(상수 쪽)으로 이항하여 **B-Tree Index Range Scan**이 가능한 **SARGable(Search Argument Able) 형태**로 변환해야 합니다.

당신은 동일한 상품 데이터셋과 쿼리 스트림에 대해 **Naive Full Table Scan 엔진**과 **SARGable B-Tree Index Scan 엔진**의 디스크/메모리 행 스캔 횟수(`ROWS_EXAMINED`)와 검색 결과 일치 여부를 비교 시뮬레이션하는 데이터베이스 최적화 엔진을 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 데이터 테이블 구조
각 상품 레코드는 공백으로 구분된 5개의 필드로 주어집니다:
- `id` (정수): 고유 상품 식별자 (1부터 시작)
- `category` (문자열): 상품 카테고리 (예: ELEC, BOOK, FOOD 등)
- `price` (정수): 상품 가격 (1 이상의 정수)
- `created_date` (문자열): 등록 날짜 (`YYYY-MM-DD` 형식)
- `sku` (문자열): 재고 관리 코드 (예: `ELEC-101`, `BOOK-001`)

### 2. B-Tree 인덱스 및 탐색 비용 모델
전체 레코드 수를 $N$이라 할 때:
- `price`, `created_date`, `sku` 각각에 대해 오름차순 정렬된 B-Tree 인덱스가 사전에 구축되어 있습니다.
- B-Tree 탐색 깊이(Tree Height Penalty):
  $$H = \max(1, \lceil \log_2 N \rceil)$$
  - 단, $N = 0$인 경우 $H = 1$입니다.

#### 1) Naive 엔진 (Non-SARGable Full Table Scan)
- 조건절 좌변 컬럼을 그대로 가공하여 전수 검사하므로, 쿼리 1회당 검사하는 행 수는 항상 전체 레코드 수입니다:
  $$\text{ROWS\_EXAMINED} = N$$

#### 2) SARGable 엔진 (B-Tree Index Range Scan)
- 조건절을 순수 컬럼과 상수의 범위 형태로 변환하여 B-Tree 이진 탐색(Binary Search)으로 시작점과 끝점을 찾습니다.
- 해당 범위를 스캔하는 데 드는 비용은 **루트에서 리프까지의 트리 탐색 비용 $H$ + 범위 내 리프 노드 레코드 수**입니다:
  $$\text{ROWS\_EXAMINED} = H + (\text{right} - \text{left})$$
- 절감된 행 수:
  $$\text{ROWS\_SAVED} = \max(0, N - \text{ROWS\_EXAMINED}_{\text{sargable}})$$

---

### 3. 4대 쿼리 유형 및 SARGable 변환 규칙

모든 가격 `price`는 정수이므로, 정수 경계값으로 올바르게 변환해야 합니다:

#### 1) `QUERY_PRICE_ARITHMETIC <multiplier> <op> <target_val>`
- **Naive 조건**: `price * multiplier (op) target_val` (부동소수점 오차 방지를 위해 $10^{-9}$ 엡실론 적용)
- **SARGable 변환**:
  - `op`가 `>=`: `price >= ceil(target_val / multiplier)` $\implies$ 범위 `[low_price, +inf)`
  - `op`가 `>`: `price >= floor(target_val / multiplier) + 1` $\implies$ 범위 `[low_price, +inf)`
  - `op`가 `<=`: `price <= floor(target_val / multiplier)` $\implies$ 범위 `(-inf, high_price]`
  - `op`가 `<`: `price <= ceil(target_val / multiplier) - 1` $\implies$ 범위 `(-inf, high_price]`

#### 2) `QUERY_DATE_YEAR <target_year>`
- **Naive 조건**: `int(created_date[0:4]) == target_year`
- **SARGable 변환**: 연초부터 연말까지의 날짜 범위 검색으로 변환:
  - `created_date >= YYYY-01-01 AND created_date <= YYYY-12-31` $\implies$ 범위 `['YYYY-01-01', 'YYYY-12-31']`

#### 3) `QUERY_SKU_PREFIX <prefix>`
- **Naive 조건**: `sku.startswith(prefix)`
- **SARGable 변환**: 접두어 범위 검색으로 변환:
  - `sku >= prefix AND sku <= prefix + '\uffff'` $\implies$ 범위 `[prefix, prefix + '\uffff']`

#### 4) `QUERY_SKU_SUBSTRING <length> <target_val>`
- **Naive 조건**: `sku[0:length] == target_val`
- **SARGable 변환**: 0번 인덱스부터 시작하는 서브스트링은 접두어 검색과 동일:
  - `sku >= target_val AND sku <= target_val + '\uffff'` $\implies$ 범위 `[target_val, target_val + '\uffff']`

---

## 입력 형식

입력은 `TABLE_DATA` 섹션과 `QUERIES` 섹션으로 구성됩니다:

```text
TABLE_DATA
<id> <category> <price> <created_date> <sku>
...
QUERIES
<query_cmd> <args...>
...
```

---

## 출력 형식

1. 각 쿼리 실행 결과 (3줄):
```text
ACT <query_index> <query_str>
  NAIVE: PLAN=FULL_TABLE_SCAN ROWS_EXAMINED:<cnt> ROWS_MATCHED:<matches>
  SARGABLE: PLAN=INDEX_RANGE_SCAN ROWS_EXAMINED:<cnt> ROWS_MATCHED:<matches> ROWS_SAVED:<saved>
```

2. 모든 쿼리 종료 후 최종 통계 요약 (4줄):
```text
SUMMARY NAIVE TOTAL_ROWS_EXAMINED:<total_naive>
SUMMARY SARGABLE TOTAL_ROWS_EXAMINED:<total_sargable>
SUMMARY ROWS_SAVED:<total_saved> (SCAN_REDUCTION:<reduction_pct>%)
SUMMARY ACCURACY_CHECK: 100% IDENTICAL RESULTS
```
- `<reduction_pct>`: `(total_saved / total_naive) * 100` (소수점 둘째 자리 포맷)
- 모든 쿼리에서 Naive 결과와 SARGable 결과의 일치 여부에 따라 `100% IDENTICAL RESULTS` 또는 `MISMATCH_DETECTED` 출력.

---

## 입출력 예시

### 예시 1

**입력:**
```text
TABLE_DATA
1 ELEC 10000 2025-05-01 ELEC-101
2 ELEC 20000 2025-08-15 ELEC-102
3 ELEC 30000 2026-01-10 ELEC-201
4 ELEC 40000 2026-03-20 ELEC-202
5 ELEC 50000 2026-06-30 ELEC-301
6 BOOK 15000 2025-02-14 BOOK-001
7 BOOK 25000 2026-04-05 BOOK-002
8 BOOK 35000 2026-07-22 BOOK-003
9 FOOD 5000 2026-01-01 FOOD-010
10 FOOD 8000 2026-09-09 FOOD-020
QUERIES
QUERY_PRICE_ARITHMETIC 1.1 >= 33000
QUERY_DATE_YEAR 2026
QUERY_SKU_PREFIX ELEC-2
QUERY_SKU_SUBSTRING 4 BOOK
```

**출력:**
```text
ACT 1 QUERY_PRICE_ARITHMETIC 1.1 >= 33000
  NAIVE: PLAN=FULL_TABLE_SCAN ROWS_EXAMINED:10 ROWS_MATCHED:4
  SARGABLE: PLAN=INDEX_RANGE_SCAN ROWS_EXAMINED:8 ROWS_MATCHED:4 ROWS_SAVED:2
ACT 2 QUERY_DATE_YEAR 2026
  NAIVE: PLAN=FULL_TABLE_SCAN ROWS_EXAMINED:10 ROWS_MATCHED:7
  SARGABLE: PLAN=INDEX_RANGE_SCAN ROWS_EXAMINED:11 ROWS_MATCHED:7 ROWS_SAVED:0
ACT 3 QUERY_SKU_PREFIX ELEC-2
  NAIVE: PLAN=FULL_TABLE_SCAN ROWS_EXAMINED:10 ROWS_MATCHED:2
  SARGABLE: PLAN=INDEX_RANGE_SCAN ROWS_EXAMINED:6 ROWS_MATCHED:2 ROWS_SAVED:4
ACT 4 QUERY_SKU_SUBSTRING 4 BOOK
  NAIVE: PLAN=FULL_TABLE_SCAN ROWS_EXAMINED:10 ROWS_MATCHED:3
  SARGABLE: PLAN=INDEX_RANGE_SCAN ROWS_EXAMINED:7 ROWS_MATCHED:3 ROWS_SAVED:3
SUMMARY NAIVE TOTAL_ROWS_EXAMINED:40
SUMMARY SARGABLE TOTAL_ROWS_EXAMINED:32
SUMMARY ROWS_SAVED:8 (SCAN_REDUCTION:20.00%)
SUMMARY ACCURACY_CHECK: 100% IDENTICAL RESULTS
```
