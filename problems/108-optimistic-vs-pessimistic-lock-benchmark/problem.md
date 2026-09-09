# [CS-108] 경합이 심할 때 낙관적 락(OCC)을 썼더니 CPU 100% 찍고 TPS가 0으로 곤두박질쳤어요?!: 동시성 제어 3대장의 경합도별 성능 임계점 (Concurrency Control Trade-offs)

> **"선생님! '낙관적 락은 DB 락을 안 잡아서 성능이 제일 좋다'고 해서 선착순 100장 티켓팅에 `@Version` 낙관적 락을 걸었거든요? 그런데 1만 명이 동시 접속하자마자 DB CPU가 100% 찍고 성공한 티켓은 초당 1장도 안 나와요! 락도 안 잡았는데 왜 서버가 터지죠?!"**
> 
> 이커머스 백엔드를 담당하는 주니어 개발자 선우는 대형 콘서트 티켓팅 시스템을 오픈했습니다.
> 블로그에서 "비관적 락(`SELECT FOR UPDATE`)은 DB 락을 잡아서 병목이 생기니, 락 없는 낙관적 락(`@Version` + 재시도 루프)이 훨씬 우아하고 빠르다"는 글을 보고 전면 도입했습니다.
> 
> 하지만 티켓팅 오픈 카운트다운이 0이 되는 순간, 서버는 지옥으로 변했습니다.
> 1만 개의 트랜잭션 중 단 1개만 버전을 올리고, 나머지 9,999개는 일제히 `OptimisticLockException`을 뿜으며 무한 재시도(Retry Loop)를 감행했습니다.
> 1만 개의 스레드가 0.01초 간격으로 `SELECT`와 `UPDATE` 쿼리를 폭격하듯 날리면서 DB 쿼리 수는 초당 수십만 건으로 폭발했고, DB 커넥션 풀은 전멸했습니다!
> 
> "락을 안 잡았는데 왜 락 잡았을 때보다 100배 느릴까요?!"  
> 시니어 아키텍트는 화이트보드에 그래프를 그리며 말했습니다.
> "선우 씨, 100명이 좁은 문 하나를 통과해야 하는데, '싸우지 말고 자유롭게 지나가세요(낙관적 락)'라고 하면 문 앞에서 서로 어깨빵 치고 튕겨 나가서 다시 시도하느라 단 한 명도 못 지나갑니다. 이럴 땐 차라리 회전문과 경호원을 둬서 한 명씩 줄을 세우는 것(비관적 락)이 100배 빠르고 질서정연합니다."

---

## 1. 문제 배경과 현실 비유: 자유 출입문(낙관적 락) vs 회전문 줄서기(비관적 락)

### 1) 낙관적 락 (Optimistic Concurrency Control, OCC)
- **철학**: "충돌이 거의 없을 것이다."
- **메커니즘**: 락 없이 읽고, 쓰기 직전 버전 번호(`WHERE version = old_ver`)를 확인하여 일치할 때만 갱신합니다. 충돌 시 롤백 후 재시도(Retry)합니다.
- **성능 임계점**: 충돌률이 낮은 일반 비즈니스에서는 락 오버헤드가 없어 최고 성능을 냅니다. 하지만 1개 자원에 수많은 스레드가 동시 집중(High Contention)되면, 매 라운드마다 1명만 성공하고 수천 명이 재시도하며 DB 쿼리 수가 $O(N^2)$로 폭발하여 시스템이 마비됩니다.

### 2) 비관적 락 (Pessimistic Concurrency Control, PCC)
- **철학**: "충돌이 무조건 발생할 것이다."
- **메커니즘**: 조회 시점부터 `SELECT ... FOR UPDATE`로 행(Row) 락을 획득하여 다른 스레드를 줄 세웁니다.
- **성능 임계점**: 스레드들이 차례로 1명씩 처리되므로 충돌 0회, 재시도 0회, 총 쿼리 수는 정확히 $O(N)$으로 일정하게 유지됩니다. 고경합 환경에서 낙관적 락보다 압도적으로 빠르고 안정적입니다.

### 3) 분산 락 (Redis Distributed Lock)
- **철학**: "DB에 가기 전에 문지기(Redis)가 먼저 걸러낸다."
- **Fast-Fail 모드**: 1등만 락을 획득하고 나머지는 DB를 건드리지도 않고 즉시 탈락(Fast-Fail)시켜 DB를 100% 보호합니다.

---

## 2. 요구사항 및 명령어 사양

당신은 동시성 제어 3대장(OCC vs PCC vs Distributed Lock)의 동작과 DB 쿼리 부하를 시뮬레이션하는 `LockBenchmarkSimulator` 엔진을 구현해야 합니다.
표준 입력(`stdin`)으로 들어오는 명령어들을 한 줄씩 파싱하여 정확한 형식으로 표준 출력(`stdout`)에 출력하십시오.

