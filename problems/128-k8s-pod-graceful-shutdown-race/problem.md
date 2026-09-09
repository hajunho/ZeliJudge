# 128. 무중단 배포(Zero Downtime)라면서 왜 롤링 업데이트마다 502 에러가 터져요?!: 쿠버네티스 Pod Graceful Shutdown과 엔드포인트 등록 해제(Deregistration) 비동기 레이스 컨디션

## 문제 설명

이커머스 스타트업의 주니어 백엔드 엔지니어 젤리(Zeli)는 결제 API 서버를 쿠버네티스(Kubernetes) 클러스터로 이전하고 `Deployment`에 롤링 업데이트(`RollingUpdate`) 전략을 적용했습니다.  
레플리카도 5개로 넉넉하게 설정했고, `maxSurge: 1`, `maxUnavailable: 0`을 주어 새 버전 Pod가 정상 가동(Readiness Probe 통과)된 후에 구버전 Pod를 종료하도록 구성했습니다.

*"새 Pod가 뜬 뒤에 이전 Pod를 죽이니까 100% 무중단 배포(Zero Downtime)겠지?!"* 😎

하지만 신규 기능 배포를 위해 CI/CD 파이프라인을 실행하자마자 슬랙 채널에 난리가 났습니다:
- **모니터링 알람**: *"배포 시작 후 3분 동안 502 Bad Gateway 에러가 150건 넘게 발생했습니다!"*
- **고객지원팀 긴급 제보**: *"결제 버튼을 누르던 고객들이 일제히 네트워크 연결 오류로 튕겼습니다!"*
- **인그레스(Nginx Ingress / ALB) 에러 로그**:
  ```
  [error] 1421#1421: *89201 connect() failed (111: Connection refused) 
  while connecting to upstream, client: 10.0.1.5, server: checkout.zeli.shop, 
  request: "POST /v1/checkout HTTP/1.1", upstream: "http://10.244.2.45:8080/v1/checkout"
  ```

*"아니, 무중단 배포라면서 왜 배포할 때마다 502 에러가 쏟아지고 결제 요청이 날아가는 거죠?!"* 😱

---

### 왜 이런 참사가 발생했을까? (비동기 엔드포인트 등록 해제와 Kubelet의 레이스 컨디션)

이 참사의 원인은 **쿠버네티스 제어 평면(Control Plane)의 네트워크 라우팅 갱신**과 **워커 노드 Kubelet의 컨테이너 종료**가 **서로 완전히 독립적인 비동기(Asynchronous) 이벤트**로 병렬 실행되기 때문입니다!

Pod 삭제 트리거(`kubectl delete pod` 또는 롤링 배포에 의한 구버전 Pod 축출)가 시작되면 쿠버네티스는 두 갈래 길을 걷습니다:

```
                  [Pod 삭제 트리거 (Terminating 시작)]
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         ▼                                                   ▼
   [경로 A: Kubelet 프로세스]                         [경로 B: 네트워크 제어 평면]
1. Pod 상태가 Terminating으로 전이                1. Endpoint Controller가 상태 감지
2. preStop Hook 실행 (설정된 경우)                 2. EndpointSlice / Endpoints에서 Pod IP 제거
3. 컨테이너에 SIGTERM 전송                        3. Ingress / kube-proxy로 Watch 이벤트 전파
4. 앱의 Listen 소켓 닫힘 (신규 커넥션 거절)        4. Ingress upstream 및 iptables 룰 갱신
5. In-flight 요청 Drain 및 앱 종료                5. [결과] 라우팅 테이블에서 해당 Pod 제거 완료!
6. terminationGracePeriod 초과 시 SIGKILL           (⏱️ 소요 시간: 2초 ~ 5초 이상)
```

#### 1. 레이스 컨디션의 물리적 원인
- **경로 B(네트워크 전파 지연, $2 \sim 5$초)**:
  - EndpointSlice 컨트롤러가 Pod 삭제를 감지하고, 인그레스 컨트롤러(Nginx, ALB, Envoy)나 `kube-proxy`로 Watch 이벤트를 쏘아 업스트림 라우팅 풀에서 Pod IP를 제거하기까지 보통 **2초 ~ 5초의 지연($T_{deregister}$)**이 소요됩니다.
