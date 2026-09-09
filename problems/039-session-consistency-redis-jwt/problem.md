# Problem #039: 서버 3대로 늘렸더니 로그인 세션이 자꾸 풀려요?!: Sticky Session vs Redis 분산 세션 vs JWT

## 📖 실무 스토리: 서버를 3대로 늘렸더니 유저들이 계속 로그인 창으로 튕겨납니다!

스타트업 백엔드 개발자 나코딩은 서비스 트래픽이 폭증하자 단일 웹 서버의 CPU가 90%를 넘나드는 것을 보고, AWS에 로드밸런서(ALB)를 붙이고 웹 서버를 **1대에서 3대로 스케일아웃(Scale-out)**했습니다.

```text
               +-----> [Web Server 1] (In-Memory Session)
               |
[Client] ---> [ALB] -> [Web Server 2] (In-Memory Session)
(Round-Robin)  |
               +-----> [Web Server 3] (In-Memory Session)
```

> **나코딩**: "이제 서버가 3대니까 트래픽이 3분의 1로 나뉘겠지! 성능 문제 끝!"

하지만 배포 직후, **전사 메신저에 비상벨이 울렸습니다!**

1. **"로그인했는데 다음 페이지 클릭하니까 '로그인이 필요합니다'라며 튕겨요!"**
   * 유저가 `Server 1`에 로그인 요청을 보내 세션 쿠키(`JSESSIONID`)를 발급받았습니다.
   * `Server 1`의 메모리 힙(Heap)에 유저 세션이 생성되었습니다.
   * 그 다음, 유저가 마이페이지를 클릭하자 로드밸런서(ALB)는 라운드로빈 규칙에 따라 요청을 **`Server 2`**로 보냈습니다.
   * `Server 2`는 자기 메모리에 해당 세션 ID가 전혀 없으므로 **"당신 누구세요? 미인증 요청입니다"**라며 로그인 화면으로 쫓아내 버렸습니다!
2. **"서버 하나가 재부팅되었더니 접속 중이던 1만 명이 전부 로그아웃되었습니다!"**
   * 배포나 장애로 `Server 1`이 크래시되자, `Server 1`의 램(RAM)에 들어있던 세션이 전부 소실되었습니다.

> **"서버가 1대일 때는 아무 문제 없던 인메모리 세션이, 서버를 3대로 늘리는 순간 재앙이 되었습니다!"**

웹 서버를 진정한 **무상태(Stateless)**로 만들어 자유롭게 늘리고 줄이려면(Auto-scaling), 세션을 어떻게 관리해야 할까요?
* 로드밸런서가 항상 같은 서버로 보내주는 **Sticky Session**?
* 모든 서버가 공유하는 **Redis 중앙 분산 세션**?
* 아니면 아예 서버에 아무것도 저장하지 않는 **JWT 무상태 토큰**?

여러분의 임무는 3가지 세션 아키텍처(LOCAL_MEMORY, STICKY_SESSION, REDIS_SESSION)를 시뮬레이션하고, 라운드로빈 분산과 서버 크래시 장애 앞에서의 생존율과 안정성을 정밀 계측하는 세션 라우팅 엔진을 구현하는 것입니다!

---

## 🎯 문제 요구사항

클라이언트의 로그인, 요청, 로그아웃, 그리고 서버의 장애/복구 이벤트를 시간 순서대로 처리하며 3가지 세션 관리 모델의 인증 상태를 평가하십시오:

### 1. 3대 세션 아키텍처 동작 규칙

1. **모델 1: LOCAL_MEMORY (단순 인메모리 세션 - 초보의 함정)**
   * 세션은 로그인이 발생한 해당 서버의 로컬 메모리에만 저장됩니다.
   * 요청이 도착한 서버(`routed_server`)가 살아있고, 그 서버의 로컬 메모리에 세션이 존재할 때만 인증 성공(`AUTH_OK`).
   * 다른 서버로 라우팅되거나 해당 서버가 다운되면 즉시 세션 풀림(`SESSION_LOST`).

2. **모델 2: STICKY_SESSION (로드밸런서 세션 고정)**
   * 유저가 로그인한 첫 서버(`assigned_server`)를 해당 유저의 '고정 서버(Sticky Target)'로 지정합니다.
   * 요청 발생 시, 해당 고정 서버가 **살아있다면(`alive`) 로드밸런서는 지정된 서버로 고정 라우팅**합니다.
   * 하지만 고정 서버가 다운(`CRASH`)된 경우, 요청은 어쩔 수 없이 다른 살아있는 서버로 우회되지만, 그 서버에는 세션이 없으므로 세션 풀림(`SESSION_LOST`)이 발생합니다.

3. **모델 3: REDIS_SESSION (중앙 분산 세션 스토리지 - Golden Standard)**
   * 모든 세션은 웹 서버 메모리가 아니라 중앙 Redis 저장소에 저장됩니다.
   * 어느 웹 서버로 요청이 가든, 심지어 특정 웹 서버가 죽고 다른 서버로 요청이 가더라도, 요청을 받은 서버가 살아있고 중앙 Redis에 유저 세션이 살아있다면 **100% 완벽하게 인증 성공(`AUTH_OK`)**합니다!

