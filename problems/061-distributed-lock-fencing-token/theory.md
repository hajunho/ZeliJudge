# 분산 락의 치명적인 함정과 펜싱 토큰 (Distributed Lock STW Pause & Fencing Token)

> **"분산 락(Distributed Lock)을 걸었는데 왜 두 명이 동시에 한정판 티켓을 결제했을까요?!"**  
> **"GC(Garbage Collection)가 멈춘 0.5초 동안, 내 시스템은 다른 사람의 손에 넘어가 있었습니다."**

---

## 1. 현실 세계 비유: 호텔 카드키 만료와 룸메이트 참사

당신이 호텔에 1박 2일 머물기 위해 체크인을 했습니다.

```
[호텔 체크인]
손님 A: "101호실 1시간만 대여할게요!"
호텔 프론트: "네, 1시간짜리 임시 디지털 카드키를 발급해 드렸습니다." (TTL = 1시간)
```

손님 A는 101호에 들어가서 짐을 풀다가 화장실 바닥에 미끄러져 **2시간 동안 기절(Stop-The-World Pause)**해 버렸습니다.

그 사이 호텔 전산실에서는 무슨 일이 일어났을까요?
1. **1시간 경과 (TTL 만료)**: 호텔 프론트 컴퓨터는 1시간이 지나자 "아, 손님 A의 사용 시간이 끝났구나!" 하고 101호를 자동으로 **빈 방(Lock 해제)** 처리합니다.
2. **새 손님 B 체크인**: 손님 B가 와서 101호를 새로 예약하고 들어옵니다. 손님 B는 옷장에 자신의 최고급 명품 정장(`DATA_B`)을 깔끔하게 걸어두었습니다.
3. **손님 A 기절에서 깨어남**: 2시간 만에 깨어난 손님 A는 자신이 2시간 동안 기절했다는 사실을 전혀 모릅니다! 자기는 방금 들어온 줄 압니다.
4. **대참사 발생**: 손님 A는 옷장에 걸린 손님 B의 명품 정장을 바닥에 내팽개치고, 자신의 흙 묻은 등산복(`DATA_A`)을 걸어버립니다!
5. **추가 대참사 (락 하이재킹)**: 손님 A가 프론트로 가더니 "저 이제 체크아웃할게요" 하고 키를 반납합니다. 프론트 직원이 무심코 101호 전원을 꺼버려서, **방에 멀쩡히 있던 손님 B까지 강제로 방에서 쫓겨납니다!**

이 황당한 시트콤 같은 일이, **Redis 분산 락을 사용하는 전 세계 수만 개의 서버에서 매일 밤낮으로 실제로 일어나고 있는 치명적인 데이터 오염 버그**입니다.

---

## 2. 분산 시스템 역사상 가장 뜨거웠던 논쟁: Kleppmann vs Antirez

2016년, 분산 시스템의 바이블 *Designing Data-Intensive Applications (DDIA)*의 저자 **마틴 클레프만(Martin Kleppmann)**과 Redis의 창시자 **살바토레 산필리포(Antirez)** 사이에 전설적인 공개 논쟁이 벌어졌습니다.

- **클레프만의 지적**:
  "Redis의 Redlock이든 단순 락이든, **타임아웃(TTL) 기반의 분산 락은 안전성을 완벽히 보장할 수 없다.**  
  클라이언트에서 언어 런타임의 **Stop-The-World GC**, OS의 **Paging/I-O Stalls**, 혹은 **CPU 쓰레드 스케줄링 지연**이 발생하면 클라이언트는 자기가 락을 잃었다는 사실도 모른 채 스토리지에 데이터를 덮어써서 데이터를 파괴한다."

```
Client 1 (JVM)              Redis (Lock Server)           Database / Storage
   |                               |                             |
   |--- 1. LOCK(key, TTL=10s) ---->|                             |
   |<-- 2. Lock OK ----------------|                             |
   |                               |                             |
[ STW GC Pause (15초 동안 멈춤) ]   |                             |
   :                               |                             |
   :                        [ 10초 후 TTL 만료 ]                  |
   :                               |                             |
   :           Client 2            |                             |
   :              |-- 3. LOCK ---->|                             |
   :              |<- 4. Lock OK --|                             |
   :              |---------------- 5. WRITE("Client2 Data") --->| (DB: Client2 저장)
   :              |-- 6. RELEASE ->|                             |
   :                               |                             |
[ GC 깨어남! ]                     |                             |
   |                               |                             |
   |------------------------------- 7. WRITE("Client1 Stale") -->| 💥 DB 파괴!!
   |                                                               (Client2 데이터 증발!)
```

### 왜 단순 락(Lock)만으로는 막을 수 없는가?
- 비동기 분산 네트워크에서는 **"네트워크 지연 시간의 상한선"도 없고, "프로세스가 멈추지 않는다는 보장"도 없습니다.**
- 클라이언트가 `is_locked()`를 검사하고 다음 줄에서 `db.save()`를 호출하는 그 찰나의 순간에도 OS가 쓰레드를 멈춰버리면 락은 만료되고 맙니다 (Check-Then-Act 경쟁 상태).
- 따라서 **"락을 쥔 사람만 데이터를 쓸 수 있다"는 규칙은 스토리지 계층의 협조 없이는 절대로 성립할 수 없습니다.**

