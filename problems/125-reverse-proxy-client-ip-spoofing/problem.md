# 125. 관리자 페이지를 사내 IP로 막았는데 왜 해커가 뚫려요?!: 리버스 프록시(Reverse Proxy) 다계층 네트워크와 X-Forwarded-For(XFF) 헤더 위조(IP Spoofing) 방어 & Trusted Proxy 역방향 체인 검증

## 문제 설명

스타트업 백엔드 개발자 젤리(Zeli)는 전사 회원 개인정보와 결제 내역을 열람할 수 있는 사내 백오피스 관리자 페이지(`/admin`)를 개발했습니다.  
보안을 강화하기 위해 사내 VPN 공인 IP인 `10.0.0.50`에서 유입된 요청만 접속을 허용하는 **IP 화이트리스트 보안 인터셉터**를 작성했습니다:

```python
# 젤리가 작성한 보안 필터 코드 (⚠️ 치명적인 결함 내포!)
def check_admin_access(request):
    # 클라이언트 IP 추출 시도
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        client_ip = xff.split(",")[0].strip() # 맨 앞 첫 번째 IP를 진짜 클라이언트 IP로 간주!
    else:
        client_ip = request.remote_addr

    if request.path.startswith("/admin"):
        if client_ip not in ADMIN_IP_WHITELIST:
            return 403, "Forbidden"
    return 200, "OK"
```

배포 후 며칠 뒤, 외부 해커가 관리자 페이지에 유유히 침투하여 수십만 명의 회원 DB를 덤프해 다크웹에 유출하는 **초대형 보안 참사**가 터졌습니다! 🚨  
보안 감사 팀이 침입 로그를 까보고 경악을 금치 못했습니다. 해커는 단지 HTTP 요청 헤더에 다음 단 한 줄을 추가했을 뿐이었습니다:

```http
GET /admin/dashboard HTTP/1.1
Host: api.example.com
X-Forwarded-For: 10.0.0.50
```

---

### 왜 이런 참사가 발생할까? (XFF 헤더 위조와 순진한 왼쪽 우선 탐색의 함정)

현대의 모든 상용 웹 서비스는 보안 및 성능을 위해 다계층 리버스 프록시(AWS ALB, Cloudflare, Nginx) 뒤에 애플리케이션 서버를 배치합니다:

```
[다계층 프록시 네트워크 흐름]
사용자 / 해커 (198.51.100.77)
     │
     ▼ (L7 로드밸런서)
AWS ALB (10.0.1.5)
     │
     ▼ (내부 TCP 소켓 연결)
Spring Boot / Flask 백엔드 서버
```

1. **소켓 IP의 한계**:  
   백엔드 서버가 운영체제 소켓 레벨의 연결 IP(`request.remote_addr`)를 읽으면 항상 바로 앞단 로드밸런서의 사설 IP인 `10.0.1.5`만 보입니다.
2. **X-Forwarded-For의 동작**:  
   로드밸런서(ALB)는 자신이 전달받은 요청의 직전 송신자 IP(`198.51.100.77`)를 `X-Forwarded-For` 헤더 끝에 덧붙여서 백엔드로 넘깁니다.
3. **치명적 결함 (CWE-290 IP Spoofing)**:  
   **HTTP 요청 헤더는 클라이언트가 마음대로 작성할 수 있는 신뢰할 수 없는 데이터(Untrusted Input)입니다!**  
   해커가 `X-Forwarded-For: 10.0.0.50`을 조작해서 보내면, ALB는 해커의 실제 IP를 그 뒤에 덧붙여 백엔드로 넘깁니다:
   ```http
   X-Forwarded-For: 10.0.0.50, 198.51.100.77
   ```
   이때 백엔드가 순진하게 `split(",")[0]`(맨 왼쪽 값)을 꺼내 쓰면, **해커가 직접 적어 넣은 가짜 발송인 스티커(`10.0.0.50`)를 진짜 클라이언트 IP로 판정**하여 관리자 페이지의 문을 활짝 열어주게 되는 것입니다!

---

### 구원 원리: Right-to-Left Trusted Proxy Walking (역방향 신뢰 체인 탐색)

이 보안 결함을 해결하기 위해 Nginx(`real_ip_recursive on`), Apache Tomcat(`RemoteIpValve`), Spring Boot, Express.js 등 전 세계 표준 웹 프레임워크는 **"오른쪽에서 왼쪽으로 역방향 신뢰 체인 탐색"** 알고리즘을 사용합니다.