- **경로 A(Kubelet 컨테이너 종료, $0.1$초)**:
  - 컨테이너에 `preStop` 훅이 없으면 Kubelet은 Pod 삭제 즉시 메인 프로세스에 **`SIGTERM`**을 보냅니다.
  - 웹 프레임워크(Spring Boot, Node.js, Go 등)는 `SIGTERM`을 수신하자마자 **0.1초 만에 Listen 포트(8080)를 닫아버립니다**!
- **결과**:
  - 인그레스 컨트롤러는 아직 엔드포인트가 제거되지 않아 **죽어가는 Pod로 계속 새 HTTP 요청을 포워딩**합니다!
  - 닫힌 소켓으로 들어온 패킷은 즉시 `Connection Refused (TCP RST)`를 맞고 인그레스는 클라이언트에게 **`502 Bad Gateway`**를 반환합니다.

#### 2. 구원투수: `preStop: sleep 5` 훅의 마법
Deployment YAML에 다음 설정을 추가하면 문제가 말끔히 해결됩니다:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sleep", "5"]
```

1. Pod가 `Terminating` 상태가 되어도 Kubelet은 `SIGTERM`을 바로 보내지 않고 먼저 5초간 대기합니다.
2. **이 5초 동안 앱의 Listen 포트(8080)는 활짝 열려 있으며正常 응답합니다!**
3. 그 5초 사이에 인그레스 컨트롤러와 iptables가 라우팅 풀에서 Pod IP를 완벽하게 제거합니다 (2~3초 소요).
4. 엔드포인트가 제거되었으므로 더 이상 이 Pod로 새 트래픽이 유입되지 않습니다.
5. 5초 후 `preStop`이 끝나면 비로소 `SIGTERM`이 전달되고, 앱은 기존에 처리 중이던 잔여 요청(In-flight)만 깔끔하게 완료(Drain)하고 종료합니다!

#### 3. `terminationGracePeriodSeconds`의 함정
- `terminationGracePeriodSeconds`(기본 30초)는 **`preStop` 실행 시작 시점($t=0$)부터 카운트다운**됩니다!
- 따라서 만약 `preStop(5s)` + `App Drain(10s)` > `terminationGracePeriod(10s)`처럼 Grace Period를 너무 짧게 잡으면, Kubelet이 중간에 **`SIGKILL`**을 날려 처리 중이던 결제 요청이 잘리고 **`504 Gateway Timeout`**이 터집니다!
- **공식**: `terminationGracePeriodSeconds` $\ge$ `preStop Delay` + `App Drain Timeout` + `Safety Buffer (5~10s)`

---

## 과제

당신은 쿠버네티스의 Pod 삭제 라이프사이클 및 비동기 엔드포인트 등록 해제 과정을 시뮬레이션하는 **"K8s Graceful Shutdown Simulator"**를 구현해야 합니다.

각 배포 시나리오별로 Pod 설정, 네트워크 엔드포인트 등록 해제 지연 시간, 그리고 유입된 HTTP 요청 이벤트들이 주어질 때, 각 요청의 처리 결과(200, 502, 504)와 전체 클러스터의 다운타임 통계를 산출하십시오.

---

### 입력 형식 (JSON)

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "scenarios": [
    {
      "scenario_id": "no_prestop_immediate_exit",
      "pod_config": {
        "pod_name": "checkout-api-v1-7df8b",
        "pre_stop_delay_sec": 0.0,
        "termination_grace_period_sec": 30.0,
        "app_drain_timeout_sec": 0.0,
        "app_shutdown_behavior": "immediate"
      },
      "network_config": {
        "endpoint_deregistration_delay_sec": 3.0
      },
      "events": [
        { "time": 0.0, "type": "POD_TERMINATION_REQUESTED" },
        { "time": 0.5, "type": "INCOMING_REQUEST", "request_id": "req-01", "duration_sec": 0.5 },
        { "time": 3.2, "type": "INCOMING_REQUEST", "request_id": "req-04", "duration_sec": 0.5 }
      ]
    }
  ]
}
```

