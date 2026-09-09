# #151 최신 데이터를 덮어썼는데 왜 옛날 데이터로 되돌아가요?!: 멀티 리전 액티브-액티브(Active-Active) 분산 데이터베이스의 충돌 해결: LWW 시계 드리프트(Clock Drift) 데이터 증발 참사 vs HLC vs CRDT (Multi-Region Active-Active CRDT vs LWW Clock Drift)

## 1. 실무 장애 시나리오: "버지니아에서 방금 바꾼 닉네임이 서울 서버 구버전으로 덮어씌워졌어요?!"

글로벌 SaaS 플랫폼 '젤리글로벌'은 전 세계 사용자들에게 지연 시간 없는 쾌적한 서비스를 제공하기 위해, 서울(`SEOUL`), 미국 버지니아(`IAD`), 독일 프랑크푸르트(`FRA`) 등 주요 대륙에 데이터베이스를 구축하고 모든 리전에서 읽기/쓰기를 동시에 처리하는 **멀티 리전 액티브-액티브(Multi-Region Active-Active)** 분산 클러스터를 운영하고 있습니다.

개발팀은 여러 리전에서 동시에 동일한 데이터를 수정할 때 발생하는 충돌(Conflict)을 해결하기 위해, 가장 대중적인 **LWW(Last-Write-Wins, 타임스탬프가 큰 마지막 쓰기 승리)** 규칙을 적용했습니다.

그런데 어느 날 새벽, 글로벌 VIP 고객인 앨리스의 계정 정보에서 황당한 버그가 발생했습니다:
1. 앨리스가 미국 버지니아 리전(`IAD`)에 접속하여 **오후 12:00:00.300 (물리 시간 $t=300$)**에 자신의 닉네임을 `'Alice_IAD'`로 변경했습니다.
2. 앞서 **오후 12:00:00.100 (물리 시간 $t=100$)**에 서울 리전(`SEOUL`)에서 쓰여진 이전 닉네임은 `'Alice_Seoul'`이었습니다.
3. 분명히 앨리스는 200ms 뒤에 최신 닉네임으로 저장했는데, 두 리전 간 데이터 동기화(Replication)가 완료되자마자 **버지니아와 서울 리전 모두에서 최신 닉네임 `'Alice_IAD'`가 영구히 증발하고 옛날 닉네임 `'Alice_Seoul'`로 덮어씌워져(Lost Update)** 있었습니다!

사용자가 분명 방금 저장한 최신 데이터가 어떻게 200ms 전의 과거 데이터에 의해 삭제된 것일까요?

긴급 점검을 진행한 분산 시스템 엔지니어 호준이가 버지니아 서버의 NTP(Network Time Protocol) 상태를 확인하고 경악했습니다:

> "여러분! 버지니아 데이터센터 서버의 하드웨어 클록이 오작동하여 실제 시계보다 **무려 500ms 느리게(Clock Drift = -500ms)** 가고 있었습니다!  
> 물리 시간 $t=300$에 쓰여졌지만, 버지니아 서버가 찍은 로컬 물리 타임스탬프는 $300 - 500 = -200	ext{ms}$였습니다!  
> 반면 서울 서버의 시계는 정상이어서 $t=100$에 쓰여진 데이터의 타임스탬프는 $100	ext{ms}$였습니다.  
> 두 데이터가 동기화될 때 LWW 엔진은 단순 타임스탬프를 비교하여 $100 > -200$ 이므로, **물리적으로 200ms 늦게 일어난 진짜 최신 쓰기를 과거 데이터로 착각하고 쓰레기통에 버린 겁니다!**"

팀원들이 경악하며 물었습니다:  
"그럼 서버 시계를 100% 믿을 수 없다면 멀티 리전 충돌은 어떻게 해결해야 하죠?!"

> "2가지 현대적 분산 아키텍처 해법을 도입해야 합니다!  
> 첫째, 레지스터 쓰기에는 물리 시간과 논리 카운터를 결합하여 인과율을 절대 보존하는 **HLC(Hybrid Logical Clock)**를 적용해야 합니다!  
> 둘째, 좋아요 수나 장바구니 같은 협업 데이터에는 시계 자체에 의존하지 않고 수학적으로 100% 무충돌 자동 수렴하는 **CRDT (PN-Counter & OR-Set with Add-Wins)** 자료구조를 적용해야 합니다!"

---

