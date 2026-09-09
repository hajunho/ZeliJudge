# 인덱스를 탔는데 왜 풀 테이블 스캔보다 10배 느려요?!: 커버링 인덱스(Covering Index) vs 북마크 룩업(Bookmark Lookup)과 옵티마이저 손익분기점(Tipping Point)

> "게시판 테이블에 100만 건의 데이터가 쌓여 검색 쿼리가 느려졌습니다.  
> 쿼리 튜닝을 하겠다고 `WHERE status = 'ACTIVE'` 조건 컬럼에 B-Tree 인덱스를 정성스럽게 생성했습니다.  
> 그리고 `SELECT * FROM orders WHERE status = 'ACTIVE'` 쿼리를 날렸는데...  
> **인덱스가 없을 때 풀 테이블 스캔(Full Table Scan)으로 0.1초 걸리던 쿼리가, 인덱스를 달자마자 오히려 1.5초(15배!)로 끔찍하게 느려졌습니다!**  
> `EXPLAIN`을 까보니 `type: ref, key: idx_status`로 인덱스를 분명히 탔는데, 왜 인덱스를 탄 쿼리가 전체 테이블을 몽땅 뒤지는 풀 스캔보다 훨씬 느릴까요?!"

---

## 1. 전설의 '인덱스 역전 참사'와 북마크 룩업 (Bookmark Lookup)

데이터베이스 입문자와 주니어 개발자들이 가장 크게 오해하는 미신 중 하나가 **"인덱스(B-Tree)를 타면 무조건 풀 테이블 스캔보다 빠르다"**는 생각입니다.

하지만 실제 프로덕션 데이터베이스(MySQL InnoDB, PostgreSQL, Oracle, SQL Server)에서는 **인덱스를 탔기 때문에 서버 디스크 I/O가 폭증하여 데이터베이스가 사망하는 역전 현상**이 매일같이 발생합니다.

이유를 이해하려면 RDBMS의 두 가지 인덱스 구조를 알아야 합니다:
1. **클러스터드 인덱스 (Clustered Index / Primary Key)**:
   - 테이블의 실제 모든 컬럼 데이터 행이 PK 순서대로 정렬되어 리프 블록에 직접 저장됩니다. 테이블 그 자체가 인덱스입니다.
2. **세컨더리 인덱스 (Secondary Index / 보조 인덱스)**:
   - 인덱스로 지정한 특정 컬럼 값과, 그 행을 가리키는 **PK 값(포인터)**만 컴팩트하게 가지고 있습니다. 테이블의 나머지 컬럼 데이터는 갖고 있지 않습니다.

---

## 2. 북마크 룩업(Bookmark Lookup)과 랜덤 I/O(Random I/O)의 저주

개발자가 `SELECT * FROM orders WHERE status = 'ACTIVE'` 처럼 세컨더리 인덱스에 없는 컬럼을 포함하여 조회하면 다음과 같은 2단계 조회가 발생합니다:

```
[1단계: 세컨더리 인덱스 탐색]
  B-Tree 리프 노드에서 status = 'ACTIVE'인 항목 1만 개를 고속 스캔
  ──► 결과: PK 목록 [101, 5092, 12044, 99012, ...] 수집 완료! (아주 빠름)

[2단계: 북마크 룩업 (Bookmark Lookup / Table Access)]
  수집한 1만 개의 PK를 들고, 실제 데이터 행(모든 컬럼)을 가져오기 위해
  클러스터드 인덱스(테이블 데이터 블록)로 이동!
  ──► 💥 1만 번의 무작위 디스크 페이지 조회(Random Page Fetch) 발생!
```

### 🚨 순차 I/O(Sequential I/O) vs 랜덤 I/O(Random I/O)의 성능 격차
- **풀 테이블 스캔 (Full Table Scan)**:  
  테이블의 첫 페이지부터 끝 페이지까지 **연속된 디스크 블록을 통째로 긁어모으는 멀티블록 순차 I/O(Multiblock Sequential Read)**를 수행합니다. 디스크 헤드의 이동이 적고 OS/DB의 사전 읽기(Read-Ahead) 캐싱이 완벽히 작동하여 수십만 건도 눈 깜짝할 사이에 읽습니다.
- **북마크 룩업 (Bookmark Lookup)**:  
  세컨더리 인덱스는 `status` 순으로 정렬되어 있지만, 그 행들이 저장된 실제 물리 데이터 페이지는 **테이블 전체에 무작위로 흩뿌려져(Scatter)** 있습니다.  
  결과적으로 1만 번의 조회가 **1만 번의 디스크 헤드 점프(Random Seek)**를 유발하여 디스크 I/O 비용이 기하급수적으로 폭증합니다!

---

## 3. 옵티마이저의 손익분기점 (The Tipping Point)

CBO(Cost-Based Optimizer, 비용 기반 옵티마이저)는 쿼리를 실행하기 전 인덱스 스캔 비용과 풀 테이블 스캔 비용을 수학적으로 계산합니다:

