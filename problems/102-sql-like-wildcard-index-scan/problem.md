# 102. SQL LIKE '%abc%'로 검색했더니 왜 DB CPU 100% 찍고 인덱스를 안 타요?!: B+Tree 인덱스의 최좌측 접두사 규칙(Leftmost Prefix Rule)과 Trigram/역색인의 구원

---

## 1. 비극의 시작 (Real-World Disaster)

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

## 3. 핵심 아키텍처 및 요구사항

당신은 데이터베이스의 B+Tree 인덱스, 최좌측 접두사 규칙(Leftmost Prefix Rule), 접미사 최적화를 위한 역순 인덱스(Reverse B+Tree), 중간 검색을 위한 Trigram GIN 인덱스, 그리고 쿼리 옵티마이저의 실행 계획(`EXPLAIN`) 엔진을 시뮬레이션해야 합니다.

### 1) 테이블 생성 및 데이터 적재 (`LOAD_TABLE`)
- `LOAD_TABLE <table_name> <csv_words>`
  - 쉼표로 구분된 단어 목록을 테이블에 적재합니다.
  - 출력: `LOAD_TABLE_OK table=<table_name> rows=<N>`

### 2) 인덱스 생성 (`CREATE_INDEX`)
- `CREATE_INDEX <index_name> <table_name> <BTREE|REVERSE_BTREE|TRIGRAM>`
  - `BTREE`: 원본 단어를 사전식 오름차순으로 정렬하여 보관합니다 (접두사 `word%` 및 단건 `word` 검색 최적화).
  - `REVERSE_BTREE`: 단어를 뒤집은 문자열(`word[::-1]`)을 사전식 정렬하여 보관합니다 (접미사 `%word` 검색 최적화).
  - `TRIGRAM`: 단어를 3글자 단위 조각으로 쪼갠 뒤 Trigram 역색인 맵을 구축합니다 (중간 검색 `%word%` 최적화).
  - 출력: `CREATE_INDEX_OK name=<index_name> type=<type>`

### 3) 쿼리 실행 계획 평가 (`EXPLAIN_QUERY`)
- `EXPLAIN_QUERY <table_name> <pattern>`
  - 인덱스 가용성 및 패턴에 따라 옵티마이저의 스캔 방식을 결정합니다:
    1. **단건 일치 (`word`)**:  
       - `BTREE` 인덱스 존재 시: `INDEX_SEEK` (스캔 행 수 = 매칭 건수).
       - 인덱스 미존재 시: `FULL_TABLE_SCAN` (스캔 행 수 = 테이블 전체 행 수).
    2. **접두사 검색 (`word%`)**:  
       - `BTREE` 인덱스 존재 시: 최좌측 접두사 규칙 만족 -> `INDEX_RANGE_SCAN` (스캔 행 수 = 매칭 건수).
       - 인덱스 미존재 시: `FULL_TABLE_SCAN`.
    3. **접미사 검색 (`%word`)**:  
       - `REVERSE_BTREE` 인덱스 존재 시: 단어를 뒤집어 범위 탐색 -> `INDEX_RANGE_SCAN` (스캔 행 수 = 매칭 건수).
       - 미존재 시: `FULL_TABLE_SCAN` (B+Tree가 있어도 사용 불가!).
    4. **중간 검색 (`%word%`)**:  
       - `TRIGRAM` 인덱스 존재 시: 비트맵 인덱스 스캔 -> `BITMAP_INDEX_SCAN` (스캔 행 수 = 트라이그램 후보 행 수).
       - 미존재 시: `FULL_TABLE_SCAN` (B+Tree가 있어도 무용지물!).
  - 출력:  
    `EXPLAIN_RESULT table=<table_name> pattern=<pattern> scan_type=<INDEX_SEEK|INDEX_RANGE_SCAN|BITMAP_INDEX_SCAN|FULL_TABLE_SCAN> index_used=<index_name|NONE> scanned_rows=<scanned> matched_rows=<matched>`

### 4) 실제 검색 쿼리 실행 (`SEARCH`)
- `SEARCH <table_name> <pattern>`
  - 패턴에 매칭되는 단어 목록을 오름차순으로 정렬하여 출력합니다.
  - 출력: `SEARCH_OK pattern=<pattern> count=<matched_count> matches=[<m1>, <m2>, ...]`

### 5) 테이블 상태 조회 (`STATS`)
- `STATS <table_name>`
  - 테이블 행 수와 생성된 인덱스 목록을 출력합니다.
  - 출력: `STATS table=<table_name> total_rows=<rows> indexes=[<idx1>:<type>, <idx2>:<type>, ...]`

---

## 4. 실무 권장 아키텍처 및 교훈

1. **최좌측 접두사 규칙(Leftmost Prefix Rule)의 절대성**:
   - B+Tree 인덱스는 정렬 구조에 기반하므로, 검색 키의 첫 글자를 모르면 정렬 순서를 전혀 활용할 수 없습니다. 따라서 `LIKE '%abc'`나 `LIKE '%abc%'`는 B+Tree 인덱스를 무조건 타지 못합니다.
2. **함수 기반 역순 인덱스(Reverse Index)의 활용**:
   - 끝자리 검색(`%@gmail.com`)이 빈번하다면 `REVERSE(email)` 인덱스를 생성하고 쿼리 조건을 `REVERSE(email) LIKE 'moc.liamg@%'`로 변환하여 Range Scan을 유도해야 합니다.
3. **PostgreSQL Trigram GIN 인덱스 (`pg_trgm`)**:
   - RDBMS 내부에서 부분 문자열 검색이 반드시 필요하다면 3글자 단위 역색인을 지원하는 Trigram GIN 인덱스를 도입합니다.
4. **전문 검색 엔진(Search Engine) 분리**:
   - 100만 건 이상의 대규모 텍스트 검색은 RDBMS에 부하를 주지 말고 Elasticsearch, OpenSearch와 같은 분산 역색인 검색 엔진으로 오프로딩하는 것이 정석입니다.
