# Problem #040: DB 1대에 1억 건이 넘어가니 죽으려고 해요?!: 데이터베이스 샤딩(Sharding)과 리밸런싱

## 📖 실무 스토리: 단일 DB의 한계와 모듈로 샤딩의 '대이사' 재앙!

스타트업 백엔드 개발자 나코딩은 서비스의 주문 및 피드 데이터가 **1억 건**을 돌파하자 매일 밤 악몽을 꾸었습니다.
AWS에서 가장 큰 메모리(1TB RAM)와 가장 빠른 NVMe SSD를 장착한 인스턴스로 스케일업(Scale-up)했지만, B-Tree 인덱스 크기가 RAM을 초과하면서 디스크 I/O 100%가 찍히고 쿼리가 30초씩 멈추기 시작했습니다.

> **나코딩**: "이제 단일 DB로는 물리적 한계다. 데이터를 여러 대의 DB로 쪼개는 **데이터베이스 샤딩(Database Sharding)**을 적용하자!"

나코딩은 가장 간단하고 직관적인 **모듈로 해시 샤딩(Modulo Hash Sharding)**을 선택했습니다:
* 초기 샤드 3대(`shard_0`, `shard_1`, `shard_2`)를 띄우고:
  $$\text{shard} = \text{user\_id} \pmod 3$$
* 유저 ID에 3을 나눈 나머지로 샤드를 지정하여 데이터를 골고루 분산시켰습니다.

하지만 6개월 뒤, 데이터가 또 2배로 늘어나자 나코딩은 샤드를 1대 더 늘려 **4대(`shard_3` 추가)**로 확장하기로 했습니다.
그리고 배포 스크립트를 실행한 순간, **전사 서비스가 멈추고 3일간의 지옥문이 열렸습니다!**

1. **"모듈로가 바뀌는 순간, 기존 데이터의 75%가 다른 DB로 이사를 가야 합니다!"**
   * 유저 10번: $10 \pmod 3 = 1$ (`shard_1`) $\to$ $10 \pmod 4 = 2$ (`shard_2`로 이사!)
   * 유저 11번: $11 \pmod 3 = 2$ (`shard_2`) $\to$ $11 \pmod 4 = 3$ (`shard_3`로 이사!)
   * 유저 12번: $12 \pmod 3 = 0$ (`shard_0`) $\to$ $12 \pmod 4 = 0$ (유지)
   * 샤드를 고작 1대 늘렸을 뿐인데, **기존 데이터 수천만 건이 네트워크를 타고 다른 DB로 복사되고 삭제되는 초대형 데이터 마이그레이션 폭풍**이 발생하여 네트워크 대역폭과 디스크가 마비되었습니다!
2. **"특정 샤드에만 데이터가 쏠리는 핫스팟(Hotspot / Data Skew)을 전혀 수동으로 조절할 수 없습니다!"**

> **"샤드를 1대 늘릴 때 왜 기존 데이터 전체가 이사를 가야 하죠?! 새 샤드가 필요한 만큼만 기존 샤드에서 조금씩 덜어올 수는 없나요?!"**

이 재앙을 극복하기 위해 엔터프라이즈 시스템에서는 **디렉토리 기반 샤딩(Directory / Lookup Table Sharding)**을 사용합니다.
샤드 매핑을 유연한 룩업 테이블로 관리하여, 샤드가 증설될 때 **가장 짐이 많은 샤드에서 필요한 만큼만 선택적으로 이전(Selective Rebalancing)**시키는 것입니다!

여러분의 임무는 2가지 샤딩 전략(HASH_MODULO vs DIRECTORY)을 시뮬레이션하고, 샤드 증설 리밸런싱 시 발생하는 데이터 이동 비용과 절감 효과를 정밀 계측하는 샤딩 라우팅 엔진을 구현하는 것입니다!

---

## 🎯 문제 요구사항