$$	ext{Index Cost} = 	ext{Index Leaf Pages} 	imes 	ext{Sequential Cost} + 	ext{Visited Data Pages} 	imes 	ext{Random Cost}$$
$$	ext{FTS Cost} = 	ext{Total Table Pages} 	imes 	ext{Sequential Cost}$$

```
비용 (Cost)
  ▲
  │                                   / (인덱스 + 북마크 룩업 비용) 💥
  │                                 /
  │                               / 
  │=============================+================== (풀 테이블 스캔 비용: 고정)
  │                           / │
  │                         /   │
  │                       /     │
  │                     /       │
  └───────────────────+─────────+──────────────────────────► 매칭 행 비율 (Selectivity %)
                      0%     손익분기점 (Tipping Point: 약 10% ~ 20%)
```

- **선택도(Selectivity)가 1% 미만일 때**:  
  방문할 데이터 페이지가 몇 개 안 되므로 인덱스 스캔이 압도적으로 유리합니다.
- **선택도가 손익분기점(보통 전체의 10% ~ 20%)을 넘어설 때**:  
  랜덤 북마크 룩업 비용이 테이블 전체를 다 퍼올리는 풀 스캔 비용을 초과합니다!  
  똑똑한 옵티마이저는 인덱스가 존재하더라도 **인덱스를 과감히 버리고 풀 테이블 스캔(Full Table Scan)을 선택**합니다.
- **최악의 개발자 실수 (`FORCE INDEX`)**:  
  옵티마이저가 FTS를 선택하자 당황한 개발자가 힌트(`FORCE INDEX`)를 써서 강제로 인덱스를 타게 만들면, 10배~20배 느려지는 지옥의 성능 참사가 완성됩니다!

---

## 4. 궁극의 구원투수: 커버링 인덱스 (Covering Index)

이 참사를 해결하는 가장 완벽한 해법은 바로 **커버링 인덱스(Covering Index / Index-Only Scan)**입니다.

### 📌 커버링 인덱스의 원리
쿼리가 요구하는 **모든 컬럼**을 인덱스 키에 포함시키는 것입니다:

```sql
-- 튜닝 전: status 컬럼만 인덱스에 있음 -> SELECT * 때문에 북마크 룩업 필수!
CREATE INDEX idx_status ON orders(status);
SELECT order_id, order_date, total_price FROM orders WHERE status = 'ACTIVE';

-- 튜닝 후: 쿼리에 필요한 모든 컬럼을 복합 인덱스로 구성!
CREATE INDEX idx_covering ON orders(status, order_date, total_price);
SELECT order_id, order_date, total_price FROM orders WHERE status = 'ACTIVE';
```

```
[커버링 인덱스(Covering Index)의 동작]
  B-Tree 리프 노드에 [status, order_date, total_price, (PK)]가 이미 다 들어있음!
  ──► 테이블 실제 데이터 페이지로 갈 필요가 전혀 없음!
  ──► 💥 북마크 룩업(Bookmark Lookup) 횟수: 정확히 0회! (Zero Table Access)
  ──► 순수 인덱스 페이지만 순차적으로 읽고 즉시 결과 반환!
```

### 🚀 커버링 인덱스의 기적
- 1만 번의 무작위 디스크 헤드 점프(Random I/O)가 **완전히 소멸**합니다.
- 선택도가 20%, 50%, 80%에 달하더라도 풀 테이블 스캔보다 수십 배~수백 배 빠릅니다.
- `EXPLAIN` 실행 계획에 **`Using index`** (MySQL) 또는 **`Index Only Scan`** (PostgreSQL)이 선명하게 찍힙니다.

---

## 5. 클러스터링 팩터 (Clustering Factor)

실제 테이블에서 북마크 룩업의 비용을 결정짓는 핵심 물리 통계는 **클러스터링 팩터(Clustering Factor)**입니다:
- 인덱스 키 순서와 실제 테이블 데이터의 물리적 저장 순서가 완벽히 일치하면(`Clustering Ratio ≈ 0.0`), 인접한 레코드들이 동일한 데이터 페이지에 모여 있어 방문 페이지 수가 대폭 줄어듭니다.
- 반면 데이터가 완전히 무작위로 뒤섞여 있으면(`Clustering Ratio ≈ 1.0`), 레코드 1건을 읽을 때마다 매번 새로운 디스크 블록을 로딩해야 하므로 손익분기점이 1% 미만으로 곤두박질칩니다.

---

## 6. 결론: 실무 SQL 작성 3대 원칙

1. **무지성 `SELECT *` 금지**: 필요한 컬럼만 명시해야 커버링 인덱스를 탈 수 있는 기회가 생깁니다.
2. **카디널리티가 낮은 컬럼 주의**: `status`, `gender` 등 값의 종류가 적고 결과 건수가 많은 컬럼에 단독 인덱스를 걸면 FTS보다 느려질 수 있습니다.
3. **자주 조회되는 컬럼은 복합 인덱스(Covering Index)로 결합**: 조회 컬럼을 인덱스 후미에 배치하여 북마크 룩업을 0으로 박멸하십시오.
