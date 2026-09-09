# Problem 075: SNS 피드 타임라인 아키텍처와 하이브리드 팬아웃 (Feed Timeline Fan-out-on-Write vs Hybrid Fan-out)

## 문제 설명

수천만 명의 유저가 활동하는 소셜 네트워크 서비스(트위터/인스타그램 형태)를 운영하던 팀에 초대형 서비스 장애가 발생했습니다:
> "팔로워 1,000만 명을 보유한 슈퍼스타가 콘서트 사진 한 장(`POST`)을 올리는 순간, 백엔드 메시지 브로커(Kafka)에 수천만 건의 이벤트가 폭주하고 Redis 클러스터와 DB CPU가 100%로 치솟았습니다!  
> 20분 동안 다른 일반 사용자들의 게시글 업로드와 알림 발송까지 모조리 멈춰 섰습니다!"

이 장애의 원인은 SNS 피드(Timeline)의 대표적인 병목인 **쓰기 시점 팬아웃(Fan-out-on-Write / Push 방식)의 핫스팟 셀럽 문제(Celebrity Problem)**였습니다:
- **쓰기 시점 푸시 모델 (Fan-out-on-Write / Push)**:
  - 사용자가 글을 쓸 때, 해당 사용자를 팔로우하는 모든 팔로워의 개인 수신함(`inbox`)에 글을 일일이 복사(Push)해 넣는 방식입니다.
  - 장점: 사용자가 홈 피드를 읽을 때는 자기 `inbox`만 열어보면 되므로 읽기 속도가 극도로 빠릅니다 ($O(1)$).
  - 치명적 단점: 팔로워가 수백만 명인 인플루언서가 글을 쓰면, 포스트 단 1개 때문에 수백만 번의 쓰기 I/O가 발생하여 시스템이 마비됩니다 ($O(N)$).
- **읽기 시점 풀 모델 (Fan-out-on-Read / Pull)**:
  - 글을 쓸 때는 아무 데도 복사하지 않고 작성자의 보관함(`outbox`)에만 저장합니다 ($O(1)$).
  - 치명적 단점: 사용자가 피드를 조회할 때마다 내가 팔로우하는 수백 명의 작성자 보관함을 일일이 디스크에서 긁어모아 시간순으로 정렬(Merge Sort)해야 하므로 읽기 지연(Read Latency)이 심각하게 폭증합니다.

1만 세대가 사는 아파트 단지에 비유하자면:
- 동네 친구 편지(팔로워 5명)는 집배원이 우편함(Inbox)에 직접 꽂아주는 게 빠릅니다 (Push).
- 하지만 단지 전체 1만 명이 팔로우하는 관리소장님(팔로워 10,000명)의 공지문은 집배원이 1만 가구를 돌며 우편함에 넣으면 탈진해 쓰러집니다. 대신 엘리베이터 입구 게시판(Outbox)에 딱 1장만 붙여두고, 주민들이 엘리베이터를 탈 때 읽게 해야 합니다 (Pull)!

이 두 방식의 장점만을 결합한 것이 바로 트위터와 인스타그램이 전 세계 표준으로 정립한 **하이브리드 팬아웃(Hybrid Fan-out)** 아키텍처입니다:
1. **일반 사용자 (`followers < CELEBRITY_THRESHOLD`)**: 포스트 작성 시 팔로워들의 `inbox`에 즉시 배달 (**Push**). 팔로워 수가 적으므로 부하가 거의 없습니다.
2. **인플루언서 (`followers >= CELEBRITY_THRESHOLD`)**: 팔로워들에게 푸시하지 않고 본인의 `outbox`에만 1건 기록 (**Pull**). 쓰기 부하를 $O(1)$로 완전 제거합니다.
3. **피드 조회 (`READ_FEED`)**: 사용자의 개인 `inbox`(일반 친구 글)와 사용자가 팔로우하는 소수 인플루언서들의 `outbox`(최신 글)를 가져와 시간 역순으로 병합(Merge)하여 상위 `FEED_LIMIT`개를 반환합니다.

