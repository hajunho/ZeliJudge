# 130. keepalive 32를 줬는데 왜 백엔드 소켓이 10만 개까지 치솟고 로컬 포트가 말라죽어요?!: Nginx 리버스 프록시 Upstream Keepalive 커넥션 풀과 HTTP/1.0 Close 트랩

## 문제 설명

이커머스 스타트업의 주니어 백엔드/인프라 엔지니어 젤리(Zeli)는 연중 최대 할인 프로모션을 앞두고 Nginx 리버스 프록시(Reverse Proxy) 뒤에 3대의 스프링 부트(Spring Boot) 백엔드 API 서버를 연결했습니다.  
백엔드와의 TCP 연결 오버헤드를 줄이기 위해 Nginx 공식 문서를 참고하여 `upstream` 블록에 커넥션 풀 설정인 `keepalive 32;`를 야심 차게 추가했습니다:

```nginx
# /etc/nginx/conf.d/api.conf
upstream backend_servers {
    server 10.0.1.10:8080;
    server 10.0.1.11:8080;
    server 10.0.1.12:8080;
    keepalive 32; # 🌟 젤리가 추가한 업스트림 커넥션 풀 설정!
}

server {
    listen 80;
    location /api/ {
        proxy_pass http://backend_servers;
    }
}
```

*"upstream에 `keepalive 32`를 줬으니 Nginx가 백엔드와 연결을 32개씩 유지하면서 초고속으로 재사용하겠지?!"* 😎

하지만 프로모션 오픈 5분 만에 서버가 먹통이 되며 Nginx 에러 로그에 충격적인 메시지가 도배되었습니다! 🚨

```
[error] 2104#2104: *49102 connect() to 10.0.1.10:8080 failed 
(99: Cannot assign requested address) while connecting to upstream, 
client: 203.0.113.19, server: api.zeli.shop, request: "GET /api/products HTTP/1.1", 
upstream: "http://10.0.1.10:8080/api/products"
```

황급히 서버에 접속하여 네트워크 소켓 상태를 확인한 젤리는 자신의 눈을 의심했습니다:

```bash
$ netstat -nat | grep TIME_WAIT | wc -l
28232  # ⚠️ 리눅스 임시 포트(Ephemeral Port) 28,232개가 100% 전부 잠겨 있음!
```

Nginx가 백엔드로 새 TCP 연결을 맺으려고 할 때마다 쓸 수 있는 로컬 포트가 단 1개도 남아있지 않아 **`Cannot assign requested address` (EADDRNOTAVAIL, 에러 코드 99)**를 뿜어내며 모든 요청을 502 에러로 떨어뜨린 것입니다! 😱

*"분명히 `keepalive 32;`를 설정했는데 왜 연결이 전혀 재사용되지 않고 수만 개의 TIME_WAIT 소켓이 쌓여 로컬 포트가 말라죽은 걸까요?!"*

---

### 왜 이런 참사가 발생했을까? (Nginx의 HTTP/1.0 Close 트랩)

이 참사의 원인은 Nginx 공식 문서에 적힌 충격적인 동작 사양 때문입니다:

> **Nginx Official Documentation**:  
> *"The `keepalive` directive does not limit the total number of connections to upstream servers... For HTTP, the `proxy_http_version` directive should be set to `"1.1"` and the `"Connection"` header field should be cleared:"*

```nginx
# ❌ 젤리가 작성한 설정 (Keepalive 100% 무력화!)
location /api/ {
    proxy_pass http://backend_servers;
}

# ✅ 반드시 적어야 하는 올바른 설정 (Keepalive 정상 동작!)
location /api/ {
    proxy_pass http://backend_servers;
    proxy_http_version 1.1;         # 1. HTTP/1.1 사용 선언
    proxy_set_header Connection ""; # 2. Nginx 기본 close 헤더 제거!
}
```

#### 1. Nginx의 기본 프록시 프로토콜은 HTTP/1.0이다
- `proxy_http_version`의 Nginx 기본값은 **`1.0`**입니다 (`GET / HTTP/1.0`).
- HTTP/1.0 사양(RFC 1945)은 원칙적으로 매 요청 후 연결을 끊는 것(`Connection: close`)이 기본입니다.

#### 2. Nginx는 기본적으로 `Connection: close` 헤더를 강제한다
- 클라이언트가 Nginx로 아무리 `Connection: keep-alive`를 보내도, Nginx는 백엔드로 요청을 넘길 때 **헤더를 `Connection: close`로 강제 덮어쓰기**하여 전송합니다!
- 백엔드 웹서버는 이 헤더를 보고 응답 전송 직후 TCP FIN을 보내어 연결을 즉시 끊어버립니다.

