# 092. 보안 좋다고 UUID v4를 PK로 썼더니 왜 INSERT 속도가 100배 느려지고 DB 용량이 2배로 폭발해요?!: B+Tree 리프 페이지 분할(Page Split)과 무작위 단편화(Internal Fragmentation)

---

## 1. 비극의 시작 (Real-World Disaster)

스타트업 백엔드 개발자 준호는 사내 코드 리뷰에서 시니어 개발자에게 이런 피드백을 받았습니다:
> **"게시글 번호나 주문 ID를 1, 2, 3... 처럼 `BIGINT AUTO_INCREMENT`로 두면, 해커가 숫자를 1씩 올리며 남의 주문서나 개인정보를 다 긁어가는 IDOR(Insecure Direct Object Reference) 취약점이 생깁니다. Primary Key를 무조건 `UUID.randomUUID()` (UUID v4)로 바꾸세요!"**

보안 권고를 충실히 따른 준호는 모든 테이블의 기본키(PK)를 128비트 랜덤 문자열인 **UUID v4**(`e3b0c442-98fc-4c14...`)로 변경하고 배포했습니다.

출시 첫 달, 데이터가 1만 건일 때는 아무 문제 없이 완벽해 보였습니다.  
하지만 서비스가 흥행하여 주문 건수가 **100만 건, 500만 건**을 넘어서자 기괴한 대재앙이 터졌습니다:

1. **INSERT 지연시간 100배 폭증**: 초당 수천 건씩 척척 들어가던 주문 INSERT 쿼리가 건당 100ms~500ms씩 지연되며 백엔드 스레드 풀이 전멸했습니다.
2. **디스크 용량 2배 폭발**: 동일한 주문 내역을 순차 ID로 넣었을 때는 10GB였던 테이블이, UUID v4를 썼더니 **22GB**로 부풀어 올랐습니다.
3. **DB 서버 메모리(RAM) 캐시 사망**: DB 서버의 버퍼 풀(Buffer Pool) 캐시 히트율이 99%에서 30%로 곤두박질치며 디스크 I/O 사용률이 100%를 찍고 서버가 멈췄습니다.

분명 쿼리는 단순한 `INSERT INTO orders VALUES (...)` 1건인데, 도대체 디스크 내부에서 무슨 일이 벌어진 걸까요?

---

## 2. 도서관 서가의 비유: 왜 UUID v4는 B+Tree를 파괴하는가?

MySQL InnoDB, Oracle, SQL Server 등 대부분의 RDBMS는 **클러스터드 인덱스(Clustered Index)**를 사용합니다. 즉, **테이블의 실제 행 데이터 전체가 Primary Key 순서대로 정렬된 B+Tree 잎(Leaf) 페이지에 저장**됩니다.

도서관의 서가 한 칸(페이지)에 **책이 딱 4권**만 들어갈 수 있다고 가정해 봅시다:

### 1) 순차 키 (Auto-Increment, UUID v7) 인입 시:
새 책이 `1번, 2번, 3번, 4번...` 순서대로 들어옵니다.
- 서가가 꽉 차면, 사서는 기존 서가를 건드리지 않고 옆에 **새 서가를 하나 놓고 맨 오른쪽에 새 책을 꽂습니다** (**Right-Append Split**).
- **결과**: 모든 서가가 빈틈없이 100% 꽉 채워집니다 (**Fill Factor ~ 100%**). 사서는 항상 맨 마지막 서가만 만지므로 발걸음(디스크 I/O)이 극소화됩니다.

### 2) 무작위 키 (UUID v4) 인입 시:
책 번호가 `50번, 10번, 90번, 30번, 20번...` 무작위로 도착합니다.
- 이미 `[ 10번 | 30번 | 50번 | 90번 ]`으로 꽉 차 있는 서가 한가운데에 `25번 책`이 도착했습니다.
- 청구기호 순서(정렬)를 유지하려면 **10번과 30번 사이에 25번 책을 강제로 쑤셔 넣어야** 합니다!
- 빈틈이 없으므로 사서는 기존 서가의 책 절반을 빼내어 새 서가로 옮기는 **50/50 페이지 분할(Page Split)**을 감행합니다.
- 그 결과, 서가 두 개 모두 2~3권만 꽂힌 채 절반이 빈 공간으로 낭비됩니다 (**내부 단편화, Internal Fragmentation**).
- 데이터가 늘어날수록 모든 페이지가 반쯤 빈 채로 디스크 용량이 2배로 폭증하고, 사서는 이 서가 저 서가를 미친 듯이 오가며 책을 찾느라 탈진합니다 (**버퍼 풀 캐시 미스 & 디스크 I/O 병목**)!

---

## 3. 핵심 아키텍처 및 요구사항

당신은 B+Tree 리프 레벨 및 버퍼 풀(Buffer Pool)의 물리적 동작을 시뮬레이션하는 엔진을 구현해야 합니다.