당신은 동일한 소셜 활동 스트림에 대해 단순 푸시를 수행하는 **Naive Push 엔진**과 스마트 팬아웃을 수행하는 **Hybrid Fan-out 엔진**의 쓰기/읽기 I/O 비용과 피드 데이터 일관성(Consistency)을 검증하는 SNS 피드 시뮬레이터를 작성해야 합니다.

---

## 시스템 요구사항 및 동작 규칙

### 1. 전역 설정 (`SYSTEM_CONFIG`)
- `CELEBRITY_THRESHOLD <int>`: 인플루언서(Celebrity) 판정 기준 팔로워 수.
- `FEED_LIMIT <int>`: 피드 조회 시 반환할 최대 포스트 수.

---

### 2. 엔티티 및 상태 관리
- 모든 포스트는 시스템 전역 시퀀스 번호(`seq`, 1부터 1씩 단조 증가)를 부여받습니다.
- `FOLLOW <follower> <followee>` 시점의 `seq`가 기록되며, 사용자는 **팔로우 이후에 작성된 글만** 피드에서 볼 수 있습니다.

---

### 3. 두 가지 피드 엔진 메커니즘

#### 1) Naive Push Engine (Fan-out-on-Write)
- `POST <author> <post_id>`:
  - 작성자의 모든 팔로워의 개인 `inbox`에 해당 포스트를 복사(Push).
  - 쓰기 I/O 비용: $1 \text{ (작성자 저장)} + \text{len(followers)}$.
- `READ_FEED <user>`:
  - 본인의 `inbox`에서 최신 포스트 순으로 최대 `FEED_LIMIT`개 추출.
  - 읽기 I/O 비용: $1$.

#### 2) Hybrid Fan-out Engine (Smart Push + Pull)
- `POST <author> <post_id>`:
  - 모든 포스트는 작성자의 `outbox`에 저장 ($1$회 쓰기).
  - 작성자가 **CELEBRITY** (`len(followers) >= CELEBRITY_THRESHOLD`)인 경우:
    - 팔로워들에게 푸시하지 않음. 쓰기 I/O 비용: $1$.
  - 작성자가 **NORMAL** (`len(followers) < CELEBRITY_THRESHOLD`)인 경우:
    - 작성자의 모든 팔로워의 `inbox`에 푸시. 쓰기 I/O 비용: $1 + \text{len(followers)}$.
- `READ_FEED <user>`:
  - 1) 본인의 `inbox` (일반 친구들이 푸시한 글) 조회 ($1$회 읽기).
  - 2) 자신이 팔로우하는 **셀럽들**의 `outbox` (팔로우 이후 글) 조회 ($\text{len(celeb\_following)}$회 읽기).
  - 읽기 I/O 비용: $1 + \text{len(celeb\_following)}$.
  - 두 소스의 글들을 `seq` 내림차순(최신순)으로 병합 정렬하여 상위 `FEED_LIMIT`개 반환.
  - 두 엔진이 반환한 피드 목록이 100% 동일한지 일관성(`MATCH:TRUE|FALSE`) 판정.

---

### 4. 액션 명세

#### 1) `FOLLOW <follower> <followee>`
- 팔로우 관계 추가.
- 출력 (1줄):
  ```text
  ACT <idx> FOLLOW <follower> -> <followee> (FOLLOWEE_FOLLOWERS:<cnt>)
  ```

#### 2) `POST <author> <post_id>`
- 포스트 작성.
- 출력 (3줄):
  ```text
  ACT <idx> POST AUTHOR:<author> POST_ID:<post_id>
    NAIVE: FANOUT_WRITES:<w> CUMULATIVE_WRITES:<cum_w>
    HYBRID: ROLE:<NORMAL|CELEBRITY> FANOUT_WRITES:<w> CUMULATIVE_WRITES:<cum_w>
  ```

#### 3) `READ_FEED <user>`
- 홈 피드 조회.
- 출력 (3줄):
  ```text
  ACT <idx> READ_FEED USER:<user>
    NAIVE: READ_OPS:<r> FEED:[<ids>]
    HYBRID: READ_OPS:<r> (CELEB_SOURCES:<c_cnt>) FEED:[<ids>] MATCH:<TRUE|FALSE>
  ```