## 2. 핵심 이론: LWW 시계 왜곡과 현대 분산 동기화 기술

### (1) LWW (Last-Write-Wins)의 시계 드리프트(Clock Drift) 참사
* 분산 환경의 물리 시계는 NTP 동기화를 거쳐도 항상 수 밀리초~수백 밀리초의 오차가 존재합니다.
* 시계가 느리게 가는 리전에서 발생한 최신 쓰기는 타임스탬프가 낮게 기록되어, 타 리전의 구버전 데이터와 머지될 때 **영구 소각(Lost Update)**됩니다.

### (2) HLC (Hybrid Logical Clock, Kulkarni 2014)
* 물리 시간($l$)과 논리 카운터($c$)의 튜플 $(l, c)$을 사용합니다.
* 타 리전으로부터 복제 패킷 수신 시 $l' \leftarrow \max(l_{local}, phys_{local}, l_{msg})$로 시간을 전진시키고, 물리 시간이 정체되면 논리 카운터 $c$를 증가시킵니다.
* **인과율($e_1 	o e_2 \implies HLC(e_1) < HLC(e_2)$)**을 완벽히 보장하여 시계가 느린 노드라도 인과적으로 뒤에 일어난 쓰기가 과거로 역전되지 않습니다.

### (3) CRDT (Conflict-free Replicated Data Types, Shapiro 2011)
* **PN-Counter (Positive-Negative Counter)**:
  * 각 리전별 증가량 벡터($P$)와 감소량 벡터($N$)를 독립 관리: $Total = \sum P_i - \sum N_i$.
  * 병합 시 각 원소별 $\max(P_i), \max(N_i)$를 취하므로 동시 증감이 100% 무손실 보존됩니다.
* **OR-Set (Observed-Remove Set with Add-Wins)**:
  * 원소 추가 시 고유한 태그(UUID)를 부여하고, 삭제 시 해당 시점까지 로컬에서 관측된(Observed) 태그만 삭제 집합에 기록합니다.
  * 동시 추가와 삭제가 경합할 때 새 태그를 가진 추가가 삭제를 이기는 **Add-Wins** 시맨틱스를 수학적으로 보장합니다.

---

## 3. 입출력 규격 및 요구사항

멀티 리전 환경에서 시계 드리프트(`DRIFT`), LWW 레지스터 쓰기, HLC 레지스터 쓰기, PN-Counter 증감, OR-Set 추가/삭제, 리전 간 복제(`REPLICATE`, `REPLICATE_ALL`), 조회(`QUERY`), 감사(`AUDIT`) 명령어가 주어질 때 분산 동기화 시뮬레이터를 구현하세요.

### 입력 명령 DSL 명세 (표준 입력)
* `REGIONS <r1> <r2> ...`: 클러스터에 참여하는 리전 목록 선언
* `DRIFT <region> <drift_ms>`: 해당 리전의 물리 시계 오차 설정 (양수/음수)
* `WRITE_LWW <pt> <region> <key> <val>`: 절대 물리 시간 `pt`에 해당 리전의 LWW 레지스터에 쓰기
* `WRITE_HLC <pt> <region> <key> <val>`: 절대 물리 시간 `pt`에 해당 리전의 HLC 레지스터에 쓰기
* `PN_INC <region> <counter> <delta>`: PN-Counter 증가
* `PN_DEC <region> <counter> <delta>`: PN-Counter 감소
* `ORSET_ADD <region> <set_name> <item> <tag>`: OR-Set에 아이템 및 고유 태그 추가
* `ORSET_REM <region> <set_name> <item>`: OR-Set에서 관측된 모든 태그 삭제
* `REPLICATE <pt> <src> <dst>`: `src` 리전의 모든 상태(LWW, HLC, PN, OR-Set)를 `dst` 리전으로 단방향 머지
* `REPLICATE_ALL <pt>`: 전 리전 간 양방향 완전 동기화 (Gossip Flood)
* `QUERY <region>`: 해당 리전의 상태 출력
* `AUDIT`: 전 리전의 데이터 수렴 여부 및 LWW 갱신 분실(LOST_UPDATE) 이상 징후 분석 출력
* `END`: 시뮬레이션 종료

---

## 4. 입출력 예시

### 예시 1: 버지니아(-500ms 드리프트) 환경에서 LWW 갱신 분실 참사와 HLC/CRDT 구원

#### 입력
```
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

#### 출력
```
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