- `scenarios`: 시뮬레이션할 시나리오 목록
  - `scenario_id`: 시나리오 식별자
  - `pod_config`:
    - `pod_name`: Pod 이름
    - `pre_stop_delay_sec`: `preStop` 훅 실행 지연 시간(초, 실수 $\ge 0.0$)
    - `termination_grace_period_sec`: Kubelet의 Pod 강제 종료 유예 시간(초, 실수 $\ge 1.0$)
    - `app_drain_timeout_sec`: `SIGTERM` 수신 후 애플리케이션의 내부 드레인 허용 시간(초, 실수 $\ge 0.0$)
    - `app_shutdown_behavior`: `"immediate"` (즉시 종료/포트 닫기) | `"graceful"` (진행 중 요청 드레인 허용)
  - `network_config`:
    - `endpoint_deregistration_delay_sec`: 인그레스/kube-proxy 라우팅 테이블에서 Pod IP가 완전히 제거되기까지 걸리는 전파 지연 시간(초, 실수 $\ge 0.0$)
  - `events`: 타임라인 이벤트 목록
    - `POD_TERMINATION_REQUESTED`: Pod 삭제 요청 시점 (`time`, 없으면 $0.0$)
    - `INCOMING_REQUEST`: 클라이언트의 HTTP 요청 유입 (`time`, `request_id`, `duration_sec`)

---

### 시뮬레이션 규칙

1. **타임라인 주요 시점 정의**:
   - $t_{\text{term}}$: `POD_TERMINATION_REQUESTED` 이벤트 발생 시점 (기본 $0.0$)
   - $t_{\text{deregister}} = t_{\text{term}} + \text{endpoint\_deregistration\_delay\_sec}$: 인그레스 라우팅 풀에서 Pod 제거 완료 시점
   - $t_{\text{prestop\_end}} = t_{\text{term}} + \text{pre\_stop\_delay\_sec}$: `preStop` 훅 종료 시점
   - $t_{\text{sigterm}} = t_{\text{prestop\_end}}$: Kubelet이 컨테이너에 `SIGTERM` 시그널을 발송한 시점
   - $t_{\text{sigkill\_limit}} = t_{\text{term}} + \text{termination\_grace\_period\_sec}$: Kubelet이 `SIGKILL`을 발송하는 절대 마감 시점

2. **개별 요청(`INCOMING_REQUEST`) 처리 판정** (요청 시각 $t_{\text{req}}$, 소요 시간 $D$, 완료 예정 시각 $t_{\text{finish}} = t_{\text{req}} + D$):
   - **경우 1 ($t_{\text{req}} \ge t_{\text{deregister}}$)**:
     - 인그레스가 이미 라우팅 테이블에서 이 Pod를 제거했으므로, 정상적으로 다른 정상 레플리카로 전달됩니다.
     - `status`: `"ROUTED_TO_OTHER_REPLICA"`, `http_status`: 200, `error`: null
   - **경우 2 ($t_{\text{req}} < t_{\text{deregister}}$)**:
     - 인그레스가 이 Pod로 요청을 라우팅합니다.
     - **2-A ($t_{\text{req}} \ge t_{\text{sigterm}}$)**:
       - 이미 `SIGTERM`이 발송되어 앱의 Listen 포트가 닫혀 있습니다.
       - `status`: `"CONNECTION_REFUSED"`, `http_status`: 502, `error`: `"ERR_CONNECTION_REFUSED_PORT_CLOSED"`
     - **2-B ($t_{\text{req}} < t_{\text{sigterm}}$)**:
       - 앱의 포트가 열려 있으므로 커넥션이 정상 수락(Accept)되어 처리를 시작합니다.
       - **종료 모드가 `"immediate"`인 경우**:
         - $t_{\text{finish}} \le t_{\text{sigterm}}$: `SIGTERM` 이전에 완료됨 $\to$ `status`: `"COMPLETED"`, `http_status`: 200, `error`: null
         - $t_{\text{finish}} > t_{\text{sigterm}}$: 처리 도중 `SIGTERM`을 맞아 즉시 중단됨 $\to$ `status`: `"IN_FLIGHT_ABORTED_SIGTERM"`, `http_status`: 502, `error`: `"ERR_IN_FLIGHT_ABORTED_ON_SIGTERM"`
       - **종료 모드가 `"graceful"`인 경우**:
         - 유효 드레인 한계 $t_{\text{cutoff}} = \min(t_{\text{sigterm}} + \text{app\_drain\_timeout\_sec}, t_{\text{sigkill\_limit}})$
         - $t_{\text{finish}} \le t_{\text{cutoff}}$: 드레인 유예 기간 내 정상 완료됨 $\to$ `status`: `"COMPLETED"`, `http_status`: 200, `error`: null
         - $t_{\text{finish}} > t_{\text{cutoff}}$:
           - 만약 $t_{\text{cutoff}} == t_{\text{sigkill\_limit}}$이면 Kubelet의 강제 종료에 사살됨 $\to$ `status`: `"DROPPED_BY_SIGKILL"`, `http_status`: 504, `error`: `"ERR_GATEWAY_TIMEOUT_SIGKILL"`
           - 만약 $t_{\text{cutoff}} < t_{\text{sigkill\_limit}}$이면 앱 드레인 타임아웃 초과로 중단됨 $\to$ `status`: `"DRAIN_TIMEOUT_ABORTED"`, `http_status`: 504, `error`: `"ERR_APP_DRAIN_TIMEOUT_EXCEEDED"`