#### 4) `CHECK_METRICS`
- 현재 시점의 누적 I/O 메트릭 점검.
- 출력 (3줄):
  ```text
  ACT <idx> CHECK_METRICS
    NAIVE: TOTAL_WRITES:<w> TOTAL_READS:<r> TOTAL_IO:<w+r>
    HYBRID: TOTAL_WRITES:<w> TOTAL_READS:<r> TOTAL_IO:<w+r>
  ```

---

## 입력 형식

```text
SYSTEM_CONFIG
CELEBRITY_THRESHOLD <threshold>
FEED_LIMIT <limit>
ACTIONS
<action_cmd> <args...>
...
```

---

## 출력 형식

1. 각 액션별 실행 결과 (위 명세 참조)
2. 모든 액션 종료 후 최종 통계 요약 (6줄):
```text
SUMMARY TOTAL_POSTS:<posts> TOTAL_READS:<reads>
SUMMARY NAIVE TOTAL_WRITES:<w> TOTAL_READS:<r> TOTAL_IO:<tot>
SUMMARY HYBRID TOTAL_WRITES:<w> TOTAL_READS:<r> TOTAL_IO:<tot>
SUMMARY WRITE_OPS_SAVED:<saved> (WRITE_REDUCTION:<pct:.2f>%)
SUMMARY FEED_CONSISTENCY: 100%_MATCH
SUMMARY ARCHITECTURE_VERDICT: HYBRID_FANOUT_ELIMINATES_CELEBRITY_BOTTLENECK
```

---

## 입출력 예시

### 예시 1

**입력:**
```text
SYSTEM_CONFIG
CELEBRITY_THRESHOLD 3
FEED_LIMIT 5
ACTIONS
FOLLOW U1 U2
FOLLOW U3 U2
FOLLOW U4 U2
POST U2 P1
READ_FEED U1
POST U1 P2
READ_FEED U3
CHECK_METRICS
```

**출력:**
```text
ACT 1 FOLLOW U1 -> U2 (FOLLOWEE_FOLLOWERS:1)
ACT 2 FOLLOW U3 -> U2 (FOLLOWEE_FOLLOWERS:2)
ACT 3 FOLLOW U4 -> U2 (FOLLOWEE_FOLLOWERS:3)
ACT 4 POST AUTHOR:U2 POST_ID:P1
  NAIVE: FANOUT_WRITES:4 CUMULATIVE_WRITES:4
  HYBRID: ROLE:CELEBRITY FANOUT_WRITES:1 CUMULATIVE_WRITES:1
ACT 5 READ_FEED USER:U1
  NAIVE: READ_OPS:1 FEED:[P1]
  HYBRID: READ_OPS:2 (CELEB_SOURCES:1) FEED:[P1] MATCH:TRUE
ACT 6 POST AUTHOR:U1 POST_ID:P2
  NAIVE: FANOUT_WRITES:1 CUMULATIVE_WRITES:5
  HYBRID: ROLE:NORMAL FANOUT_WRITES:1 CUMULATIVE_WRITES:2
ACT 7 READ_FEED USER:U3
  NAIVE: READ_OPS:1 FEED:[P1]
  HYBRID: READ_OPS:2 (CELEB_SOURCES:1) FEED:[P1] MATCH:TRUE
ACT 8 CHECK_METRICS
  NAIVE: TOTAL_WRITES:5 TOTAL_READS:2 TOTAL_IO:7
  HYBRID: TOTAL_WRITES:2 TOTAL_READS:4 TOTAL_IO:6
SUMMARY TOTAL_POSTS:2 TOTAL_READS:2
SUMMARY NAIVE TOTAL_WRITES:5 TOTAL_READS:2 TOTAL_IO:7
SUMMARY HYBRID TOTAL_WRITES:2 TOTAL_READS:4 TOTAL_IO:6
SUMMARY WRITE_OPS_SAVED:3 (WRITE_REDUCTION:60.00%)
SUMMARY FEED_CONSISTENCY: 100%_MATCH
SUMMARY ARCHITECTURE_VERDICT: HYBRID_FANOUT_ELIMINATES_CELEBRITY_BOTTLENECK
```
