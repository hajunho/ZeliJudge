# #042 DB가 잠깐 끊겼는데 왜 서버 100대가 전부 강제 재부팅돼요?!: 헬스체크와 Liveness vs Readiness Probe

---

## 1. 현실 세계 비유: 비행기 조종사의 심장 박동 vs 시야

어느 날 안개가 짙게 끼어 공항 활주로가 전혀 보이지 않고, 관제탑 레이더 신호가 3초간 끊겼습니다.  
이때 여러분이 항공사 관제관이라면 어떻게 해야 할까요?

1. **상식적인 대처**: 조종사에게 무전을 쳐서 "시야가 확보되고 레이더가 복구될 때까지 착륙과 승객 탑승을 잠시 대기하세요"라고 지시한다.
2. **정신 나간 대처**: 조종실 문을 박차고 들어가 조종사 심장에 5만 볼트 전기 충격기를 쏴서 기절시켰다가 강제로 깨운다.

말도 안 되는 소리 같지만, 수많은 백엔드 초보 개발자와 AI 바이브 코더들이 쿠버네티스(Kubernetes, k8s)를 도입할 때 **정확히 2번 짓**을 저지릅니다!

- **Liveness Probe (생존 확인)**: "조종사의 심장이 뛰고 있는가?" (프로세스가 데드락에 걸리지 않고 살아있는가?)
- **Readiness Probe (준비 확인)**: "조종사 눈앞의 시야가 확보되었는가?" (DB나 외부 API와 통신하여 지금 당장 사용자 요청을 처리할 수 있는가?)

초보 개발자들은 스프링부트의 `/actuator/health` 엔드포인트 하나에 DB 연결 확인까지 전부 욱여넣은 뒤, 이를 쿠버네티스의 **Liveness Probe**에 그대로 등록해 버립니다. 이것이 바로 악명 높은 **"딥 헬스체크(Deep Health Check)" 안티패턴**입니다!

DB에 순간적인 쿼리 폭주로 3초간 응답 지연이 발생하자, 멀쩡히 살아서 서빙 중이던 웹 서버 파드 100대가 일제히 쿠버네티스에게 "나 죽었소!"를 외칩니다.  
쿠버네티스는 즉각 100개 파드를 전부 강제 사살(`SIGKILL`)하고 재부팅합니다. 재부팅된 100개의 파드는 부팅되자마자 DB 커넥션 풀을 맺으려고 수만 개의 TCP 연결을 동시에 DB로 쏟아붓습니다.  
결국 DB는 완전히 뻗어버리고, 파드들은 기동 실패를 반복하며 전사 서비스가 영구 마비되는 **연쇄 재시작 폭풍(Cascading Pod Restart Storm / CrashLoopBackOff)**에 빠지게 됩니다!

---

## 2. 문제 개요

당신은 쿠버네티스 인프라 장애를 수습해야 하는 수석 SRE 엔지니어입니다.  
주기적으로 수집되는 각 파드의 내부 상태(`app_internal`)와 외부 DB 의존성 상태(`db_dep`) 이벤트를 입력받아,  
기존의 **초보자 방식(NAIVE_DEEP_LIVENESS)**과 **올바른 분리 방식(SEPARATED_PROBES)**의 동작을 동시에 시뮬레이션하고, 불필요한 파드 재부팅을 얼마나 방지할 수 있는지 검증하세요.

### 헬스체크 모델 상세 규칙

#### 1. NAIVE_DEEP_LIVENESS (단일 딥 헬스체크 모델)
- 단일 헬스체크로 앱 내부와 DB 의존성을 모두 확인합니다.
- `app_internal == "OK"` 이고 `db_dep == "OK"` 일 때만 정상(`HEALTHY`)으로 판정하며, 연속 실패 카운트를 `0`으로 리셋합니다.
- 둘 중 하나라도 정상이 아니면 연속 실패 카운트가 `1` 증가합니다.
  - 연속 실패 카운트가 `LIVENESS_FAIL_LIMIT`에 도달하면 즉시 파드가 강제 재부팅(`RESTART`)됩니다.
  - 재부팅 시 누적 재시작 횟수가 `1` 증가하며, 연속 실패 카운트는 `0`으로 리셋됩니다.
  - 아직 임계치 미만이면 상태는 `FAILING`입니다.

