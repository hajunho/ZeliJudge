# #048 새로 배포했더니 502 Bad Gateway가 10초 동안 떠요?!: 쿠버네티스 무중단 배포와 그레이스풀 셧다운(Graceful Shutdown & PreStop Hook)

---

## 1. 현실 세계 비유: 영업 중인 레스토랑의 주방장 교대식

한창 손님이 붐비는 저녁 7시, 레스토랑에서 주방장을 신임 주방장으로 교대(새 버전 배포)하는 상황을 상상해 보세요.

```text
❌ 초보자의 무식한 셧다운 (Naive Immediate Shutdown):
   지배인이 주방 문을 박차고 들어가 구 주방장의 멱살을 잡고 문밖으로 내동댕이칩니다(SIGKILL 즉시 사살).
   1. 구 주방장이 굽고 있던 한우 스테이크 5개(진행 중인 결제/주문 HTTP 요청)는 바닥에 패대기쳐집니다.
      -> 손님 테이블에 [502 Bad Gateway / Connection Reset by Peer] 폭탄 투하!
   2. 홀 서빙 매니저(Kube-Proxy 로드밸런서)에게 "구 주방장 퇴근했다"는 무전이 전파되는 데 3초가 걸립니다.
      매니저는 쫓겨난 주방장의 빈 화구로 계속 새 손님 주문서를 던져서 수십 장이 허공으로 날아갑니다!

✅ 올바른 그레이스풀 셧다운 (Graceful Shutdown with PreStop Hook):
   1단계: 신임 주방장이 출근해서 조리도구를 완벽히 세팅합니다 (Readiness Probe 통과).
   2단계: 홀 서빙 매니저에게 "구 주방장 퇴근 예정이니 더 이상 주문서를 넣지 말라"고 무전을 칩니다 (Service Endpoint 제외).
   3단계 [PreStop sleep 5초]: 무전이 전파되는 5초 동안 구 주방장은 화구 앞에서 대기하며,
          이미 던져져서 날아오고 있던 마지막 주문서들까지 남김없이 손으로 받습니다.
   4단계 [SIGTERM & Grace Period]: 새 주문 접수창구를 닫고, 이미 굽기 시작한 스테이크(In-Flight Requests)를
          30초 동안 끝까지 정성스럽게 구워 손님에게 서빙한 뒤 깔끔하게 퇴근합니다!
   결과 -> 손님은 주방장이 바뀐 사실조차 모른 채 502 에러 0건의 완벽한 무중단 서빙(Zero Downtime) 달성!
```

수많은 주니어 개발자와 AI 바이브 코더들이 "쿠버네티스에서 롤링 업데이트(RollingUpdate) 설정했으니 당연히 무중단 배포겠지!"라며 배포 버튼을 누릅니다.  
그리고 배포할 때마다 **사용자 화면에 502 Bad Gateway 에러가 10초 동안 뿜어져 나와 결제가 취소되는 끔찍한 배포 참사**를 겪습니다.

파드가 종료될 때 **Kube-Proxy 엔드포인트 전파 딜레이(Network Propagation Delay)**와 **진행 중인 요청(In-Flight Requests)**을 배려하지 않았기 때문입니다!

---

## 2. 문제 개요

당신은 대규모 이커머스 서비스의 쿠버네티스 무중단 배포 파이프라인을 책임지는 SRE 엔지니어입니다.  
배포 시 구 파드 종료(`DEPLOY_TERMINATE`)와 신규 HTTP 요청(`REQ`)들이 인입될 때,  
기존의 **즉시 종료 모델(NAIVE_SHUTDOWN)**과 **PreStop Hook 및 그레이스풀 셧다운 모델(GRACEFUL_SHUTDOWN)**의 동작을 시뮬레이션하고,  
502 에러 방어율과 무중단 배포 달성 여부(`ZERO_DOWNTIME_ACHIEVED`)를 정밀 계측하세요.

### 시뮬레이션 상세 규칙

