# Problem 076: ORM N+1 쿼리 문제와 데이터로더 배치 최적화 (N+1 Query Problem & DataLoader Batching)

## 문제 설명

수백만 명의 사용자가 이용하는 웹 애플리케이션(Spring Boot JPA, Node.js GraphQL, TypeORM, Prisma)을 운영하던 팀에 심각한 성능 지연 장애가 발생했습니다:
> "메인 화면에서 게시글 고작 20개를 긁어오는 API인데, 개발 서버에서는 0.05초 만에 뜨던 것이 운영 클라우드에 배포하자마자 응답 시간이 3초로 폭증했습니다!  
> DB 쿼리 로그를 열어보니 게시글 20개를 가져오는 쿼리 1개 뒤에, 작성자를 조회하는 `SELECT * FROM users WHERE id = ?` 쿼리가 무려 20번이나 연속으로 쏟아져 DB 커넥션 풀이 고갈되었습니다!"

이 장애의 주범은 객체-관계 불일치(Impedance Mismatch)로 인해 발생하는 **ORM의 치명적인 지연 로딩(Lazy Loading) 안티패턴인 N+1 쿼리 문제**였습니다:
- **객체 지향 탐색과 지연 로딩의 함정**:
  - 개발자는 편리하게 `post.getAuthor().getName()` 형태로 코드를 작성합니다.
  - 하지만 ORM은 부모 엔티티(게시글 $N$개)를 조회한 후, 루프를 돌며 각 객체의 연관 엔티티(작성자)에 접근할 때마다 개별 SQL 쿼리를 즉각 DB로 전송합니다.
  - 부모 쿼리 1회 + 자식 쿼리 $N$회 = **총 $1 + N$회의 쿼리가 연쇄 발생**합니다.
- **네트워크 왕복 시간(RTT: Round Trip Time)의 누적 참사**:
  - 단일 쿼리 실행 시간이 0.5ms로 아무리 빨라도, 앱 서버와 DB 서버 사이에는 물리적인 네트워크 지연(예: 5ms)이 존재합니다.
  - 100개의 쿼리가 순차적으로 날아가면 네트워크 왕복 대기 시간만 $100 \times 5\text{ms} = 500\text{ms}$가 누적되어 전체 응답이 멈춰 섭니다.

마트에서 저녁 요리 재료 20가지를 사려고 할 때:
- 두부 1모 사서 집에 오고, 다시 마트 가서 대파 1단 사서 집에 오고, 다시 마트 가서 양파 1망 사서 집에 오는 짓을 20번 반복하다가 다리가 부러지는 꼴입니다 (Naive N+1 방식).
- 현명한 사람이라면 메모장에 살 재료 20개를 적어두고(배치 수집), 중복된 재료는 1개로 합친 뒤(Deduplication), 마트에 단 1번만 가서 카트에 다 쓸어 담아 옵니다 (DataLoader 방식: `WHERE id IN (...)`).

페이스북(Meta)이 GraphQL을 위해 고안하여 전 세계 표준이 된 **DataLoader** 패턴은 이를 완벽하게 해결합니다:
1. **배치 수집 (Batching)**: 각 게시글이 작성자 정보를 요청할 때 즉시 DB로 쏘지 않고 메모리 버퍼에 등록합니다.
2. **중복 제거 (Deduplication)**: 여러 게시글의 작성자가 동일한 경우 중복 키를 제거하여 고유 ID 목록(`Set`)을 구성합니다.
3. **단 1회의 배치 쿼리**: 모인 키들로 `SELECT * FROM users WHERE id IN (:unique_author_ids)` 쿼리를 단 1회 실행하여 인메모리에 캐싱하고 각 게시글에 결과를 매핑합니다.
4. 총 쿼리 수는 $1 + N$회에서 **단 2회($1 + 1$)**로 급감하며, 수십 번의 네트워크 RTT가 사라집니다!

당신은 동일한 데이터 조회 요청에 대해 단순 Lazy Loading을 수행하는 **Naive ORM 엔진**과 배치 수집 및 중복 제거를 적용한 **DataLoader 엔진**의 쿼리 횟수, 네트워크 누적 지연시간, 데이터 무결성을 검증하는 N+1 시뮬레이터를 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정 (`SYSTEM_CONFIG`)
- `NETWORK_RTT_MS <int>`: 앱 서버와 DB 서버 간의 1회 네트워크 왕복 시간(ms).
- `QUERY_EXEC_MS <int>`: DB 내부의 1회 쿼리 실행 시간(ms).
- 1회 쿼리당 소요 지연시간: $\text{PER\_QUERY\_MS} = \text{NETWORK\_RTT\_MS} + \text{QUERY\_EXEC\_MS}$.

