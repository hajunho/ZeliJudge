# 리버스 프록시 다계층 네트워크와 X-Forwarded-For 헤더 위조(IP Spoofing) 방어

> **"사내 관리자 페이지(`/admin`)를 사내 VPN IP `10.0.0.50`만 접속할 수 있게 막았는데, 왜 외부 해커에게 전사 데이터베이스가 털렸을까요?!"**  
> 백엔드 엔지니어가 클라우드 인프라(AWS ALB, Cloudflare, Nginx) 뒤에서 서비스할 때 가장 흔하게 저지르는 치명적 보안 취약점 중 하나가 **"X-Forwarded-For 첫 번째 IP 맹신으로 인한 IP 스푸핑(IP Spoofing)"** 참사입니다.

---

## 1. 문제의 발단: "택배 상자 발송지 스티커 위조 사기극"

실제 세계의 택배에 비유해 보면 이 취약점의 본질이 한눈에 보입니다:

1. **해커의 사기극**:
   - 사기꾼(해커)이 택배 상자를 보낼 때, 상자 겉면에 발송인 스티커로 **"청와대 비서실 (10.0.0.50)"**이라고 거짓으로 적어서 우체국에 접수합니다.
2. **경유지의 정직한 도장**:
   - 공인 우체국 A(AWS ALB)는 상자를 받고, "보낸 사람: 해커(203.0.113.195)" 도장을 상자 끝에 정직하게 덧찍어 물류센터 B(사내 Nginx)로 보냅니다.
   - 물류센터 B는 상자를 받고, "보낸 사람: 우체국 A(10.0.1.5)" 도장을 또 덧찍어 최종 수령자(Spring Boot 백엔드)에게 건넵니다.
3. **백엔드의 멍청한 판정**:
   - 상자를 받은 백엔드 개발자가 상자의 **"맨 첫 줄(청와대 비서실 10.0.0.50)"**만 읽고는,  
     *"와! 청와대에서 온 진짜 VIP 택배네! 비밀 문서 창고 문을 열어주자!"* 라며 관리자 페이지 권한을 넘겨준 것입니다! 😱

이것이 바로 `X-Forwarded-For.split(",")[0]`을 그대로 믿었을 때 발생하는 **IP 스푸핑 취약점(CWE-290: Authentication Bypass by Spoofing)**입니다.

---

## 2. 왜 리버스 프록시 뒤에서는 클라이언트 IP가 사라질까?

현대의 모든 상용 웹 서비스는 백엔드 서버가 인터넷에 직접 노출되지 않고 다계층 프록시 뒤에 숨어 있습니다:

```
[클라우드 웹 인프라의 일반적 요청 흐름]
사용자 (203.0.113.195)
     │
     ▼ (L4/L7 라우팅)
Cloudflare CDN (198.41.128.1)
     │
     ▼ (TLS 오프로딩 & 부하 분산)
AWS ALB / 로드밸런서 (10.0.1.5)
     │
     ▼ (리버스 프록시 / Ingress)
Nginx 웹 서버 (127.0.0.1)
     │
     ▼ (내부 TCP 소켓 연결)
Spring Boot / Node.js 백엔드 앱
```

백엔드 애플리케이션 입장에서 TCP 소켓 레벨의 연결 송신자(`request.remote_addr`)를 확인하면, 항상 바로 앞에 위치한 **`Nginx(127.0.0.1)`**나 **`ALB(10.0.1.5)`**의 내부 사설 IP만 보입니다!

이로 인해 두 가지 심각한 문제가 발생합니다:
- **문제 1**: 모든 사용자의 IP가 `127.0.0.1`로 보여서, 로그인 5회 실패 시 10분 차단하는 Rate Limiting을 걸었더니 전 세계 모든 유저가 동시에 로그인 차단당함.
- **문제 2**: 접속 국가별 분기(GeoIP), 부정 거래 탐지(FDS), 보안 감사 로그가 전부 엉망이 됨.

---

## 3. `X-Forwarded-For` (XFF / RFC 7239) 헤더의 탄생과 함정

이 문제를 해결하기 위해 표준 사실(De facto standard)로 도입된 것이 `X-Forwarded-For` HTTP 헤더입니다.
프록시 서버는 클라이언트의 요청을 다음 노드로 전달할 때, **자신에게 연결한 직전 송신자의 IP를 헤더 끝에 덧붙여서(Append)** 넘깁니다:

$$	ext{X-Forwarded-For: } 	ext{client}, 	ext{proxy}_1, 	ext{proxy}_2, \dots$$

### ⚠️ 치명적인 함정: HTTP 헤더는 클라이언트가 마음대로 적을 수 있다!
HTTP 헤더는 네트워크 계층의 패킷 헤더와 달리, **클라이언트(브라우저, Postman, curl, 파이썬 스크립트)가 원하는 대로 임의의 문자열을 적어서 보낼 수 있는 신뢰할 수 없는 데이터(Untrusted User Input)**입니다:

```bash
curl -H "X-Forwarded-For: 10.0.0.50" https://api.example.com/admin/users
```

해커가 위와 같이 악의적으로 위조된 헤더를 실어 보내면, AWS ALB는 해커의 실제 IP(`203.0.113.195`)를 그 뒤에 정직하게 덧붙여서 백엔드로 넘깁니다:
```http
X-Forwarded-For: 10.0.0.50, 203.0.113.195
```

