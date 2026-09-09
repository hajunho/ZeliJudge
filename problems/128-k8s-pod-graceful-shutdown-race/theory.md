# 쿠버네티스 Pod Graceful Shutdown과 엔드포인트 등록 해제(Deregistration) 비동기 레이스 컨디션

> **"무중단 배포(Zero Downtime Rolling Update)를 걸어뒀는데, 왜 배포 시작 버튼만 누르면 502 Bad Gateway 에러가 수백 건씩 터지고 사용자 결제가 날아갈까요?!"**  
> 쿠버네티스(Kubernetes)를 처음 도입한 개발팀이 가장 흔하게 겪는 대표적인 실무 참사가 바로 **Pod 종료 시점의 비동기 엔드포인트 등록 해제(Endpoint Deregistration) 레이스 컨디션**입니다.

---

## 1. 무중단 배포의 환상과 502 Bad Gateway

쿠버네티스의 `Deployment` 리소스는 기본적으로 **롤링 업데이트(RollingUpdate)** 전략을 제공합니다.  
`maxSurge: 1`, `maxUnavailable: 0`과 같은 옵션을 주면 새 버전의 Pod가 정상 기동되어 헬스체크(Readiness Probe)를 통과한 후에 이전 버전의 Pod를 하나씩 종료하므로, 언뜻 보기에 트래픽이 100% 무중단으로 유지될 것처럼 보입니다.

하지만 실제 운영 환경에서 배포를 진행하면 다음과 같은 기현상이 발생합니다:

```
[클라이언트 모바일 앱 / 웹 브라우저 에러]
HTTP 502 Bad Gateway (or HTTP 504 Gateway Timeout)

[인그레스 컨트롤러(Nginx Ingress / ALB) 에러 로그]
[error] 1421#1421: *89201 connect() failed (111: Connection refused) 
while connecting to upstream, client: 10.0.1.5, server: api.zeli.shop, 
request: "POST /v1/checkout HTTP/1.1", upstream: "http://10.244.2.45:8080/v1/checkout"
```

인그레스가 이미 죽어버린 Pod의 IP(`10.244.2.45:8080`)로 트래픽을 전달하여 **`Connection Refused`**가 발생한 것입니다!

---

## 2. 쿠버네티스 Pod 삭제 라이프사이클의 두 갈래 길 (비동기 아키텍처)

이 문제가 발생하는 근본 원인은 **쿠버네티스 제어 평면(Control Plane)의 네트워크 라우팅 갱신**과 **워커 노드(Worker Node) Kubelet의 컨테이너 종료**가 **서로 완전히 독립적인 비동기(Asynchronous) 이벤트**로 병렬 실행되기 때문입니다.

Pod 종료 명령(`kubectl delete pod` 또는 롤링 배포에 의한 구버전 Pod 축출)이 내려지면, 쿠버네티스는 두 갈래 길을 동시에 걷습니다:

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

### 경로 A: 워커 노드의 Kubelet (컨테이너 종료)
1. Kubelet은 Pod 상태를 `Terminating`으로 변경합니다.
2. 컨테이너에 `preStop` 훅이 정의되어 있다면 이를 먼저 실행합니다.
3. `preStop`이 끝나면 메인 프로세스(PID 1)에 **`SIGTERM`** 시그널을 보냅니다.
4. 웹 프레임워크(Spring Boot, Node.js, Go 등)는 `SIGTERM`을 받자마자 **더 이상 새 요청을 받지 않기 위해 Listen 포트(8080)를 닫습니다**.
5. 만약 Pod 삭제 시작 후 `terminationGracePeriodSeconds`(기본 30초)가 지날 때까지 컨테이너가 살아있으면 Kubelet이 **`SIGKILL`**을 날려 강제 종료합니다.

### 경로 B: 마스터 노드의 제어 평면과 네트워크 프록시 (엔드포인트 제거)
1. API Server가 Pod 상태가 `Terminating`이 된 것을 감지합니다.
2. `Endpoint Controller`가 서비스의 `EndpointSlice`에서 해당 Pod의 IP를 제거합니다.
3. 이 변경 사항이 워커 노드들의 `kube-proxy`(iptables/IPVS)와 `Ingress Controller`(Nginx, Envoy, AWS ALB Controller)에 **네트워크를 통해 비동기 전파(Watch)**됩니다.
4. 인그레스 컨트롤러는 새 업스트림 설정을 리로드하거나 인메모리 엔드포인트 풀을 갱신합니다.
5. **이 모든 네트워크 전파와 설정 반영에는 네트워크 환경에 따라 약 2초에서 5초(때로는 10초)가 소요됩니다!**

---

## 3. 레이스 컨디션의 참사: 왜 502 Bad Gateway가 터질까?

만약 개발자가 Deployment 설정에 `preStop` 훅을 넣지 않았다면 어떤 일이 벌어질까요?

