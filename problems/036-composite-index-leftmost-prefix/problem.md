# Problem #036: 인덱스를 5개나 걸었는데 왜 10초나 걸려요?!: 복합 인덱스(Composite Index)와 Leftmost Prefix의 저주

## 📖 실무 스토리: AI가 짜준 인덱스를 걸었는데 서버가 죽었습니다!

스타트업의 주니어 백엔드 개발자 나코딩은 중고 거래 플랫폼의 상품 검색 속도가 10초 이상 걸린다는 유저들의 원성을 들었습니다.
테이블에는 이미 **10만 건 이상의 상품 데이터**가 쌓여 있었습니다.

나코딩은 AI 코딩 어시스턴트에게 도움을 청했습니다:
> **나코딩**: "검색 쿼리가 너무 느려! `category`, `status`, `price`, `created_at` 컬럼으로 검색하는데 어떻게 해?"  
> **AI**: "4개 컬럼을 묶은 복합 인덱스(Composite Index)를 생성하세요! B-Tree 인덱스를 타면 $O(\log N)$으로 순식간에 조회됩니다!"

나코딩은 기뻐하며 즉시 운영 DB에 복합 인덱스를 적용했습니다:
```sql
CREATE INDEX idx_goods_search ON products (category, status, price, created_at);
```

하지만 배포 다음 날, **DB CPU 사용률이 100%를 찍고 슬로우 쿼리 경보가 빗발치며 서버가 뻗어버렸습니다!**
DB 슬로우 쿼리 로그를 뜯어보니 기가 막힌 일들이 벌어지고 있었습니다:

1. **"판매 중인 최근 등록 상품 보기" (`WHERE status = 'SALE' AND created_at >= '2026-01-01'`):**
   * 인덱스에 분명 `status`와 `created_at`이 들어있는데, DB는 인덱스를 쳐다보지도 않고 **10만 건 전체 테이블을 풀스캔(Table Full Scan)**하고 있었습니다!
2. **"전자제품 중 1만~5만원 사이 오늘 등록된 상품" (`WHERE category = 'DIGITAL' AND price BETWEEN 10000 AND 50000 AND status = 'SALE'`):**
   * 분명 `category`와 `status`, `price`가 다 인덱스에 있는데, DB는 `price` 범위까지만 인덱스 탐색(Index Seek)을 하고, 그 뒤의 `status` 조건은 인덱스 범위를 좁히는 데 전혀 쓰지 못한 채 수만 건의 레코드를 일일이 디스크에서 꺼내어 확인(Filter)하고 있었습니다!
3. **"1만 원 이하 특가 상품 검색" (`WHERE price <= 10000`):**
   * 인덱스의 세 번째 컬럼인 `price` 조건만 주어지자, 인덱스를 아예 타지 못하고 테이블 전체를 처음부터 끝까지 다 뒤졌습니다.

> **"분명히 인덱스 괄호 안에 컬럼을 다 집어넣었는데, 왜 어떤 쿼리는 0.001초 만에 끝나고 어떤 쿼리는 풀스캔을 타는 거죠?!"**

복합 인덱스는 컬럼들을 그냥 가방에 담아두는 바구니가 아닙니다.
B-Tree는 **철저하게 왼쪽 첫 번째 컬럼부터 차례대로 정렬(Leftmost Prefix)**되기 때문에, 컬럼의 순서와 조건의 종류(`=` 등치 vs `RANGE` 범위)에 따라 인덱스의 운명이 180도 달라집니다!

여러분의 임무는 쿼리 옵티마이저의 **인덱스 실행 계획 분석기(Query Execution Analyzer)**와 **최적 복합 인덱스 추천 엔진(Optimal Index Recommender)**을 구현하는 것입니다.

---

## 🎯 문제 요구사항

주어진 복합 인덱스 정의와 테이블 크기, 그리고 실행할 쿼리들의 조건 목록을 입력받아 다음을 평가하십시오:

1. **인덱스 접근 방식 (`ACCESS_TYPE`)**:
   * 복합 인덱스의 첫 번째 컬럼($C_1$)이 쿼리 조건에 포함되지 않으면, B-Tree 탐색을 시작조차 할 수 없으므로 `TABLE_FULL_SCAN`입니다.
   * 첫 번째 컬럼($C_1$)이 쿼리 조건에 포함되어 있다면 `INDEX_SEEK`입니다.