#### 1. 공통 환경
- `PRESTOP_SLEEP <prestop_sec>`: PreStop 훅에서 대기하는 시간 (초, $0 \le prestop\_sec \le 30$).
- `GRACE_PERIOD <grace_sec>`: SIGTERM 후 파드에 주어지는 최대 처리 유예 시간 (`terminationGracePeriodSeconds`, 초, $1 \le grace\_sec \le 60$).
- `PROPAGATION_DELAY <delay_sec>`: 쿠버네티스 엔드포인트 컨트롤러와 로드밸런서가 파드 종료 이벤트를 감지하고 라우팅 목록에서 완전히 제외하기까지 걸리는 네트워크 전파 지연 시간 (초, $1 \le delay\_sec \le 10$).

#### 2. 즉시 종료 모델 (NAIVE_SHUTDOWN)
스프링부트나 앱 서버가 기본 설정(즉시 종료)으로 되어 있고, PreStop 훅이 없는 모델입니다.
- 파드 종료 명령 시각 $T_{term}$이 주어지면, 파드는 $T_{term}$에 즉시 종료됩니다.
- 요청 인입 시각 $t_{req}$, 소요 시간 $dur$:
  - 만약 파드가 아직 종료되지 않았고 종료 전에 요청이 끝나면 ($t_{req} + dur \le T_{term}$): `SUCCESS`.
  - 만약 종료 전에 시작되었으나 종료 시점까지 끝나지 못했다면 ($t_{req} < T_{term}$ 이고 $t_{req} + dur > T_{term}$):
    - 서버 프로세스가 강제 종료되어 소켓이 끊어집니다: `HTTP_502_DROPPED_INFLIGHT`.
  - 만약 이미 종료된 후 라우팅 테이블 전파 지연 중에 요청이 들어왔다면 ($t_{req} \ge T_{term}$):
    - 죽은 파드로 요청이 전달되어 즉시 에러가 납니다: `HTTP_502_ROUTED_TO_DEAD_POD`.

#### 3. 그레이스풀 셧다운 모델 (GRACEFUL_SHUTDOWN)
PreStop 훅과 스프링부트 그레이스풀 셧다운(`server.shutdown=graceful`)이 적용된 모델입니다.
- 파드 종료 명령 시각 $T_{term}$에 쿠버네티스는 로드밸런서 라우팅 테이블에서 파드 제외를 시작합니다.
  - 라우팅이 완전히 제외되는 시각 $T_{unroute} = T_{term} + delay\_sec$.
- **PreStop Hook 단계**:
  - 파드는 종료 명령 후 $prestop\_sec$ 동안 계속 살아서 정상적으로 새 요청을 수용합니다.
  - SIGTERM 신호가 전달되어 새 요청을 닫는 시각 $T_{sigterm} = T_{term} + prestop\_sec$.
  - SIGKILL 강제 사살 시각 $T_{kill} = T_{sigterm} + grace\_sec$.
- **요청 판정 규칙**:
  - 만약 $t_{req} \ge T_{sigterm}$:
    - 이미 파드가 `SIGTERM`을 받아 새 요청 커넥터를 닫았습니다.
    - 만약 $t_{req} < T_{unroute}$ 라면 (로드밸런서에서 미처 빠지기 전에 파드가 먼저 닫힘):
      - PreStop 시간이 너무 짧아서 터진 에러: `HTTP_502_PRESTOP_TOO_SHORT`.
    - 만약 $t_{req} \ge T_{unroute}$ 라면 (이미 제외된 파드로 잘못 온 요청):
      - `HTTP_502_ROUTED_TO_DEAD_POD`.
  - 만약 $t_{req} < T_{sigterm}$:
    - 파드가 아직 살아서 요청을 안전하게 정상 수신했습니다.
    - 처리 완료 예정 시각 $t_{end} = t_{req} + dur$:
      - 만약 $t_{end} \le T_{kill}$: Grace Period 내에 무사히 완료되어 정상 서빙: `SUCCESS`.
      - 만약 $t_{end} > T_{kill}$: 작업이 너무 길어 SIGKILL로 강제 사살됨: `HTTP_502_GRACE_PERIOD_EXCEEDED`.

---

## 3. 입력 형식

```text
PRESTOP_SLEEP <prestop_sec>
GRACE_PERIOD <grace_sec>
PROPAGATION_DELAY <delay_sec>
EVENTS <E>
NEW_POD <pod_id>
DEPLOY_TERMINATE <pod_id> <timestamp>
REQ <req_id> <timestamp> <pod_id> <duration_sec>
... (총 E개의 줄)
```

