# 120. 새벽에 통계 쿼리 한 번 돌렸더니 왜 전사 결제 쿼리가 디스크로 떨어져 DB가 뻗어요?!: MySQL InnoDB 버퍼 풀 오염(Buffer Pool Pollution)과 Midpoint LRU 2계층 캐시 알고리즘

## 문제 설명

온라인 서비스의 데이터베이스(MySQL)는 디스크 I/O 병목을 줄이기 위해 테이블과 인덱스 데이터 페이지를 메모리에 캐싱하는 **버퍼 풀(Buffer Pool)**을 운영합니다.  
초당 수만 건의 결제 및 주문 쿼리가 평소에는 99.9% 버퍼 풀 캐시 적중률(Hit Ratio)을 기록하며 1ms 미만의 빠른 응답 속도를 자랑했습니다.

그러나 새벽 3시, 마케팅 부서에서 전체 사용자 통계를 산출하기 위해 **대규모 풀 테이블 스캔 쿼리(`SELECT * FROM users`)**를 실행한 직후 **대재앙**이 발생했습니다! 💥  
수천만 건의 데이터를 순차적으로 읽는 동안, 매일 활발하게 쓰이던 소중한 결제/주문용 핫(Hot) 페이지들이 캐시에서 **몽땅 디스크로 쫓겨나고(Eviction)**, 방금 딱 한 번 읽고 다시는 안 볼 일회성 통계 데이터가 버퍼 풀을 100% 장악해 버린 것입니다.

이 현상을 **버퍼 풀 오염 (Buffer Pool Pollution / Cache Pollution)**이라고 부릅니다.  
전통적인 단순 LRU(Least Recently Used) 캐시는 새로운 데이터를 읽을 때마다 무조건 리스트의 맨 앞(Head, MRU)에 넣기 때문에, 대용량 스캔 작업 한 번에 캐시 전체가 순식간에 초토화되는 치명적인 결함을 가지고 있습니다.

---

### MySQL InnoDB의 구원: Midpoint Insertion LRU (2계층 LRU)

MySQL InnoDB 스토리지 엔진은 이 문제를 완벽하게 해결하기 위해 LRU 리스트를 2개의 구역으로 나눈 **Midpoint LRU 알고리즘**을 도입했습니다:

1. **Young Sublist (상위 5/8, 약 63%)**:  
   실제 빈번하게 재참조되는 진짜 핫(Hot) 페이지만 머무르는 보호 구역입니다.
2. **Old Sublist (하위 3/8, 약 37%)**:  
   새로 디스크에서 읽어 들인 페이지들이 처음 격리되는 수용소입니다.

```
Head (MRU)                                         Tail (LRU)
 ┌─────────────────────────┬─────────────────────────┐
 │   Young Sublist (5/8)   │    Old Sublist (3/8)    │
 │ (진짜 Hot 페이지 보호 구역) │ (신규 페이지 격리 수용소)   │
 └─────────────────────────┴─────────────────────────┘
                           ▲
                  [Midpoint 삽입 지점]
```

### InnoDB의 2대 방어 원리

- **중간 삽입 (Midpoint Insertion)**:  
  새로 읽은 페이지는 리스트의 맨 앞이 아니라, Young과 Old의 경계인 **Midpoint(Old Sublist의 헤드)**에 삽입됩니다. 풀 스캔으로 수백만 건이 들어와도 하위 3/8(Old) 영역 내에서만 회전하며 꼬리(Tail)로 조용히 축출되므로, Young 영역의 핫 페이지는 털끝 하나 다치지 않고 100% 안전하게 보존됩니다!
- **시간 창 방어 (`innodb_old_blocks_time`)**:  
  풀 스캔 시 동일 페이지 내의 여러 행(Row)을 연속으로 읽기 때문에 수 밀리초 내에 재참조가 일어날 수 있습니다.  
  InnoDB는 Old 영역에 처음 들어온 시점으로부터 **최소 1000ms(1초) 이상 지난 뒤에 다시 참조된 경우에만** 진짜 핫 페이지로 인정하여 Young의 헤드로 승급(Promote)시키며, 1000ms 이내의 연속 재참조는 승급시키지 않고 무시합니다!

---

## 입력 형식

표준 입력(stdin)으로 한 줄에 하나씩 다음 명령어들이 주어집니다:

1. `CONFIG mode=<STANDARD_LRU|MIDPOINT_LRU> capacity=<int> old_pct=<int> old_blocks_time_ms=<int>`
   - 버퍼 풀 모드와 총 용량(capacity), Old 비율(old_pct, 기본 37%), 시간 창(기본 1000ms)을 설정합니다.
   - 출력: `OK mode=<mode> capacity=<capacity> old_pct=<old_pct> old_blocks_time_ms=<old_blocks_time_ms>`