3. **컨테이너 실제 종료 시각(`container_exit_time`) 및 시그널 추적**:
   - `immediate`: $t_{\text{sigterm}}$에 즉시 프로세스 종료.
   - `graceful`:
     - `SIGKILL`이 발생한 경우: `sigkill_sent_time = t_sigkill_limit`, `container_exit_time = t_sigkill_limit`
     - 앱 드레인 타임아웃으로 중단된 경우: `sigkill_sent_time = null`, `container_exit_time = t_sigterm + app_drain_timeout_sec`
     - 모든 수락된 요청이 정상 완료된 경우: `sigkill_sent_time = null`, `container_exit_time = max(t_sigterm, max(t_finish of completed requests))` (수락된 요청이 없으면 $t_{\text{sigterm}}$)

4. **통계 및 요약 집계**:
   - 실패 요청: `http_status`가 502 또는 504인 요청.
   - `has_downtime_or_errors`: 실패 요청 수가 1건 이상이면 `true`, 0건이면 `false`.
   - 모든 시간 출력값은 소수점 둘째 자리까지 반올림(`round(x, 2)`).

---

### 출력 형식 (JSON)

표준 출력(stdout)으로 다음 구조의 JSON 객체를 출력합니다 (인덴트 2칸):

```json
{
  "summary": {
    "total_scenarios": 1,
    "zero_downtime_scenarios": 0,
    "failed_scenarios": 1,
    "total_502_errors": 1,
    "total_504_errors": 0
  },
  "scenarios": [
    {
      "scenario_id": "no_prestop_immediate_exit",
      "pod_name": "checkout-api-v1-7df8b",
      "has_downtime_or_errors": true,
      "container_exit_time": 0.0,
      "sigterm_sent_time": 0.0,
      "sigkill_sent_time": null,
      "endpoint_deregistered_time": 3.0,
      "stats": {
        "total_requests": 2,
        "successful_requests": 1,
        "failed_requests": 1,
        "bad_gateway_502_count": 1,
        "gateway_timeout_504_count": 0
      },
      "request_results": [
        {
          "request_id": "req-01",
          "arrival_time": 0.5,
          "status": "CONNECTION_REFUSED",
          "http_status": 502,
          "error": "ERR_CONNECTION_REFUSED_PORT_CLOSED"
        },
        {
          "request_id": "req-04",
          "arrival_time": 3.2,
          "status": "ROUTED_TO_OTHER_REPLICA",
          "http_status": 200,
          "error": null
        }
      ]
    }
  ]
}
```

---

## 입출력 예시

### 예시 1

#### 입력
```json
{
  "scenarios": [
    {
      "scenario_id": "no_prestop_immediate_exit",
      "pod_config": {
        "pod_name": "checkout-api-v1-7df8b",
        "pre_stop_delay_sec": 0.0,
        "termination_grace_period_sec": 30.0,
        "app_drain_timeout_sec": 0.0,
        "app_shutdown_behavior": "immediate"
      },
      "network_config": {
        "endpoint_deregistration_delay_sec": 3.0
      },
      "events": [
        { "time": 0.0, "type": "POD_TERMINATION_REQUESTED" },
        { "time": 0.5, "type": "INCOMING_REQUEST", "request_id": "req-01", "duration_sec": 0.5 },
        { "time": 1.2, "type": "INCOMING_REQUEST", "request_id": "req-02", "duration_sec": 0.8 },
        { "time": 2.8, "type": "INCOMING_REQUEST", "request_id": "req-03", "duration_sec": 0.4 },
        { "time": 3.2, "type": "INCOMING_REQUEST", "request_id": "req-04", "duration_sec": 0.5 }
      ]
    }
  ]
}
```

