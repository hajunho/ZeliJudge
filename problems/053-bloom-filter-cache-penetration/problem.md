# #053 DB에 없는 데이터만 골라서 공격당했어요?!: 캐시 관통(Cache Penetration)과 블룸 필터(Bloom Filter)

---

## 1. 현실 세계 비유: 클럽 입구의 VIP 명부와 1초 만에 튕겨내는 도어맨

강남의 초호화 프라이빗 클럽 입구를 상상해 보세요.

```text
❌ 무방비 캐시(Cache-Aside)의 최후 (도어맨의 탈진 사망):
   손님이 "제 이름 박철수인데요!"라고 말하면, 도어맨은 기억(Redis 메모리 캐시)을 떠올립니다.
   기억에 없으면 사무실 금고로 달려가 3,000페이지짜리 두꺼운 VIP 명부 원본(DB)을 한 장 한 장 뒤적입니다.
   하지만 박철수는 VIP 명단에 없는 사람입니다.
   도어맨은 "없는데요?" 하고 돌아서지만, 악의적인 스팸 조직 1,000명이 존재하지도 않는 가짜 이름
   ("김가짜", "이가짜", "박가짜"...)을 0.1초마다 대며 들어옵니다.
   도어맨은 하루 종일 금고로 뛰어가 3,000페이지 장부만 뒤적거리다 심장마비로 쓰러집니다(DB CPU 100% 폭사).

✅ 블룸 필터 (Bloom Filter - 스마트 안경을 쓴 도어맨):
   도어맨이 클럽 VIP 명부 전체를 손바닥만 한 압축 종이(블룸 필터 비트 배열)에 요약해 두었습니다.
   손님이 가짜 이름을 대면, 종이에 몇 개의 도장(해시 비트)을 대조해 봅니다.
   "어? 도장 3개 중에 2번 도장이 안 찍혀 있네? 당신은 우리 클럽 VIP에 100% 존재할 수 없습니다. 입구 컷(BLOOM_REJECT)!"
   도어맨은 금고(DB)에 발걸음조차 떼지 않고 0.001초 만에 가짜 손님을 문전박대합니다.
   수만 번의 악의적 요청 속에서도 금고(DB)는 단 1번도 열리지 않고 평화롭습니다!
```

대규모 웹 서비스를 운영할 때 가장 흔하게 겪는 보안/성능 공격 중 하나가 바로 **캐시 관통(Cache Penetration)**입니다.  
악의적인 공격자나 버그가 있는 웹 크롤러가 DB에 존재하지 않는 무작위 키(`userId = -9999`, `productId = "invalid_uuid"`)를  
초당 수만 건씩 요청하면, **캐시에는 당연히 없으니 매번 DB로 쿼리가 직행하여 DB를 마비**시킵니다.

컴퓨터 과학의 가장 위대한 확률적 자료구조 중 하나인 **블룸 필터(Bloom Filter)**를 통해,  
단 몇 킬로바이트의 메모리로 캐시 관통 공격을 99.9% 완벽 차단하는 원리를 시뮬레이션해 봅시다.

---

## 2. 문제 개요

당신은 대규모 이커머스 포털의 데이터베이스 보안 아키텍트입니다.  
해커의 무차별 무효 키 대량 조회 공격으로부터 DB를 보호하기 위해,  
기존의 **무방비 캐시 모델(NAIVE)**과 **블룸 필터 사전 차단 모델(BLOOM)**을 시뮬레이션하고,  
DB 쿼리 절감률(`DB_QUERY_SAVED`)과 위양성(False Positive) 발생 횟수를 정밀 계측하세요.

### 시뮬레이션 상세 규칙

#### 1. 인프라 및 블룸 필터 환경
- `BLOOM_FILTER_SIZE <M>`: 블룸 필터 비트 배열의 크기 ($10 \le M \le 100,000$).
- `BLOOM_HASH_COUNT <K>`: 독립 해시 함수 개수 ($1 \le K \le 10$).
- `INIT_KEYS <N>`: 실제 DB 테이블에 사전에 등록된 유효 키 개수 ($1 \le N \le 10,000$).
  - 이후 $N$개의 줄에 실제 DB에 존재하는 고유 키(`valid_key`)들이 주어집니다.
- 초기 블룸 필터 비트 배열: 크기 $M$의 비트 배열로, 모든 비트는 `0`으로 초기화됩니다.
  - $N$개의 유효 키를 순회하며 각각 $K$개의 비트 인덱스를 계산하여 해당 비트를 `1`로 설정합니다.

#### 2. 결정론적 해시 함수 (Kirsch-Mitzenmacher 이중 해싱)
각 키(`key`)에 대해 두 개의 기본 32비트 해시값을 계산합니다:
- $h_1(key)$:
  ```python
  h = 0
  for c in key:
    h = (h * 31 + ord(c)) & 0xFFFFFFFF
```
- $h_2(key)$:
  ```python
  h = 0
  for c in key:
    h = (h * 37 + ord(c)) & 0xFFFFFFFF
```
- $i$번째 해시 비트 인덱스 ($0 \le i < K$):
  $$bit\_index_i = (h_1(key) + i \times h_2(key)) \pmod M$$

