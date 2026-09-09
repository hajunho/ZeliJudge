# 멀티 리전 액티브-액티브(Active-Active) 분산 데이터베이스의 충돌 해결: LWW 시계 드리프트 데이터 증발 참사 vs HLC vs CRDT

## 1. 개요 및 실무 배경: "최신 데이터를 저장했는데 왜 1초 전 데이터로 되돌아가요?!"

글로벌 서비스를 운영하는 빅테크 기업 '젤리글로벌'은 전 세계 사용자들에게 50ms 미만의 초저지연 응답을 제공하기 위해, 서울(SEOUL), 버지니아(IAD), 프랑크푸르트(FRA) 리전에 분산 데이터베이스를 배치하고 모든 리전에서 동시에 쓰기가 가능한 **멀티 리전 액티브-액티브(Multi-Region Active-Active)** 아키텍처를 도입했습니다.

개발팀은 멀티 리전 간의 데이터 동기화 시 발생하는 동시 쓰기 충돌을 해결하기 위해, 가장 널리 쓰이는 **LWW(Last-Write-Wins, 마지막 쓰기 승리)** 정책을 채택했습니다:
```python
# LWW 충돌 해결 규칙: 타임스탬프가 큰 쓰기가 승리한다!
if incoming_timestamp > local_timestamp:
    local_value = incoming_value
```

그런데 글로벌 런칭 직후, 고객센터에 기괴한 버그 제보가 쏟아졌습니다:
* 버지니아 리전에 접속한 유저 '앨리스'가 오후 12시 00분 00초 300ms에 닉네임을 `'Alice_IAD'`로 수정했습니다.
* 서울 리전에서는 이미 12시 00분 00초 100ms에 이전 닉네임 `'Alice_Seoul'`이 저장되어 있었습니다.
* 네트워크 복제(Replication)가 완료된 후, 버지니아와 서울 리전 모두에서 앨리스의 닉네임을 조회해 보니 놀랍게도 **최신으로 수정한 `'Alice_IAD'`가 감쪽같이 사라지고 200ms 전의 옛날 닉네임 `'Alice_Seoul'`로 덮어씌워져(Lost Update)** 있었습니다!

사용자가 분명 방금 최신 값으로 저장했는데, **어떻게 과거의 옛날 데이터가 최신 데이터를 덮어써서 영구 증발시킨 것일까요?**

---

## 2. 참사의 주범: NTP 시계 드리프트(Clock Drift)와 물리 시계의 한계

### (1) 서버 시계는 결코 완벽하지 않다 (Physical Clock Drift)
컴퓨터 메인보드의 수정 발진기(Quartz Oscillator)는 온도, 진동, 하드웨어 노후화에 따라 1초에 수 마이크로초씩 시간이 어긋납니다.  
NTP(Network Time Protocol)로 시계를 주기적으로 동기화하더라도, 네트워크 패킷 지연 편차로 인해 **실무 서버들 사이에는 항상 수 밀리초에서 수백 밀리초에 달하는 시계 오차(Clock Drift / Clock Skew)**가 존재합니다.

### (2) LWW 시계 왜곡 시나리오
```
[물리적 절대 시간 (True Time)]
t = 100ms: SEOUL에서 닉네임을 'Alice_Seoul'로 쓰기
t = 300ms: IAD에서 닉네임을 'Alice_IAD'로 쓰기  <-- (분명히 200ms 더 늦게 일어난 진짜 최신 쓰기!)
```

그런데 버지니아(IAD) 서버의 NTP 데몬이 이상 작동하여 시계가 실제보다 **500ms 느리게(Drift = -500ms)** 가고 있었습니다:
* **SEOUL 서버의 로컬 시계**: $t_{SEOUL} = 100 + 0 = 100	ext{ms}$
  * 서울은 `('Alice_Seoul', ts=100)`으로 기록.
* **IAD 서버의 로컬 시계**: $t_{IAD} = 300 - 500 = -200	ext{ms}$
  * 버지니아는 `('Alice_IAD', ts=-200)`으로 기록!

두 데이터가 네트워크를 통해 복제(Replication)될 때, LWW 머지 엔진은 단순 타임스탬프를 비교합니다:
$$ts_{SEOUL}(100) > ts_{IAD}(-200)$$

LWW 엔진은 물리적으로 200ms 뒤에 일어난 최신 쓰기(`Alice_IAD`)를 **과거의 유령 데이터로 오판하여 영구 삭제(Drop)**하고, 옛날 데이터(`Alice_Seoul`)를 승리자로 선언했습니다.

이것이 바로 분산 시스템의 고전적 비극인 **LWW 시계 드리프트 갱신 분실(Lost Update via Clock Drift)** 참사입니다.

---

## 3. 해결책 1: 하이브리드 논리 시계 (HLC, Hybrid Logical Clock)