---

### 2. 데이터 저장소 스키마
- `USERS`: `(id, name)`
- `POSTS`: `(id, title, author_id)`
- `COMMENTS`: `(id, post_id, commenter_id, content)`

---

### 3. 두 가지 조회 액션 메커니즘

#### 1) `FETCH_POSTS_WITH_AUTHORS <id1,id2,...>`
- **Naive ORM Engine**:
  - 1회 쿼리: `SELECT * FROM posts WHERE id IN (...)` $\to$ 게시글 목록 조회.
  - $N$회 쿼리: 각 게시글마다 `SELECT * FROM users WHERE id = :author_id` 개별 전송.
  - 총 쿼리 수: $1 + N$ (게시글 수).
  - 지연시간: $(1 + N) \times \text{PER\_QUERY\_MS}$.
- **DataLoader Engine**:
  - 1회 쿼리: `SELECT * FROM posts WHERE id IN (...)` $\to$ 게시글 목록 조회.
  - 1회 쿼리: 게시글들의 모든 `author_id`를 중복 제거하여 `SELECT * FROM users WHERE id IN (:unique_ids)` 배치 전송 (작성자가 있으면 1회).
  - 총 쿼리 수: 2회 (게시글이 비어있으면 1회).
  - 지연시간: $\text{쿼리 수} \times \text{PER\_QUERY\_MS}$.

#### 2) `FETCH_POST_DETAILS_WITH_COMMENTS <post_id>` (다단계 N+1)
- 게시글 1개 + 게시글 작성자 + 게시글의 댓글들($M$개) + 각 댓글의 작성자 조회.
- **Naive ORM Engine**:
  - 1회 쿼리: `SELECT * FROM posts WHERE id = :post_id`
  - 1회 쿼리: `SELECT * FROM users WHERE id = :author_id`
  - 1회 쿼리: `SELECT * FROM comments WHERE post_id = :post_id` (댓글 $M$개 반환)
  - $M$회 쿼리: 각 댓글마다 `SELECT * FROM users WHERE id = :commenter_id` 개별 전송.
  - 총 쿼리 수: $3 + M$.
  - 지연시간: $(3 + M) \times \text{PER\_QUERY\_MS}$.
- **DataLoader Engine**:
  - 1회 쿼리: `SELECT * FROM posts WHERE id = :post_id`
  - 1회 쿼리: `SELECT * FROM comments WHERE post_id = :post_id`
  - 1회 쿼리: 게시글 작성자 ID 및 모든 댓글 작성자 ID를 중복 제거하여 `SELECT * FROM users WHERE id IN (:all_unique_user_ids)` 배치 전송.
  - 총 쿼리 수: 단 3회!
  - 지연시간: $3 \times \text{PER\_QUERY\_MS}$.

---

### 4. 액션 명세

#### 1) `INSERT_USER <id> <name>`
- 신규 사용자 삽입.
- 출력 (1줄): `ACT <idx> INSERT_USER ID:<id> NAME:<name>`

#### 2) `INSERT_POST <id> <title> <author_id>`
- 신규 게시글 삽입.
- 출력 (1줄): `ACT <idx> INSERT_POST ID:<id> TITLE:<title> AUTHOR_ID:<author_id>`

#### 3) `INSERT_COMMENT <id> <post_id> <commenter_id> <content>`
- 신규 댓글 삽입.
- 출력 (1줄): `ACT <idx> INSERT_COMMENT ID:<id> POST_ID:<post_id> COMMENTER_ID:<commenter_id>`

#### 4) `FETCH_POSTS_WITH_AUTHORS <id1,id2,...>`
- 게시글 및 작성자 조회.
- 출력 (3줄):
  ```text
  ACT <idx> FETCH_POSTS_WITH_AUTHORS COUNT:<cnt>
    NAIVE: QUERIES:<q> LATENCY:<lat>ms DATA:[<id>:<title>(<author>),...]
    DATALOADER: QUERIES:<q> (BATCH_KEYS:<unique_keys>) LATENCY:<lat>ms MATCH:<TRUE|FALSE>
  ```

