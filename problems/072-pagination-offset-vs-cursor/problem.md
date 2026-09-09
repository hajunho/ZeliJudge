# Problem 072: 오프셋 페이징의 덫과 커서 기반 페이징 (OFFSET Pagination Bottleneck vs Keyset Cursor Pagination)

## 문제 설명

수백만 명의 사용자가 이용하는 전자상거래 플랫폼에서 상품 목록 및 게시판 API를 운영하던 팀에 치명적인 장애가 발생했습니다:
> "게시판 1페이지를 볼 때는 0.01초 만에 번개처럼 뜨는데, 검색 로봇이나 사용자가 1만 페이지(`OFFSET 200000`)를 누르는 순간 DB CPU가 100%로 치솟고 30초 동안 멈춰 섭니다!  
> 게다가 모바일 앱 피드에서 사용자가 1페이지를 보고 스크롤을 내렸는데, 그 사이에 새로 등록된 상품들 때문에 1페이지에서 이미 보았던 상품 3개가 2페이지 첫머리에 또다시 중복 노출되는 기괴한 버그가 발생하고 있습니다!"

원인은 대규모 데이터베이스의 특성을 고려하지 않고 작성한 **오프셋(OFFSET) 페이징 안티패턴**이었습니다:
- **디스크 I/O 폭증의 함정**: `LIMIT 20 OFFSET 200000` 쿼리를 실행하면, DB 엔진은 20만 번째 위치로 바로 점프할 수 없어 200,020개의 행을 디스크에서 메모리로 전부 퍼 올린 뒤 앞의 200,000개를 손수 버립니다 ($O(N + M)$). 페이지가 뒤로 갈수록 DB가 읽고 버리는 데이터양이 선형적으로 증가합니다.
- **데이터 드리프트(Data Drift)**: 사용자가 페이징을 탐색하는 도중 신규 데이터가 삽입(`INSERT`)되거나 삭제되면, 페이지 경계가 밀려나면서 이전 페이지의 데이터가 다시 노출되는 중복 버그(`DUPLICATE_COUNT`)나 특정 데이터가 건너뛰어지는 누락 버그가 발생합니다.

100만 쪽에 달하는 백과사전에서 50만 쪽을 읽기 위해 1쪽부터 50만 장을 손으로 한 장 한 장 세어 넘기는 바보짓을 멈추려면, 마지막으로 읽은 위치에 책갈피를 꽂아두는 **커서(Cursor / Keyset) 기반 페이징**을 사용해야 합니다:
1. **B-Tree 핀포인트 점프 ($O(\log N + M)$)**: "몇 개를 건너뛸지(OFFSET)" 대신 "마지막으로 본 ID(Cursor)"를 기준으로 조회(`WHERE id < :cursor_id ORDER BY id DESC LIMIT 20`)하여, B-Tree 인덱스 트리를 타고 $0.001$초 만에 해당 위치로 직행합니다.
2. **100% 무결성 유지**: 신규 데이터가 아무리 실시간으로 유입되더라도 커서 이후의 데이터만 순차 탐색하므로 데이터 중복 노출이나 누락이 물리적으로 발생하지 않습니다.

당신은 동일한 데이터셋과 페이징 요청 스트림에 대해 **Naive OFFSET 엔진**과 **Cursor Keyset 엔진**의 검사 행 수(`ROWS_EXAMINED`)와 중복 노출 발생 건수를 비교 시뮬레이션하는 데이터베이스 페이징 최적화 엔진을 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정
- `PAGE_SIZE <page_size>`: 1회 페이징 시 반환할 기본 레코드 수.
- 모든 레코드는 `id` 내림차순(`DESC`) 정렬 상태로 관리됩니다 (최신순).

---

### 2. 두 가지 페이징 아키텍처

#### 1) Naive OFFSET Engine (안티패턴)
- `PAGE_OFFSET <page_num>` 호출 시:
  - 오프셋 계산: $\text{offset} = (\text{page\_num} - 1) \times \text{page\_size}$
  - 스캔 비용:
    $$\text{ROWS\_EXAMINED} = \min(N, \text{offset} + \text{page\_size})$$
  - 반환 범위: `[offset : offset + page_size]`
  - 중복 검사: 이전에 이미 조회했던 ID가 다시 반환되면 `DUPLICATES_SEEN` 카운트 증가.

#### 2) Cursor Keyset Engine (모범 설계)
- `PAGE_CURSOR <cursor_id>` 호출 시:
  - B-Tree 탐색 깊이: $H = \max(1, \lceil \log_2 N \rceil)$ (단, $N=0$이면 $H=1$)
  - `cursor_id`가 `START`, `NONE`, `-1`인 경우: 최상단 첫 번째 레코드부터 시작.
  - 그 외의 경우: B-Tree 이진 탐색으로 `id < cursor_id`를 만족하는 첫 번째 위치 Seek.
  - 스캔 비용:
    $$\text{ROWS\_EXAMINED} = H + \text{ROWS\_RETURNED}$$
  - 반환 범위: Seek 위치부터 `page_size`개 슬라이싱.
  - 다음 커서: 반환된 마지막 레코드의 ID (반환 결과가 없으면 `NONE`).
  - 중복 검사: 커서 기반 탐색은 항상 중복 노출 0건 유지.

