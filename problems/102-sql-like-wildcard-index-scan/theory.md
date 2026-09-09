# 102. SQL LIKE '%abc%'로 검색했더니 왜 DB CPU 100% 찍고 인덱스를 안 타요?!: B+Tree 인덱스의 최좌측 접두사 규칙(Leftmost Prefix Rule)과 Trigram/역색인의 구원

---

## 1. 비극의 시작: 인덱스를 걸었는데 왜 1,000만 건을 전수 조사해요?!

스타트업 백엔드 개발자 유진이는 이커머스 서비스의 상품 검색 API를 개발했습니다.  
사용자가 검색창에 "셔츠"라고 치면 "린넨 셔츠", "셔츠 원피스", "체크 셔츠" 등 검색어가 포함된 모든 상품이 나와야 하므로, 다음과 같은 쿼리를 작성했습니다:

```sql
SELECT product_id, name, price 
FROM products 
WHERE name LIKE '%셔츠%';
```

유진이는 혹시 쿼리가 느릴까 봐 DBA에게 요청해 `name` 컬럼에 B+Tree 인덱스를 걸어두었습니다:
```sql
CREATE INDEX idx_products_name ON products(name);
```

개발 환경에서는 상품이 100개뿐이라 1ms 만에 결과가 반환되었습니다.  
하지만 대규모 여름 세일 이벤트가 시작되고 등록 상품 수가 1,000만 건으로 늘어난 순간, 검색 쿼리 하나당 DB CPU가 100%를 치솟으며 전사 DB 커넥션 풀이 초토화되었습니다!

당황한 유진이가 쿼리 실행 계획(`EXPLAIN`)을 확인하자 경악을 금치 못했습니다:

```text
+----+-------------+----------+------+-------------------+------+---------+------+----------+-------------+
| id | select_type | table    | type | possible_keys     | key  | key_len | ref  | rows     | Extra       |
+----+-------------+----------+------+-------------------+------+---------+------+----------+-------------+
|  1 | SIMPLE      | products | ALL  | idx_products_name | NULL | NULL    | NULL | 10000000 | Using where |
+----+-------------+----------+------+-------------------+------+---------+------+----------+-------------+
```

**"분명히 `idx_products_name` 인덱스가 존재하는데 왜 key는 NULL이고, type은 ALL(Full Table Scan)로 1,000만 행을 디스크에서 다 퍼 올리고 있는 거지?!"**

---

## 2. 현실 비유: 가나다순 전화번호부와 '수'가 들어간 이름 찾기

1,000만 명의 시민 이름이 적힌 두꺼운 종이 **전화번호부 책(B+Tree Index)**을 상상해 봅시다:
- 전화번호부는 이름의 첫 글자부터 끝 글자까지 **철저하게 '가나다순'으로 정렬**되어 있습니다.

### 1) 접두사 검색 (`LIKE '김%'`) - 인덱스 레인지 스캔
- 손님이 찾아와 **"이름이 '김'으로 시작하는 사람 찾아주세요!"**라고 요청했습니다.
- 직원은 전화번호부에서 'ㄱ' -> '김' 섹션을 **단 1초 만에 펼칩니다(B+Tree Seek, $O(\log N)$)**.
- '김'으로 시작하는 첫 번째 사람부터 마지막 사람까지만 순서대로 읽고 책을 덮습니다.  
  총 1,000만 명 중 불과 0.01%만 읽고 끝났습니다!

### 2) 중간/접미사 와일드카드 검색 (`LIKE '%수%'`) - 풀 테이블 스캔
- 다른 손님이 찾아와 **"이름 앞이든 중간이든 끝이든 어디에나 '수'가 들어가는 사람 다 찾아주세요!"**라고 요청했습니다.
- 직원은 망연자실합니다:
  - '수'가 첫 글자(수지, 수철)일 수도 있고,
  - 둘째 글자(김수현, 박수홍)일 수도 있고,
  - 셋째 글자(홍길동수, 이철수)일 수도 있습니다.