#### 5) `FETCH_POST_DETAILS_WITH_COMMENTS <post_id>`
- 포스트 상세 및 댓글/댓글작성자 다단계 조회.
- 출력 (3줄):
  ```text
  ACT <idx> FETCH_POST_DETAILS_WITH_COMMENTS POST_ID:<post_id>
    NAIVE: QUERIES:<q> LATENCY:<lat>ms DATA:POST:<id>(<author>) COMMENTS:[<c_id>:<c_author>:<content>,...]
    DATALOADER: QUERIES:<q> (BATCH_KEYS:<unique_keys>) LATENCY:<lat>ms MATCH:<TRUE|FALSE>
  ```

#### 6) `CHECK_METRICS`
- 누적 메트릭 점검.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_METRICS
    NAIVE: TOTAL_QUERIES:<q> TOTAL_LATENCY:<lat>ms
    DATALOADER: TOTAL_QUERIES:<q> TOTAL_LATENCY:<lat>ms
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
NETWORK_RTT_MS <rtt_ms>
QUERY_EXEC_MS <query_ms>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 실행 결과 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (7줄):
```text
SUMMARY TOTAL_FETCH_REQUESTS:<cnt>
SUMMARY NAIVE TOTAL_QUERIES:<q> TOTAL_LATENCY:<lat>ms
SUMMARY DATALOADER TOTAL_QUERIES:<q> TOTAL_LATENCY:<lat>ms
SUMMARY QUERIES_SAVED:<saved> (QUERY_REDUCTION:<pct:.2f>%)
SUMMARY LATENCY_SAVED:<lat_saved>ms (LATENCY_REDUCTION:<pct:.2f>%)
SUMMARY DATA_CONSISTENCY: 100%_MATCH
SUMMARY ORM_VERDICT: DATALOADER_ELIMINATES_N_PLUS_ONE
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
NETWORK_RTT_MS 5
QUERY_EXEC_MS 1
ACTIONS
INSERT_USER 1 Alice
INSERT_USER 2 Bob
INSERT_POST 101 Intro 1
INSERT_POST 102 News 2
INSERT_POST 103 Guide 1
FETCH_POSTS_WITH_AUTHORS 101,102,103
INSERT_COMMENT 1 101 2 Great!
INSERT_COMMENT 2 101 1 Thanks!
FETCH_POST_DETAILS_WITH_COMMENTS 101
CHECK_METRICS
```

**출력:**
```text
ACT 1 INSERT_USER ID:1 NAME:Alice
ACT 2 INSERT_USER ID:2 NAME:Bob
ACT 3 INSERT_POST ID:101 TITLE:Intro AUTHOR_ID:1
ACT 4 INSERT_POST ID:102 TITLE:News AUTHOR_ID:2
ACT 5 INSERT_POST ID:103 TITLE:Guide AUTHOR_ID:1
ACT 6 FETCH_POSTS_WITH_AUTHORS COUNT:3
  NAIVE: QUERIES:4 LATENCY:24ms DATA:[101:Intro(Alice),102:News(Bob),103:Guide(Alice)]
  DATALOADER: QUERIES:2 (BATCH_KEYS:2) LATENCY:12ms MATCH:TRUE
ACT 7 INSERT_COMMENT ID:1 POST_ID:101 COMMENTER_ID:2
ACT 8 INSERT_COMMENT ID:2 POST_ID:101 COMMENTER_ID:1
ACT 9 FETCH_POST_DETAILS_WITH_COMMENTS POST_ID:101
  NAIVE: QUERIES:5 LATENCY:30ms DATA:POST:101(Alice) COMMENTS:[1:Bob:Great!,2:Alice:Thanks!]
  DATALOADER: QUERIES:3 (BATCH_KEYS:2) LATENCY:18ms MATCH:TRUE
ACT 10 CHECK_METRICS
  NAIVE: TOTAL_QUERIES:9 TOTAL_LATENCY:54ms
  DATALOADER: TOTAL_QUERIES:5 TOTAL_LATENCY:30ms
SUMMARY TOTAL_FETCH_REQUESTS:2
SUMMARY NAIVE TOTAL_QUERIES:9 TOTAL_LATENCY:54ms
SUMMARY DATALOADER TOTAL_QUERIES:5 TOTAL_LATENCY:30ms
SUMMARY QUERIES_SAVED:4 (QUERY_REDUCTION:44.44%)
SUMMARY LATENCY_SAVED:24ms (LATENCY_REDUCTION:44.44%)
SUMMARY DATA_CONSISTENCY: 100%_MATCH
SUMMARY ORM_VERDICT: DATALOADER_ELIMINATES_N_PLUS_ONE
```
