# DB 인덱스와 SARGable 쿼리 최적화 (B-Tree Indexing & SARGable Queries)

> **"분명히 컬럼에 인덱스를 걸었는데, 왜 실행 계획을 보면 Full Table Scan이 뜰까요?!"**  
> **"두꺼운 전화번호부에서 성씨 찾기(Index Scan) vs 끝 글자 찾기(Full Scan)의 참사"**

---

## 1. 현실 세계 비유: 100만 명 전화번호부와 이름 검색

100만 명의 시민 이름과 전화번호가 **가나다순(B-Tree 정렬)**으로 가지런히 정리된 두꺼운 전화번호부가 있습니다.

```
[상황 A: SARGable 쿼리 - "성(姓)이 '김'씨인 사람 찾아줘!"]
직원은 전화번호부 앞부분의 'ㄱ' 색인(B-Tree Root Node)을 펼칩니다.
1. 'ㄱ' 색인을 거쳐 '김'씨가 시작하는 500페이지로 0.1초 만에 직행합니다.
2. 500페이지부터 '김'씨가 끝나는 600페이지까지만 눈으로 훑고 책을 덮습니다 (Index Range Scan).
3. 비용: 100만 페이지 중 딱 100페이지만 읽었습니다!
```

```
[상황 B: Non-SARGable 쿼리 - "이름의 끝 두 글자가 '민우'인 사람 찾아줘!"]
(WHERE SUBSTRING(name, 2) = '민우')

무슨 일이 일어났을까요?
1. 전화번호부는 '전체 이름의 첫 글자' 순서로 정렬되어 있지, '끝 두 글자' 순서로 정렬되어 있지 않습니다!
2. 직원은 'ㄱ' 색인을 쓸 수가 없습니다.
3. 결국 1페이지부터 100만 페이지까지 한 장 한 장 손으로 넘기며 모든 사람의 끝 두 글자를 읽어야 합니다 (Full Table Scan)!
4. 비용: 100만 장을 전부 읽느라 10분 동안 창구 업무가 마비되었습니다!
```

이것이 바로 **개발자가 쿼리 작성 시 인덱스 컬럼을 함수나 연산자로 가공(Wrapping)했을 때 발생하는 B-Tree 인덱스 무력화 참사**입니다.

---

## 2. SARGable이란 무엇인가?

**SARGable**이란 **Search Argument Able**의 약어로, **"데이터베이스 엔진이 B-Tree 인덱스를 활용하여 검색 범위를 좁힐 수 있는 형태의 조건식"**을 의미합니다.

- **B-Tree 인덱스의 본질**:  
  B-Tree는 컬럼의 **"원래 가공되지 않은 순수 값(Raw Value)"**을 기준으로 오름차순 정렬되어 있습니다.
- **가공의 저주**:  
  조건절의 좌변(컬럼 쪽)에 함수를 씌우거나 산술 연산을 가하면, DB 엔진은 테이블의 **모든 행(Row)을 메모리로 퍼 올려서 함수를 일일이 계산한 뒤에야 비교**할 수 있으므로 무조건 **풀 테이블 스캔(Full Table Scan)**으로 전락합니다.

---

## 3. 실무에서 가장 흔한 5대 Non-SARGable 안티패턴과 해법

| 안티패턴 유형 | ❌ 인덱스 무력화 (Full Table Scan) | ⭕ SARGable 최적화 (Index Range Scan) | 최적화 원리 |
| :--- | :--- | :--- | :--- |
| **1. 날짜 함수 가공** | `WHERE YEAR(created_at) = 2026` | `WHERE created_at >= '2026-01-01' AND created_at <= '2026-12-31'` | 컬럼 대신 상수를 범위로 변환하여 B-Tree Range Scan 유도 |
| **2. 컬럼 산술 연산** | `WHERE price * 1.1 >= 55000` | `WHERE price >= 55000 / 1.1` (즉 `price >= 50000`) | 연산자를 우변(상수 쪽)으로 이항하여 컬럼의 순수성 유지 |
| **3. 앞단 와일드카드** | `WHERE email LIKE '%@gmail.com'` | `WHERE email LIKE 'alice%'` (접두어 검색) | 앞단 `%`는 B-Tree 시작점을 찾을 수 없음 (필요시 역방향 인덱스 활용) |
| **4. 문자열 자르기** | `WHERE SUBSTRING(sku, 1, 4) = 'ELEC'` | `WHERE sku LIKE 'ELEC%'` 또는 `WHERE sku >= 'ELEC' AND sku < 'ELED'` | 문자열 접두어 범위 검색으로 변환 |
| **5. 묵시적 형변환** | `WHERE varchar_code = 1234` (숫자 대입) | `WHERE varchar_code = '1234'` (문자열 대입) | DB가 모든 row를 `CAST(code AS SIGNED)` 하느라 풀스캔 발생 방지 |

---

## 4. B-Tree Index Range Scan의 수학적 복잡도

테이블의 전체 레코드 수를 $N$, 조건에 매칭되는 결과 수를 $M$이라 할 때:

- **풀 테이블 스캔(Full Table Scan)**:
  $$\text{Examined Rows} = N$$
  - 데이터가 1,000만 건이면 1,000만 번의 디스크/메모리 블록을 읽어야 함 ($O(N)$).
- **B-Tree 인덱스 레인지 스캔(Index Range Scan)**:
  $$\text{Examined Rows} = \lceil \log_2 N \rceil + M$$
  - $\log_2 N$: B-Tree 루트부터 리프 노드까지의 탐색 깊이 (1,000만 건이어도 단 24번 탐색!).
  - $M$: 실제로 조건을 만족하는 리프 노드의 연속된 범위만 읽음.
  - $M \ll N$인 환경(선택도가 높은 OLTP 쿼리)에서 **스캔 비용이 99.9% 이상 절감**됩니다.

---

## 5. 실행 계획(EXPLAIN) 확인 방법

MySQL/MariaDB에서 쿼리 앞에 `EXPLAIN`을 붙여 옵티마이저의 실행 계획을 확인합니다:

```sql
-- ❌ 나쁜 실행 계획:
EXPLAIN SELECT * FROM orders WHERE YEAR(created_at) = 2026;
-- 결과: type = ALL (Full Table Scan), rows = 1,000,000

-- ⭕ 좋은 실행 계획:
EXPLAIN SELECT * FROM orders WHERE created_at >= '2026-01-01' AND created_at <= '2026-12-31';
-- 결과: type = range (Index Range Scan), key = idx_created_at, rows = 120
```

> **"좌변(컬럼)을 건드리지 말고, 우변(상수)을 가공하라!"**  
> 이것이 인덱스를 살리는 데이터베이스 쿼리 튜닝의 제1원칙입니다.