- `prestop_sec`: PreStop 대기 시간 (정수, 초)
- `grace_sec`: 최대 그레이스 유예 시간 (정수, 초)
- `delay_sec`: 라우팅 전파 지연 시간 (정수, 초)
- `E`: 총 이벤트 줄 수 ($1 \le E \le 30,000$)
- 각 명령:
  - `NEW_POD <pod_id>`: 신규 파드 생성
  - `DEPLOY_TERMINATE <pod_id> <timestamp>`: 롤링 배포로 인한 구 파드 종료 명령 하달
  - `REQ <req_id> <timestamp> <pod_id> <duration_sec>`: HTTP 요청 인입

---

## 4. 출력 형식

각 `REQ` 이벤트마다 한 줄씩 출력합니다:
```text
REQ <req_id> AT:<timestamp> POD:<pod_id> NAIVE:<naive_status> GRACEFUL:<graceful_status>
```
- `<naive_status>`, `<graceful_status>`:
  - `SUCCESS`, `HTTP_502_DROPPED_INFLIGHT`, `HTTP_502_ROUTED_TO_DEAD_POD`, `HTTP_502_PRESTOP_TOO_SHORT`, `HTTP_502_GRACE_PERIOD_EXCEEDED` 중 하나

모든 이벤트 처리 후 마지막 줄에 통계 요약을 출력합니다:
```text
SUMMARY TOTAL_REQS:<total> NAIVE_502_ERRORS:<n_err> GRACEFUL_502_ERRORS:<g_err> ERRORS_SAVED:<saved> ZERO_DOWNTIME_ACHIEVED:<YES|NO>
```
- `ZERO_DOWNTIME_ACHIEVED`: `graceful_errors == 0` 이면 `YES`, 아니면 `NO`.

---

## 5. 입출력 예시

### 예시 입력 1
```text
PRESTOP_SLEEP 5
GRACE_PERIOD 10
PROPAGATION_DELAY 3
EVENTS 5
NEW_POD pod_v1
REQ req_01 10 pod_v1 4
DEPLOY_TERMINATE pod_v1 12
REQ req_02 13 pod_v1 2
REQ req_03 20 pod_v1 2
```

### 예시 출력 1
```text
REQ req_01 AT:10 POD:pod_v1 NAIVE:HTTP_502_DROPPED_INFLIGHT GRACEFUL:SUCCESS
REQ req_02 AT:13 POD:pod_v1 NAIVE:HTTP_502_ROUTED_TO_DEAD_POD GRACEFUL:SUCCESS
REQ req_03 AT:20 POD:pod_v1 NAIVE:HTTP_502_ROUTED_TO_DEAD_POD GRACEFUL:HTTP_502_ROUTED_TO_DEAD_POD
SUMMARY TOTAL_REQS:3 NAIVE_502_ERRORS:3 GRACEFUL_502_ERRORS:1 ERRORS_SAVED:2 ZERO_DOWNTIME_ACHIEVED:NO
```

### 설명
- **`req_01` (인플라이트 요청)**:
  - $t=10$에 시작되어 $t=14$에 끝나는 4초짜리 요청입니다.
  - NAIVE 모델은 $t=12$에 파드가 강제 종료되어 소켓이 끊기며 `HTTP_502_DROPPED_INFLIGHT`로 터집니다.
  - GRACEFUL 모델은 PreStop(5초) + Grace Period(10초) 유예 덕분에 $t=14$까지 안전하게 처리되어 `SUCCESS`합니다.
- **`req_02` (라우팅 전파 지연 중 인입된 요청)**:
  - 배포 명령($t=12$) 직후 라우팅 해제 전파 지연($t=12 \sim 15$) 중에 $t=13$에 요청이 들어왔습니다.
  - NAIVE 모델은 파드가 이미 죽어버려 `HTTP_502_ROUTED_TO_DEAD_POD`가 터집니다.
  - GRACEFUL 모델은 PreStop 훅(5초) 덕분에 $t=17$까지 파드가 살아서 새 요청을 정상 접수하여 `SUCCESS`합니다.
- **`req_03`**: $t=20$에는 이미 두 모델 모두 완전히 종료된 파드이므로 정상적인 에러로 기록됩니다.
- 그레이스풀 셧다운을 통해 치명적인 502 에러 2건을 완벽하게 방어했습니다 (`ERRORS_SAVED: 2`).