---

## 3. 해결책: 마틴 클레프만의 펜싱 토큰 (Fencing Token)

마틴 클레프만이 제시한 궁극의 해결책이 바로 **펜싱 토큰(Fencing Token)**입니다.

> **"울타리(Fence)를 쳐서 오래된 유령 클라이언트의 접근을 물리적으로 차단하라!"**

### 1) 펜싱 토큰의 3대 불변식 (Invariants)
1. **단조 증가(Strictly Monotonically Increasing)**:  
   락 서버는 락을 성공적으로 획득할 때마다 1씩 증가하는 고유 번호(Token: 1, 2, 3...)를 발급합니다.
2. **토큰 전달(Token Propagation)**:  
   클라이언트는 스토리지에 `WRITE`할 때 반드시 자신이 발급받은 펜싱 토큰을 함께 보냅니다:  
   `WRITE(token=33, payload)`
3. **스토리지 울타리 검증(Storage Fencing Check)**:  
   스토리지(DB/S3/파일시스템)는 자신이 지금까지 본 가장 높은 토큰 `highest_token_seen`을 기억합니다.  
   - 만약 들어온 요청의 `token > highest_token_seen` 이면:  
     수락! `highest_token_seen = token` 갱신 후 쓰기 실행.
   - 만약 들어온 요청의 `token <= highest_token_seen` 이면:  
     **즉각 거부(REJECT)!** "손님, 당신은 과거의 유령입니다. 이미 더 최신 토큰의 클라이언트가 지나갔습니다."

```
Client 1 (Token=33)         Redis (Lock Server)           Database (highest_token=33)
   |                               |                             |
   |--- 1. LOCK 획득 (Token=33) --->|                             |
[ 15초 STW GC 멈춤 ]               |                             |
   :                        [ TTL 만료 ]                         |
   :           Client 2            |                             |
   :              |-- 2. LOCK (Token=34)                         |
   :              |---------------- 3. WRITE(Token=34) --------->| (최고 토큰 34 갱신!)
   :                               |                             |
[ GC 깨어남! ]                     |                             |
   |                               |                             |
   |------------------------------- 4. WRITE(Token=33) --------->| 🛡️ 거부!! (33 <= 34)
                                                                   (스토리지 오염 차단 성공!)
```

### 2) 락 무단 해제 방어 (Stale Release Hijack 방어)
단순한 Redis 락에서는 `DEL my_lock` 명령을 날립니다.  
하지만 클라이언트 A가 늦게 깨어나서 `DEL my_lock`을 날리면 **클라이언트 B가 힘들게 얻어둔 락이 날아가 버립니다!**  
이를 막기 위해 Safe 락은 해제 시에도 토큰(또는 UUID 소유권)을 대조합니다:
- Redis에서는 반드시 **Lua Script**로 원자적 검증 및 삭제를 수행합니다:
  ```lua
  if redis.call("get", KEYS[1]) == ARGV[1] then
      return redis.call("del", KEYS[1])
  else
      return 0 -- 남의 락이므로 건드리지 않음!
  end
  ```

---

## 4. 실무에서 펜싱 토큰은 어떻게 구현하는가?

1. **RDBMS (MySQL, PostgreSQL)**:  
   테이블에 `lock_version BIGINT` 컬럼을 두고 낙관적 락(Optimistic Locking)을 결합합니다:
   ```sql
   UPDATE orders 
   SET status = 'PAID', lock_token = 34 
   WHERE id = 1001 AND lock_token < 34;
   -- 만약 영향받은 row 수가 0이면 Stale Token 에러 처리!
   ```
2. **분산 코디네이터 (ZooKeeper, etcd)**:  
   ZooKeeper의 `zxid`나 `cversion`, etcd의 `mod_revision` 자체가 단조 증가하는 펜싱 토큰 역할을 하므로, 이를 트랜잭션 조건절(`txn`)에 넣어 안전하게 사용합니다.
3. **AWS S3 / GCP GCS**:  
   Conditional Writes (`If-Match`, `ETag`) 또는 메타데이터 버전 조건을 사용하여 오래된 유령 쓰기를 거부합니다.

---

## 5. 요약 및 실무 체크리스트

| 점검 항목 | Naive 단순 분산 락 | Safe 펜싱 토큰 분산 락 |
| :--- | :--- | :--- |
| **GC / 네트워크 지연 시** | TTL 만료 후 유령 클라이언트가 스토리지 파괴 | 스토리지 차원에서 구버전 토큰 감지 및 거부 |
| **락 해제(`RELEASE`) 시** | `del key`로 다른 사람의 새 락을 강제 탈취/해제 | Lua 스크립트로 토큰 일치 시에만 안전 해제 |
| **동시성 안전성 보장** | 보장 불가 (Probabilistic Safe) | 100% 보장 (Provably Safe) |
| **핵심 전제 조건** | "락 서버만 믿으면 된다" (틀린 믿음) | "락 서버 + 스토리지의 토큰 검증 협업" (정답) |