2. **유효 탐색 키 (`SEEK_KEYS`) 결정 규칙**:
   * 인덱스 정의 순서대로($C_1, C_2, C_3, \dots$) 검사합니다.
   * **등치 조건(`=`)**: 조건을 만족하는 동안 연속적으로 `SEEK_KEYS`에 포함됩니다.
   * **범위 조건(`RANGE`)**: 범위 조건(`<, >, BETWEEN`)을 만나는 순간, **해당 컬럼까지는 범위의 시작점/끝점을 찾는 Seek Key로 포함되지만, 그 이후의 모든 컬럼($C_{r+1}, \dots$)은 아무리 쿼리에 조건이 있어도 더 이상 Seek Key가 될 수 없습니다!** (단순 인덱스 필터로 격하됨)
   * **조건 누락**: 인덱스 순서 중간에 쿼리 조건이 없는 컬럼이 나타나면, 체인이 끊어져 그 이후 컬럼들은 모두 Seek Key가 될 수 없습니다.
   * 활용된 Seek Key가 하나도 없으면 `NONE`으로 표기합니다.
3. **스캔 행 수 (`SCANNED_ROWS`) 및 반환 행 수 (`RETURNED_ROWS`)**:
   * `seek_selectivity`: `SEEK_KEYS`에 포함된 컬럼들의 `selectivity`의 누적 곱 ($\prod_{c \in SEEK\_KEYS} s_c$). (Seek Key가 없으면 1.0)
   * `INDEX_SEEK`인 경우: $\text{SCANNED\_ROWS} = \max(1, \text{round}(\text{TABLE\_SIZE} \times \text{seek\_selectivity}))$. (단, $\text{TABLE\_SIZE} = 0$이면 0)
   * `TABLE_FULL_SCAN`인 경우: $\text{SCANNED\_ROWS} = \text{TABLE\_SIZE}$.
   * `total_selectivity`: 쿼리에 주어진 **모든 조건**의 `selectivity`의 누적 곱.
   * $\text{RETURNED\_ROWS} = \min(\text{SCANNED\_ROWS}, \text{round}(\text{TABLE\_SIZE} \times \text{total\_selectivity}))$. (단, $\text{TABLE\_SIZE} = 0$이면 0)
4. **불필요한 스캔 낭비율 (`WASTE`)**:
   * $\text{WASTE} = \frac{\text{SCANNED\_ROWS} - \text{RETURNED\_ROWS}}{\text{SCANNED\_ROWS}} \times 100\%$ (소수점 첫째 자리까지 반올림 표기, 예: `90.0%`. 단 $\text{SCANNED\_ROWS} = 0$이면 `0.0%`).
5. **최적 복합 인덱스 재배치 추천 (`OPTIMAL_INDEX` 및 `OPTIMAL_SCANNED`)**:
   * 해당 쿼리에 주어진 조건들을 가장 효율적으로 처리할 수 있는 복합 인덱스 컬럼 순서를 도출합니다:
     * **1순위 (앞쪽)**: 등치(`=`) 조건 컬럼들을 배치. (선택도 `selectivity` 오름차순, 동일 시 컬럼명 알파벳 오름차순)
     * **2순위 (뒤쪽)**: 범위(`RANGE`) 조건 컬럼들을 배치. (선택도 `selectivity` 오름차순, 동일 시 컬럼명 알파벳 오름차순)
   * 최적 인덱스 하에서는 모든 등치 조건과 **가장 선택도가 좁은(작은) 첫 번째 범위 조건 1개**까지가 모두 `OPTIMAL_SEEK_KEYS`로 동작합니다!
   * 최적 인덱스 하에서의 스캔 행 수 $\text{OPTIMAL\_SCANNED}$를 계산합니다. (단, $\text{OPTIMAL\_SCANNED} \le \text{SCANNED\_ROWS}$)

---

## 📥 입력 형식 (Input Format)

```text
INDEX <K> <col_1> <col_2> ... <col_K>
TABLE_SIZE <N>
QUERIES <Q>
QUERY <query_id> <M>
<col_name_1> <op_1> <selectivity_1>
<col_name_2> <op_2> <selectivity_2>
...
```