#### 핵심 원칙: "내가 직접 관리하는 신뢰할 수 있는 프록시(Trusted Proxies)가 보증한 것만 믿는다"
1. **신뢰할 수 있는 프록시 대역(Trusted Proxies)**을 사전에 등록합니다 (예: `127.0.0.1`, `10.0.0.0/8`, `172.16.0.0/12`, Cloudflare IP 대역 등).
2. **가장 오른쪽(소켓 연결 IP)부터 검사 시작**:
   - `socket_remote_addr`는 OS 커널 소켓이 직접 맺은 연결이므로 위조가 불가능합니다.
   - 만약 이 IP가 Trusted Proxy가 아니라면? 외부에서 직접 직통 연결된 것이므로, 헤더의 모든 값은 가짜이며 **소켓 IP 자체가 진짜 클라이언트 IP**입니다!
   - 만약 Trusted Proxy라면? 그 프록시가 헤더 맨 끝에 기록해 준 직전 IP를 신뢰하고 한 단계 왼쪽으로 이동합니다.
3. **최초의 Untrusted IP를 만나는 순간 즉시 정지 (Real Client IP 확정)**:
   - 오른쪽에서 왼쪽으로 거슬러 올라가다가, **처음으로 Trusted Proxy 대역에 속하지 않는 IP를 만나는 순간, 바로 그 IP가 실제 외부 클라이언트 IP(Real Client IP)**입니다!
   - **그 IP의 왼쪽에 적혀 있는 모든 값은 공격자가 임의로 주입한 가짜 데이터이므로 전부 폐기합니다.**

```
[Right-to-Left 역방향 신뢰 체인 검증]

헤더: [ 10.0.0.50 (가짜 사기 스티커), 198.51.100.77 (해커 실제 IP) ]  |  소켓: 10.0.1.5 (ALB)
            ▲                                      ▲                              ▲
            │                                      │                              │
         [버림!]                         [처음 만난 Untrusted!]             [Trusted Proxy]
                                                   │                              │
                                                   └─► 진짜 클라이언트 IP 확정! ◄──┘
                                                       (198.51.100.77 차단 성공!)
```

---

## 과제

당신은 다계층 리버스 프록시 환경에서 유입되는 HTTP 요청들의 IP 스푸핑 공격을 감지하고, 실제 클라이언트 IP를 안전하게 복원하여 관리자 페이지 접근을 제어하는 **"신뢰 역방향 체인 검증기"**를 구현해야 합니다.

### 입력 형식 (JSON)

표준 입력(stdin)으로 다음 JSON 객체가 주어집니다:
- `trusted_proxies`: 신뢰할 수 있는 프록시의 IP 주소 또는 CIDR 서브넷 목록 (예: `["127.0.0.1", "10.0.0.0/8", "2606:4700::/32"]`)
- `admin_whitelist`: 관리자 페이지 접근이 허용된 사내 IP 또는 CIDR 목록 (예: `["10.0.0.50", "10.10.0.0/16"]`)
- `requests`: 유입된 HTTP 요청 객체들의 배열. 각 요청 객체:
  - `request_id`: 고유 요청 식별자 (문자열)
  - `target_endpoint`: 요청 URL 경로 (예: `"/admin/dashboard"`, `"/api/v1/products"`)
  - `socket_remote_addr`: 백엔드 서버 소켓에 직접 연결된 피어 IP (포트 번호가 포함될 수 있음)
  - `headers`: HTTP 헤더 맵.
    - `X-Forwarded-For`: 쉼표로 구분된 프록시 경유 IP 목록 (포트 포함 가능, 대소문자 무관)
    - 또는 `Forwarded`: RFC 7239 표준 포워디드 헤더 (예: `for=10.0.0.50, for=198.51.100.77`)

---

### 세부 처리 규칙

1. **IP 정제 및 파싱**:
   - IPv4에 포트가 붙어 있는 경우(`192.0.2.1:8080`) 포트를 제거하고 IP만 추출합니다.
   - IPv6에 브래킷과 포트가 붙어 있는 경우(`[2001:db8::1]:8080`) 브래킷과 포트를 제거합니다.
   - `X-Forwarded-For` 헤더를 우선 파싱하며, 없으면 `Forwarded` 헤더에서 `for=...` 값들을 파싱합니다.
