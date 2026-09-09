# Problem #041: 동시에 좋아요를 1,000명이 눌렀더니 숫자가 50밖에 안 올라가요?!: 분산 카운터(Distributed Counter)와 샤디드 카운터

## 📖 실무 스토리: 라이브 방송에서 하트를 10만 번 눌렀는데 카운터가 멈췄습니다!

인기 라이브 커머스 플랫폼의 백엔드 개발자 나코딩은 유명 연예인이 출연하는 라이브 방송을 오픈했습니다.
방송이 시작되자마자 **10만 명의 시청자가 화면의 '좋아요(하트)' 버튼을 초당 수십 번씩 광클**하기 시작했습니다!

나코딩은 가장 단순하고 직관적인 쿼리로 좋아요 수를 증가시켰습니다:
```sql
UPDATE posts SET like_count = like_count + 1 WHERE id = :post_id;
```

> **나코딩**: "1씩 더하는 UPDATE 쿼리니까 동시성 문제 없이 정확하게 집계되겠지!"

하지만 10초 뒤, **DB 서버의 CPU가 100%를 찍고 슬로우 쿼리와 커넥션 풀 고갈로 전사 서비스가 마비되었습니다!**

1. **"화면에는 10만 명이 하트를 눌렀는데, 실제 DB에는 50개밖에 안 찍혔어요!"**
   * 관계형 데이터베이스(MySQL InnoDB, PostgreSQL 등)는 단일 행을 수정할 때 데이터 정합성을 위해 **행 배타락(Row Exclusive Lock / X-Lock)**을 겁니다.
   * `WHERE id = 1`이라는 **단 1개의 행(Row)**을 두고 초당 수만 개의 트랜잭션이 한 줄로서서 락을 획득하려고 대기했습니다!
   * DB의 락 대기열이 폭발하면서 대부분의 트랜잭션이 락 타임아웃(`Lock wait timeout exceeded`)으로 강제 롤백되었습니다.
   * 유저들은 하트를 10번 넘게 눌렀지만, 락 경쟁에서 밀려 9번은 실패하고 단 1번만 간신히 반영된 것입니다!
2. **"락을 기다리는 스레드가 수천 개로 불어나 CPU가 컨텍스트 스위칭으로 자멸했습니다!"**

> **"단 1개의 출입문(행)에 10만 명이 한 번에 몰려드니 압사 사고가 날 수밖에 없습니다! 출입문을 16개, 32개로 쪼갤 수는 없을까요?!"**

인스타그램, 유튜브, 레딧과 같은 대규모 플랫폼에서는 초당 수십만 건의 좋아요/조회수 폭주를 버텨내기 위해 **샤디드 카운터(Sharded Counter)** 아키텍처를 사용합니다!
단일 카운터 1개 대신 **$S$개의 독립된 슬롯(Slot)**을 만들어 쓰기 트랜잭션을 분산시키고, 총합을 읽을 때는 $S$개 슬롯의 합계를 더하는(`SUM`) 것입니다.

여러분의 임무는 단일 카운터(SINGLE)와 샤디드 카운터(SHARDED)의 동시성 락 경합 모델을 시뮬레이션하고, 락 타임아웃 방어율과 처리량 개선율(Throughput Improvement)을 정밀 계측하는 카운터 엔진을 구현하는 것입니다!

---

## 🎯 문제 요구사항

좋아요 클릭(`LIKE`)과 조회(`READ`) 이벤트를 시간 순서대로 처리하며 두 카운터 모델의 동작을 비교 평가하십시오:

### 1. 락 경합 및 시간 윈도우 규칙
* 시스템 시간은 밀리초(ms) 단위이며, **100ms 단위의 시간 윈도우(Window ID = $timestamp // 100$)**로 나뉩니다.
* 각 슬롯(단일 카운터의 1개 슬롯 또는 샤디드 카운터의 각 슬롯)은 **단위 100ms 윈도우 내에서 최대 `SLOT_CAPACITY` $C$건**의 쓰기 트랜잭션만 락 경합 없이 처리할 수 있습니다.
* 해당 윈도우 내에서 슬롯의 누적 처리 횟수가 이미 $C$에 도달했다면, 그 윈도우 동안 해당 슬롯으로 들어오는 추가 쓰기 요청은 **`LOCK_TIMEOUT`**으로 실패(롤백)합니다.
* 새로운 윈도우($timestamp // 100$ 증가)가 시작되면 각 슬롯의 동시성 사용량은 자동으로 0으로 리셋됩니다.
* 여러 게시글(`post_id`)이 주어질 수 있으며, 게시글마다 독립된 슬롯과 카운터를 가집니다.

### 2. 2대 카운터 모델 동작 방식

1. **모델 1: SINGLE (단일 행 카운터 - 초보의 함정)**
   * 해당 게시글의 모든 유저 요청이 **단 하나의 슬롯(Slot 0)**으로 몰립니다.
   * 해당 윈도우에서 게시글의 처리 횟수가 $C$ 미만이면 성공(`SUCCESS`), $C$ 이상이면 즉시 `LOCK_TIMEOUT` 실패.

2. **모델 2: SHARDED (샤디드 카운터 - Golden Standard)**
   * 게시글마다 $S$개의 독립된 슬롯(`slot_0`, `slot_1`, ..., `slot_{S-1}`)을 둡니다.
   * 유저 $U$의 좋아요 요청은 유저 해시 규칙에 따라 특정 슬롯으로 분산됩니다:
     $$\text{slot\_id} = U \pmod S$$
   * 해당 슬롯의 윈도우 내 처리 횟수가 $C$ 미만이면 성공(`SUCCESS`), $C$ 이상이면 해당 슬롯의 `LOCK_TIMEOUT` 실패.
   * 각 슬롯은 서로 다른 행(Row)이므로 락을 공유하지 않고 완전히 병렬로 실행됩니다!

3. **조회 이벤트 (`READ`)**:
   * SINGLE 카운터는 단일 누적 성공 횟수를 출력합니다.
   * SHARDED 카운터는 $S$개 슬롯 전체의 누적 성공 횟수의 합계(`SUM`)를 출력합니다.

---

## 📥 입력 형식 (Input Format)

```text
NUM_SLOTS <S>
SLOT_CAPACITY <C>
EVENTS <E>
<event_1>
<event_2>
...
```

* 첫 번째 줄: `NUM_SLOTS` 키워드 뒤에 샤디드 카운터 슬롯 수 $S$ ($1 \le S \le 32$)가 주어집니다.
* 두 번째 줄: `SLOT_CAPACITY` 키워드 뒤에 100ms당 슬롯 최대 처리 용량 $C$ ($1 \le C \le 1,000$)가 주어집니다.
* 세 번째 줄: `EVENTS` 키워드 뒤에 총 이벤트 개수 $E$ ($1 \le E \le 30,000$)가 주어집니다.
* 네 번째 줄부터 각 이벤트가 시간 순서(오름차순)대로 주어집니다:
  * `LIKE <timestamp> <user_id> <post_id>`
  * `READ <timestamp> <post_id>`

---

## 📤 출력 형식 (Output Format)

각 이벤트에 대해 다음 형식으로 1줄씩 출력합니다:
* `LIKE` 이벤트:
  ```text
  LIKE <timestamp> USER:<user_id> POST:<post_id> SINGLE:<single_status> SHARDED:slot_<slot_id>:<sharded_status>
  ```
  * 상태값: `SUCCESS` 또는 `LOCK_TIMEOUT`
* `READ` 이벤트:
  ```text
  READ <timestamp> POST:<post_id> SINGLE:<single_count> SHARDED:<sharded_sum>
  ```

모든 이벤트 처리 후 마지막 줄에 종합 통계(Summary)를 1줄 출력합니다:
```text
SUMMARY TOTAL_LIKES:<total_likes> SINGLE_SUCCESS:<s_ok> SINGLE_TIMEOUTS:<s_to> SHARDED_SUCCESS:<sh_ok> SHARDED_TIMEOUTS:<sh_to> THROUGHPUT_IMPROVEMENT:<pct>%
```
* `THROUGHPUT_IMPROVEMENT`: 단일 카운터 대비 샤디드 카운터의 성공 처리량 개선율 (소수점 첫째 자리 반올림, 예: `100.0%`):
  $$\text{Improvement} = \frac{\text{SHARDED\_SUCCESS} - \text{SINGLE\_SUCCESS}}{\text{SINGLE\_SUCCESS}} \times 100\%$$
  *(단, $\text{SINGLE\_SUCCESS} = 0$인 경우 `0.0%`로 출력)*

---

## 💡 입출력 예제 (Sample I/O)

### 예제 입력
```text
NUM_SLOTS 4
SLOT_CAPACITY 2
EVENTS 9
LIKE 105 0 post_1
LIKE 105 1 post_1
LIKE 105 2 post_1
LIKE 105 3 post_1
LIKE 105 4 post_1
LIKE 105 8 post_1
READ 150 post_1
LIKE 210 0 post_1
READ 250 post_1
```

### 예제 출력
```text
LIKE 105 USER:0 POST:post_1 SINGLE:SUCCESS SHARDED:slot_0:SUCCESS
LIKE 105 USER:1 POST:post_1 SINGLE:SUCCESS SHARDED:slot_1:SUCCESS
LIKE 105 USER:2 POST:post_1 SINGLE:LOCK_TIMEOUT SHARDED:slot_2:SUCCESS
LIKE 105 USER:3 POST:post_1 SINGLE:LOCK_TIMEOUT SHARDED:slot_3:SUCCESS
LIKE 105 USER:4 POST:post_1 SINGLE:LOCK_TIMEOUT SHARDED:slot_0:SUCCESS
LIKE 105 USER:8 POST:post_1 SINGLE:LOCK_TIMEOUT SHARDED:slot_0:LOCK_TIMEOUT
READ 150 POST:post_1 SINGLE:2 SHARDED:5
LIKE 210 USER:0 POST:post_1 SINGLE:SUCCESS SHARDED:slot_0:SUCCESS
READ 250 POST:post_1 SINGLE:3 SHARDED:6
SUMMARY TOTAL_LIKES:7 SINGLE_SUCCESS:3 SINGLE_TIMEOUTS:4 SHARDED_SUCCESS:6 SHARDED_TIMEOUTS:1 THROUGHPUT_IMPROVEMENT:100.0%
```

---

## 힌트 & 핵심 점검 사항
1. **$t=105$ (단일 100ms 윈도우 동시 폭주)**:
   * SINGLE 카운터는 2명(유저 0, 1)만 통과하고 나머지 4명은 전부 락 타임아웃으로 실패합니다.
   * SHARDED 카운터는 4개 슬롯으로 분산되어 유저 0, 1, 2, 3, 4까지 5명이 정상 성공하고, Slot 0에 3번째로 겹친 유저 8만 실패합니다.
2. **$t=210$ (윈도우 리셋)**:
   * $t=210$은 윈도우 2($210 // 100 = 2$)이므로 용량이 다시 초기화되어 유저 0의 요청이 정상 처리됩니다.
3. **최종 처리량**:
   * SINGLE은 3개 성공에 그쳤지만 SHARDED는 6개 성공으로 **처리량이 정확히 100.0% 증가**했습니다!