#### 2. SEPARATED_PROBES (올바른 쿠버네티스 2대 프로브 분리 모델)
파드 상태는 파드별로 독립 격리되어 관리됩니다. (초기 상태: 트래픽 `ENABLED`, 실패 카운트 `0`)

- **Liveness Probe (생존 확인)**:
  - 오직 애플리케이션 자체의 생존 여부(`app_internal`)만 검사합니다. (외부 DB 상태는 철저히 무시)
  - `app_internal == "OK"` 이면 정상(`ALIVE`)이며, Liveness 연속 실패 카운트를 `0`으로 리셋합니다.
  - `app_internal != "OK"` (예: `DEADLOCK`) 이면 Liveness 연속 실패 카운트가 `1` 증가합니다.
    - Liveness 연속 실패 카운트가 `LIVENESS_FAIL_LIMIT`에 도달하면 파드가 강제 재부팅(`RESTART`)됩니다.
    - 재부팅 시:
      - 분리 모델 누적 재시작 횟수 `1` 증가
      - Liveness 연속 실패 카운트 `0`으로 리셋
      - Readiness 연속 성공/실패 카운트 모두 `0`으로 초기화
      - 트래픽 상태는 즉시 차단(`DISABLED`)으로 전환
    - 아직 임계치 미만이면 `FAILING` 상태가 됩니다.

- **Readiness Probe (트래픽 준비 확인)**:
  - Liveness에서 `RESTART`가 발생한 턴에는 파드가 부팅 중이므로 Readiness 액션은 `UNREADY`가 됩니다.
  - Liveness에서 `RESTART`가 발생하지 않은 일반 턴의 경우:
    - `app_internal == "OK"` 이고 `db_dep == "OK"` 이면 준비 완료(`READY`)입니다.
      - Readiness 연속 실패 카운트 = `0`, 연속 성공 카운트 `1` 증가.
      - 연속 성공 카운트가 `READINESS_SUCCESS_LIMIT` 이상이 되면 트래픽 상태가 `ENABLED`로 전환됩니다.
    - 둘 중 하나라도 비정상이면 준비 미완료(`UNREADY`)입니다.
      - Readiness 연속 성공 카운트 = `0`, 연속 실패 카운트 `1` 증가.
      - 연속 실패 카운트가 `READINESS_FAIL_LIMIT` 이상이 되면 트래픽 상태가 `DISABLED`로 전환됩니다.

---

## 3. 입력 형식

```text
LIVENESS_FAIL_LIMIT <L_limit>
READINESS_FAIL_LIMIT <R_limit>
READINESS_SUCCESS_LIMIT <R_succ>
EVENTS <E>
STATUS <timestamp> <pod_id> <app_internal> <db_dep>
... (총 E개의 이벤트 줄)
```

- `L_limit`: Liveness 연속 실패 허용 임계치 (정수, $1 \le L\_limit \le 10$)
- `R_limit`: Readiness 연속 실패 시 트래픽 차단 임계치 (정수, $1 \le R\_limit \le 10$)
- `R_succ`: Readiness 연속 성공 시 트래픽 재개 임계치 (정수, $1 \le R\_succ \le 10$)
- `E`: 이벤트 총 개수 ($1 \le E \le 30,000$)
- 각 `STATUS` 라인:
  - `timestamp`: 타임스탬프 (정수)
  - `pod_id`: 파드 식별자 문자열 (예: `pod-1`)
  - `app_internal`: `OK` 또는 `DEADLOCK`
  - `db_dep`: `OK` 또는 `DB_DOWN`

---

## 4. 출력 형식

각 이벤트마다 다음 형식으로 한 줄씩 출력합니다:
```text
STATUS <timestamp> POD:<pod_id> NAIVE:<naive_act> SEPARATED:LIVENESS=<liveness_act>,READINESS=<readiness_act>,TRAFFIC=<traffic_state>
```
- `<naive_act>`: `HEALTHY`, `FAILING`, `RESTART`
- `<liveness_act>`: `ALIVE`, `FAILING`, `RESTART`
- `<readiness_act>`: `READY`, `UNREADY`
- `<traffic_state>`: `ENABLED`, `DISABLED`

