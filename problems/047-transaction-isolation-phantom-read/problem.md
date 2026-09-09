# #047 100장 한정 쿠폰인데 왜 105장이 발급돼요?!: 트랜잭션 격리 수준(Isolation Level)과 팬텀 리드(Phantom Read)

---

## 1. 현실 세계 비유: 콘서트장 객석 안전요원과 비상구로 잠입하는 관객

100석 한정 콘서트장의 입장을 관리하는 상황을 상상해 보세요.

```text
❌ 반복 읽기(Repeatable Read) 격리 수준의 맹점:
   안전요원 A(트랜잭션 A)가 무전기로 객석을 확인합니다.
   "현재 입장 인원 98명! 아직 2자리 남았으니 입장권 발급 진행합니다."
   그런데 바로 그 순간, 반대편 비상구에서 안전요원 B(트랜잭션 B)가 손님 2명을 들여보내고 문을 닫았습니다(COMMIT).
   안전요원 A는 자기 트랜잭션 시작 시점의 사진(MVCC 스냅샷)만 보고 있으므로 여전히 "아직 98명이네" 하고
   손님 2명을 추가로 입장시켜 버립니다.
   결과 -> 100석 콘서트장에 총 102명이 들어차며 안전사고(오버부킹, Overbooking) 발생!

✅ 직렬화 가능(Serializable) 격리 수준의 철벽 방어:
   안전요원 A가 객석을 확인하는 동안 객석 출입문 전체에 자물쇠(Range / Next-Key Lock)를 걸어 잠급니다.
   안전요원 B가 비상구로 손님을 들여보내려(INSERT) 시도하자마자,
   자물쇠 충돌(Serialization Conflict)이 발생하여 B의 입장이 단호하게 거부(ABORT)됩니다!
   결과 -> 정확히 100명 정원 엄수!
```

수많은 주니어 개발자와 AI 바이브 코더들이 "DB 트랜잭션(`@Transactional`) 걸어뒀으니 동시성 문제는 당연히 없겠지!"라며 안심합니다.  
그리고 선착순 100명 쿠폰 이벤트 날, **`SELECT count(*)`로 잔여 수량을 확인하고 `INSERT`를 쳤는데 쿠폰이 105장이나 발급되어 회사에 막대한 손실을 입히는 참사**를 겪습니다.  
트랜잭션 격리 수준(Transaction Isolation Level)과 **유령 행이 나타나는 "팬텀 리드(Phantom Read)"** 현상을 몰랐기 때문입니다!

---

## 2. 문제 개요

당신은 선착순 한정판 티켓팅 시스템의 DB 무결성을 지켜야 하는 데이터베이스 아키텍트입니다.  
여러 트랜잭션이 동시에 시작되어 잔여 수량을 확인(`TX_READ`)하고 티켓을 발급(`TX_INSERT`)하는 환경에서,  
ANSI SQL의 3대 격리 수준(`READ_COMMITTED`, `REPEATABLE_READ`, `SERIALIZABLE`)의 동작을 시뮬레이션하고,  
팬텀 오버부킹(`OVERBOOKED`) 발생 여부를 정밀 판정하세요.

### 격리 수준별 시뮬레이션 상세 규칙

#### 1. 공통 환경
- `MAX_CAPACITY <limit>`: 시스템이 허용하는 최대 총 발급 수량 ($1 \le limit \le 10,000$).
- 테이블은 영구 커밋된 아이템 목록(`committed_items`)을 관리합니다.
- 각 트랜잭션은 고유 식별자 `tx_id`와 지정된 `isolation_level`로 시작됩니다.

#### 2. 격리 수준별 `TX_READ <tx_id>` 동작
현재 트랜잭션의 눈에 보이는 아이템 총 개수를 반환합니다.
- **`READ_COMMITTED`**:
  - 현재 시점에 커밋된 총 아이템 수 + 본인 트랜잭션에서 아직 커밋 안 된 INSERT 수.
  - 다른 트랜잭션이 중간에 커밋하면 조회할 때마다 숫자가 실시간으로 증가합니다 (Non-Repeatable / Phantom Read 발생).
