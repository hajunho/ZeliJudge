# #050 서버가 죽었는데 왜 트래픽이 죽은 서버로 계속 가요?!: DNS 캐싱(TTL)의 덫 vs BGP Anycast / Floating VIP 페일오버

---

## 1. 현실 세계 비유: 이사 간 식당과 옛날 전단지 vs 114 대표번호 자동 착신전환

당신이 단골로 가던 맛집이 불의의 화재로 인해 맞은편 신축 건물로 급히 이사를 가야 하는 상황을 상상해 보세요.

```text
❌ 초보자의 DNS 기반 페일오버 (옛날 전단지를 보고 찾아가는 손님들):
   식당 주인은 이전 공지를 올리고 구청 전산망(권한 DNS)의 주소를 변경했습니다.
   하지만 손님들 주머니 속에는 60분 유효기간이 적힌 "옛날 전단지(DNS TTL 캐시)"가 들어있습니다.
   손님들은 구청에 다시 물어보지 않고, 옛날 전단지에 적힌 불탄 건물(죽은 PRIMARY 서버)로 계속 찾아가
   닫힌 셔터문을 쾅쾅 두드리며 욕을 합니다 ("Connection Refused! 500 에러 폭풍!").
   심지어 어떤 손님(Java JVM 기본 캐시: networkaddress.cache.ttl = -1)은
   전단지를 평생 간직하는 성격이라, 식당이 망한 줄도 모르고 평생 불탄 건물로만 찾아갑니다!

✅ BGP Anycast / Floating VIP 페일오버 (114 대표번호 자동 착신전환):
   손님들은 식당의 실제 물리 주소(192.168.1.x)를 전혀 모릅니다. 단지 "114 대표번호(10.0.0.1 VIP)" 하나만 압니다.
   1번 조리대(PRIMARY)에 불이 나면, 통신사 교환기(L4 로드밸런서/BGP 라우터)가 헬스체크 직후
   0.1초 만에 전화를 2번 예비 조리대(BACKUP)로 자동 착신전환합니다!
   손님들은 전화번호를 바꿀 필요도, 캐시를 지울 필요도 없이 즉각 따뜻한 음식을 받습니다.
```

수많은 주니어 엔지니어와 AI 바이브 코더들이 서비스 고가용성(HA, High Availability)을 구축할 때  
"서버 2대 띄워놓고, 1번 죽으면 AWS Route53이나 Cloudflare DNS 레코드만 2번으로 바꾸면 되겠지?"라며  
순진하게 **DNS 기반 페일오버**를 도입했다가 서비스 오픈 날 처참한 대형 장애를 겪습니다.

- 전 세계 로컬 ISP DNS, 브라우저, 사내 프록시, 모바일 OS가 DNS 레코드를 제멋대로 캐싱합니다.
- 특히 **Java/JVM 환경에서는 기본 설정으로 DNS 조회 결과를 영구(Forever) 캐싱**하여,  
  클라이언트 애플리케이션 팟(Pod)을 전부 재시작하지 않는 한 영원히 죽은 서버로 트래픽을 쏟아붓는  
  **"좀비 트래픽(Zombie Traffic)"** 재앙이 발생합니다!

---

## 2. 문제 개요

당신은 초대형 글로벌 핀테크 결제 게이트웨이의 인프라 아키텍트입니다.  
결제 서버 장애 시 결제 유실을 0건으로 만들기 위해,  
기존의 **DNS 레코드 변경 페일오버 모델(NAIVE_DNS)**과  
L4 고가용성 가상 IP 기반 **Anycast / Floating VIP 페일오버 모델(ANYCAST_VIP)**을 시뮬레이션하고,  
클라이언트 캐시 만료 지연에 따른 실패율과 Anycast VIP의 신뢰성 우위(`ANYCAST_RELIABILITY_ADVANTAGE`)를 정밀 검증하세요.

### 시뮬레이션 상세 규칙

#### 1. 인프라 구성
- **백엔드 물리 서버 2대**:
  - `PRIMARY`: IP `192.168.1.10` (초기 상태: `UP`)
  - `BACKUP`: IP `192.168.1.20` (초기 상태: `UP`)
- **ANYCAST VIP**:
  - 가상 IP `10.0.0.1`
- **타이밍 및 캐시 설정**:
  - `DNS_TTL_SEC <ttl>`: DNS 레코드의 유효 시간 (초, $1 \le ttl \le 3,600$).
  - `HEALTH_CHECK_INTERVAL_SEC <interval>`: 헬스체커 감지 주기 (초, $1 \le interval \le 60$).
  - `CLIENT_CACHE_MODE <STANDARD | JVM_FOREVER>`:
    - `STANDARD`: 클라이언트는 DNS 질의 시점 $t$로부터 $t + DNS\_TTL\_SEC$ 동안 IP를 캐시.
    - `JVM_FOREVER`: Java JVM의 기본값처럼, 한번 캐시한 IP를 프로세스 종료까지 **영구(Forever)** 보관.