2. `READ page=<id> now=<timestamp_ms>`
   - 시각 `now`에 특정 페이지를 읽습니다.
   - **`STANDARD_LRU` 모드**:  
     - 적중 시: `READ_RESULT page=<page> action=CACHE_HIT evicted=none`  
     - 미스 시: `READ_RESULT page=<page> action=CACHE_MISS evicted=<evicted_page|none>`
   - **`MIDPOINT_LRU` 모드**:  
     - 적중 시 (Young): `READ_RESULT page=<page> action=CACHE_HIT sublist=YOUNG promoted=false evicted=none`  
     - 적중 시 (Old, 승급 성공): `READ_RESULT page=<page> action=CACHE_HIT sublist=YOUNG promoted=true evicted=<evicted_page|none>`  
     - 적중 시 (Old, 시간 미달 승급 실패): `READ_RESULT page=<page> action=CACHE_HIT sublist=OLD promoted=false evicted=none`  
     - 미스 시: `READ_RESULT page=<page> action=CACHE_MISS sublist=OLD promoted=false evicted=<evicted_page|none>`

3. `DUMP`
   - 현재 버퍼 풀의 페이지 목록을 헤드부터 순서대로 출력합니다:  
     - `STANDARD_LRU`: `BUFFER_POOL pages=[p1,p2,...]`  
     - `MIDPOINT_LRU`: `BUFFER_POOL young=[y1,y2,...] old=[o1,o2,...]`

4. `STATS`
   - 통계 출력: `STATS hits=<H> misses=<M> evictions=<E> promotions=<P>`

5. `RESET`
   - 모든 상태를 초기화합니다: `OK mode=STANDARD_LRU capacity=10 old_pct=37 old_blocks_time_ms=1000`

---

## 예제 입력 1 (Standard LRU의 버퍼 풀 오염 참사)

```text
CONFIG mode=STANDARD_LRU capacity=4 old_pct=37 old_blocks_time_ms=1000
READ page=hot_1 now=0
READ page=hot_2 now=0
READ page=hot_3 now=0
READ page=hot_4 now=0
DUMP
READ page=scan_1 now=100
READ page=scan_2 now=100
DUMP
READ page=hot_1 now=200
STATS
```

## 예제 출력 1

```text
OK mode=STANDARD_LRU capacity=4 old_pct=37 old_blocks_time_ms=1000
READ_RESULT page=hot_1 action=CACHE_MISS evicted=none
READ_RESULT page=hot_2 action=CACHE_MISS evicted=none
READ_RESULT page=hot_3 action=CACHE_MISS evicted=none
READ_RESULT page=hot_4 action=CACHE_MISS evicted=none
BUFFER_POOL pages=[hot_4,hot_3,hot_2,hot_1]
READ_RESULT page=scan_1 action=CACHE_MISS evicted=hot_1
READ_RESULT page=scan_2 action=CACHE_MISS evicted=hot_2
BUFFER_POOL pages=[scan_2,scan_1,hot_4,hot_3]
READ_RESULT page=hot_1 action=CACHE_MISS evicted=hot_3
STATS hits=0 misses=7 evictions=3 promotions=0
```

---

## 예제 입력 2 (Midpoint LRU의 철통 스캔 방어)

```text
CONFIG mode=MIDPOINT_LRU capacity=5 old_pct=40 old_blocks_time_ms=1000
READ page=hot_1 now=1000
READ page=hot_1 now=2500
DUMP
READ page=scan_1 now=3000
READ page=scan_2 now=3010
READ page=scan_3 now=3020
DUMP
READ page=hot_1 now=4000
STATS
```

## 예제 출력 2

```text
OK mode=MIDPOINT_LRU capacity=5 old_pct=40 old_blocks_time_ms=1000
READ_RESULT page=hot_1 action=CACHE_MISS sublist=OLD promoted=false evicted=none
READ_RESULT page=hot_1 action=CACHE_HIT sublist=YOUNG promoted=true evicted=none
BUFFER_POOL young=[hot_1] old=[]
READ_RESULT page=scan_1 action=CACHE_MISS sublist=OLD promoted=false evicted=none
READ_RESULT page=scan_2 action=CACHE_MISS sublist=OLD promoted=false evicted=none
READ_RESULT page=scan_3 action=CACHE_MISS sublist=OLD promoted=false evicted=scan_1
BUFFER_POOL young=[hot_1] old=[scan_3,scan_2]
READ_RESULT page=hot_1 action=CACHE_HIT sublist=YOUNG promoted=false evicted=none
STATS hits=2 misses=4 evictions=1 promotions=1
```

> **설명**:  
> `hot_1`은 1000ms 이상 경과 후 재참조되어 `Young` 보호 영역에 안전하게 승급되었습니다.  
> 이후 `scan_1, scan_2, scan_3`이 쏟아져 들어왔지만, 이들은 오직 `old` 영역(크기 2) 내에서만 회전하며 가장 오래된 `scan_1`을 축출했습니다.  
> 결과적으로 `hot_1`은 털끝 하나 다치지 않고 `Young` 영역에 보존되어 후속 쿼리에서 0ms 캐시 적중(`CACHE_HIT`)을 달성했습니다!\n