- **`REPEATABLE_READ`**:
  - MVCC 스냅샷 격리: **본인 트랜잭션 시작 시점**에 커밋되어 있던 아이템 수 + 본인 트랜잭션의 미커밋 INSERT 수.
  - 다른 트랜잭션이 중간에 아무리 많은 행을 커밋해도 본인의 스냅샷에는 보이지 않습니다.
- **`SERIALIZABLE`**:
  - 트랜잭션 시작 시점의 스냅샷 카운트를 읽지만, 동시에 해당 범위에 대한 **공유 범위 락(Range / Gap Lock)**을 획득합니다 (`has_read = True`).

#### 3. `TX_INSERT <tx_id> <item_id>` 동작
- **직렬화 충돌(Serialization Conflict) 검사**:
  - 만약 현재 활성화된 다른 트랜잭션 중 `SERIALIZABLE` 모드이면서 이미 `TX_READ`를 수행한 트랜잭션이 존재한다면:
    - 해당 트랜잭션이 쥐고 있는 범위 락과 충돌이 발생합니다!
    - 현재 트랜잭션의 INSERT는 거부되고 트랜잭션이 즉시 강제 취소(ABORT)됩니다: `STATUS:SERIALIZATION_CONFLICT`.
    - 충돌 카운트 `conflicts_count`가 `1` 증가하며, 해당 트랜잭션의 기존 미커밋 데이터는 모두 폐기됩니다.
  - 충돌이 없다면:
    - 본인의 미커밋 목록에 정상 추가됩니다: `STATUS:ACCEPTED`.
- 이미 `ABORTED` 상태인 트랜잭션의 모든 후속 명령(`TX_READ`, `TX_INSERT`, `TX_COMMIT`)은 실행되지 않고 에러 상태를 반환합니다.

#### 4. `TX_COMMIT <tx_id>` 및 `TX_ROLLBACK <tx_id>`
- `TX_COMMIT`:
  - 정상 트랜잭션: 미커밋된 아이템들이 `committed_items`에 영구 반영됩니다: `STATUS:COMMITTED ITEMS_COMMITTED:<count>`.
  - 이미 어보트된 트랜잭션: `STATUS:ABORTED_CANNOT_COMMIT`.
- `TX_ROLLBACK`:
  - 미커밋 데이터 폐기 후 종료: `STATUS:ROLLED_BACK`.

---

## 3. 입력 형식

```text
MAX_CAPACITY <limit>
EVENTS <E>
TX_START <tx_id> <READ_COMMITTED | REPEATABLE_READ | SERIALIZABLE>
TX_READ <tx_id>
TX_INSERT <tx_id> <item_id>
TX_COMMIT <tx_id>
TX_ROLLBACK <tx_id>
... (총 E개의 줄)
```

- `limit`: 최대 허용 정원 (정수, $1 \le limit \le 10,000$)
- `E`: 총 이벤트 줄 수 ($1 \le E \le 30,000$)
- 각 명령:
  - `TX_START <tx_id> <level>`: 트랜잭션 시작
  - `TX_READ <tx_id>`: 현재 보이는 수량 조회
  - `TX_INSERT <tx_id> <item_id>`: 아이템 삽입 시도
  - `TX_COMMIT <tx_id>`: 트랜잭션 커밋
  - `TX_ROLLBACK <tx_id>`: 트랜잭션 롤백

---

## 4. 출력 형식

각 이벤트마다 한 줄씩 출력합니다:

- `TX_START <tx_id> LEVEL:<level>`
- `TX_READ <tx_id> COUNT:<count>` (또는 어보트 시 `STATUS:ABORTED`)
- `TX_INSERT <tx_id> ITEM:<item_id> STATUS:<ACCEPTED | SERIALIZATION_CONFLICT | ABORTED>`
- `TX_COMMIT <tx_id> STATUS:<COMMITTED ITEMS_COMMITTED:<count> | ABORTED_CANNOT_COMMIT>`
- `TX_ROLLBACK <tx_id> STATUS:ROLLED_BACK`