#### 2. 서버 장애 및 헬스체크 감지 메커니즘
- `SERVER_STATUS <server: PRIMARY|BACKUP> <status: UP|DOWN> <t>`:
  - 시점 $t$에 실제 서버의 물리적 상태(`actual_status`)가 즉시 변경됩니다.
  - 헬스체커는 장애/복구를 감지하는 데 `HEALTH_CHECK_INTERVAL_SEC`의 지연이 소요됩니다.
  - 따라서 권한 DNS 서버와 Anycast L4 라우터는 $t_{detect} = t + HEALTH\_CHECK\_INTERVAL\_SEC$ 시점에 비로소 상태 변화를 감지(`detected_status`)합니다.

#### 3. 권한 DNS 서버 (Authoritative DNS) 동작
- 클라이언트가 DNS를 질의하는 시점 $t$에 권한 DNS가 인지하고 있는 상태(`detected_status`)에 따라 IP를 응답합니다:
  - `PRIMARY`가 `UP`이면 $\to$ `192.168.1.10` 반환.
  - `PRIMARY`가 `DOWN`이고 `BACKUP`이 `UP`이면 $\to$ `192.168.1.20` 반환.
  - 둘 다 `DOWN`이면 $\to$ 기본값 `192.168.1.10` 반환.

#### 4. 모델 A: DNS 기반 페일오버 (NAIVE_DNS)
클라이언트는 목적지 도메인을 IP로 변환한 뒤 해당 물리 IP로 직접 TCP 연결을 맺습니다:
- 클라이언트가 시점 $t$에 요청을 보낼 때:
  1. 로컬 DNS 캐시를 확인합니다.
  2. 캐시가 없거나, 캐시 만료 시각에 도달했거나 지났다면($t \ge expires\_at$):
     - 권한 DNS 서버에 질의하여 현재 권한 IP를 받아 캐시합니다.
     - `STANDARD` 모드: $expires\_at = t + DNS\_TTL\_SEC$.
     - `JVM_FOREVER` 모드: $expires\_at = \infty$ (영구 불변).
  3. 캐시된 IP의 실제 서버(`actual_status`) 상태를 확인합니다:
     - 해당 서버의 실제 상태가 `UP`이면 $\to$ `SUCCESS`.
     - 해당 서버의 실제 상태가 `DOWN`이면 $\to$ `FAIL` (Connection Refused 발생).

#### 5. 모델 B: Anycast / Floating VIP 페일오버 (ANYCAST_VIP)
클라이언트는 DNS 캐시와 무관하게 언제나 불변의 대표 가상 IP `10.0.0.1`로 패킷을 전송합니다:
- L4 Anycast 라우터는 감지된 상태(`detected_status`)에 따라 즉시 패킷의 백엔드 포워딩 경로를 결정합니다:
  - `PRIMARY`가 `UP`이면 $\to$ `PRIMARY`로 라우팅.
  - `PRIMARY`가 `DOWN`이고 `BACKUP`이 `UP`이면 $\to$ `BACKUP`으로 즉시 스위칭.
  - 둘 다 `DOWN`이면 $\to$ 기본값 `PRIMARY`로 라우팅.
- 포워딩된 백엔드 서버의 실제 상태(`actual_status`)를 확인합니다:
  - 해당 서버의 실제 상태가 `UP`이면 $\to$ `SUCCESS`.
  - 해당 서버의 실제 상태가 `DOWN`이면 $\to$ `FAIL`.

---

## 3. 입력 형식

```text
DNS_TTL_SEC <ttl_sec>
HEALTH_CHECK_INTERVAL_SEC <interval_sec>
CLIENT_CACHE_MODE <STANDARD | JVM_FOREVER>
EVENTS <E>
... (총 E개의 이벤트 줄)
```

이벤트 줄의 종류:
1. `SERVER_STATUS <PRIMARY | BACKUP> <UP | DOWN> <timestamp>`
2. `REQ <client_id> <timestamp>`

- 모든 `timestamp`는 초 단위 정수입니다 ($1 \le timestamp \le 1,000,000$).
- 동일한 `timestamp`에 여러 이벤트가 발생할 경우, 다음 순서로 처리됩니다:
  1. 실제 하드웨어 상태 변경 (`SERVER_STATUS` at $t$)
  2. 헬스체커의 감지 완료 반영 ($t_{detect} = t_{event} + interval$)
  3. 클라이언트의 요청 인입 (`REQ` at $t$)