### 1) 페이지(LeafPage)와 B+Tree 구조
- 각 페이지는 최대 `page_capacity` ($C$)개의 정렬된 `(key, value)` 레코드를 저장합니다.
- 페이지들은 정렬된 연결 리스트(`page_order`)로 이어져 있으며, 각 페이지는 다음 페이지와의 경계키(`high_key`, 미만 범위)를 가집니다 (마지막 페이지의 `high_key`는 `None`).
- 초기화 시 ID가 0인 빈 페이지 1개가 생성되며 메모리에 로드됩니다.

### 2) 키 정렬 및 중복 방지 규칙
- 키는 정수 문자열(예: `"10"`, `"2"`)인 경우 숫자 크기 순(`2 < 10`), 그 외 문자열(예: UUID)인 경우 사전식 순서로 정렬됩니다.
- 이미 동일한 키가 B+Tree에 존재하면 삽입을 거부하고 `PAGE:<page_id> ERROR:DUPLICATE_KEY CACHE:<HIT|MISS>`를 출력합니다.

### 3) 버퍼 풀(Buffer Pool) 캐시 (LRU 정책)
- 버퍼 풀은 최대 `buffer_pool_capacity` ($B$)개의 페이지만 RAM에 유지할 수 있습니다.
- 페이지 접근 시:
  - 이미 버퍼 풀에 있으면: `HIT`, 해당 페이지를 LRU 최신으로 갱신.
  - 버퍼 풀에 없으면: `MISS`, `disk_read_count += 1`.
    - 버퍼 풀이 꽉 찼다면 가장 오래 사용되지 않은(LRU) 페이지를 방출(Evict).
    - 만약 방출되는 페이지가 수정(Dirty)된 상태였다면 디스크에 영구 기록하므로 `disk_write_count += 1`.
    - 대상 페이지를 버퍼 풀에 적재.

### 4) 삽입(INSERT) 및 페이지 분할(Page Split)
레코드가 들어갈 리프 페이지를 탐색한 후 버퍼 풀에 접근합니다 (`access_page`):
- 페이지의 레코드 수 $< C$이면:
  - 정렬 순서에 맞게 삽입, `is_dirty = True`.
  - 출력: `PAGE:<page_id> STATUS:INSERTED CACHE:<HIT|MISS>`
- 페이지의 레코드 수 $== C$ (가득 참)이면 **페이지 분할** 발생 (`page_splits += 1`):
  - 기존 레코드들과 새 레코드를 합친 $C+1$개의 정렬 목록 생성.
  - **Right-Append 최적화 (`SPLIT_RIGHT`)**:
    - 해당 페이지가 B+Tree의 맨 마지막(우측 끝) 페이지이고, 새로 삽입되는 키가 기존 페이지의 최대 키보다 엄격히 크다면:
    - 기존 페이지에는 원래 $C$개를 그대로 100% 채운 채 유지하고, 새 페이지(`new_page_id`)에 새 레코드 1개만 할당.
  - **50/50 균등 분할 (`SPLIT_BALANCED`)**:
    - 그 외의 모든 경우:
    - $C+1$개 레코드 중 앞쪽 $\lceil (C+1)/2 \rceil$ 개는 기존 페이지에 남기고, 나머지 $\lfloor (C+1)/2 \rfloor$ 개는 새 페이지로 이동.
  - 새 페이지를 할당하고 B+Tree 체인에 연결한 뒤 버퍼 풀에 적재 (필요 시 LRU 방출 및 더티 플러시).
  - 출력: `PAGE:<target_page_id> STATUS:<SPLIT_RIGHT|SPLIT_BALANCED> CACHE:<HIT|MISS>`

### 5) 범위 쿼리 (`RANGE <start_key> <end_key>`)
- `start_key`가 속한 리프 페이지부터 체인을 따라 순회하며 `start_key <= k <= end_key` 조건의 레코드 개수를 셉니다.
- 각 페이지를 거칠 때마다 버퍼 풀 접근(`access_page`)을 수행합니다.
- 다음 페이지들이 모두 `end_key`를 초과함이 확실하면(`page.high_key is not None and key_less(end_key, page.high_key)`) 순회를 즉시 조기 종료(Break)합니다.
- 출력: `RANGE count=<count> pages_visited=<pages_visited>`

### 6) 테이블 최적화 (`OPTIMIZE`)
- `OPTIMIZE TABLE` / `VACUUM FULL` 시뮬레이션:
- 모든 레코드를 수집하여 여백 없이 $C$개씩 가득 찬 연속 새 페이지들로 재패킹합니다.
- 새 페이지들을 디스크에 기록하므로 `disk_write_count += new_pages_count`.
- 버퍼 풀을 초기화하고 재구축된 첫 `min(new_pages, B)`개 페이지를 로드합니다.
- 출력: `OPTIMIZE_OK old_pages=<old> new_pages=<new> saved_pages=<saved> new_fill=<new_fill:.1f>%`

