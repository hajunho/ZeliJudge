# Problem #037: 방금 글 썼는데 새로고침하니 사라졌어요?!: DB 복제 지연(Replication Lag)과 Read-Your-Own-Writes 정합성

## 📖 실무 스토리: DB 트래픽 분산하려다 유령 글과 404 참사가 터졌습니다!

스타트업 백엔드 개발자 나코딩은 서비스가 급성장하자 데이터베이스 부하를 줄이기 위해 AWS RDS에 **Read Replica(읽기 전용 복제본, Slave DB)**를 도입했습니다.

Spring Boot의 `ReplicationRoutingDataSource`를 설정하여:
* 쓰기 트랜잭션(`@Transactional(readOnly = false)`)은 **Master DB**로 보냅니다.
* 읽기 트랜잭션(`@Transactional(readOnly = true)`)은 **Slave DB**로 보냅니다.

> **나코딩**: "이제 읽기 트래픽이 Slave로 분산되니 DB가 터질 일은 절대 없겠지!"

하지만 배포 당일 오후, **고객센터에 항의 전화가 빗발쳤습니다!**

1. **"글을 썼는데 404 에러가 뜨고 글이 날아갔어요!"**
   * 유저가 게시글을 작성(`POST /posts`, ID=101)하고 '성공' 응답을 받았습니다.
   * 프론트엔드는 작성 완료 즉시 상세 페이지(`GET /posts/101`)로 리다이렉트했습니다.
   * 하지만 상세 페이지 조회 요청은 **Slave DB**로 라우팅되었습니다!
   * Master에서 Slave로 변경 사항이 비동기로 전송되는 데 **100ms의 복제 지연(Replication Lag)**이 걸리는데, 리다이렉트는 10ms 만에 도착했습니다.
   * Slave DB에는 아직 ID=101 글이 없었기 때문에 **`404 Not Found`**를 반환했습니다!
   * 유저는 글이 안 써진 줄 알고 **작성 버튼을 5번 연타하여 중복 게시글 5개**가 올라갔습니다.
2. **"프로필 사진을 바꿨는데 옛날 사진으로 돌아가요!"**
   * 유저가 프로필을 변경(`WRITE`)하고 새로고침을 눌렀더니 옛날 정보(`STALE`)가 뜨고, 3초 뒤에 다시 새로고침을 누르니 그제서야 새 정보로 바뀌는 유령 현상이 발생했습니다.

> **"다른 사람이 쓴 글은 1초 늦게 보여도 되지만, 내가 방금 쓴 글이나 내 결제 내역은 내가 볼 때 무조건 100% 최신이어야 하잖아요?!"**

이것이 분산 데이터베이스 환경에서 가장 중요한 일관성 모델 중 하나인 **Read-Your-Own-Writes (자신이 쓴 데이터 읽기 정합성)** 문제입니다.

여러분의 임무는 복제 지연이 존재하는 분산 환경에서 **3가지 읽기 라우팅 전략(NAIVE, TIME_WINDOW, LSN_AWARE)**을 시뮬레이션하고, 사용자 경험 보장과 Master DB 부하 절감 효과를 정밀하게 계측하는 라우터 엔진을 구현하는 것입니다!

---

## 🎯 문제 요구사항

시스템에는 1대의 **Master DB**와 1대 이상의 **Slave DB (Replica)**가 존재합니다.
시간 순서대로 발생하는 이벤트(`WRITE`, `SYNC`, `READ`)를 처리하며 각 읽기 요청에 대해 3가지 라우팅 전략의 동작을 평가하십시오:

### 1. 이벤트 처리 규칙
* `WRITE <timestamp> <user_id> <doc_id> <value>`:
  * Master에 즉시 반영되며, Master의 LSN(Log Sequence Number)이 1 증가합니다 ($LSN_{master} \leftarrow LSN_{master} + 1$).
  * 해당 `doc_id`의 새로운 버전 `(value, LSN)`이 Master에 기록됩니다.
  * 해당 `user_id`의 마지막 쓰기 정보가 갱신됩니다: `(last_write_time, last_write_lsn)`.
* `SYNC <timestamp> <replica_id> <applied_lsn>`:
  * 특정 Replica가 Master의 로그를 복제하여 `applied_lsn`까지 상태 동기화를 완료합니다.
  * 해당 Replica는 이제 `applied_lsn` 이하의 LSN을 가진 문서 버전들을 읽을 수 있습니다.