---

## 4. 출력 형식

각 `REQ` 이벤트마다 한 줄씩 처리 결과를 출력합니다:
```text
REQ <client_id> AT:<t> NAIVE:RESOLVED=<ip>,RESULT=<SUCCESS|FAIL> ANYCAST:ROUTED=<PRIMARY|BACKUP>,RESULT=<SUCCESS|FAIL>
```

모든 이벤트 종료 후 최종 종합 통계를 출력합니다:
```text
SUMMARY TOTAL_REQS:<total> NAIVE_FAILURES:<n_fails> ANYCAST_FAILURES:<a_fails> FAILURES_SAVED:<saved> ANYCAST_RELIABILITY_ADVANTAGE:<rate>%
```

- `FAILURES_SAVED = NAIVE_FAILURES - ANYCAST_FAILURES`
- `ANYCAST_RELIABILITY_ADVANTAGE`:
  - `NAIVE_FAILURES > 0`일 때: `(FAILURES_SAVED / NAIVE_FAILURES) * 100.0` (소수점 둘째 자리까지 출력, 예: `83.33%`, `100.00%`).
  - `NAIVE_FAILURES == 0`일 때: `0.00%`.

---

## 5. 입출력 예시

### 예시 1 (STANDARD 모드: TTL 캐시 만료 지연 실패 vs Anycast 즉각 복구)

#### 입력
```text
DNS_TTL_SEC 10
HEALTH_CHECK_INTERVAL_SEC 3
CLIENT_CACHE_MODE STANDARD
EVENTS 8
REQ C1 5
SERVER_STATUS PRIMARY DOWN 10
REQ C1 11
REQ C1 12
REQ C1 14
REQ C2 14
REQ C1 16
REQ C2 26
```

#### 출력
```text
REQ C1 AT:5 NAIVE:RESOLVED=192.168.1.10,RESULT=SUCCESS ANYCAST:ROUTED=PRIMARY,RESULT=SUCCESS
REQ C1 AT:11 NAIVE:RESOLVED=192.168.1.10,RESULT=FAIL ANYCAST:ROUTED=PRIMARY,RESULT=FAIL
REQ C1 AT:12 NAIVE:RESOLVED=192.168.1.10,RESULT=FAIL ANYCAST:ROUTED=PRIMARY,RESULT=FAIL
REQ C1 AT:14 NAIVE:RESOLVED=192.168.1.10,RESULT=FAIL ANYCAST:ROUTED=BACKUP,RESULT=SUCCESS
REQ C2 AT:14 NAIVE:RESOLVED=192.168.1.20,RESULT=SUCCESS ANYCAST:ROUTED=BACKUP,RESULT=SUCCESS
REQ C1 AT:16 NAIVE:RESOLVED=192.168.1.20,RESULT=SUCCESS ANYCAST:ROUTED=BACKUP,RESULT=SUCCESS
REQ C2 AT:26 NAIVE:RESOLVED=192.168.1.20,RESULT=SUCCESS ANYCAST:ROUTED=BACKUP,RESULT=SUCCESS
SUMMARY TOTAL_REQS:7 NAIVE_FAILURES:3 ANYCAST_FAILURES:2 FAILURES_SAVED:1 ANYCAST_RELIABILITY_ADVANTAGE:33.33%
```

#### 해설
- $t=5$: C1이 DNS 질의를 통해 `192.168.1.10`을 캐시 ($expires\_at = 5 + 10 = 15$).
- $t=10$: PRIMARY가 DOWN됨. 헬스체커 감지 시점은 $10 + 3 = 13$초.
- $t=11, 12$: 헬스체커 감지 전이므로 권한 DNS와 Anycast 라우터 모두 장애를 모름. 둘 다 PRIMARY로 향하여 `FAIL` (불가피한 헬스체크 윈도우 실패).
- $t=14$: 헬스체커가 감지 완료($t \ge 13$)!
  - **NAIVE DNS**: C1의 캐시 만료 시각은 15초이므로 재질의 없이 죽은 `192.168.1.10`으로 접속 $\to$ **`FAIL` (TTL 캐시의 덫)**!
  - **ANYCAST**: 라우터가 즉각 BACKUP으로 스위칭 $\to$ **`SUCCESS`**!
  - 신규 클라이언트 C2는 캐시가 없으므로 DNS 질의 시 새로 업데이트된 `192.168.1.20`을 받아 `SUCCESS`.
- $t=16$: C1의 캐시 만료($15 < 16$)로 인해 DNS 재질의 후 `192.168.1.20`을 받아 비로소 복구됨.
- Anycast VIP는 DNS 캐시 지연 구간에서 발생할 뻔한 장애를 완벽히 방어했습니다.
