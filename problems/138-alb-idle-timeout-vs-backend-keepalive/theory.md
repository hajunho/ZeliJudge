# 간헐적으로 502 Bad Gateway가 떠요?!: 로드밸런서(ALB) Idle Timeout vs 백엔드 Keep-Alive Timeout 불일치 레이스 컨디션

> "AWS ALB(Application Load Balancer) 뒤에 Node.js/Spring Boot 백엔드 서버를 띄워 서비스를 운영 중입니다.  
> CPU 사용률은 10% 미만이고 메모리도 넉넉하며, 백엔드 애플리케이션 로그에는 어떤 에러도 찍히지 않습니다.  
> 그런데 신기하게도 **1분에 서너 번씩, 유저들에게 간헐적인 '502 Bad Gateway' 에러가 불규칙하게 발생**합니다!  
> 새로고침하면 다시 잘 되는데, 도대체 왜 아무 에러 로그도 없이 502 에러가 터지는 걸까요?!"

---

## 1. 전설의 '유령 502 Bad Gateway' (Phantom 502 Mystery)

AWS ALB, Nginx, GCP Cloud Load Balancing, Cloudflare 등 **L7 리버스 프록시 / 로드밸런서**를 도입한 모든 기업에서 시니어 엔지니어들을 가장 오랜 시간 골머리 썩이게 만드는 버그가 바로 **간헐적 502 Bad Gateway**입니다.

이 장애의 가장 악랄한 특징은 다음과 같습니다:
1. **백엔드 애플리케이션 로그에 아무것도 찍히지 않는다**:  
   요청이 백엔드 웹 애플리케이션 코드(Spring Controller, Express Handler)에 도달조차 하지 못하고 OS 커널 TCP 계층에서 튕겨 나가기 때문에 `error.log`가 완전히 깨끗합니다.
2. **트래픽이 폭주할 때보다 어중간할 때 더 자주 발생한다**:  
   초당 수천 건이 들어올 때는 커넥션이 쉴 틈 없이 쓰여 문제가 없다가, 요청 간격이 몇 초~수십 초 단위로 뜸해질 때(유휴 상태) 집중적으로 터집니다.

이 미스터리한 참사의 원인은 바로 **로드밸런서의 유휴 타임아웃(Idle Timeout)과 백엔드의 지속 연결 타임아웃(Keep-Alive Timeout)의 미세한 불일치로 인한 TCP 레이스 컨디션(Race Condition)**입니다.

---

## 2. HTTP Keep-Alive와 커넥션 풀링(Connection Pooling)

클라이언트가 로드밸런서로 요청을 보내면, 로드밸런서는 백엔드 서버와 **HTTP Keep-Alive 지속 연결**을 맺고 커넥션 풀에 보관하여 다음 요청 시 TCP 3-Way Handshake 비용을 아낍니다.

```
[클라이언트] ──► [AWS ALB (로드밸런서)] ──(Keep-Alive 커넥션 풀)──► [백엔드 서버 (Node.js/Tomcat)]
```

하지만 무한정 커넥션을 열어둘 수는 없으므로, 양쪽 모두 **"일정 시간 동안 아무 요청이 없으면 커넥션을 닫는다"**는 타이머를 둡니다:
- **ALB Idle Timeout**: 로드밸런서 입장에서 유휴 커넥션을 유지하는 시간 (AWS 기본값: **60초**)
- **Backend Keep-Alive Timeout**: 백엔드 서버가 유휴 커넥션을 유지하는 시간  
  - Node.js 기본값: 과거 **5초** (현재 65초 권장)
  - Tomcat 기본값: 20초 ~ 60초
  - Nginx 기본값: 65초 ~ 75초

---

## 3. 치명적 충돌: 엇갈리는 패킷과 TCP RST 폭풍

만약 **ALB Idle Timeout(60초)**과 **백엔드 Keep-Alive Timeout(60초)**을 동일하게 설정했거나, 백엔드 타임아웃이 더 짧다면 어떤 일이 벌어질까요?

### ⏱️ 시간대별 레이스 컨디션 추적
- $T = 0	ext{초}$: 첫 번째 요청이 정상 완료되고, 커넥션이 유휴(IDLE) 상태로 전환됩니다.
- $T = 60.000	ext{초}$: **백엔드 서버의 60초 타이머 만료!**  
  백엔드는 "60초 동안 요청이 없었으니 이 소켓을 닫겠다"라며 커널 소켓을 닫고 ALB를 향해 `FIN` 패킷을 전송합니다.