* `READ <timestamp> <user_id> <doc_id> <target_replica>`:
  * `user_id`가 `target_replica`로 `doc_id` 읽기를 요청합니다.
  * 아래 3가지 라우팅 전략에 따라 대상 DB와 상태(`OK`, `STALE`, `NOT_FOUND`)를 판정합니다.

### 2. 3대 라우팅 전략 및 상태 판정 규칙

문서의 상태 정의:
* 대상 DB에 해당 문서가 아예 존재하지 않는 경우: `NOT_FOUND`
* 대상 DB에 문서가 존재하지만, Master의 최신 LSN보다 낮은 과거 버전인 경우: `STALE`
* 대상 DB의 문서 버전이 Master의 최신 버전과 일치하는 경우: `OK`
*(참고: Master는 항상 모든 문서의 최신 상태를 보유하므로 Master에서 읽을 때 문서가 존재한다면 항상 `OK`입니다.)*

1. **전략 1: NAIVE (단순 복제본 라우팅)**
   * 복제 지연 여부와 상관없이 무조건 `target_replica`로 라우팅합니다.
   * `ROUTED_TO`: `<target_replica>`
   * `STATUS`: `target_replica`의 문서 상태 (`OK`, `STALE`, `NOT_FOUND`)

2. **전략 2: TIME_WINDOW (쓰기 후 시간 기반 Master 라우팅)**
   * 해당 유저가 마지막으로 쓰기를 수행한 시각 $t_{write}$로부터 현재 시각 $t$까지의 경과 시간 $\Delta t = t - t_{write}$를 확인합니다.
   * $\Delta t < SAFE\_WINDOW$인 경우:
     * 유저가 방금 쓰기를 했으므로 **`MASTER`**로 라우팅합니다.
     * `ROUTED_TO`: `MASTER`, `STATUS`: Master의 문서 상태 (`OK`)
   * $\Delta t \ge SAFE\_WINDOW$이거나 유저의 쓰기 이력이 없는 경우:
     * 복제가 끝났다고 가정하고 **`target_replica`**로 라우팅합니다.
     * `ROUTED_TO`: `<target_replica>`, `STATUS`: `target_replica`의 문서 상태

3. **전략 3: LSN_AWARE (사용자 LSN 추적 정밀 라우팅 - Golden Standard)**
   * 유저의 `last_write_lsn`을 확인합니다 (쓰기 이력이 없으면 0).
   * `target_replica`의 현재 `applied_lsn >= last_write_lsn`인 경우:
     * 해당 복제본은 이미 이 유저가 쓴 내용을 모두 동기화 완료했으므로 안심하고 **`target_replica`**로 라우팅합니다!
     * `ROUTED_TO`: `<target_replica>`, `STATUS`: `target_replica`의 문서 상태
   * `target_replica`의 현재 `applied_lsn < last_write_lsn`인 경우:
     * 아직 이 유저의 쓰기 내용이 복제되지 않았으므로 **`MASTER`**로 우회(Fallback)합니다!
     * `ROUTED_TO`: `MASTER`, `STATUS`: Master의 문서 상태 (`OK`)

---

## 📥 입력 형식 (Input Format)

```text
SAFE_WINDOW <W>
EVENTS <E>
<event_type_1> <args...>
<event_type_2> <args...>
...
```

* 첫 번째 줄: `SAFE_WINDOW` 키워드 뒤에 시간 윈도우 $W$ (정수, ms 단위, $1 \le W \le 10,000$)가 주어집니다.
* 두 번째 줄: `EVENTS` 키워드 뒤에 총 이벤트 개수 $E$ ($1 \le E \le 30,000$)가 주어집니다.
* 세 번째 줄부터 각 이벤트가 주어집니다:
  * `WRITE <timestamp> <user_id> <doc_id> <value>`
  * `SYNC <timestamp> <replica_id> <applied_lsn>`
  * `READ <timestamp> <user_id> <doc_id> <target_replica>`
* 모든 이벤트의 `timestamp`는 비내림차순(오름차순)으로 정렬되어 주어집니다.

---

## 📤 출력 형식 (Output Format)

각 `READ` 이벤트마다 다음 형식으로 1줄씩 출력합니다:
```text
READ <timestamp> USER:<user_id> DOC:<doc_id> NAIVE:<route>:<status> TIME_WINDOW:<route>:<status> LSN_AWARE:<route>:<status>
```