---

### 3. 4대 액션 명세

#### 1) `INSERT_RECORD <id> <title>`
- 신규 레코드 삽입 (초기 적재 또는 페이징 도중 동적 유입).
- 출력 (1줄):
  ```text
  ACT <idx> INSERT_RECORD ID:<id> TITLE:<title>
  ```

#### 2) `PAGE_OFFSET <page_num>`
- 오프셋 기반 페이징 실행.
- 출력 (2줄):
  ```text
  ACT <idx> PAGE_OFFSET PAGE:<page_num>
    NAIVE_OFFSET: EXAMINED:<examined> ROWS_RETURNED:<cnt> IDS:[<ids>] DUPLICATES_SEEN:<dups>
  ```

#### 3) `PAGE_CURSOR <cursor_id>`
- 커서 기반 페이징 실행.
- 출력 (2줄):
  ```text
  ACT <idx> PAGE_CURSOR CURSOR:<cursor_id>
    CURSOR_KEYSET: EXAMINED:<examined> ROWS_RETURNED:<cnt> NEXT_CURSOR:<next_cur> IDS:[<ids>] DUPLICATES_SEEN:<dups>
  ```

#### 4) `CHECK_METRICS`
- 현재까지의 누적 스캔 행 수 및 중복 발생 수 점검.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_METRICS
    NAIVE_OFFSET: TOTAL_EXAMINED:<tot_naive> DUPLICATES:<dups_naive>
    CURSOR_KEYSET: TOTAL_EXAMINED:<tot_cursor> DUPLICATES:<dups_cursor>
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
PAGE_SIZE <page_size>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 출력 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (5줄):
```text
SUMMARY TOTAL_RECORDS:<total_records>
SUMMARY NAIVE_OFFSET TOTAL_EXAMINED:<tot_naive> DUPLICATES_SEEN:<dups_naive>
SUMMARY CURSOR_KEYSET TOTAL_EXAMINED:<tot_cursor> DUPLICATES_SEEN:<dups_cursor>
SUMMARY ROWS_EXAMINED_SAVED:<saved> (SCAN_REDUCTION:<pct:.2f>%)
SUMMARY PAGINATION_VERDICT: CURSOR_100%_CONSISTENT_AND_FAST
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
PAGE_SIZE 3
ACTIONS
INSERT_RECORD 1 Item1
INSERT_RECORD 2 Item2
INSERT_RECORD 3 Item3
INSERT_RECORD 4 Item4
INSERT_RECORD 5 Item5
INSERT_RECORD 6 Item6
PAGE_OFFSET 1
PAGE_CURSOR START
INSERT_RECORD 7 Item7
PAGE_OFFSET 2
PAGE_CURSOR 4
CHECK_METRICS
```

**출력:**
```text
ACT 1 INSERT_RECORD ID:1 TITLE:Item1
ACT 2 INSERT_RECORD ID:2 TITLE:Item2
ACT 3 INSERT_RECORD ID:3 TITLE:Item3
ACT 4 INSERT_RECORD ID:4 TITLE:Item4
ACT 5 INSERT_RECORD ID:5 TITLE:Item5
ACT 6 INSERT_RECORD ID:6 TITLE:Item6
ACT 7 PAGE_OFFSET PAGE:1
  NAIVE_OFFSET: EXAMINED:3 ROWS_RETURNED:3 IDS:[6,5,4] DUPLICATES_SEEN:0
ACT 8 PAGE_CURSOR CURSOR:START
  CURSOR_KEYSET: EXAMINED:6 ROWS_RETURNED:3 NEXT_CURSOR:4 IDS:[6,5,4] DUPLICATES_SEEN:0
ACT 9 INSERT_RECORD ID:7 TITLE:Item7
ACT 10 PAGE_OFFSET PAGE:2
  NAIVE_OFFSET: EXAMINED:6 ROWS_RETURNED:3 IDS:[4,3,2] DUPLICATES_SEEN:1
ACT 11 PAGE_CURSOR CURSOR:4
  CURSOR_KEYSET: EXAMINED:6 ROWS_RETURNED:3 NEXT_CURSOR:1 IDS:[3,2,1] DUPLICATES_SEEN:0
ACT 12 CHECK_METRICS
  NAIVE_OFFSET: TOTAL_EXAMINED:9 DUPLICATES:1
  CURSOR_KEYSET: TOTAL_EXAMINED:12 DUPLICATES:0
SUMMARY TOTAL_RECORDS:7
SUMMARY NAIVE_OFFSET TOTAL_EXAMINED:9 DUPLICATES_SEEN:1
SUMMARY CURSOR_KEYSET TOTAL_EXAMINED:12 DUPLICATES_SEEN:0
SUMMARY ROWS_EXAMINED_SAVED:-3 (SCAN_REDUCTION:-33.33%)
SUMMARY PAGINATION_VERDICT: CURSOR_100%_CONSISTENT_AND_FAST
```
