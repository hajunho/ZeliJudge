# #151 멀티 리전 액티브-액티브(Multi-Region Active-Active) 복제 충돌과 CRDT vs LWW 시계 왜곡 참사

## 문제 배경 및 장애 상황

글로벌 서비스를 운영 중인 핀테크/이커머스 기업 '글로벌페이'는 전 세계 사용자들에게 50ms 미만의 초저지연 응답을 제공하기 위해 **멀티 리전 액티브-액티브(Multi-Region Multi-Master Active-Active)** 분산 데이터스토어를 구축했습니다.

한국(`SEOUL`), 미국 동부(`IAD`), 유럽(`FRA`) 등 각 대륙에 독립적인 데이터베이스 클러스터를 배치하고, 클라이언트는 가장 가까운 리전으로 즉시 쓰기(Write) 및 읽기(Read)를 수행한 뒤, 각 리전 간의 데이터는 **비동기 교차 복제(Asynchronous Cross-Region Replication)** 를 통해 최종 일관성(Eventual Consistency)을 달성하도록 설계되었습니다.

```
       [Client in Asia]           [Client in US]
              │                          │
              ▼                          ▼
       ┌──────────────┐           ┌──────────────┐
       │ Region SEOUL │           │  Region IAD  │
       │ (Drift: 0ms) │           │(Drift:-500ms)│
       └──────┬───────┘           └───────┬──────┘
              │                          │
              │◄─── Cross-Region Sync ───►│
              │      (Async Latency)     │
              ▼                          ▼
       ┌──────────────┐           ┌──────────────┐
       │  True Last   │    vs     │   Overwrote  │
       │    Write     │           │ with Old Data│
       └──────────────┘           └──────────────┘
```

그러나 블랙 프라이데이 대규모 글로벌 트래픽 이벤트 도중 **치명적인 데이터 유실 및 롤백 참사**가 발생했습니다!

### 장애 1: NTP 시계 왜곡과 단순 LWW(Last-Write-Wins)의 사일런트 덮어쓰기(Lost Update) 참사
미국 `IAD` 리전의 일부 베어메탈 인스턴스에서 NTP(Network Time Protocol) 동기화 데몬이 비정상 지연되면서, 시스템 시계가 실제 우주 물리 시간(True Physical Time)보다 무려 **500ms 느리게(과거 시간으로)** 흐르는 Clock Drift가 발생했습니다.
1. 물리 시간 $t=100\text{ms}$에 `SEOUL` 리전에서 사용자가 프로필 닉네임을 `"Alice_Seoul"`로 변경했습니다. (로컬 Wall Clock 타임스탬프: $100$).
2. 해당 변경 사항이 $t=200\text{ms}$에 `IAD` 리전으로 정상 복제되었습니다.
3. 물리 시간 $t=300\text{ms}$에 `IAD` 리전에서 동일 사용자가 닉네임을 `"Alice_IAD"`로 추가 수정했습니다.
4. 그러나 `IAD` 리전의 시스템 시계는 500ms 느렸기 때문에, 기록된 타임스탬프는 $300 - 500 = -200\text{ms}$였습니다!
5. 양 리전이 데이터를 상호 동기화(Reconcile)할 때, 데이터스토어의 단순 LWW(Last-Write-Wins based on Wall Clock Timestamp) 엔진은 다음과 같이 판정했습니다:
   $$\text{Timestamp}(\text{SEOUL}: 100) > \text{Timestamp}(\text{IAD}: -200)$$
6. 결과적으로 **물리적으로 나중에 발생한 최신 쓰기("Alice_IAD")가 과거의 쓰기("Alice_Seoul")에 의해 강제로 덮어씌워져 영구 유실(Silent Lost Update)** 되었습니다!

### 장애 2: 동시성 카운터와 장바구니 집합 데이터의 소실
- 상품 '좋아요' 수나 재고 카운터를 각 리전에서 단순 숫자로 덮어쓰기(LWW)하자, 각 리전에서 동시에 발생한 수천 건의 증감이 서로 덮어씌워져 숫자가 거꾸로 줄어드는 참사가 일어났습니다.
- 장바구니(Cart) 아이템을 리전 A에서 담고 리전 B에서 삭제하거나 동시에 담을 때, 비동기 전파 순서에 따라 담았던 아이템이 통째로 증발하거나 삭제한 아이템이 유령처럼 부활하는 괴현상이 발생했습니다.

