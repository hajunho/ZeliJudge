# [리프레시 토큰이 털렸는데 왜 새 토큰을 계속 재발급해줘요?!: JWT Refresh Token Rotation (RTR)과 토큰 패밀리 무효화(Token Family Revocation)]

## 1. 장애 및 보안 참사 시나리오: "XSS로 유출된 리프레시 토큰 하나가 부른 전 회원 계정 탈취 재앙"

모바일 앱 및 웹 SPA(Single Page Application)를 운영하는 핀테크 서비스에서 세션 서버의 부하를 줄이기 위해 무상태(Stateless) 기반의 **JWT(JSON Web Token) 인증 체계**를 도입했습니다.
- 유효기간 30분의 짧은 **액세스 토큰(Access Token, AT)**
- 유효기간 14일의 긴 **리프레시 토큰(Refresh Token, RT)**

개발팀은 "액세스 토큰이 만료되면 클라이언트가 브라우저 로컬 스토리지에 보관된 리프레시 토큰으로 새 액세스 토큰을 발급받도록 하면 완벽하다!"고 생각했습니다.

그러나 서비스가 오픈된 지 한 달 만에 대규모 보안 사고가 터졌습니다:
1. 웹 게시판의 서드파티 스크립트 취약점(XSS)으로 인해 일부 유저들의 브라우저 로컬 스토리지에 저장되어 있던 **리프레시 토큰($RT_1$)이 해커의 외부 C&C 서버로 탈취**되었습니다.
2. 해커는 탈취한 $RT_1$을 이용해 `/api/auth/refresh` 엔드포인트를 호출하여 손쉽게 새 액세스 토큰을 받아냈습니다.
3. 기존 시스템에서는 **리프레시 토큰이 만료일(14일)까지 영구적으로 유효**했기 때문에, 해커는 14일 내내 피해자 명의로 계좌 잔액을 조회하고 결제를 승인할 수 있었습니다!
4. 피해자가 비밀번호를 바꾸거나 로그아웃을 해도, 서버는 무상태(Stateless) JWT만을 신뢰했기 때문에 해커가 쥐고 있는 리프레시 토큰을 무효화할 방법이 없었습니다.

CISO(정보보호최고책임자)의 긴급 소집 회의:
> "한 번 발급된 리프레시 토큰이 영구 재사용되는 구조를 즉시 뜯어고치세요! OAuth 2.0 Security BCP(Best Current Practice) 표준인 **Refresh Token Rotation (RTR)**과 **토큰 패밀리 재사용 감지(Automatic Token Family Reuse Detection)**를 즉시 구축하십시오!"

---

## 2. 시뮬레이션 사양 및 규칙

본 문제에서는 최신 보안 표준(RFC 6749 BCP & Auth0 표준)에 따른 **JWT Refresh Token Rotation (RTR)**과 **토큰 패밀리 무효화(Token Family Revocation)** 메커니즘을 시뮬레이션합니다.

### (1) 토큰 패밀리(Token Family) 라이프사이클
1. 유저가 로그인하면 새로운 **토큰 패밀리(Family)**가 생성되며, 초기 상태는 `ACTIVE`입니다.
   - 최초 발급된 액세스 토큰(`at`)과 리프레시 토큰(`rt`)이 등록됩니다.
   - 해당 패밀리의 활성 리프레시 토큰(`active_rt`)은 `rt`가 되며, 활성 액세스 토큰 세트(`active_ats`)에 `at`가 추가됩니다.
2. **리프레시 토큰 회전 (RTR - Refresh Token Rotation)**:
   - 클라이언트가 새 토큰을 요청할 때, **액세스 토큰뿐만 아니라 리프레시 토큰도 새로 발급(Rotation)**되어야 합니다.
   - 클라이언트가 제출한 리프레시 토큰(`provided_rt`)이 현재 패밀리의 `active_rt`와 일치하는 경우:
     - 기존 `provided_rt`는 **사용 완료(USED)** 처리되어 `used_rts` 세트에 보관됩니다 (다시 사용할 수 없음!).
     - 새로운 리프레시 토큰 `new_rt`가 패밀리의 `active_rt`가 됩니다.
     - 새로운 액세스 토큰 `new_at`가 `active_ats` 세트에 추가됩니다.
     - `REFRESH_SUCCESS += 1`