* 첫 번째 줄: `INDEX` 키워드 뒤에 복합 인덱스 컬럼 개수 $K$ ($1 \le K \le 10$)와 인덱스 컬럼명들이 공백으로 구분되어 주어집니다.
* 두 번째 줄: `TABLE_SIZE` 키워드 뒤에 테이블 전체 행 수 $N$ ($0 \le N \le 1,000,000$)이 주어집니다.
* 세 번째 줄: `QUERIES` 키워드 뒤에 실행할 쿼리 개수 $Q$ ($1 \le Q \le 30,000$)가 주어집니다.
* 네 번째 줄부터 각 쿼리가 주어집니다:
  * `QUERY <query_id> <M>`: 쿼리 ID 문자열과 해당 쿼리의 조건 개수 $M$ ($0 \le M \le 10$)
  * 다음 $M$개의 줄에 걸쳐 `<col_name> <op> <selectivity>`가 주어집니다:
    * `col_name`: 컬럼명 (문자열)
    * `op`: `=` (등치 조건) 또는 `RANGE` (범위 조건)
    * `selectivity`: 해당 조건이 만족하는 비율 ($0 < s \le 1.0$, 소수점 표기)

---

## 📤 출력 형식 (Output Format)

각 쿼리에 대해 다음 형식으로 1줄씩 출력합니다:
```text
QUERY <query_id> ACCESS:<access_type> SEEK_KEYS:<seek_keys> SCANNED:<scanned_rows> RETURNED:<returned_rows> WASTE:<waste_ratio>% OPTIMAL_INDEX:<opt_index> OPTIMAL_SCANNED:<opt_scanned>
```
* `<access_type>`: `INDEX_SEEK` 또는 `TABLE_FULL_SCAN`
* `<seek_keys>`: Seek Key 컬럼 목록 (예: `[category,status,price]`), 없으면 `NONE`
* `<opt_index>`: 최적 추천 복합 인덱스 컬럼 목록 (예: `[category,created_at,status,price]`), 없으면 `NONE`
* `<waste_ratio>`: 소수점 첫째 자리까지 표기된 퍼센트 (예: `90.0%`)

모든 쿼리 출력 후 마지막 줄에 종합 통계(Summary)를 1줄 출력합니다:
```text
SUMMARY TOTAL_QUERIES:<Q> FULL_SCANS:<full_scans> TOTAL_SCANNED:<total_scanned> TOTAL_OPTIMAL_SCANNED:<total_opt_scanned> ROWS_SAVED:<rows_saved>
```

---

## 💡 입출력 예제 (Sample I/O)

### 예제 입력
```text
INDEX 4 category status price created_at
TABLE_SIZE 100000
QUERIES 3
QUERY Q1 4
category = 0.1
status = 0.2
price RANGE 0.5
created_at = 0.1
QUERY Q2 2
status = 0.2
created_at RANGE 0.5
QUERY Q3 2
price RANGE 0.2
category = 0.1
```

### 예제 출력
```text
QUERY Q1 ACCESS:INDEX_SEEK SEEK_KEYS:[category,status,price] SCANNED:1000 RETURNED:100 WASTE:90.0% OPTIMAL_INDEX:[category,created_at,status,price] OPTIMAL_SCANNED:100
QUERY Q2 ACCESS:TABLE_FULL_SCAN SEEK_KEYS:NONE SCANNED:100000 RETURNED:10000 WASTE:90.0% OPTIMAL_INDEX:[status,created_at] OPTIMAL_SCANNED:10000
QUERY Q3 ACCESS:INDEX_SEEK SEEK_KEYS:[category] SCANNED:10000 RETURNED:2000 WASTE:80.0% OPTIMAL_INDEX:[category,price] OPTIMAL_SCANNED:2000
SUMMARY TOTAL_QUERIES:3 FULL_SCANS:1 TOTAL_SCANNED:111000 TOTAL_OPTIMAL_SCANNED:12100 ROWS_SAVED:98900
```

---

## 힌트 & 핵심 점검 사항
1. **Leftmost Prefix**: 인덱스의 첫 컬럼인 `category`가 쿼리에 없으면 (Q2처럼) 아무리 다른 컬럼 조건이 좋아도 B-Tree를 타지 못하고 전체 테이블 풀스캔(`TABLE_FULL_SCAN`)이 발생합니다.
2. **Range 뒤의 무력화**: Q1에서 `price`가 `RANGE`이므로, 그 뒤에 있는 `created_at = 0.1`은 Seek Key가 되지 못합니다. 따라서 1,000건을 스캔한 뒤 100건만 건져내어 90%의 디스크 I/O가 낭비됩니다.
3. **최적 인덱스 재배치**: 등치 조건들을 앞쪽(`category, created_at, status`)에 몰고, 범위 조건(`price`)을 뒤로 보내면 4개 조건 모두가 완벽하게 Seek Key가 되어 스캔 행 수를 1,000건에서 단 100건으로 90% 추가 절감할 수 있습니다!