모든 이벤트 처리 후 마지막 줄에 종합 통계(Summary)를 출력합니다:
```text
SUMMARY TOTAL_READS:<total_reads> NAIVE_FAILURES:<naive_failures> TIME_WINDOW_FAILURES:<tw_failures> TIME_WINDOW_MASTER_READS:<tw_master_reads> LSN_AWARE_MASTER_READS:<lsn_master_reads> MASTER_LOAD_SAVED:<saved_master>
```
* `NAIVE_FAILURES`: NAIVE 전략에서 상태가 `OK`가 아닌(`STALE` 또는 `NOT_FOUND`) 읽기 요청 수
* `TIME_WINDOW_FAILURES`: TIME_WINDOW 전략에서 상태가 `OK`가 아닌 읽기 요청 수 (복제 지연 스파이크 발생 시)
* `TIME_WINDOW_MASTER_READS`: TIME_WINDOW 전략에서 Master로 전송된 읽기 요청 수
* `LSN_AWARE_MASTER_READS`: LSN_AWARE 전략에서 Master로 전송된 읽기 요청 수
* `MASTER_LOAD_SAVED`: `TIME_WINDOW_MASTER_READS - LSN_AWARE_MASTER_READS` (LSN 기반 정밀 라우팅을 통해 불필요하게 Master로 가던 트래픽을 Slave로 분산하여 절감한 쿼리 수)

---

## 💡 입출력 예제 (Sample I/O)

### 예제 입력
```text
SAFE_WINDOW 500
EVENTS 9
WRITE 100 user1 post_1 Hello
READ 110 user1 post_1 slave1
SYNC 150 slave1 1
READ 200 user1 post_1 slave1
READ 700 user1 post_1 slave1
WRITE 1000 user2 profile_2 Avatar2
READ 1600 user2 profile_2 slave2
SYNC 2000 slave2 2
READ 2100 user2 profile_2 slave2
```

### 예제 출력
```text
READ 110 USER:user1 DOC:post_1 NAIVE:slave1:NOT_FOUND TIME_WINDOW:MASTER:OK LSN_AWARE:MASTER:OK
READ 200 USER:user1 DOC:post_1 NAIVE:slave1:OK TIME_WINDOW:MASTER:OK LSN_AWARE:slave1:OK
READ 700 USER:user1 DOC:post_1 NAIVE:slave1:OK TIME_WINDOW:slave1:OK LSN_AWARE:slave1:OK
READ 1600 USER:user2 DOC:profile_2 NAIVE:slave2:NOT_FOUND TIME_WINDOW:slave2:NOT_FOUND LSN_AWARE:MASTER:OK
READ 2100 USER:user2 DOC:profile_2 NAIVE:slave2:OK TIME_WINDOW:slave2:OK LSN_AWARE:slave2:OK
SUMMARY TOTAL_READS:5 NAIVE_FAILURES:2 TIME_WINDOW_FAILURES:1 TIME_WINDOW_MASTER_READS:2 LSN_AWARE_MASTER_READS:2 MASTER_LOAD_SAVED:0
```

---

## 힌트 & 핵심 점검 사항
1. **$t=110$**: `slave1`에 아직 복제되지 않았으므로 NAIVE는 `NOT_FOUND` 실패를 겪습니다. TIME_WINDOW와 LSN_AWARE는 Master로 라우팅하여 정합성을 보장합니다.
2. **$t=200$**: `slave1`이 이미 LSN 1 동기화를 마쳤습니다! LSN_AWARE는 이를 즉시 감지하고 `slave1`으로 트래픽을 분산하지만, TIME_WINDOW는 500ms가 지나지 않았다는 이유로 여전히 Master로 트래픽을 쏟아붓습니다.
3. **$t=1600$ (지연 스파이크)**: `slave2`의 복제가 2000ms까지 지연되었습니다. TIME_WINDOW는 500ms가 지났다고 순진하게 믿고 `slave2`로 요청을 보냈다가 `NOT_FOUND` 참사를 겪습니다! 반면 LSN_AWARE는 Replica가 아직 LSN 2에 도달하지 못했음을 정밀하게 파악하여 Master로 우회함으로써 완벽한 무결성을 지켜냅니다.