### 지원 명령어 목록

1. `INIT_STOCK <item_id> <initial_stock>`
   - 상품을 생성하고 초기 재고를 설정합니다 (초기 버전 1).
   - 출력: `INIT_STOCK item=<item_id> stock=<initial_stock> version=1`

2. `BENCHMARK_OCC <item_id> <threads> <retry_limit>`
   - 낙관적 락 시뮬레이션:
   - 각 라운드마다 대기 중인 모든 스레드가 SELECT (스레드 수만큼 쿼리 증가).
   - 재고가 1 이상이면 모든 스레드가 UPDATE 시도 (스레드 수만큼 쿼리 증가).
   - 이 중 단 1개 스레드만 성공(재고 -1, 버전 +1). 나머지 스레드는 충돌(conflicts +1, retries +1).
   - 재시도 횟수가 `retry_limit`을 초과하거나 재고가 0이 되면 포기(aborts +1).
   - 출력: `RESULT_OCC item=<item_id> initial_threads=<threads> successes=<successes> conflicts=<conflicts> total_retries=<total_retries> aborts=<aborts> db_queries=<db_queries> final_stock=<stock> final_version=<version>`

3. `BENCHMARK_PCC <item_id> <threads>`
   - 비관적 락 시뮬레이션:
   - 스레드들이 1명씩 순차적으로 `SELECT FOR UPDATE`(1쿼리) 실행 후, 재고가 있으면 `UPDATE`(1쿼리) 실행. 재고가 없으면 추가 쿼리 없이 종료.
   - 충돌 0회, 재시도 0회, 락 대기 횟수 = `max(0, threads - 1)`.
   - 출력: `RESULT_PCC item=<item_id> initial_threads=<threads> successes=<successes> lock_waits=<lock_waits> conflicts=0 retries=0 db_queries=<db_queries> final_stock=<stock>`

4. `BENCHMARK_DIST_LOCK <item_id> <threads> <mode: FAST_FAIL|WAIT_QUEUE>`
   - 분산 락 시뮬레이션:
   - `FAST_FAIL` 모드: 첫 1개 스레드만 락을 얻어 DB 2쿼리(SELECT+UPDATE) 실행, 나머지 $threads - 1$개는 DB 접근 없이 즉시 거절(`fast_fail_rejected`).
     - 출력: `RESULT_DIST_LOCK item=<item_id> mode=FAST_FAIL successes=<succ> fast_fail_rejected=<rejected> db_queries=<queries> final_stock=<stock>`
   - `WAIT_QUEUE` 모드: Redis 대기열을 통해 1명씩 DB로 진입 (PCC와 동일한 쿼리 수).
     - 출력: `RESULT_DIST_LOCK item=<item_id> mode=WAIT_QUEUE successes=<succ> redis_waits=<waits> db_queries=<queries> final_stock=<stock>`

5. `STATS <item_id>`
   - 현재 상품의 재고와 버전을 출력합니다.
   - 출력: `STATS item=<item_id> stock=<stock> version=<version>`

---

## 3. 입출력 예시

### 예시 입력 1
```text
INIT_STOCK item_occ 100
BENCHMARK_OCC item_occ 10 10
STATS item_occ
INIT_STOCK item_pcc 100
BENCHMARK_PCC item_pcc 10
STATS item_pcc
INIT_STOCK item_fast 100
BENCHMARK_DIST_LOCK item_fast 10 FAST_FAIL
STATS item_fast
```

### 예시 출력 1
```text
INIT_STOCK item=item_occ stock=100 version=1
RESULT_OCC item=item_occ initial_threads=10 successes=10 conflicts=45 total_retries=45 aborts=0 db_queries=110 final_stock=90 final_version=11
STATS item=item_occ stock=90 version=11
INIT_STOCK item=item_pcc stock=100 version=1
RESULT_PCC item=item_pcc initial_threads=10 successes=10 lock_waits=9 conflicts=0 retries=0 db_queries=20 final_stock=90
STATS item=item_pcc stock=90
INIT_STOCK item=item_fast stock=100 version=1
RESULT_DIST_LOCK item=item_fast mode=FAST_FAIL successes=1 fast_fail_rejected=9 db_queries=2 final_stock=99
STATS item=item_fast stock=99
```

---

## 4. 실무 핵심 요약 (Architecture Takeaway)

1. **경합도에 따른 락 선택 공식**:
   - 저경합(충돌 빈도 낮음): 락 오버헤드가 없는 **낙관적 락(OCC)**이 압도적으로 유리.
   - 고경합(동일 자원에 수백~수천 요청 집중): **비관적 락(PCC)** 또는 **분산 락(Fast-Fail)**을 써서 쿼리 폭증($O(N^2)$)과 재시도 폭풍(Retry Storm)을 차단해야 함.