```
시간(초)   Kubelet (컨테이너)                      Ingress Controller (라우팅)
 0.0s    Pod 삭제 트리거 수신!                  Pod 삭제 감지 및 엔드포인트 갱신 시작
 0.1s    preStop 없음 -> 즉시 SIGTERM 발송!     전파 중... (아직 Pod IP 살아있음)
 0.2s    앱이 Listen 소켓(8080) 닫아버림!       전파 중... (아직 Pod IP 살아있음)
 0.5s    💥 클라이언트 신규 요청 도착! ---------> Ingress: "어? 엔드포인트 목록에 8080 있네? 전달!"
                                               -> 닫힌 소켓으로 패킷 전송 -> TCP RST!
                                               -> Ingress: "Connection refused?! 502 응답!"
 3.0s    앱 프로세스 완전 종료                   드디어 엔드포인트 갱신 완료 (Pod IP 제거)
```

- **레이스 컨디션 갭(Race Gap)**:
  - 컨테이너는 삭제 트리거 후 **0.2초 만에 포트를 닫았는데**,
  - 인그레스 컨트롤러는 엔드포인트 제거를 완료하는 데 **3.0초가 걸렸습니다**!
  - 이 차이($0.2s \sim 3.0s$) 사이에 들어온 모든 클라이언트 요청은 이미 닫힌 포트로 라우팅되어 **`Connection Refused (HTTP 502 Bad Gateway)`**를 맞게 됩니다.

---

## 4. 해결책: `preStop: sleep` 훅의 마법

이 끔찍한 레이스 컨디션을 해결하는 가장 우아하고 표준적인 방법은 **"Kubelet에게 일부러 잠(sleep)을 자라고 명령하는 것"**입니다!

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout-service
spec:
  replicas: 5
  template:
    spec:
      terminationGracePeriodSeconds: 45 # ⚠️ preStop + drain 시간보다 넉넉히 설정!
      containers:
        - name: app
          image: checkout-service:v2
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sleep", "5"] # 🌟 마법의 5초 슬립!
```

### 왜 `sleep 5`를 주면 해결될까?
1. Pod가 `Terminating` 상태가 되면, Kubelet은 `SIGTERM`을 바로 보내지 않고 **`/bin/sleep 5`를 5초 동안 실행**합니다.
2. **이 5초 동안 컨테이너 내부의 앱은 여전히 정상 가동 중이며 포트 8080도 활짝 열려 있습니다!**
3. 그 5초 사이에 경로 B(네트워크 제어 평면)가 인그레스 컨트롤러와 iptables에서 Pod IP를 완전히 제거합니다 (보통 2~3초 소요).
4. 엔드포인트가 제거되었으므로 **인그레스는 더 이상 새 트래픽을 이 Pod로 보내지 않습니다**.
5. 5초가 지나 `preStop`이 끝나면 비로소 Kubelet이 앱에 `SIGTERM`을 보냅니다.
6. 앱은 이미 들어와 있던 잔여 요청(In-flight Request)만 깔끔하게 처리(Drain)하고 안전하게 문을 닫습니다!
7. 결과적으로 **에러율 0.000%, 완벽한 무중단 배포(Zero Downtime)**가 달성됩니다!

---

## 5. `terminationGracePeriodSeconds`의 치명적 함정

많은 주니어들이 저지르는 또 다른 실수는 **Grace Period의 시작 시점**에 대한 오해입니다:

> ❌ **잘못된 생각**: "`preStop` 10초가 끝난 뒤부터 `terminationGracePeriodSeconds` 30초 타이머가 돌아가겠지?"  
> ✅ **실제 쿠버네티스 동작**: **`terminationGracePeriodSeconds` 타이머는 Pod 삭제가 시작된 바로 그 순간($t=0$)부터 즉시 카운트다운을 시작합니다!**

따라서 만약 다음과 같이 설정하면 대참사가 납니다:
- `preStop`: 10초
- 결제 API 최대 처리 시간: 15초
- `terminationGracePeriodSeconds`: 20초 (주니어가 "20초면 넉넉하겠지" 하고 줄여둠)

```
0s (삭제 시작, 타이머 20s 시작)
├─ 0s ~ 10s: preStop 실행 (남은 시간 10s)
├─ 10s: SIGTERM 전달, 앱이 15초짜리 결제 요청 처리 시작
└─ 20s: ⚠️ terminationGracePeriodSeconds 만료! -> Kubelet이 SIGKILL 발사!
        -> 결제 처리 중이던 스레드가 강제 사살됨! (DB 트랜잭션 파편화, 504 Timeout)
```

### 올바른 공식
$$	ext{terminationGracePeriodSeconds} \ge 	ext{preStop Delay} + 	ext{App Drain Timeout} + 	ext{Safety Buffer (5~10s)}$$

예: `preStop(5s)` + `App Drain(20s)` + `Buffer(10s)` = **최소 35초 이상** 설정해야 합니다.

---

## 6. 요약

1. **원인**: Pod 삭제 시 Kubelet의 `SIGTERM` 발송과 Ingress의 `Endpoint Deregistration`은 비동기로 병렬 실행되며, 네트워크 전파 지연($2 \sim 5$s)으로 인해 닫힌 포트로 트래픽이 인입되어 502 에러가 발생함.
2. **해결책**: `lifecycle.preStop.exec.command: ["/bin/sleep", "5"]`를 두어 라우팅 테이블에서 완전히 빠져나갈 때까지 `SIGTERM` 발송을 지연시킴.
3. **주의사항**: `terminationGracePeriodSeconds`는 `preStop` 실행 시간을 포함하므로, 둘의 합보다 항상 충분히 크게 잡아야 `SIGKILL`에 의한 요청 유실을 막을 수 있음.