#### 3. 에페머럴 포트 고갈(Ephemeral Port Exhaustion)의 수학
- 리눅스 커널의 아웃바운드 임시 포트(Ephemeral Port) 범위는 보통 `32768 ~ 60999` (총 **28,232개**)입니다.
- TCP 연결이 정상 종료되면 지연 패킷 충돌을 방지하기 위해 소켓은 60초(2MSL) 동안 **`TIME_WAIT` 상태로 묶여 포트를 반환하지 않습니다**.
- 초당 500개의 요청이 들어올 때 연결이 매번 닫히면:
  $$\text{60초 동안 누적 소켓} = 500 \times 60 = 30,000\text{개}$$
- 가용 포트(28,232개)를 초과하여 **불과 56초 만에 서버의 모든 포트가 100% 고갈**됩니다!

#### 4. 구원투수: 두 줄의 마법
`proxy_http_version 1.1;`과 `proxy_set_header Connection "";`를 추가하면:
- Nginx는 백엔드와의 사이에 최대 32개의 유휴 연결을 메모리 풀에 상시 보관합니다.
- 새 요청이 오면 3-Way Handshake(1 RTT, 10~50ms) 없이 **0ms 만에 소켓을 재사용**합니다!
- 소켓 재사용률 **95%+**, 상시 점유 포트 32개 내외로 수렴, TIME_WAIT 전멸!

---

## 과제

당신은 Nginx 리버스 프록시의 업스트림 커넥션 풀 및 소켓 라이프사이클을 시뮬레이션하는 **"Nginx Upstream Keepalive Simulator"**를 구현해야 합니다.

Nginx 설정, 네트워크 환경(핸드셰이크 지연 시간, 가용 포트 범위, TIME_WAIT 지속 시간), 그리고 유입되는 트래픽 목록이 주어질 때, 커넥션 풀 동작 및 에페머럴 포트 고갈 여부를 판정하고 종합 통계를 산출하십시오.

---

### 입력 형식 (JSON)

표준 입력(stdin)으로 다음 구조의 JSON 객체가 주어집니다:

```json
{
  "nginx_config": {
    "proxy_http_version": "1.0",
    "proxy_set_header_connection": "default",
    "upstream_keepalive_pool_size": 32,
    "keepalive_timeout_sec": 60.0,
    "keepalive_requests": 100
  },
  "network_config": {
    "handshake_latency_ms": 10.0,
    "ephemeral_port_range": { "min": 32768, "max": 60999 },
    "time_wait_duration_sec": 60.0
  },
  "traffic": [
    {
      "time": 0.0,
      "request_id": "req-01",
      "duration_ms": 20.0
    }
  ]
}
```

- `nginx_config`:
  - `proxy_http_version`: 프록시 HTTP 버전 (`"1.0"` | `"1.1"`)
  - `proxy_set_header_connection`: Connection 헤더 정책 (`"default"`: Nginx 기본 close 전달 | `"empty"`: 빈 문자열 `""`로 헤더 제거)
  - `upstream_keepalive_pool_size`: 유휴 커넥션 풀 최대 크기 (정수 $\ge 0$)
  - `keepalive_timeout_sec`: 유휴 커넥션 최대 유지 시간(초, 실수 $\ge 0.0$)
  - `keepalive_requests`: 단일 연결당 최대 처리 가능 요청 수 (정수 $\ge 1$)
- `network_config`:
  - `handshake_latency_ms`: 신규 TCP 연결 시 소요되는 3-Way Handshake 왕복 지연 시간(ms, 실수 $\ge 0.0$)
  - `ephemeral_port_range`: 가용 임시 포트 범위 (`min`, `max`, 총 가용 포트 수 $N = \text{max} - \text{min} + 1$)
  - `time_wait_duration_sec`: 연결 종료 후 소켓이 TIME_WAIT 상태로 포트를 점유하는 시간(초, 실수 $\ge 0.0$)
- `traffic`: 유입 요청 목록
  - `time`: 요청 도착 시각(초)
  - `request_id`: 요청 고유 ID
  - `duration_ms`: 백엔드 서버의 순수 요청 처리 시간(ms, 실수 $\ge 0.0$)

---

### 시뮬레이션 규칙