---

## 분산 일관성 구원 아키텍처: HLC와 CRDT

인프라 아키텍처팀은 물리적 시계(Wall Clock)에 의존하는 단순 LWW를 폐기하고, 학계와 글로벌 테크 기업(Google Spanner, Amazon DynamoDB, Riak, Redis Enterprise)에서 검증된 3대 분산 일관성 기술을 도입하기로 결정했습니다:

1. **HLC (Hybrid Logical Clock, Kulkarni et al.)**:
   - 물리적 시계(Physical Clock)의 편리함과 램포트 논리 시계(Logical Clock)의 인과성(Causality) 보장 능력을 결합한 하이브리드 시계.
   - 각 노드는 $(l, c)$ (물리 시간 반영치 $l$, 논리 카운터 $c$)를 유지하며, 메시지를 수신하거나 이벤트를 생성할 때 단조 증가(Monotonic Increase)성을 엄격히 보장하여 시계 왜곡이 있더라도 인과적으로 선행하는 쓰기가 후행 쓰기를 덮어쓰지 못하도록 방어합니다.
2. **PN-Counter (Positive-Negative Counter CRDT)**:
   - 각 리전별 증가 벡터 $P$와 감소 벡터 $N$을 분리하여 관리.
   - 두 리전의 상태를 병합(Merge)할 때 각 성분의 최댓값($\max$)을 취하는 유계 반격자(Join-Semilattice) 구조를 형성하여, 어떤 순서로 복제 패킷이 도착하더라도 결합법칙, 교환법칙, 멱등성에 의해 완벽히 수렴합니다.
3. **OR-Set (Observed-Remove Set with Add-Wins CRDT)**:
   - 원소 추가 시 고유한 태그(UUID/Tag)를 부여하여 $\text{AddSet}$에 저장.
   - 원소 삭제 시 해당 시점까지 해당 리전에서 **관찰된(Observed)** 태그들만 $\text{RemSet}$(Tombstone)에 등록.
   - 병합 시 동시 발생한 추가와 삭제에 대해 "새로 추가된 태그"는 살아남도록 보장하는 **Add-Wins** 의미론을 완벽히 구현합니다.

당신은 멀티 리전 시뮬레이션 엔진을 구현하여, 시스템 시계 왜곡 하에서도 LWW의 치명적 결함(Lost Update)을 정밀 탐지(Audit)하고, HLC와 CRDT(PN-Counter, OR-Set)가 어떻게 완벽한 무손실 최종 일관성(Strong Eventual Consistency)을 달성하는지 증명해야 합니다.

---

## 입력 형식

표준 입력(stdin)으로 여러 줄의 명령어가 주어집니다.

1. **첫 번째 줄**: 클러스터에 참여하는 리전 식별자 목록
   ```text
   REGIONS <region_1> <region_2> ... <region_K>
   ```