모든 이벤트 처리 후 마지막 줄에 통계 요약을 출력합니다:
```text
SUMMARY TOTAL_EVENTS:<E> FINAL_COMMITTED:<final_committed> LIMIT:<limit> OVERBOOKED:<overbooked> CONFLICTS_CAUGHT:<conflicts_count>
```
- `<overbooked>`: 초과 발급 수량 $\max(0, final\_committed - limit)$

---

## 5. 입출력 예시

### 예시 입력 1
```text
MAX_CAPACITY 2
EVENTS 18
TX_START tx_1 REPEATABLE_READ
TX_START tx_2 REPEATABLE_READ
TX_READ tx_1
TX_READ tx_2
TX_INSERT tx_1 item_A
TX_INSERT tx_1 item_B
TX_COMMIT tx_1
TX_READ tx_2
TX_INSERT tx_2 item_C
TX_COMMIT tx_2
TX_START tx_3 SERIALIZABLE
TX_START tx_4 SERIALIZABLE
TX_READ tx_3
TX_INSERT tx_4 item_D
TX_COMMIT tx_4
TX_INSERT tx_3 item_E
TX_COMMIT tx_3
TX_START tx_5 READ_COMMITTED
```

### 예시 출력 1
```text
TX_START tx_1 LEVEL:REPEATABLE_READ
TX_START tx_2 LEVEL:REPEATABLE_READ
TX_READ tx_1 COUNT:0
TX_READ tx_2 COUNT:0
TX_INSERT tx_1 ITEM:item_A STATUS:ACCEPTED
TX_INSERT tx_1 ITEM:item_B STATUS:ACCEPTED
TX_COMMIT tx_1 STATUS:COMMITTED ITEMS_COMMITTED:2
TX_READ tx_2 COUNT:0
TX_INSERT tx_2 ITEM:item_C STATUS:ACCEPTED
TX_COMMIT tx_2 STATUS:COMMITTED ITEMS_COMMITTED:1
TX_START tx_3 LEVEL:SERIALIZABLE
TX_START tx_4 LEVEL:SERIALIZABLE
TX_READ tx_3 COUNT:3
TX_INSERT tx_4 ITEM:item_D STATUS:SERIALIZATION_CONFLICT
TX_COMMIT tx_4 STATUS:ABORTED_CANNOT_COMMIT
TX_INSERT tx_3 ITEM:item_E STATUS:ACCEPTED
TX_COMMIT tx_3 STATUS:COMMITTED ITEMS_COMMITTED:1
TX_START tx_5 LEVEL:READ_COMMITTED
SUMMARY TOTAL_EVENTS:18 FINAL_COMMITTED:4 LIMIT:2 OVERBOOKED:2 CONFLICTS_CAUGHT:1
```

### 설명
- **`tx_1`과 `tx_2`의 REPEATABLE_READ 참사**:
  - `tx_1`이 `item_A`, `item_B`를 커밋하여 이미 정원 2개가 꽉 찼습니다.
  - 하지만 `tx_2`는 스냅샷 격리 때문에 `TX_READ` 시 여전히 `COUNT: 0`으로 보입니다!
  - `tx_2`는 안심하고 `item_C`를 삽입 커밋하여, 정원 2개짜리에 3개가 들어가는 **팬텀 오버부킹**이 터졌습니다.
- **`tx_3`과 `tx_4`의 SERIALIZABLE 방어**:
  - `tx_3`이 `TX_READ`로 범위 락을 쥔 상태에서 `tx_4`가 몰래 `item_D`를 삽입하려 하자, 즉시 `SERIALIZATION_CONFLICT`로 차단되고 강제 취소되었습니다!
  - `tx_4`의 끼어들기가 원천 봉쇄되어 데이터 정합성이 수호되었습니다.