1. **Keepalive 활성화 조건**:
   - `proxy_http_version == "1.1"` AND `proxy_set_header_connection == "empty"` AND `upstream_keepalive_pool_size > 0`을 **모두 만족할 때만** Keepalive가 활성화됩니다 (`keepalive_active = true`).
   - 하나라도 만족하지 못하면 Keepalive는 비활성화됩니다 (`keepalive_active = false`).

2. **요청 도착 시 커넥션 획득 로직**:
   - 유효하지 않은(유휴 시간 > `keepalive_timeout_sec`) 유휴 연결들을 먼저 풀에서 정리하여 `TIME_WAIT` 상태로 보냅니다.
   - **Keepalive 활성 상태이고 유휴 풀에 연결이 있는 경우**:
     - 풀에서 가장 최근에 보관된 연결(LIFO)을 꺼냅니다.
     - 핸드셰이크 지연 시간: **0.0 ms** (소켓 재사용!)
     - `is_reused`: `true`
     - 해당 연결의 `requests_served += 1`
   - **Keepalive 비활성이거나 유휴 풀이 비어있는 경우**:
     - 새로운 TCP 연결을 생성해야 합니다.
     - 현재 할당 중인 포트 수(활성 처리 중 + 유휴 풀 보관 중 + TIME_WAIT 점유 중)가 전체 가용 포트 수($N$) 이상이면:
       - **에페머럴 포트 고갈 발생!**
       - `status`: `"FAILED"`, `error`: `"ERR_EPHEMERAL_PORT_EXHAUSTION"`, `is_reused`: `false`, `latency_ms`: 0.0
       - 이 요청은 즉시 실패 처리됩니다.
     - 가용 포트가 남아있다면:
       - 포트 1개를 할당하고 신규 연결을 맺습니다.
       - 핸드셰이크 지연 시간: `handshake_latency_ms`
       - `is_reused`: `false`
       - 총 지연 시간 `latency_ms = handshake_latency_ms + duration_ms`
   - 요청 완료 시각: $t_{\text{finish}} = t_{\text{arrival}} + (\text{latency\_ms} / 1000.0)$

3. **요청 완료 시 커넥션 반환 및 종료 로직**:
   - **Keepalive 활성 상태인 경우**:
     - 해당 연결의 `requests_served >= keepalive_requests`이면:
       - 최대 요청 한도 도달! 소켓을 닫고 $t_{\text{finish}}$부터 `time_wait_duration_sec` 동안 `TIME_WAIT` 상태로 진입합니다.
     - 아직 한도가 남았으면:
       - 풀에 보관된 만료 연결들을 먼저 정리합니다.
       - 현재 유휴 풀 크기가 `upstream_keepalive_pool_size` 이상이면:
         - 풀이 가득 찼으므로 가장 오래된 유휴 연결(index 0)을 축출(Evict)하여 닫고 `TIME_WAIT`로 보냅니다.
       - 이번 요청을 처리한 연결을 유휴 풀에 넣고 `last_used_time = t_finish`로 갱신합니다.
   - **Keepalive 비활성 상태인 경우**:
     - 요청이 끝나자마자 연결을 닫고 $t_{\text{finish}}$부터 `time_wait_duration_sec` 동안 `TIME_WAIT` 상태로 진입합니다.

4. **TIME_WAIT 만료**:
   - $t_{\text{close}} + \text{time\_wait\_duration\_sec}$ 시점에 도달하면 포트가 완전히 반환되어 다시 사용 가능해집니다.

---

### 출력 형식 (JSON)

표준 출력(stdout)으로 다음 구조의 JSON 객체를 출력합니다 (인덴트 2칸):

```json
{
  "summary": {
    "keepalive_active": false,
    "total_requests": 15,
    "successful_requests": 10,
    "failed_requests": 5,
    "connection_reuse_ratio_pct": 0.0,
    "new_connections_created": 10,
    "peak_time_wait_sockets": 10,
    "peak_allocated_ports": 10,
    "average_latency_ms": 30.0
  },
  "requests": [
    {
      "request_id": "req-00",
      "time": 0.0,
      "status": "SUCCESS",
      "error": null,
      "is_reused": false,
      "latency_ms": 30.0
    },
    {
      "request_id": "req-10",
      "time": 0.1,
      "status": "FAILED",
      "error": "ERR_EPHEMERAL_PORT_EXHAUSTION",
      "is_reused": false,
      "latency_ms": 0.0
    }
  ]
}
```

---

## 입출력 예시

### 예시 1 (주니어의 실수: HTTP/1.0 Close 트랩으로 인한 포트 고갈)