#### 3. 모델 A: 무방비 Cache-Aside (NAIVE)
- 요청된 `key`가 캐시(`naive_cache`)에 있으면 $\to$ `CACHE_HIT` (DB 쿼리 0회).
- 캐시에 없으면 DB 조회를 수행합니다 (`naive_db_queries += 1`):
  - 실제 DB에 존재하는 키라면 $\to$ 캐시에 적재하고 `DB_FOUND`.
  - 실제 DB에 존재하지 않는 키라면 $\to$ 캐시에 적재하지 않고 `DB_NOT_FOUND`.

#### 4. 모델 B: 블룸 필터 사전 차단 (BLOOM)
- 요청된 `key`가 캐시(`bloom_cache`)에 있으면 $\to$ `CACHE_HIT` (DB 쿼리 0회).
- 캐시에 없으면 **블룸 필터 검사**를 먼저 수행합니다:
  - $K$개의 비트 인덱스 중 **단 하나라도 `0`인 비트가 있다면**:
    - "이 키는 100% DB에 존재하지 않음!" $\to$ DB 조회를 즉시 생략하고 `BLOOM_REJECT` (DB 쿼리 0회!).
  - $K$개의 비트가 **모두 `1`이라면**:
    - "이 키는 DB에 존재할 가능성이 있음!" $\to$ DB 조회를 수행합니다 (`bloom_db_queries += 1`):
      - 실제 DB에 존재하는 키라면 $\to$ 캐시에 적재하고 `DB_FOUND`.
      - 실제 DB에 존재하지 않는 키라면 $\to$ **위양성(False Positive)** 발생! `FALSE_POSITIVE_MISS`.

---

## 3. 입력 형식

```text
BLOOM_FILTER_SIZE <M>
BLOOM_HASH_COUNT <K>
INIT_KEYS <N>
<valid_key_1>
<valid_key_2>
... (총 N개의 실제 유효 키)
EVENTS <E>
REQ <client_id> <key>
... (총 E개의 조회 요청 줄)
```

- `M`, `K`, `N`, `E`: 양의 정수 ($1 \le E \le 30,000$)
- `key`: 공백 없는 문자열

---

## 4. 출력 형식

각 `REQ`마다 한 줄씩 두 모델의 처리 상태를 출력합니다:
```text
REQ <client_id> KEY:<key> NAIVE:<n_status> BLOOM:<b_status>
```

- 상태 종류:
  - NAIVE: `CACHE_HIT`, `DB_FOUND`, `DB_NOT_FOUND`
  - BLOOM: `CACHE_HIT`, `DB_FOUND`, `BLOOM_REJECT`, `FALSE_POSITIVE_MISS`

모든 요청 처리 후 최종 종합 성능 통계를 출력합니다:
```text
SUMMARY TOTAL_REQS:<total>
NAIVE DB_QUERIES:<n_db>
BLOOM DB_QUERIES:<b_db> BLOOM_REJECTS:<rejects> FALSE_POSITIVES:<fps>
SUMMARY DB_QUERY_SAVED:<saved_pct>%
```

- `DB_QUERY_SAVED`: `((n_db - b_db) / n_db) * 100.0` (소수점 둘째 자리까지 반올림, 예: `95.50%`, `n_db == 0`이면 `0.00%`)

---

## 5. 입출력 예시

### 입력
```text
BLOOM_FILTER_SIZE 100
BLOOM_HASH_COUNT 3
INIT_KEYS 3
user_1
user_2
user_3
EVENTS 7
REQ C1 user_1
REQ C2 user_1
REQ C3 hacker_invalid_999
REQ C4 hacker_invalid_999
REQ C5 user_2
REQ C6 hacker_invalid_888
REQ C7 user_3
```

### 출력
```text
REQ C1 KEY:user_1 NAIVE:DB_FOUND BLOOM:DB_FOUND
REQ C2 KEY:user_1 NAIVE:CACHE_HIT BLOOM:CACHE_HIT
REQ C3 KEY:hacker_invalid_999 NAIVE:DB_NOT_FOUND BLOOM:BLOOM_REJECT
REQ C4 KEY:hacker_invalid_999 NAIVE:DB_NOT_FOUND BLOOM:BLOOM_REJECT
REQ C5 KEY:user_2 NAIVE:DB_FOUND BLOOM:DB_FOUND
REQ C6 KEY:hacker_invalid_888 NAIVE:DB_NOT_FOUND BLOOM:BLOOM_REJECT
REQ C7 KEY:user_3 NAIVE:DB_FOUND BLOOM:DB_FOUND
SUMMARY TOTAL_REQS:7
NAIVE DB_QUERIES:6
BLOOM DB_QUERIES:3 BLOOM_REJECTS:3 FALSE_POSITIVES:0
SUMMARY DB_QUERY_SAVED:50.00%
```

#### 해설
- `user_1`, `user_2`, `user_3`은 DB에 실재하는 키이며, 첫 조회 시 DB 조회가 발생하고 이후에는 캐시 히트됩니다.
- `hacker_invalid_999`와 `hacker_invalid_888`은 존재하지 않는 악성 키입니다.
  - **NAIVE**: 캐시에 들어가지 않으므로 매 요청마다 DB 조회가 반복 발생하여 총 6번의 DB 쿼리가 발생합니다.
  - **BLOOM**: 블룸 필터가 0번 비트를 감지하여 DB 조회를 즉시 차단(`BLOOM_REJECT`)하므로, DB 쿼리를 정상 키 조회 3회로 억제하여 50.00%의 DB 쿼리를 절감했습니다.