초기 샤드 개수 $K$와 일련의 이벤트(`INSERT`, `LOOKUP`, `ADD_SHARD`)를 입력받아 두 샤딩 전략의 동작을 평가하십시오:

### 1. 2대 샤딩 전략 규칙

1. **전략 1: HASH_MODULO (모듈로 해시 샤딩)**
   * 유저 $U$의 데이터는 항상 현재 샤드 수 $K$에 대한 모듈로 연산으로 결정됩니다:
     $$\text{shard\_id} = U \pmod K$$
   * **샤드 증설 시 (`ADD_SHARD`)**:
     * 샤드 수가 $K \to K + 1$로 증가합니다.
     * 모든 유저 $U$에 대해 이전 샤드($U \pmod K$)와 새 샤드($U \pmod{K+1}$)를 비교합니다.
     * 샤드가 달라진 모든 유저의 **모든 레코드**가 새 샤드로 이동해야 하므로, 이동된 총 레코드 수만큼 `hash_migrated`가 누적됩니다.

2. **전략 2: DIRECTORY (디렉토리 / 룩업 테이블 샤딩 - Golden Standard)**
   * 유저별 샤드 매핑을 `user_to_shard` 룩업 테이블로 관리합니다.
   * **신규 유저 INSERT 시**:
     * 해당 유저가 처음 등장한 경우, 현재 저장된 총 레코드 수가 **가장 적은 샤드(Least Loaded Shard)**에 유저를 영구 배정합니다.
     * *(동점일 경우 샤드 번호가 작은 샤드 우선)*
     * 이미 등록된 유저의 추가 INSERT는 해당 유저의 기존 샤드에 계속 저장됩니다.
   * **샤드 증설 시 (`ADD_SHARD`)**:
     * 새 샤드(`shard_K`)가 0개의 레코드로 추가됩니다 ($K \leftarrow K + 1$).
     * 전체 레코드 수 $N_{total}$에 대해, 새 샤드가 채워야 할 목표 레코드 수 $T = \lfloor N_{total} / K_{new} \rfloor$를 계산합니다.
     * 새 샤드의 레코드 수가 $T$에 도달할 때까지 다음 과정을 반복합니다:
       1. 새 샤드를 제외한 기존 샤드들 중 **레코드 수가 가장 많은 샤드(Most Loaded Shard)**를 찾습니다. *(동점일 경우 샤드 번호가 작은 샤드 우선)*
       2. 만약 가장 많은 샤드의 레코드 수가 이미 $T$ 이하이거나 더 이상 이전할 유저가 없다면 즉시 리밸런싱을 종료합니다.
       3. 해당 샤드에 속한 유저 중 **유저 ID가 가장 작은 유저**를 새 샤드로 통째로 이전합니다.
       4. 해당 유저가 가진 레코드 수만큼 `dir_migrated`가 누적되고 각 샤드의 레코드 수가 갱신됩니다.

---

## 📥 입력 형식 (Input Format)

```text
INITIAL_SHARDS <K>
EVENTS <N>
<event_1>
<event_2>
...
```

* 첫 번째 줄: `INITIAL_SHARDS` 키워드 뒤에 초기 샤드 개수 $K$ ($1 \le K \le 20$)가 주어집니다. 샤드 번호는 0부터 $K-1$까지입니다.
* 두 번째 줄: `EVENTS` 키워드 뒤에 총 이벤트 개수 $N$ ($1 \le N \le 30,000$)이 주어집니다.
* 세 번째 줄부터 각 이벤트가 주어집니다:
  * `INSERT <user_id> <data_id>`: 정수 `user_id` ($0 \le user\_id \le 1,000,000$)와 문자열 `data_id`
  * `LOOKUP <user_id>`: 정수 `user_id`의 현재 샤드 위치 조회
  * `ADD_SHARD`: 새로운 샤드 1대 증설 및 리밸런싱 수행

---

## 📤 출력 형식 (Output Format)

각 이벤트에 대해 다음 형식으로 1줄씩 출력합니다:
* `INSERT` 이벤트:
  ```text
  INSERT USER:<user_id> DATA:<data_id> HASH:shard_<s1> DIR:shard_<s2>
  ```