#### 입력
```json
{
  "nginx_config": {
    "proxy_http_version": "1.0",
    "proxy_set_header_connection": "default",
    "upstream_keepalive_pool_size": 32,
    "keepalive_timeout_sec": 60.0,
    "keepalive_requests": 100
  },
  "network_config": {
    "handshake_latency_ms": 10.0,
    "ephemeral_port_range": { "min": 32768, "max": 32777 },
    "time_wait_duration_sec": 10.0
  },
  "traffic": [
    { "time": 0.0, "request_id": "req-00", "duration_ms": 20.0 },
    { "time": 0.01, "request_id": "req-01", "duration_ms": 20.0 },
    { "time": 0.02, "request_id": "req-02", "duration_ms": 20.0 },
    { "time": 0.03, "request_id": "req-03", "duration_ms": 20.0 },
    { "time": 0.04, "request_id": "req-04", "duration_ms": 20.0 },
    { "time": 0.05, "request_id": "req-05", "duration_ms": 20.0 },
    { "time": 0.06, "request_id": "req-06", "duration_ms": 20.0 },
    { "time": 0.07, "request_id": "req-07", "duration_ms": 20.0 },
    { "time": 0.08, "request_id": "req-08", "duration_ms": 20.0 },
    { "time": 0.09, "request_id": "req-09", "duration_ms": 20.0 },
    { "time": 0.1, "request_id": "req-10", "duration_ms": 20.0 }
  ]
}
```

#### 출력
```json
{
  "summary": {
    "keepalive_active": false,
    "total_requests": 11,
    "successful_requests": 10,
    "failed_requests": 1,
    "connection_reuse_ratio_pct": 0.0,
    "new_connections_created": 10,
    "peak_time_wait_sockets": 10,
    "peak_allocated_ports": 10,
    "average_latency_ms": 30.0
  },
  "requests": [
    {
      "request_id": "req-00",
      "time": 0.0,
      "status": "SUCCESS",
      "error": null,
      "is_reused": false,
      "latency_ms": 30.0
    },
    {
      "request_id": "req-10",
      "time": 0.1,
      "status": "FAILED",
      "error": "ERR_EPHEMERAL_PORT_EXHAUSTION",
      "is_reused": false,
      "latency_ms": 0.0
    }
  ]
}
```

---

### 예시 2 (시니어의 구원: HTTP/1.1 및 Connection "" 설정)

#### 입력
```json
{
  "nginx_config": {
    "proxy_http_version": "1.1",
    "proxy_set_header_connection": "empty",
    "upstream_keepalive_pool_size": 32,
    "keepalive_timeout_sec": 60.0,
    "keepalive_requests": 100
  },
  "network_config": {
    "handshake_latency_ms": 10.0,
    "ephemeral_port_range": { "min": 32768, "max": 32777 },
    "time_wait_duration_sec": 10.0
  },
  "traffic": [
    { "time": 0.0, "request_id": "req-00", "duration_ms": 20.0 },
    { "time": 0.01, "request_id": "req-01", "duration_ms": 20.0 },
    { "time": 0.02, "request_id": "req-02", "duration_ms": 20.0 },
    { "time": 0.03, "request_id": "req-03", "duration_ms": 20.0 },
    { "time": 0.04, "request_id": "req-04", "duration_ms": 20.0 },
    { "time": 0.05, "request_id": "req-05", "duration_ms": 20.0 },
    { "time": 0.06, "request_id": "req-06", "duration_ms": 20.0 },
    { "time": 0.07, "request_id": "req-07", "duration_ms": 20.0 },
    { "time": 0.08, "request_id": "req-08", "duration_ms": 20.0 },
    { "time": 0.09, "request_id": "req-09", "duration_ms": 20.0 },
    { "time": 0.1, "request_id": "req-10", "duration_ms": 20.0 }
  ]
}
```

#### 출력
```json
{
  "summary": {
    "keepalive_active": true,
    "total_requests": 11,
    "successful_requests": 11,
    "failed_requests": 0,
    "connection_reuse_ratio_pct": 72.73,
    "new_connections_created": 3,
    "peak_time_wait_sockets": 0,
    "peak_allocated_ports": 3,
    "average_latency_ms": 22.73
  },
  "requests": [
    {
      "request_id": "req-00",
      "time": 0.0,
      "status": "SUCCESS",
      "error": null,
      "is_reused": false,
      "latency_ms": 30.0
    },
    {
      "request_id": "req-10",
      "time": 0.1,
      "status": "SUCCESS",
      "error": null,
      "is_reused": true,
      "latency_ms": 20.0
    }
  ]
}
```