모든 이벤트 처리가 끝난 후, 마지막 줄에 요약 통계를 출력합니다:
```text
SUMMARY TOTAL_EVENTS:<E> NAIVE_RESTARTS:<naive_cnt> SEPARATED_RESTARTS:<sep_cnt> UNNECESSARY_RESTARTS_SAVED:<saved>
```
- `<saved>`: 불필요한 재시작 방어 횟수 (`naive_cnt - sep_cnt`)

---

## 5. 입출력 예시

### 예시 입력 1
```text
LIVENESS_FAIL_LIMIT 3
READINESS_FAIL_LIMIT 2
READINESS_SUCCESS_LIMIT 1
EVENTS 9
STATUS 1001 pod-1 OK DB_DOWN
STATUS 1002 pod-1 OK DB_DOWN
STATUS 1003 pod-1 OK DB_DOWN
STATUS 1004 pod-1 OK OK
STATUS 1005 pod-1 OK OK
STATUS 1006 pod-1 DEADLOCK OK
STATUS 1007 pod-1 DEADLOCK OK
STATUS 1008 pod-1 DEADLOCK OK
STATUS 1009 pod-1 OK OK
```

### 예시 출력 1
```text
STATUS 1001 pod-1 NAIVE:FAILING SEPARATED:LIVENESS=ALIVE,READINESS=UNREADY,TRAFFIC=ENABLED
STATUS 1002 pod-1 NAIVE:FAILING SEPARATED:LIVENESS=ALIVE,READINESS=UNREADY,TRAFFIC=DISABLED
STATUS 1003 pod-1 NAIVE:RESTART SEPARATED:LIVENESS=ALIVE,READINESS=UNREADY,TRAFFIC=DISABLED
STATUS 1004 pod-1 NAIVE:HEALTHY SEPARATED:LIVENESS=ALIVE,READINESS=READY,TRAFFIC=ENABLED
STATUS 1005 pod-1 NAIVE:HEALTHY SEPARATED:LIVENESS=ALIVE,READINESS=READY,TRAFFIC=ENABLED
STATUS 1006 pod-1 NAIVE:FAILING SEPARATED:LIVENESS=FAILING,READINESS=UNREADY,TRAFFIC=ENABLED
STATUS 1007 pod-1 NAIVE:FAILING SEPARATED:LIVENESS=FAILING,READINESS=UNREADY,TRAFFIC=DISABLED
STATUS 1008 pod-1 NAIVE:RESTART SEPARATED:LIVENESS=RESTART,READINESS=UNREADY,TRAFFIC=DISABLED
STATUS 1009 pod-1 NAIVE:HEALTHY SEPARATED:LIVENESS=ALIVE,READINESS=READY,TRAFFIC=ENABLED
SUMMARY TOTAL_EVENTS:9 NAIVE_RESTARTS:2 SEPARATED_RESTARTS:1 UNNECESSARY_RESTARTS_SAVED:1
```

### 설명
- **1001 ~ 1003**: 외부 DB가 일시 장애(`DB_DOWN`)에 빠졌습니다.
  - NAIVE 모델은 3회 연속 실패하자 멀쩡한 파드를 강제 재시작(`RESTART`)해버립니다.
  - SEPARATED 모델은 파드 자체는 정상(`ALIVE`)이므로 재시작하지 않고, Readiness 실패 2회 도달 시 트래픽만 조용히 차단(`DISABLED`)합니다.
- **1004**: DB가 복구되자 SEPARATED 모델은 즉시 트래픽을 재개(`ENABLED`)합니다.
- **1006 ~ 1008**: 파드 내부에서 실제 심각한 결함(`DEADLOCK`)이 발생했습니다.
  - 이때는 SEPARATED 모델도 Liveness가 3회 연속 실패하여 파드를 재부팅(`RESTART`)시켜 자가 치유(Self-Healing)를 수행합니다.
- 최종적으로 SEPARATED 모델은 단 1회의 정당한 재시작만 수행하여, DB 장애로 인한 1회의 불필요한 강제 재시작을 성공적으로 막아냈습니다 (`UNNECESSARY_RESTARTS_SAVED:1`).