### 7) 인덱스 통계 및 건전성 진단 (`STATS`)
- `TOTAL_PAGES`: 리프 페이지 총 개수
- `TOTAL_RECORDS`: 총 레코드 수
- `PAGE_SPLITS`: 누적 분할 횟수
- `FILL_FACTOR`: 전체 용량 대비 실제 저장 비율 ($\frac{\text{TOTAL\_RECORDS}}{\text{TOTAL\_PAGES} \times C} \times 100$)
- `FRAGMENTATION`: 내부 단편화율 ($100.0\% - \text{FILL\_FACTOR}$)
- `CACHE_HIT_RATE`: 버퍼 풀 적중률 ($\frac{\text{hits}}{\text{hits} + \text{misses}} \times 100$, 총 접근 0회 시 `0.0%`)
- `DISK_IO`: `disk_read_count + disk_write_count`
- `HEALTH` 판정 기준:
  - `total_pages <= 1`: **`OPTIMAL`** (단일 페이지는 단편화 없음)
  - `fill_factor >= 80.0%` 이고 (`total_accesses == 0` 또는 `hit_rate >= 70.0%`): **`OPTIMAL`**
  - `fill_factor < 70.0%` 또는 `fragmentation > 30.0%`: **`FRAGMENTED`**
  - 그 외: **`NORMAL`**
- 출력 형식:
  `STATS pages=<pages> records=<records> splits=<splits> fill=<fill>% frag=<frag>% hit_rate=<hit_rate>% disk_io=<disk_io> health=<health>`

---

## 4. 입출력 형식

### 입력
표준 입력(stdin)으로 여러 줄의 명령어가 주어집니다. 빈 줄이나 `#`으로 시작하는 주석은 무시합니다.

- `INIT <page_capacity> <buffer_pool_capacity>`
- `INSERT <key> <value>`
- `RANGE <start_key> <end_key>`
- `OPTIMIZE`
- `STATS`

### 출력
각 명령어의 실행 결과를 표준 출력(stdout)으로 한 줄씩 출력합니다.

---

## 5. 입출력 예시

### 예시 1: 순차 인입 (Auto-Increment / UUID v7) vs 무작위 인입 (UUID v4)
**입력:**
```text
INIT 4 3
INSERT 1 user_a
INSERT 2 user_b
INSERT 3 user_c
INSERT 4 user_d
INSERT 5 user_e
INSERT 6 user_f
INSERT 7 user_g
INSERT 8 user_h
STATS
INIT 4 3
INSERT 50 user_50
INSERT 10 user_10
INSERT 90 user_90
INSERT 30 user_30
INSERT 20 user_20
INSERT 70 user_70
INSERT 40 user_40
INSERT 25 user_25
STATS
```

**출력:**
```text
INIT_OK page_cap=4 pool_cap=3
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:1 STATUS:SPLIT_RIGHT CACHE:HIT
PAGE:1 STATUS:INSERTED CACHE:HIT
PAGE:1 STATUS:INSERTED CACHE:HIT
PAGE:1 STATUS:INSERTED CACHE:HIT
STATS pages=2 records=8 splits=1 fill=100.0% frag=0.0% hit_rate=100.0% disk_io=0 health=OPTIMAL
INIT_OK page_cap=4 pool_cap=3
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:SPLIT_BALANCED CACHE:HIT
PAGE:1 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:INSERTED CACHE:HIT
PAGE:0 STATUS:SPLIT_BALANCED CACHE:HIT
STATS pages=3 records=8 splits=2 fill=66.7% frag=33.3% hit_rate=100.0% disk_io=0 health=FRAGMENTED
```

---

## 6. 실무 아키텍트 가이드: 어떻게 해결해야 하는가?

1. **보안과 분산 생성이 필요하다면 무조건 UUID v7 (RFC 9562) 또는 TSID를 사용하라**:
   - UUID v4의 무작위성은 B+Tree의 최대 적입니다.
   - 앞 48비트에 밀리초 타임스탬프가 들어가 시간순으로 단조 증가하는 **UUID v7**이나 **TSID (Time-Sorted Unique Identifier)**를 사용하면, Auto-Increment와 동일하게 오른쪽 끝에 착착 삽입되어 페이지 분할을 99% 방지할 수 있습니다.
2. **정기적인 OPTIMIZE TABLE 및 REINDEX 스케줄링**:
   - 이미 무작위 삽입이나 대량 UPDATE/DELETE로 인해 단편화가 심각해진 테이블은 트래픽이 적은 새벽 시간대에 `OPTIMIZE TABLE`을 수행하여 흩어진 페이지를 압축하고 디스크 여백을 회수해야 합니다.
