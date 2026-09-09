# Nginx 리버스 프록시 Upstream Keepalive 커넥션 풀과 HTTP/1.0 Close 트랩

> **"Nginx upstream 설정에 `keepalive 32;`를 분명히 적어뒀는데, 왜 트래픽이 몰리면 백엔드 소켓이 10만 개까지 치솟고 `Cannot assign requested address` 에러로 서버가 폭사할까요?!"**  
> Nginx를 리버스 프록시(Reverse Proxy)로 운영하는 수많은 개발자와 데브옵스 엔지니어가 겪는 가장 악명 높은 실무 함정이 바로 **"Nginx의 HTTP/1.0 Close 트랩"**입니다.

---

## 1. 실무 참사 시나리오: 50,000개의 TIME_WAIT 좀비 소켓

스타트업 백엔드 엔지니어 젤리(Zeli)는 대규모 프로모션을 앞두고 Nginx 뒤에 Spring Boot / Tomcat API 서버 3대를 연결했습니다.  
Nginx 공식 문서를 보고 업스트림 커넥션 풀링을 켜기 위해 `upstream` 블록에 `keepalive 32;`를 추가했습니다:

```nginx
# /etc/nginx/nginx.conf
upstream backend_servers {
    server 10.0.1.10:8080;
    server 10.0.1.11:8080;
    server 10.0.1.12:8080;
    keepalive 32; # 🌟 젤리가 추가한 회심의 설정!
}

server {
    listen 80;
    location /api/ {
        proxy_pass http://backend_servers;
    }
}
```

*"이제 Nginx가 백엔드 서버와 32개의 연결을 계속 유지하면서 재사용하겠지?!"* 😎

하지만 프로모션 오픈 10분 후, 서버에서 엄청난 에러가 뿜어져 나오기 시작했습니다:
- **Nginx 에러 로그**:
  ```
  [error] 2104#2104: *49102 connect() to 10.0.1.10:8080 failed 
  (99: Cannot assign requested address) while connecting to upstream
  ```
- **서버 터미널 모니터링**:
  ```bash
  $ netstat -nat | grep TIME_WAIT | wc -l
  28232  # ⚠️ 리눅스 임시 포트(Ephemeral Port) 28,232개가 100% 고갈됨!
  ```

Nginx가 백엔드로 새로운 연결을 맺으려고 할 때마다 쓸 수 있는 로컬 포트가 1개도 남아있지 않아 **`Cannot assign requested address` (EADDRNOTAVAIL, 에러 코드 99)**를 뱉어내며 전사 서비스가 다운된 것입니다!

---

## 2. 왜 `keepalive 32;`가 전혀 작동하지 않았을까? (HTTP/1.0 Close 트랩)

Nginx 공식 문서의 주의사항에는 다음과 같은 치명적인 설명이 적혀 있습니다:

> **Nginx Official Documentation**:  
> *"The `keepalive` directive does not limit the total number of connections to upstream servers... For HTTP, the `proxy_http_version` directive should be set to `"1.1"` and the `"Connection"` header field should be cleared:"*