2. **역방향(Right-to-Left) 탐색**:
   - `socket_remote_addr`부터 검사:
     - Trusted Proxy가 아니면: `resolved_client_ip = socket_remote_addr`로 확정하고 탐색 종료 (`decision = "REAL_CLIENT"`).
     - Trusted Proxy이면: 헤더의 맨 오른쪽 IP부터 왼쪽으로 역순 검사 진행.
   - 역순 검사 중:
     - 처음으로 Trusted Proxy 목록에 없는 IP를 만나는 순간: 해당 IP를 `resolved_client_ip`로 확정하고 탐색 종료 (`decision = "REAL_CLIENT"`).
     - 모든 IP가 Trusted Proxy 목록에 속해 있다면: 맨 왼쪽 IP를 `resolved_client_ip`로 확정 (`decision = "REAL_CLIENT_ALL_TRUSTED"`).
3. **취약한 나이브(Naive) 비교 및 공격 감지**:
   - `naive_client_ip`: 헤더의 첫 번째 IP (헤더가 없으면 `socket_remote_addr`).
   - `is_spoofing_detected`: 헤더가 존재하면서 `naive_client_ip != resolved_client_ip`인 경우 `true`.
4. **접근 제어 판정**:
   - `target_endpoint`가 `"/admin"`으로 시작하는 경우:
     - `resolved_client_ip`가 `admin_whitelist`에 포함되면: `access_granted = true`, `reason = "ADMIN_AUTHORIZED"`.
     - 그렇지 않으면: `access_granted = false`, `reason = "ADMIN_FORBIDDEN"`.
   - `target_endpoint`가 일반 엔드포인트인 경우:
     - `access_granted = true`, `reason = "PUBLIC_ACCESS"`.
   - `spoof_prevented`: 관리자 엔드포인트이면서, 만약 나이브 방식을 썼다면 허용되었을 텐데(`naive_admin_allowed`), 안전한 방식으로 인해 올바르게 차단된 경우(`not access_granted`) `true`.

---

### 출력 형식 (JSON)

표준 출력(stdout)으로 다음 JSON 객체(들여쓰기 2칸)를 출력합니다:
```json
{
  "summary": {
    "total_requests": 1,
    "admin_requests": 1,
    "admin_authorized": 0,
    "admin_forbidden": 1,
    "spoofing_attempts_detected": 1,
    "spoofing_attacks_prevented": 1
  },
  "results": [
    {
      "request_id": "req_spoof_01",
      "target_endpoint": "/admin/dashboard",
      "socket_remote_addr": "10.0.1.5",
      "resolved_client_ip": "198.51.100.77",
      "naive_client_ip": "10.0.0.50",
      "is_spoofing_detected": true,
      "spoof_prevented": true,
      "access_granted": false,
      "reason": "ADMIN_FORBIDDEN",
      "hop_trace": [
        {
          "ip": "10.0.1.5",
          "trusted": true
        },
        {
          "ip": "198.51.100.77",
          "trusted": false,
          "decision": "REAL_CLIENT"
        }
      ]
    }
  ]
}
```

---

## 입출력 예시

### 예시 1 (관리자 페이지 XFF IP 위조 침투 시도 차단)
**입력**:
```json
{
  "trusted_proxies": [
    "127.0.0.1",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16"
  ],
  "admin_whitelist": [
    "10.0.0.50"
  ],
  "requests": [
    {
      "request_id": "req_spoof_01",
      "target_endpoint": "/admin/dashboard",
      "socket_remote_addr": "10.0.1.5",
      "headers": {
        "X-Forwarded-For": "10.0.0.50, 198.51.100.77"
      }
    }
  ]
}
```

**출력**:
```json
{
  "summary": {
    "total_requests": 1,
    "admin_requests": 1,
    "admin_authorized": 0,
    "admin_forbidden": 1,
    "spoofing_attempts_detected": 1,
    "spoofing_attacks_prevented": 1
  },
  "results": [
    {
      "request_id": "req_spoof_01",
      "target_endpoint": "/admin/dashboard",
      "socket_remote_addr": "10.0.1.5",
      "resolved_client_ip": "198.51.100.77",
      "naive_client_ip": "10.0.0.50",
      "is_spoofing_detected": true,
      "spoof_prevented": true,
      "access_granted": false,
      "reason": "ADMIN_FORBIDDEN",
      "hop_trace": [
        {
          "ip": "10.0.1.5",
          "trusted": true
        },
        {
          "ip": "198.51.100.77",
          "trusted": false,
          "decision": "REAL_CLIENT"
        }
      ]
    }
  ]
}
```