- $T = 60.001	ext{초}$: **ALB에 새로운 유저 요청 도착!**  
  ALB는 백엔드가 보낸 `FIN` 패킷을 아직 수신하지 못했습니다 (네트워크 전파 지연 2ms 필요).  
  ALB 입장에서는 "마지막 요청이 59.999초 전이었으니 커넥션이 아직 살아있네!"라고 판단하고, **방금 닫힌 커넥션으로 유저의 새 HTTP 요청을 밀어 넣습니다!**

```
[AWS ALB]                                                      [백엔드 서버]
    │                                                               │
    │                                          (t=60.000s) ⏱️ 60초 타임아웃 만료!
    │                                                               │ 백엔드 소켓 close()
    │◄─────────────── [FIN 패킷] (전파 중...) ──────────────────────│ (상태: FIN_WAIT)
    │                                                               │
    │ (t=60.001s) 새 유저 요청 도착!                                │
    │ ALB: "커넥션 살아있네? 재사용!"                                 │
    │────────────► [HTTP GET 요청 패킷] ───────────────────────────►│
    │                                                               │
    │                 ═══════════════════════════                   │
    │                 네트워크 선로 위에서 패킷 교차!                │
    │                 ═══════════════════════════                   │
    │                                                               │
    │                                          (t=60.003s) HTTP 요청 패킷 도착!
    │                                          백엔드 커널: "어? 이미 close()된 소켓에
    │                                          데이터가 왜 들어와?! 비정상 접근이다!"
    │                                                               │
    │◄─────────────── [TCP RST (Reset) 강제 반환] ──────────────────│ 💥
    │                                                               │
(t=60.005s) ALB: "백엔드가 RST를 던지고 연결을 끊어버렸네?!"
ALB: 유저에게 즉시 [502 Bad Gateway] 반환! 💥
```

### 왜 백엔드 로그에는 아무것도 안 찍힐까?
백엔드 커널의 TCP 스택은 이미 애플리케이션 레벨에서 `close()`된 소켓으로 들어온 데이터에 대해 즉시 하드웨어 레벨의 **`RST`(Connection Reset)** 패킷을 회신합니다.  
애플리케이션(Spring/Node.js) 프로세스로 데이터가 전달조차 되지 않으므로, 백엔드에는 4xx나 5xx 에러 로그가 단 1줄도 남지 않는 것입니다!

---

## 4. 해결책: 로드밸런서 아키텍처의 황금률 (The Golden Rule)

AWS 공식 문서와 모든 클라우드 아키텍처 가이드가 명시하는 철칙은 다음과 같습니다:

> **"백엔드의 Keep-Alive Timeout은 반드시 로드밸런서의 Idle Timeout보다 엄격하게 길어야 한다!"**  
> $$	ext{Backend Keep-Alive Timeout} > 	ext{ALB Idle Timeout} + 	ext{Network Latency Buffer}$$

```
[타임아웃 설정의 정석]
- AWS ALB Idle Timeout: 60초
- 백엔드 Keep-Alive Timeout: 65초 이상 (보통 65초 ~ 75초 권장)
```

### 왜 이렇게 설정하면 502 에러가 완벽히 사라지는가?
1. 유휴 시간이 60초에 도달하면, **ALB가 백엔드보다 5초 먼저 유휴 커넥션을 능동적으로 닫습니다.**
2. ALB는 자신이 방금 닫은 커넥션 풀의 소켓을 절대 새 요청에 재사용하지 않습니다.
3. 60초 이후에 들어온 새 요청에 대해 ALB는 깨끗한 신규 TCP 커넥션을 맺어서 요청을 안전하게 전송합니다.
4. 백엔드가 먼저 커넥션을 끊어버리는 레이스 컨디션 상황 자체가 물리적으로 발생하지 않습니다!

---

## 5. 실무 서버별 설정 가이드

### ① Node.js (Express / Fastify)
Node.js HTTP 서버의 기본 Keep-Alive 타임아웃은 5초(`keepAliveTimeout = 5000`)로 매우 짧습니다. AWS ALB(60초) 뒤에 둘 경우 반드시 변경해야 합니다:
```javascript
const server = app.listen(port);
server.keepAliveTimeout = 65000;      // 65초 (ALB 60초보다 길게!)
server.headersTimeout = 66000;        // keepAliveTimeout보다 커야 함
```

### ② Spring Boot / Tomcat
`application.yml`:
```yaml
server:
  tomcat:
    connection-timeout: 65000         # 65초
    keep-alive-timeout: 65000         # 65초
```

### ③ Nginx (Upstream)
```nginx
keepalive_timeout 65s;               # ALB 60초 대비 65초
```