```nginx
# ❌ 젤리가 적은 코드 (Keepalive 100% 무력화!)
location /api/ {
    proxy_pass http://backend_servers;
}

# ✅ 반드시 적어야 하는 코드 (Keepalive 정상 동작!)
location /api/ {
    proxy_pass http://backend_servers;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

### 왜 이 두 줄이 없으면 Keepalive가 무력화될까?

1. **Nginx의 기본 프록시 프로토콜은 HTTP/1.0이다**:
   - `proxy_http_version`을 명시하지 않으면 Nginx는 백엔드로 요청을 보낼 때 **HTTP/1.0**을 사용합니다 (`GET / HTTP/1.0`).
   - HTTP/1.0 사양(RFC 1945)은 원칙적으로 매 요청마다 연결을 끊는 것이 기본(`Connection: close`)입니다.
2. **Nginx는 기본적으로 `Connection: close` 헤더를 백엔드로 보낸다**:
   - 클라이언트(브라우저/앱)가 Nginx로 아무리 `Connection: keep-alive`를 보내도, Nginx는 백엔드로 패킷을 보낼 때 **헤더를 `Connection: close`로 덮어써서 전송**합니다!
   - 백엔드 웹서버(Tomcat, Netty, FastAPI 등)는 이 헤더를 보고 응답 직후 TCP 소켓을 즉시 닫아버립니다 (`FIN` 전송).
3. **결과**:
   - Nginx는 매 요청마다 새로운 TCP 3-Way Handshake(SYN $	o$ SYN/ACK $	o$ ACK)를 맺고,
   - 응답을 받자마자 소켓을 닫아 **커넥션 풀 재사용률 0.0%**를 기록하며,
   - 닫힌 소켓은 60초(2MSL) 동안 **`TIME_WAIT` 상태로 묶여 로컬 포트를 영구 점유**하게 됩니다!

---

## 3. 에페머럴 포트 고갈(Ephemeral Port Exhaustion)의 수학

리눅스 커널에서 외부 서버로 아웃바운드 TCP 연결을 맺을 때 사용할 수 있는 로컬 임시 포트(Ephemeral Port) 범위는 보통 다음과 같습니다:

```bash
$ cat /proc/sys/net/ipv4/ip_local_port_range
32768   60999   # 총 28,232개
```

- TCP 연결이 정상 종료되면 소켓은 지연 패킷(Duplicate Segment)과의 충돌을 방지하기 위해 **60초 동안 `TIME_WAIT` 상태**로 머뭅니다.
- 만약 초당 500개의 요청이 Nginx로 유입되고 Keepalive가 꺼져 있다면:
  $$	ext{1초당 소모 포트} = 500	ext{개}$$
  $$	ext{60초 동안 누적되는 TIME\_WAIT 소켓} = 500 	imes 60 = 30,000	ext{개}$$
- 가용 포트가 28,232개뿐이므로, **불과 56초 만에 시스템의 모든 포트가 바닥나고(100% 고갈)** 그 이후의 모든 요청은 Nginx가 백엔드에 연결조차 못 해보고 502 에러로 터지게 됩니다!

---

## 4. 구원투수: `proxy_http_version 1.1`과 `proxy_set_header Connection ""`

```nginx
location /api/ {
    proxy_pass http://backend_servers;
    proxy_http_version 1.1;         # 1. HTTP/1.1 사용 선언
    proxy_set_header Connection ""; # 2. Nginx 기본 close 헤더 제거!
}
```

이 두 줄을 추가하면 다음과 같은 기적이 일어납니다:

1. **소켓 재사용 (Connection Reuse)**:
   - Nginx 워커 프로세스는 백엔드 서버당 최대 `keepalive`(예: 32개)개의 유휴(Idle) 소켓을 메모리 풀에 보관합니다.
   - 새 요청이 들어오면 TCP 3-Way Handshake를 생략하고 풀에 있던 소켓을 즉시 꺼내어 재사용합니다 (**핸드셰이크 지연 0ms!**).
2. **소켓 반환 및 보관**:
   - 응답이 끝나면 소켓을 닫지 않고 다시 유휴 풀에 집어넣습니다.
   - 풀이 꽉 찼을 경우에만 가장 오래된 소켓(LRU)을 정상 종료합니다.
3. **결과**:
   - 소켓 재사용률 **95% ~ 99% 달성**!
   - 1초에 10만 건이 쏟아져도 상시 열려있는 소켓은 고작 32개 내외로 유지됨!
   - `TIME_WAIT` 소켓이 거의 발생하지 않아 **에페머럴 포트 고갈이 완전히 소멸**하고, RTT 왕복 시간이 사라져 p99 응답 지연이 대폭 감소합니다.