이때 백엔드가:
```python
# ❌ 절대 하지 말아야 할 최악의 코드!
client_ip = request.headers["X-Forwarded-For"].split(",")[0].strip()
```
이렇게 **왼쪽 첫 번째 값(Leftmost)**을 가져오면, 해커가 조작해 넣은 `10.0.0.50`을 그대로 믿게 되어 보안 필터가 뚫리게 됩니다.

---

## 4. 올바른 구원 알고리즘: Right-to-Left Trusted Proxy Walking

진짜 클라이언트 IP를 안전하게 찾아내기 위해 전 세계 웹 서버(Nginx, Tomcat, Express, Envoy)가 채택한 표준 알고리즘은 **"오른쪽에서 왼쪽으로 역방향 신뢰 체인 탐색(Right-to-Left Trusted Proxy Walking)"**입니다.

### 핵심 원칙: "내가 신뢰하는 프록시(Trusted Proxies)의 말만 믿는다"
1. **신뢰할 수 있는 프록시 목록(Trusted Proxies) 사전 등록**:
   - 인프라 관리자는 내가 직접 제어하는 인프라 대역(예: VPC 사설망 `10.0.0.0/8`, 로컬호스트 `127.0.0.1`, Cloudflare 공인 IP 대역)을 백엔드에 미리 등록해 둡니다.
2. **역방향(오른쪽 $	o$ 왼쪽) 순회**:
   - 가장 오른쪽의 소켓 연결 IP(`socket_remote_addr`)부터 검사합니다.
   - 이 IP는 커널이 직접 맺은 TCP 연결이므로 위조가 불가능합니다.
   - **경우 A**: 만약 `socket_remote_addr`가 Trusted Proxy가 아니라면?  
     $	o$ 백엔드가 외부에 직접 노출되어 클라이언트와 직통 연결된 상태입니다.  
     $	o$ 따라서 헤더에 적힌 모든 값은 가짜이므로, **`socket_remote_addr` 자체가 진짜 클라이언트 IP**입니다!
   - **경우 B**: `socket_remote_addr`가 Trusted Proxy라면?  
     $	o$ 내가 신뢰하는 프록시이므로, 그 프록시가 헤더 맨 끝에 기록해 준 IP를 믿을 수 있습니다.  
     $	o$ 한 칸 왼쪽으로 이동하여 그 IP를 검사합니다!
3. **최초의 Untrusted IP 발견 시 즉시 종료 (The Anchor)**:
   - 오른쪽에서 왼쪽으로 거슬러 올라가다가, **처음으로 Trusted Proxy 목록에 속하지 않는 IP를 만나는 순간, 바로 그 IP가 진짜 클라이언트 IP(Real Client IP)**입니다!
   - **그 IP의 왼쪽에 적혀 있는 모든 값들은 그 외부 클라이언트가 직접 써서 보낸 것이므로 100% 무시하고 버려야 합니다.**

```
[Right-to-Left 역방향 신뢰 체인 검증]

XFF: [ 10.0.0.50 (가짜), 203.0.113.195 (해커) ]  |  Socket: 10.0.1.5 (ALB)
        ▲                      ▲                           ▲
        │                      │                           │
     [무시/버림]       [처음 만난 Untrusted!]          [Trusted Proxy]
                             │                           │
                             └─► 진짜 클라이언트 확정! ◄──┘
                                (검증 완료, 탐색 종료)
```

---

## 5. 실무 웹 프레임워크 설정 가이드

### 1) Nginx (`ngx_http_realip_module`)
```nginx
# 신뢰할 수 있는 상위 프록시 IP 대역 지정
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 192.168.0.0/16;

# 클라이언트 IP를 추출할 헤더 지정
real_ip_header X-Forwarded-For;

# 오른쪽부터 역방향으로 신뢰 프록시를 건너뛰도록 설정
real_ip_recursive on;
```

### 2) Spring Boot (`application.yml`)
```yaml
server:
  forward-headers-strategy: framework # 또는 native
  tomcat:
    remote-ip-header: X-Forwarded-For
    internal-proxies: "10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
```

### 3) Express.js (Node.js)
```javascript
// loopback, 사설망 대역을 신뢰할 수 있는 프록시로 등록
app.set('trust proxy', 'loopback, linklocal, uniquelocal');
// 또는 신뢰할 홉 수나 IP 서브넷 명시:
// app.set('trust proxy', ['10.0.0.0/8', '172.16.0.0/12']);
```

---

## 6. 핵심 요약 및 보안 체크리스트

1. **`X-Forwarded-For`의 첫 번째 값을 절대 믿지 마라**: 공격자가 헤더를 조작하여 IP 화이트리스트를 뚫을 수 있습니다.
2. **반드시 신뢰할 수 있는 프록시 목록(CIDR 서브넷)을 정의하라**: 신뢰할 수 없는 프록시가 보낸 XFF는 전체를 무시해야 합니다.
3. **역방향(Right-to-Left) 탐색으로 최초의 Untrusted IP를 찾아라**: 그 IP가 유일하게 검증된 실제 클라이언트 IP입니다.