* `LOOKUP` 이벤트:
  ```text
  LOOKUP USER:<user_id> HASH:shard_<s1> DIR:shard_<s2>
  ```
  *(단, DIRECTORY 전략에서 한 번도 등록된 적 없는 유저는 `DIR:shard_-1`로 출력)*
* `ADD_SHARD` 이벤트:
  ```text
  REBALANCE SHARDS:<K_new> HASH_MIGRATED:<m1> DIR_MIGRATED:<m2> MIGRATIONS_SAVED:<saved>
  ```
  * `MIGRATIONS_SAVED`: `m1 - m2` (디렉토리 샤딩이 모듈로 샤딩 대비 절감한 레코드 이동 건수)

모든 이벤트 처리 후 마지막 줄에 종합 통계(Summary)를 1줄 출력합니다:
```text
SUMMARY TOTAL_INSERTS:<ins> TOTAL_LOOKUPS:<lkp> TOTAL_REBALANCES:<reb> TOTAL_HASH_MIGRATED:<tot_hm> TOTAL_DIR_MIGRATED:<tot_dm> TOTAL_MIGRATIONS_SAVED:<tot_saved>
```

---

## 💡 입출력 예제 (Sample I/O)

### 예제 입력
```text
INITIAL_SHARDS 3
EVENTS 11
INSERT 10 d1
INSERT 11 d2
INSERT 12 d3
INSERT 10 d4
INSERT 14 d5
INSERT 15 d6
LOOKUP 10
ADD_SHARD
LOOKUP 10
LOOKUP 11
INSERT 16 d7
```

### 예제 출력
```text
INSERT USER:10 DATA:d1 HASH:shard_1 DIR:shard_0
INSERT USER:11 DATA:d2 HASH:shard_2 DIR:shard_1
INSERT USER:12 DATA:d3 HASH:shard_0 DIR:shard_2
INSERT USER:10 DATA:d4 HASH:shard_1 DIR:shard_0
INSERT USER:14 DATA:d5 HASH:shard_2 DIR:shard_1
INSERT USER:15 DATA:d6 HASH:shard_0 DIR:shard_2
LOOKUP USER:10 HASH:shard_1 DIR:shard_0
REBALANCE SHARDS:4 HASH_MIGRATED:4 DIR_MIGRATED:2 MIGRATIONS_SAVED:2
LOOKUP USER:10 HASH:shard_2 DIR:shard_3
LOOKUP USER:11 HASH:shard_3 DIR:shard_1
INSERT USER:16 DATA:d7 HASH:shard_0 DIR:shard_0
SUMMARY TOTAL_INSERTS:7 TOTAL_LOOKUPS:3 TOTAL_REBALANCES:1 TOTAL_HASH_MIGRATED:4 TOTAL_DIR_MIGRATED:2 TOTAL_MIGRATIONS_SAVED:2
```

---

## 힌트 & 핵심 점검 사항
1. **샤드 증설 시 모듈로 샤딩의 비극**:
   * 총 6개 레코드 중 유저 10(2개), 유저 11(1개), 유저 14(1개)의 모듈로 결과가 바뀌어 총 4개(66.7%)의 레코드가 이사를 가야 했습니다 (`HASH_MIGRATED: 4`).
2. **디렉토리 샤딩의 미니멀 마이그레이션**:
   * 새 샤드(`shard_3`)의 목표 할당량은 $6 // 4 = 1$입니다.
   * 가장 레코드가 많았던 `shard_0`(유저 10, 2개 레코드)에서 유저 10만 `shard_3`로 이전시킴으로써, 단 2건의 이동(`DIR_MIGRATED: 2`)만으로 리밸런싱을 완료했습니다.
3. **절감 효과**: 대규모 운영 환경에서 수천만 건의 네트워크 I/O 병목을 획기적으로 줄일 수 있습니다!