물리 시계의 드리프트 취약점을 해결하기 위해 Kulkarni 연구팀이 2014년에 발표한 알고리즘이 **HLC(Hybrid Logical Clock)**입니다. (CockroachDB, MongoDB, YugabyteDB 등 현대 분산 DB의 표준)

HLC는 램포트 논리 시계(Lamport Logical Clock)와 물리 시계(Physical Clock)를 우아하게 결합합니다:
* 타임스탬프를 **물리 시간 $l$**과 **논리 카운터 $c$**의 순서쌍 $(l, c)$로 관리합니다.
* 노드 간 메시지를 주고받을 때:
  $$l' \leftarrow \max(l_{local}, phys_{local}, l_{msg})$$
  만약 $l'$이 이전 물리 시간과 같다면 논리 카운터를 $c + 1$로 증가시키고, 새로운 물리 시간으로 전진하면 $c \leftarrow 0$으로 리셋합니다.
* **인과율 보존 ($e_1 	o e_2 \implies HLC(e_1) < HLC(e_2)$)**:
  * 서울에서 버지니아로 복제 패킷이 전송된 후($e_1 	o e_2$) 버지니아에서 쓰기가 발생하면, 버지니아의 물리 시계가 아무리 느리더라도 수신된 서울의 HLC를 바탕으로 자신의 HLC를 전진시키므로 **인과적 최신 쓰기가 절대 과거로 역전되지 않습니다!**

---

## 4. 해결책 2: 무충돌 복제 자료형 (CRDT, Conflict-free Replicated Data Types)

타임스탬프 경쟁(LWW) 대신, **어떤 순서로 복제 패킷이 도착하더라도 수학적으로 100% 동일한 상태로 자동 수렴(Eventual Consistency)하는 자료구조**가 바로 Marc Shapiro 교수의 **CRDT(CvRDT, State-based CRDT)**입니다.

### (1) PN-Counter (Positive-Negative Counter)
* **문제점**: 멀티 리전에서 동시에 `views += 1`을 날리면 단순 덮어쓰기로 인해 숫자가 증발함.
* **원리**: 각 리전 $i$별로 증가 벡터 $P[i]$와 감소 벡터 $N[i]$를 독립 배열로 유지.
* **값 계산**: $Total = \sum_i P[i] - \sum_i N[i]$
* **병합 (Merge)**: $P_{merged}[i] = \max(P_A[i], P_B[i])$, $N_{merged}[i] = \max(N_A[i], N_B[i])$
* **결과**: 락(Lock)이나 트랜잭션 없이도 전 세계 모든 리전의 증감이 100% 무손실 합산!

### (2) OR-Set (Observed-Remove Set with Add-Wins)
* **문제점**: 장바구니에서 서울 유저가 '노트북'을 삭제하는 순간, 버지니아 유저가 '노트북'을 다시 추가하면 동시성 충돌 발생.
* **원리**:
  1. 원소를 추가할 때마다 고유한 **태그(UUID)**를 붙여 `AddSet`에 `(Item, Tag)`로 저장.
  2. 원소를 삭제할 때, **해당 시점에 로컬에서 관측된(Observed) 태그들만 `RemSet`에 등록**.
  3. 집합 원소 판정: $	ext{Item} \in 	ext{Set} \iff \exists (Item, Tag) \in AddSet 	ext{ s.t. } Tag 
otin RemSet$
* **Add-Wins 시맨틱스**: 삭제와 동시에 다른 리전에서 새 태그로 추가된 동일 아이템은 삭제 집합에 포함되지 않으므로 **동시 추가가 삭제를 이김(Add-Wins)**!

---

## 5. 분산 동기화 전략 종합 비교표

| 전략 | 시계 의존도 | 충돌 시 데이터 손실 위험 | 구현 난이도 | 적합한 사용 사례 |
|:---|:---:|:---:|:---:|:---|
| **LWW (Last-Write-Wins)** | 매우 높음 (NTP 취약) | ❌ **높음 (시계 드리프트 시 최신 데이터 소각)** | 쉬움 | 센서 데이터, 덮어써도 무방한 캐시 |
| **HLC (Hybrid Logical Clock)** | 낮음 (논리 카운터 보정) | ⚠️ 동시 쓰기는 타이브레이커 | 중간 | 분산 RDBMS (CockroachDB), 트랜잭션 |
| **PN-Counter (CRDT)** | 없음 (시계 불필요) | 🟢 **0% (완벽 무손실 합산)** | 보통 | 좋아요, 조회수, 분산 재고 카운팅 |
| **OR-Set (CRDT)** | 없음 (시계 불필요) | 🟢 **0% (Add-Wins 무손실)** | 중간 | 협업 편집, 태그, 장바구니, 팔로우 목록 |