### 2. 이벤트 처리 규칙
* `LOGIN <timestamp> <user_id> <assigned_server>`:
  * 유저가 로그인합니다. 각 모델별 저장소에 세션이 생성됩니다.
* `REQUEST <timestamp> <user_id> <routed_server>`:
  * 유저가 요청을 보냅니다. 로드밸런서가 1차적으로 배정한 서버는 `routed_server`입니다.
  * 3개 모델별로 `AUTH_OK` 또는 `SESSION_LOST`를 판정합니다.
* `CRASH <timestamp> <server_id>`:
  * 특정 서버가 다운됩니다.
  * 해당 서버의 로컬 메모리에 있던 모든 세션은 즉시 영구 증발합니다. (중앙 Redis는 영향 없음)
* `RECOVER <timestamp> <server_id>`:
  * 다운되었던 서버가 재부팅되어 정상 복구됩니다.
  * 재부팅된 서버의 로컬 메모리는 깨끗하게 비어있는 상태로 시작합니다.
* `LOGOUT <timestamp> <user_id>`:
  * 유저가 명시적으로 로그아웃합니다. 모든 모델에서 해당 유저의 세션이 만료/삭제됩니다.

---

## 📥 입력 형식 (Input Format)

```text
EVENTS <N>
<event_type_1> <args...>
<event_type_2> <args...>
...
```

* 첫 번째 줄: `EVENTS` 키워드 뒤에 총 이벤트 개수 $N$ ($1 \le N \le 40,000$)이 주어집니다.
* 두 번째 줄부터 $N$개의 줄에 걸쳐 각 이벤트가 주어집니다:
  * `LOGIN <timestamp> <user_id> <assigned_server>`
  * `REQUEST <timestamp> <user_id> <routed_server>`
  * `CRASH <timestamp> <server_id>`
  * `RECOVER <timestamp> <server_id>`
  * `LOGOUT <timestamp> <user_id>`

---

## 📤 출력 형식 (Output Format)

각 `REQUEST` 이벤트마다 다음 형식으로 1줄씩 출력합니다:
```text
REQ <timestamp> USER:<user_id> LOCAL:<local_status> STICKY:<sticky_status> REDIS:<redis_status>
```
* 상태값: `AUTH_OK` 또는 `SESSION_LOST`

모든 이벤트 처리 후 마지막 줄에 종합 통계(Summary)를 1줄 출력합니다:
```text
SUMMARY TOTAL_REQUESTS:<total> LOCAL_AUTH_OK:<loc_ok> STICKY_AUTH_OK:<stk_ok> REDIS_AUTH_OK:<red_ok> REDIS_SESSIONS_SAVED:<saved>
```
* `LOCAL_AUTH_OK`: LOCAL_MEMORY 모델에서 인증 성공한 횟수
* `STICKY_AUTH_OK`: STICKY_SESSION 모델에서 인증 성공한 횟수
* `REDIS_AUTH_OK`: REDIS_SESSION 모델에서 인증 성공한 횟수
* `REDIS_SESSIONS_SAVED`: `REDIS_AUTH_OK - LOCAL_AUTH_OK` (중앙 분산 세션을 통해 라운드로빈 및 서버 장애로 인한 세션 풀림을 방어한 총 횟수)

---

## 💡 입출력 예제 (Sample I/O)

### 예제 입력
```text
EVENTS 7
LOGIN 100 user1 server1
REQUEST 110 user1 server2
REQUEST 120 user1 server1
CRASH 150 server1
REQUEST 160 user1 server2
RECOVER 180 server1
REQUEST 190 user1 server1
```

### 예제 출력
```text
REQ 110 USER:user1 LOCAL:SESSION_LOST STICKY:AUTH_OK REDIS:AUTH_OK
REQ 120 USER:user1 LOCAL:AUTH_OK STICKY:AUTH_OK REDIS:AUTH_OK
REQ 160 USER:user1 LOCAL:SESSION_LOST STICKY:SESSION_LOST REDIS:AUTH_OK
REQ 190 USER:user1 LOCAL:SESSION_LOST STICKY:SESSION_LOST REDIS:AUTH_OK
SUMMARY TOTAL_REQUESTS:4 LOCAL_AUTH_OK:1 STICKY_AUTH_OK:2 REDIS_AUTH_OK:4 REDIS_SESSIONS_SAVED:3
```

---

## 힌트 & 핵심 점검 사항
1. **$t=110$ (라운드로빈 분산)**: `user1`은 `server1`에 로그인했는데 요청이 `server2`로 갔습니다. LOCAL은 세션이 없어 `SESSION_LOST`로 튕기지만, STICKY(고정 라우팅)와 REDIS(중앙 조회)는 정상 인증됩니다.
2. **$t=160$ (서버 장애)**: `server1`이 다운되었습니다! STICKY 모델은 고정 서버가 죽어 `server2`로 대체 라우팅되었으나, `server2`에는 세션이 없으므로 `SESSION_LOST`가 발생합니다. 오직 REDIS만이 완벽하게 세션을 지켜냅니다!
3. **$t=190$ (서버 복구)**: `server1`이 재기동되었지만 램(RAM) 세션은 이미 초기화되었습니다. 따라서 LOCAL과 STICKY는 복구 후에도 인증에 실패하지만, REDIS는 영속적인 중앙 저장소를 통해 `AUTH_OK`를 유지합니다.