#### 출력
```json
{
  "summary": {
    "total_scenarios": 1,
    "zero_downtime_scenarios": 0,
    "failed_scenarios": 1,
    "total_502_errors": 3,
    "total_504_errors": 0
  },
  "scenarios": [
    {
      "scenario_id": "no_prestop_immediate_exit",
      "pod_name": "checkout-api-v1-7df8b",
      "has_downtime_or_errors": true,
      "container_exit_time": 0.0,
      "sigterm_sent_time": 0.0,
      "sigkill_sent_time": null,
      "endpoint_deregistered_time": 3.0,
      "stats": {
        "total_requests": 4,
        "successful_requests": 1,
        "failed_requests": 3,
        "bad_gateway_502_count": 3,
        "gateway_timeout_504_count": 0
      },
      "request_results": [
        {
          "request_id": "req-01",
          "arrival_time": 0.5,
          "status": "CONNECTION_REFUSED",
          "http_status": 502,
          "error": "ERR_CONNECTION_REFUSED_PORT_CLOSED"
        },
        {
          "request_id": "req-02",
          "arrival_time": 1.2,
          "status": "CONNECTION_REFUSED",
          "http_status": 502,
          "error": "ERR_CONNECTION_REFUSED_PORT_CLOSED"
        },
        {
          "request_id": "req-03",
          "arrival_time": 2.8,
          "status": "CONNECTION_REFUSED",
          "http_status": 502,
          "error": "ERR_CONNECTION_REFUSED_PORT_CLOSED"
        },
        {
          "request_id": "req-04",
          "arrival_time": 3.2,
          "status": "ROUTED_TO_OTHER_REPLICA",
          "http_status": 200,
          "error": null
        }
      ]
    }
  ]
}
```

---

### 예시 2

#### 입력
```json
{
  "scenarios": [
    {
      "scenario_id": "prestop_5s_graceful_drain",
      "pod_config": {
        "pod_name": "checkout-api-v2-6c9fa",
        "pre_stop_delay_sec": 5.0,
        "termination_grace_period_sec": 30.0,
        "app_drain_timeout_sec": 15.0,
        "app_shutdown_behavior": "graceful"
      },
      "network_config": {
        "endpoint_deregistration_delay_sec": 3.0
      },
      "events": [
        { "time": 0.0, "type": "POD_TERMINATION_REQUESTED" },
        { "time": 0.5, "type": "INCOMING_REQUEST", "request_id": "req-01", "duration_sec": 0.5 },
        { "time": 1.2, "type": "INCOMING_REQUEST", "request_id": "req-02", "duration_sec": 0.8 },
        { "time": 2.8, "type": "INCOMING_REQUEST", "request_id": "req-03", "duration_sec": 1.2 },
        { "time": 3.5, "type": "INCOMING_REQUEST", "request_id": "req-04", "duration_sec": 0.5 }
      ]
    }
  ]
}
```

#### 출력
```json
{
  "summary": {
    "total_scenarios": 1,
    "zero_downtime_scenarios": 1,
    "failed_scenarios": 0,
    "total_502_errors": 0,
    "total_504_errors": 0
  },
  "scenarios": [
    {
      "scenario_id": "prestop_5s_graceful_drain",
      "pod_name": "checkout-api-v2-6c9fa",
      "has_downtime_or_errors": false,
      "container_exit_time": 5.0,
      "sigterm_sent_time": 5.0,
      "sigkill_sent_time": null,
      "endpoint_deregistered_time": 3.0,
      "stats": {
        "total_requests": 4,
        "successful_requests": 4,
        "failed_requests": 0,
        "bad_gateway_502_count": 0,
        "gateway_timeout_504_count": 0
      },
      "request_results": [
        {
          "request_id": "req-01",
          "arrival_time": 0.5,
          "status": "COMPLETED",
          "http_status": 200,
          "error": null
        },
        {
          "request_id": "req-02",
          "arrival_time": 1.2,
          "status": "COMPLETED",
          "http_status": 200,
          "error": null
        },
        {
          "request_id": "req-03",
          "arrival_time": 2.8,
          "status": "COMPLETED",
          "http_status": 200,
          "error": null
        },
        {
          "request_id": "req-04",
          "arrival_time": 3.5,
          "status": "ROUTED_TO_OTHER_REPLICA",
          "http_status": 200,
          "error": null
        }
      ]
    }
  ]
}
```