- **전화번호부가 가나다순으로 아무리 정교하게 정렬되어 있어도, 첫 글자를 모르면 정렬 순서가 아무 짝에도 쓸모없어집니다!**
- 결국 직원은 1페이지 첫 번째 이름부터 마지막 1,000만 번째 이름까지 **돋보기를 들고 한 글자 한 글자 전부 뜯어보며 전수 조사(Full Table Scan, $O(N)$)**를 할 수밖에 없습니다!

---

## 3. 컴퓨터 과학 / 데이터베이스 인덱싱 이론

### 1) B+Tree 인덱스의 물리적 특성과 최좌측 접두사 규칙 (Leftmost Prefix Rule)
- B+Tree 인덱스는 키 값을 사전식 순서(Lexicographical Order)로 물리 정렬하여 저장합니다.
- 특정 키의 위치를 이진 탐색($O(\log N)$)으로 찾아내려면, **키의 가장 왼쪽 글자(Prefix)부터 일치**해야 합니다.
- **와일드카드 패턴별 인덱스 동작**:

| 패턴 | 예시 | 인덱스 활용 여부 | 탐색 복잡도 |
| :--- | :--- | :--- | :--- |
| `Prefix Match` | `LIKE 'apple%'` | **O (Index Range Scan)** | $O(\log N + K)$ ($K$: 결과 건수) |
| `Exact Match` | `= 'apple'` | **O (Index Unique/Ref Scan)**| $O(\log N)$ |
| `Suffix Match` | `LIKE '%apple'` | **X (Full Scan)** | $O(N)$ |
| `Infix Match` | `LIKE '%apple%'` | **X (Full Scan)** | $O(N)$ |

### 2) 복합 인덱스(Composite Index)에서의 최좌측 접두사 규칙
단일 문자열뿐 아니라 다중 컬럼 인덱스에서도 동일한 물리 법칙이 적용됩니다:
- 인덱스: `INDEX (department_id, job_level, hire_date)`
- `WHERE department_id = 10 AND job_level = 3`: **인덱스 탐색 가능 (Prefix 만족)**
- `WHERE job_level = 3 AND hire_date = '2026-01-01'`: **인덱스 탐색 불가 (최좌측 `department_id` 누락으로 인한 Full Scan!)**

---

## 4. 실무 아키텍처 및 해결 솔루션

1. **접미사 검색 최적화: 역순 인덱스(Reverse Index)**:
   - 이메일 도메인 검색(`WHERE email LIKE '%@gmail.com'`)처럼 끝자리 매칭이 잦다면, 컬럼을 뒤집어 저장하는 생성 컬럼(Generated Column)이나 함수 기반 인덱스를 생성합니다:
     ```sql
     -- email을 뒤집은 reverse_email 인덱스 생성
     CREATE INDEX idx_reverse_email ON users ((REVERSE(email)));
     -- 쿼리도 뒤집어서 Prefix Match로 유도!
     SELECT * FROM users WHERE REVERSE(email) LIKE 'moc.liamg@%';
     ```
   - 이 경우 B+Tree의 Index Range Scan을 100% 활용할 수 있습니다!
2. **PostgreSQL Trigram GIN 인덱스 (`pg_trgm`)**:
   - 단어를 3글자 단위(3-gram)로 잘게 쪼개어 역색인(Inverted Index)을 생성하는 GIN 인덱스를 사용하면, 앞뒤에 `%`가 붙은 중간 검색도 인덱스를 탈 수 있습니다:
     ```sql
     CREATE EXTENSION pg_trgm;
     CREATE INDEX idx_products_name_trgm ON products USING gin (name gin_trgm_ops);
     ```
3. **전문 검색 엔진(Full-Text Search Engine) 분리**:
   - 데이터가 수백만 건을 넘어가면 RDBMS의 B+Tree 인덱스로 부분 문자열 검색을 처리하려 하지 말고, **Elasticsearch / OpenSearch** 같은 Lucene 기반 전문 검색 엔진으로 오프로딩하는 것이 표준 아키텍처입니다.