### (2) 토큰 재사용 침해 감지 (Breach & Token Reuse Detection)
- 클라이언트가 제출한 `provided_rt`가 **이미 사용된 토큰(`used_rts`)인 경우**:
  - 💥 **토큰 탈취 및 복제(Breach) 발생 판정!**
  - 이미 정상 유저가 토큰을 갱신해갔는데 해커가 과거에 탈취한 토큰을 늦게 사용했거나, 반대로 해커가 먼저 갱신한 뒤 유저가 사용하려 한 상황입니다.
  - **패밀리 전체 무효화 (Family Revocation)**:
    - 해당 토큰 패밀리의 상태를 즉시 `REVOKED`로 변경합니다.
    - 해당 패밀리의 활성 리프레시 토큰을 제거하고, 모든 활성 액세스 토큰(`active_ats`)을 전면 폐기/블랙리스트 처리합니다.
    - `BREACHES += 1`
- 만약 `provided_rt`가 `active_rt`도 아니고 `used_rts`에도 없는 정체불명의 토큰이거나, 이미 `REVOKED`된 패밀리에 대한 갱신 시도인 경우:
  - 단순 무효/거부 처리됩니다 (패밀리 상태는 변화 없음).

### (3) 액세스 토큰 검증 및 로그아웃
1. **`ACCESS <family_id> <at>`**:
   - `family_id`가 존재하고 상태가 `ACTIVE`이며, `at`가 해당 패밀리의 `active_ats`에 포함되어 있다면:
     - `ACCESS_GRANTED += 1`
   - 그 외의 경우(패밀리가 없거나, `REVOKED` 상태이거나, `at`가 목록에 없음):
     - `ACCESS_DENIED += 1`
2. **`LOGOUT <family_id>`**:
   - 해당 패밀리의 상태가 `ACTIVE`라면 즉시 `REVOKED`로 전환하고 모든 활성 토큰을 폐기합니다.

---

## 3. 입력 형식

- 첫째 줄에 명령의 총 개수 $N$ ($1 \le N \le 1,000$)이 주어집니다.
- 둘째 줄부터 $N$개 줄에 걸쳐 명령이 순서대로 주어집니다:
  - `LOGIN <user> <family_id> <rt> <at>`
  - `ACCESS <family_id> <at>`
  - `REFRESH <family_id> <provided_rt> <new_rt> <new_at>`
  - `LOGOUT <family_id>`

## 4. 출력 형식

- 모든 명령을 처리한 후, 다음 통계를 공백으로 구분하여 한 줄에 출력합니다:
  - `ACCESS_GRANTED: <수> ACCESS_DENIED: <수> REFRESH_SUCCESS: <수> BREACHES: <수> REVOKED_FAMILIES: <수>`

---

## 5. 입출력 예제

### 예제 1 (정상 사용 및 해커의 과거 토큰 재사용 공격 차단)
#### 입력
```text
6
LOGIN alice fam1 RT_1 AT_1
ACCESS fam1 AT_1
REFRESH fam1 RT_1 RT_2 AT_2
ACCESS fam1 AT_2
REFRESH fam1 RT_1 RT_HACK AT_HACK
ACCESS fam1 AT_2
```
#### 출력
```text
ACCESS_GRANTED: 2 ACCESS_DENIED: 1 REFRESH_SUCCESS: 1 BREACHES: 1 REVOKED_FAMILIES: 1
```
**설명**:
1. Alice 로그인 후 `AT_1`으로 접근 성공 (`ACCESS_GRANTED: 1`).
2. Alice가 `RT_1`을 제출해 `RT_2`, `AT_2`로 정상 회전 성공 (`REFRESH_SUCCESS: 1`, `RT_1`은 소진됨).
3. Alice가 `AT_2`로 접근 성공 (`ACCESS_GRANTED: 2`).
4. 해커가 탈취했던 옛날 토큰 `RT_1`으로 토큰 갱신을 시도함 $	o$ 이미 소진된 토큰이므로 **침해 감지(BREACH)!** $	o$ `fam1` 전체가 `REVOKED` 상태로 강제 전환되고 모든 토큰이 블랙리스트 처리됨.
5. 이후 `AT_2`로 접근하려 하자 차단됨 (`ACCESS_DENIED: 1`).