2. **이후 줄**: 시뮬레이션 이벤트 명령어가 한 줄에 하나씩 주어지며, `END` 명령어로 종료됩니다.
   - `DRIFT <region> <offset_ms>`:
     - 특정 리전의 Wall Clock 시계 오프셋(드리프트)을 밀리초 단위 정수로 설정합니다.
     - 해당 리전의 물리 시간 $pt$에서의 로컬 Wall Clock 시간은 $pt + offset\_ms$가 됩니다.
   - `WRITE_LWW <pt> <region> <key> <val>`:
     - 물리 시간 $pt$에 `<region>`에서 레지스터 `<key>`에 값 `<val>`을 Naive LWW 방식으로 씁니다.
     - 기록되는 타임스탬프: $wall\_ts = pt + drift[region]$.
     - 기존 값보다 $(wall\_ts, region)$ 튜플이 엄격히 클 경우에만 갱신됩니다.
   - `WRITE_HLC <pt> <region> <key> <val>`:
     - 물리 시간 $pt$에 `<region>`에서 레지스터 `<key>`에 값 `<val>`을 HLC 방식으로 씁니다.
     - 로컬 HLC 클록 갱신:
       $phys = pt + drift[region]$
       $l' = l$
       $l = \max(l', phys)$
       $c = (c + 1) \text{ if } l == l' \text{ else } 0$
     - 레지스터 항목은 $(val, l, c, region)$으로 저장되며, $(l, c, region)$이 사전순으로 엄격히 클 경우에만 갱신됩니다.
   - `PN_INC <region> <counter> <delta>`:
     - `<region>`의 PN-Counter `<counter>`의 $P[region]$을 `<delta>`(양의 정수)만큼 증가시킵니다.
   - `PN_DEC <region> <counter> <delta>`:
     - `<region>`의 PN-Counter `<counter>`의 $N[region]$을 `<delta>`(양의 정수)만큼 증가시킵니다.
   - `ORSET_ADD <region> <set_name> <item> <tag>`:
     - `<region>`의 OR-Set `<set_name>`의 $add\_set$에 $(item, tag)$를 추가합니다.
   - `ORSET_REM <region> <set_name> <item>`:
     - `<region>`의 OR-Set `<set_name>`의 $add\_set$에 현재 존재하는 모든 $(i, t)$ 중 $i == item$인 모든 $t$를 $rem\_set$에 추가합니다.
   - `REPLICATE <pt> <src_region> <dst_region>`:
     - 물리 시간 $pt$에 `<src_region>`의 모든 상태(LWW, HLC, PN-Counter, OR-Set)를 `<dst_region>`으로 단방향 복제 및 병합(Merge)합니다.
     - HLC 클록 동기화:
       $phys_{dst} = pt + drift[dst]$
       $l' = l_{dst}$
       $l_{dst} = \max(l', phys_{dst}, l_{src})$
       if $l_{dst} == l'$ and $l_{dst} == l_{src}$: $c_{dst} = \max(c_{dst}, c_{src}) + 1$
       elif $l_{dst} == l'$: $c_{dst} = c_{dst} + 1$
       elif $l_{dst} == l_{src}$: $c_{dst} = c_{src} + 1$
       else: $c_{dst} = 0$
     - HLC 레지스터 병합: 각 키별 $(l, c, region)$ 튜플 비교.
     - PN-Counter 병합: 모든 리전 $r$에 대해 $dst.P[r] = \max(dst.P[r], src.P[r])$, $dst.N[r] = \max(dst.N[r], src.N[r])$.
     - OR-Set 병합: $dst.add\_set \cup= src.add\_set$, $dst.rem\_set \cup= src.rem\_set$.
   - `REPLICATE_ALL <pt>`:
     - 모든 리전 쌍 간 양방향 전체 복제를 2회 라운드로 수행하여 클러스터 전체를 완전 수렴(Full Sync)시킵니다.
   - `QUERY <region>`:
     - 해당 `<region>`의 현재 4대 데이터 구조 상태를 포맷에 맞추어 출력합니다.
   - `AUDIT`:
     - 전체 리전의 수렴 상태 및 물리 시간 기준 True Last Write와 LWW 간의 불일치(Lost Update)를 감사하여 출력합니다.
   - `END`: 시뮬레이션 종료.

---

## 출력 형식

### 1. `QUERY <region>` 출력 형식
```text
REGION: <region>
  LWW: <key1>=<val1>, <key2>=<val2> (키 알파벳순 정렬, 비어있으면 EMPTY)
  HLC: <key1>=<val1>, <key2>=<val2> (키 알파벳순 정렬, 비어있으면 EMPTY)
  PN_COUNTER: <c1>=<val1>, <c2>=<val2> (카운터명 알파벳순 정렬, 비어있으면 EMPTY, 값은 sum(P)-sum(N))
  OR_SET: <s1>=[<item1>,<item2>], <s2>=[...] (세트명 알파벳순, 원소 알파벳순 정렬, 비어있으면 EMPTY)
```

### 2. `AUDIT` 출력 형식
```text
=== AUDIT SUMMARY ===
LWW_STATUS: <CONVERGED|DIVERGED>
  [ANOMALY] LOST_UPDATE on key '<key>': expected '<true_val>' (written at t=<true_pt> by <true_reg>) but got '<val>'
  (또는 이상 현상이 없으면 "  [LWW_ANOMALIES] NONE")
HLC_STATUS: <CONVERGED|DIVERGED>
PN_STATUS: <CONVERGED|DIVERGED>
ORSET_STATUS: <CONVERGED|DIVERGED>
```
- `LWW_STATUS`: 모든 리전의 LWW 키-값 사전이 완전히 일치하면 `CONVERGED`, 하나라도 다르면 `DIVERGED`.
- `[ANOMALY]`: 물리 시간 $pt$ 기준 가장 마지막에 기록된 쓰기(True Last Write)와 첫 번째 리전의 LWW 값을 비교하여, 불일치하는 키마다 알파벳순으로 출력.
- `HLC_STATUS`, `PN_STATUS`, `ORSET_STATUS`: 각 자료구조의 유효 값이 모든 리전에서 동일하면 `CONVERGED`, 아니면 `DIVERGED`.

---

## 입출력 예시

### 예제 입력 1
```text
REGIONS SEOUL IAD FRA
DRIFT IAD -500
WRITE_LWW 100 SEOUL nickname Alice_Seoul
WRITE_HLC 100 SEOUL nickname Alice_Seoul
REPLICATE 200 SEOUL IAD
WRITE_LWW 300 IAD nickname Alice_IAD
WRITE_HLC 300 IAD nickname Alice_IAD
PN_INC SEOUL likes 10
PN_INC FRA likes 5
PN_DEC IAD likes 2
ORSET_ADD SEOUL cart itemA tag1
ORSET_ADD IAD cart itemB tag2
REPLICATE_ALL 400
QUERY SEOUL
AUDIT
END
```

### 예제 출력 1
```text
REGION: SEOUL
  LWW: nickname=Alice_Seoul
  HLC: nickname=Alice_IAD
  PN_COUNTER: likes=13
  OR_SET: cart=[itemA,itemB]
=== AUDIT SUMMARY ===
LWW_STATUS: CONVERGED
  [ANOMALY] LOST_UPDATE on key 'nickname': expected 'Alice_IAD' (written at t=300 by IAD) but got 'Alice_Seoul'
HLC_STATUS: CONVERGED
PN_STATUS: CONVERGED
ORSET_STATUS: CONVERGED
```

### 예제 1 상세 해설
1. $t=100$에 `SEOUL`(드리프트 0)에서 `nickname=Alice_Seoul` 쓰기 수행 $\to$ Wall Clock $100$, HLC $(100, 0, \text{SEOUL})$.
2. $t=200$에 `SEOUL`의 데이터와 HLC 시계가 `IAD`로 복제됨 $\to$ `IAD`의 HLC 시계가 $100$으로 전진.
3. $t=300$에 `IAD`(드리프트 -500)에서 `nickname=Alice_IAD` 쓰기 수행:
   - **LWW**: Wall Clock = $300 - 500 = -200$.
   - **HLC**: 로컬 물리 시간 $-200$보다 이전 복제로 인입된 논리 시간 $100$이 더 크므로 $l=100$ 유지, 카운터 $c$가 $0 \to 1$로 증가하여 $(100, 1, \text{IAD})$ 할당!
4. 전체 복제(`REPLICATE_ALL`) 후:
   - LWW는 Wall Clock 타임스탬프 $100 > -200$이므로 오래된 과거 값인 `Alice_Seoul`로 수렴 $\to$ **LOST_UPDATE 장애 발생!**
   - HLC는 논리 타임스탬프 $(100, 1, \text{IAD}) > (100, 0, \text{SEOUL})$이므로 최신 쓰기인 `Alice_IAD`로 정확히 수렴!
   - PN-Counter는 $10 + 5 - 2 = 13$으로 완벽 수렴.
   - OR-Set은 각 리전에서 추가된 `itemA`와 `itemB`가 모두 보존되어 `[itemA,itemB]`로 완전 수렴.
